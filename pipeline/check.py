"""Check each spike for evidence that something really happened.

    python -m pipeline.check                 the last 7 finished days
    python -m pipeline.check --days 14
    python -m pipeline.check --today         also today, so far

A spike only says "more headlines than usual". This looks for two kinds
of evidence that don't come from the headline count itself:

1. Market. Real news usually moves the stock or its trading volume.
   Each day's move is compared with the S&P 500's (SPY) that day, so a
   whole-market rally doesn't count, and then with the stock's own last
   20 trading days. Evidence if |z| >= 2 or volume >= 1.5x its median.
   Data: Yahoo Finance's free daily chart (no key).
2. Story. Real news makes the same unusual words show up across many
   publishers at once ("Foundayo", "special dividend"), while noise like
   shopping deals has no common thread. Evidence if a word is in at least
   15% of the day's headlines, at least 4x as common as in 14 earlier days,
   and used by at least 5 different publishers. The 2 days right before
   are skipped, so a story that broke on Saturday still counts on Monday.

Verdict: "news found" if either fires, else "no news found". This is a
proxy, not the truth: eval/spike_checks.csv (checked by hand) is the
ground truth, and pipeline/report.py measures how often the two agree.
The thresholds were set before looking at results, except the 2-day gap,
added after Berkshire's Saturday earnings were missed on Monday.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from .extract import mentions
from .replay import at_pacific
from .run import ROOT, STORE, score_ticker
from .stats import pacific, pacific_today
from .tickers import BY_SYMBOL, WATCHLIST

CHECKS = ROOT / "data" / "checks.json"

MARKET_Z = 2.0
VOLUME_RATIO = 1.5
MARKET_HISTORY = 20       # trading days to compare with
STORY_SHARE = 0.15
STORY_LIFT = 4.0
STORY_SOURCES = 5
STORY_SKIP_DAYS = 2       # days right before the spike left out of the comparison
STORY_BASE_DAYS = 14

# Words too common in finance headlines to say what the story is.
_COMMON = set("""
the and for with from that this into over after amid about than more what will says said stock stocks
shares share inc corp corporation company today news why here what's could would should their they them
your have just ahead analyst analysts price target market markets investors buy sell hold rating week
year new top best how its it's are was were has been nasdaq nyse dow up down rises falls gains drops
higher lower jumps
""".split())


# ------------------------------------------------------------ market evidence

def fetch_daily(symbol: str) -> list[dict]:
    """[{day, close, volume}] for about the last 6 months, oldest first. [] if Yahoo fails."""
    import requests  # only needed when actually fetching

    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace('.', '-')}",
                         params={"range": "6mo", "interval": "1d"},
                         headers={"User-Agent": "Mozilla/5.0 (tickerchatter)"}, timeout=15)
        result = r.json()["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        offset = timedelta(seconds=result["meta"].get("gmtoffset", -18000))
    except Exception as e:  # noqa: BLE001 - any failure just means "no market data"
        print(f"  No price data for {symbol} ({e.__class__.__name__})")
        return []
    bars = []
    for t, close, volume in zip(result["timestamp"], quote["close"], quote["volume"]):
        if close is not None and volume:
            bars.append({"day": (datetime.fromtimestamp(t, timezone.utc) + offset).date(), "close": close, "volume": volume})
    return bars


def market_signal(bars: list[dict], spy: list[dict], day: date) -> dict | None:
    """How unusual the stock's day was, after taking out the whole market's move.

    None if the market was closed that day or there isn't enough history.
    """
    spy_close = {b["day"]: b["close"] for b in spy}
    i = next((k for k, b in enumerate(bars) if b["day"] == day), None)
    if i is None or i < MARKET_HISTORY + 1:
        return None

    def excess(k: int) -> float | None:
        """Stock's daily return minus SPY's on the same day."""
        prev, cur = bars[k - 1], bars[k]
        if prev["day"] not in spy_close or cur["day"] not in spy_close:
            return None
        return (cur["close"] / prev["close"] - 1) - (spy_close[cur["day"]] / spy_close[prev["day"]] - 1)

    today = excess(i)
    history = [x for x in (excess(k) for k in range(i - MARKET_HISTORY, i)) if x is not None]
    if today is None or len(history) < 10:
        return None
    z = today / max(statistics.stdev(history), 1e-9)
    volume_ratio = bars[i]["volume"] / statistics.median(b["volume"] for b in bars[i - MARKET_HISTORY:i])
    return {
        "excess_return": round(today, 4),
        "z": round(z, 2),
        "volume_ratio": round(volume_ratio, 2),
        "evidence": abs(z) >= MARKET_Z or volume_ratio >= VOLUME_RATIO,
    }


# ------------------------------------------------------------- story evidence

def story_words(title: str, symbol: str) -> set[str]:
    """The words of a headline that could describe a story, minus the company's own names."""
    t = BY_SYMBOL.get(symbol, {"symbol": symbol, "name": symbol, "aliases": []})
    text = title.lower()
    for name in [t["symbol"], t["name"], *t["aliases"]]:
        text = text.replace(name.lower(), " ")
    return {w for w in re.findall(r"[a-z][a-z0-9.%'-]{3,}", text) if w not in _COMMON}


def story_signal(today: list[dict], earlier: list[dict], symbol: str) -> dict:
    """today / earlier: [{title, source}] for this company. Finds words that make up a story."""
    words_today = [story_words(h["title"], symbol) for h in today]
    counts_today = Counter(w for ws in words_today for w in ws)
    counts_earlier = Counter(w for h in earlier for w in story_words(h["title"], symbol))
    n, n_earlier = len(today), len(earlier)
    found = []
    for word, count in counts_today.items():
        share = count / n
        # +1 / +2 keeps a word never seen before from dividing by zero.
        lift = share / ((counts_earlier[word] + 1) / (n_earlier + 2))
        sources = {h["source"] for h, ws in zip(today, words_today) if word in ws}
        if share >= STORY_SHARE and lift >= STORY_LIFT and len(sources) >= STORY_SOURCES:
            found.append({"word": word, "share": round(share, 2), "lift": round(lift, 1), "sources": len(sources)})
    found.sort(key=lambda f: -f["share"])
    example = next((h["title"] for h, ws in zip(today, words_today) if found and found[0]["word"] in ws), None)
    return {"words": found[:4], "example": example, "evidence": bool(found)}


# ------------------------------------------------------------------ checking

def headlines_by_day(store: dict, symbol: str) -> dict[date, list[dict]]:
    by_day: dict[date, list[dict]] = {}
    for h in store["headlines"].values():
        if mentions(h["title"], symbol):
            by_day.setdefault(pacific(datetime.fromisoformat(h["published"])).date(), []).append(h)
    return by_day


def spikes_on(store: dict, day: date, now: datetime) -> list[dict]:
    """Stocks that were spiking at the end of the day (or now, for today)."""
    end = min(now, at_pacific(day, 23) + timedelta(minutes=59))
    out = []
    for t in WATCHLIST:
        r = score_ticker(store, t["symbol"], end)
        if r["status"] == "spike":
            out.append({"symbol": t["symbol"], "z": r["z"], "current": r["current"], "mean": r["mean"]})
    return out


def check(store: dict, days: list[date], now: datetime, fetch=fetch_daily) -> list[dict]:
    spy = fetch("SPY")
    prices: dict[str, list[dict]] = {}
    results = []
    for day in days:
        for spike in spikes_on(store, day, now):
            symbol = spike["symbol"]
            if symbol not in prices:
                prices[symbol] = fetch(symbol)
            by_day = headlines_by_day(store, symbol)
            earlier = [h for k in range(STORY_SKIP_DAYS + 1, STORY_SKIP_DAYS + 1 + STORY_BASE_DAYS)
                       for h in by_day.get(day - timedelta(days=k), [])]
            market = market_signal(prices[symbol], spy, day)
            story = story_signal(by_day.get(day, []), earlier, symbol)
            evidence = [name for name, sig in (("market", market), ("story", story)) if sig and sig["evidence"]]
            results.append({"day": day.isoformat(), **spike, "market": market, "story": story,
                            "evidence": evidence, "verdict": "news found" if evidence else "no news found"})
    return results


def describe(r: dict) -> str:
    m, s = r["market"], r["story"]
    market = (f"move vs S&P {m['excess_return']:+.1%} (z {m['z']:+.1f}), volume {m['volume_ratio']:.1f}x"
              if m else "market closed or no data")
    story = ", ".join(w["word"] for w in s["words"]) or "no common story"
    found_by = f" ({' + '.join(r['evidence'])})" if r["evidence"] else ""
    return f"{r['day']} {r['symbol']:<6} {r['verdict'] + found_by:<29} | {market} | story: {story}"


def merge_checks(saved: dict, results: list[dict], days: list[date]) -> dict:
    """Replace the days just checked and keep older ones.

    Older days stay so hand checks in eval/spike_checks.csv can still be
    compared after the day leaves the 7-day window.
    """
    checked = {d.isoformat() for d in days}
    kept = [r for r in saved.get("spikes", []) if r["day"] not in checked]
    return {"spikes": sorted(kept + results, key=lambda r: (r["day"], r["symbol"]))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Look for evidence behind each spike.")
    parser.add_argument("--days", type=int, default=7, help="how many finished days to check (default 7)")
    parser.add_argument("--today", action="store_true", help="also check today so far")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    today = pacific_today(now)
    days = [today - timedelta(days=k) for k in range(args.days, 0, -1)] + ([today] if args.today else [])
    store = json.loads(STORE.read_text())
    results = check(store, days, now)

    for r in results:
        print(describe(r))
        if r["story"]["example"]:
            print(f"{'':18}e.g. {r['story']['example'][:100]}")
    found = sum(r["verdict"] == "news found" for r in results)
    print(f"\n{found} of {len(results)} spikes had news behind them.")
    saved = json.loads(CHECKS.read_text()) if CHECKS.exists() else {}
    merged = merge_checks(saved, results, days)
    merged["checked_at"] = now.isoformat(timespec="minutes")
    CHECKS.parent.mkdir(parents=True, exist_ok=True)
    CHECKS.write_text(json.dumps(merged, indent=1, default=str))


if __name__ == "__main__":
    main()
