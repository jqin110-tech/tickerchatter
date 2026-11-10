"""Run the whole pipeline once.

    python -m pipeline.run                 normal run (hourly)
    python -m pipeline.run --backfill      search every day again from scratch
    python -m pipeline.run --offline       skip fetching, just recompute from saved data

Steps:
  1. fetch    one Google search per ticker per day that still needs one
  2. store    keep what each day's search found, plus headlines to show
  3. score    compare today so far with the same hours on earlier days
  4. publish  write site/data/latest.json for the website

Which days need a search: today (it's still going), and any day that
hasn't been searched since it ended. So the first run searches all 15
days, and after that each hourly run only searches today, plus
yesterday once after midnight. Every day ends up searched the same way:
one search, after the day is over.

Busy stocks: if any day's search hits Google's 100-result cap, that
stock moves to the narrow query (see fetch.QUERIES) for good, and all
15 days are searched again with it in the same run. A stock's window
never mixes the two queries.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .extract import find_tickers, headline_key, mentions
from .stats import CHART_DAYS, pacific, pacific_today, score
from .tickers import BY_SYMBOL, WATCHLIST

GOOGLE_CAP = 100  # same as fetch.GOOGLE_CAP; not imported so --offline runs without requests installed
ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "headlines.json"
RUNS_LOG = ROOT / "data" / "runs.jsonl"  # one line per run, read by pipeline/report.py
SITE_DATA = ROOT / "site" / "data"
SITE_PY = ROOT / "site" / "py" / "pipeline"
# live.py and its imports run in the browser; fetch.py is copied so the site can show its code.
BROWSER_FILES = ["__init__.py", "tickers.py", "extract.py", "stats.py", "live.py", "fetch.py"]
KEEP_DAYS = 45
# Bump this whenever the rule for "does this headline count" changes
# (extract.py). Days counted under an older rule get searched again, so
# today and the baseline are always counted the same way. 2 = research
# notes no longer count for JPMorgan, Goldman Sachs and Bank of America.
# 3 = fund-holding filings ("$AAPL Shares Sold by X LLC") no longer count.
COUNT_RULES = 3


def load_store() -> dict:
    store = json.loads(STORE.read_text()) if STORE.exists() else {}
    store.setdefault("headlines", {})
    # Older stores counted from "headlines". "days" replaces that; if it's
    # missing, the next run simply searches all 15 days again.
    store.setdefault("days", {})
    store.setdefault("tier", {})   # symbol -> "broad" or "narrow"
    store.pop("tracking_since", None)
    store.pop("first_seen", None)
    return store


def save_store(store: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, indent=1, sort_keys=True))


def tier_of(store: dict, symbol: str) -> str:
    return store.get("tier", {}).get(symbol, "broad")


def counted_like_now(snap: dict, tier: str) -> bool:
    """Same query and same counting rule as a search made today would use."""
    return snap.get("tier", "broad") == tier and snap.get("rules", 1) == COUNT_RULES


def days_to_search(store: dict, symbol: str, now: datetime, redo_all: bool = False) -> list[date]:
    today = pacific_today(now)
    tier = tier_of(store, symbol)
    saved = store["days"].get(symbol, {})
    need = []
    for k in range(CHART_DAYS):
        day = today - timedelta(days=k)
        snap = saved.get(day.isoformat())
        if redo_all or snap is None or not snap["complete"] or not counted_like_now(snap, tier):
            need.append(day)
    return need


def needs_narrow(store: dict, symbol: str) -> bool:
    """A broad-query stock with any capped day in its window."""
    if tier_of(store, symbol) != "broad":
        return False
    return any(snap["capped"] for snap in store["days"].get(symbol, {}).values())


def record_day(store: dict, symbol: str, day: date, items: list[dict] | None, now: datetime,
               tier: str = "broad") -> None:
    """Save the publish times of this day's matching headlines.

    The new search replaces the old one instead of adding to it. If we kept
    adding, today (searched every hour) would collect far more than a past
    day searched once, which is the bias this whole design avoids.
    """
    if items is None:
        return  # failed search: keep whatever we had, or leave the day missing
    times = {}
    for item in items:
        # Google's date filter is loose (about 1 in 5 results spill into the
        # next or previous day). Only keep the ones really from this day.
        published = datetime.fromisoformat(item["published"])
        key = headline_key(item["title"])
        if key and pacific(published).date() == day and mentions(item["title"], symbol):
            times[key] = item["published"]
    store["days"].setdefault(symbol, {})[day.isoformat()] = {
        "searched_at": now.isoformat(timespec="seconds"),
        "complete": pacific_today(now) > day,
        "capped": len(items) >= GOOGLE_CAP,  # count is "at least this many"
        "tier": tier,
        "rules": COUNT_RULES,
        "times": sorted(times.values()),
    }


def merge_headlines(store: dict, items: list[dict], now: datetime) -> int:
    """Headlines shown on the site. They're not used for counting."""
    added = 0
    cutoff = now - timedelta(days=KEEP_DAYS)
    for item in items:
        published = datetime.fromisoformat(item["published"])
        if published < cutoff or published > now + timedelta(hours=1):
            continue
        key = headline_key(item["title"])
        if not key or key in store["headlines"]:
            continue
        tickers = find_tickers(item["title"])
        if not tickers:
            continue
        store["headlines"][key] = {**item, "tickers": tickers}
        added += 1

    store["headlines"] = {
        k: v for k, v in store["headlines"].items()
        if datetime.fromisoformat(v["published"]) >= cutoff
    }
    return added


def prune_days(store: dict, now: datetime) -> None:
    oldest = (pacific_today(now) - timedelta(days=CHART_DAYS - 1)).isoformat()
    for symbol, days in store["days"].items():
        store["days"][symbol] = {d: v for d, v in days.items() if d >= oldest}


def score_ticker(store: dict, symbol: str, now: datetime) -> dict:
    saved = store["days"].get(symbol, {})
    today = pacific_today(now)
    tier = tier_of(store, symbol)
    times, missing, capped = [], set(), set()
    for k in range(CHART_DAYS):
        snap = saved.get((today - timedelta(days=k)).isoformat())
        if snap is None or not counted_like_now(snap, tier):
            missing.add(k)
            continue
        times += [datetime.fromisoformat(t) for t in snap["times"]]
        if snap["capped"]:
            capped.add(k)
    return score(times, now, missing, capped)


def update(store: dict, now: datetime, fetch_days, redo_all: bool = False,
           symbols: list[str] | None = None) -> tuple[list[dict], int]:
    """Search what needs searching. Returns (fetched items, failed searches).

    fetch_days is passed in so tests can hand it a fake Google.
    """
    prune_days(store, now)  # so only days still in the window can trigger a switch
    shown, failed = [], 0
    symbols = symbols or [t["symbol"] for t in WATCHLIST]
    for attempt in range(2):  # second pass only for stocks that just moved to the narrow query
        searches = [(BY_SYMBOL[s], day, tier_of(store, s))
                    for s in symbols for day in days_to_search(store, s, now, redo_all and attempt == 0)]
        if not searches:
            break
        print(f"Running {len(searches)} Google searches (one per ticker per day)...")
        for t, day, tier, items in fetch_days(searches):
            failed += items is None
            record_day(store, t["symbol"], day, items, now, tier)
            shown += items or []
        symbols = [s for s in symbols if needs_narrow(store, s)]
        for s in symbols:
            store["tier"][s] = "narrow"
        if symbols:
            print(f"Too busy for the broad query, switching to narrow: {', '.join(symbols)}")
    return shown, failed


def build_output(store: dict, now: datetime) -> dict:
    by_ticker: dict[str, list[dict]] = {t["symbol"]: [] for t in WATCHLIST}
    for h in store["headlines"].values():
        for symbol in h["tickers"]:
            if symbol in by_ticker:
                by_ticker[symbol].append(h)

    tickers = []
    for symbol, heads in by_ticker.items():
        info = BY_SYMBOL[symbol]
        recent = sorted(heads, key=lambda h: h["published"], reverse=True)[:8]
        tickers.append({
            "symbol": symbol,
            "name": info["name"],
            "sector": info["sector"],
            **score_ticker(store, symbol, now),
            "headlines": [
                {k: h[k] for k in ("title", "link", "source", "published")} for h in recent
            ],
        })

    latest = sorted(store["headlines"].values(), key=lambda h: h["published"], reverse=True)[:40]
    last_day = sum(
        1 for h in store["headlines"].values()
        if now - datetime.fromisoformat(h["published"]) < timedelta(days=1)
    )
    sources = {h["source"] for h in store["headlines"].values()}
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "totals": {
            "headlines": len(store["headlines"]),
            "last_24h": last_day,
            "sources": len(sources),
            "tickers": len(WATCHLIST),
        },
        "thresholds": {"spike": 2.0, "elevated": 1.0, "min_baseline_days": 3},
        "watchlist": [
            {"strict": False, **{k: t.get(k) for k in ("symbol", "name", "sector", "aliases", "strict", "analyst_firm") if k in t}}
            for t in WATCHLIST
        ],
        "tickers": tickers,
        "latest": latest,
    }


def run_summary(output: dict, now: datetime) -> dict:
    """One line for the run log: how many stocks had each status, and which spiked.

    Kept so the share of flagged stocks can be measured over weeks (see
    pipeline/report.py) instead of guessed from whatever the site shows now.
    """
    tickers = output["tickers"]
    statuses = {}
    for t in tickers:
        statuses[t["status"]] = statuses.get(t["status"], 0) + 1
    return {
        "at": now.isoformat(timespec="minutes"),
        "pacific_day": pacific_today(now).isoformat(),
        "scored": sum(1 for t in tickers if t["z"] is not None),
        "statuses": statuses,
        "spikes": [{"symbol": t["symbol"], "z": t["z"], "current": t["current"], "mean": t["mean"]}
                   for t in tickers if t["status"] == "spike"],
    }


def append_run_log(line: dict) -> None:
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUNS_LOG.open("a") as f:
        f.write(json.dumps(line) + "\n")


def publish(output: dict) -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    text = json.dumps(output, separators=(",", ":"))
    (SITE_DATA / "latest.json").write_text(text)
    # Same data as a script, so index.html also works when double-clicked.
    (SITE_DATA / "latest.js").write_text(f"window.TICKERCHATTER_DATA = {text};\n")
    copy_browser_code()


def copy_browser_code() -> None:
    """Copy the Python the browser runs, so the site always uses the same code.

    After editing pipeline/ by hand:  python -c "from pipeline.run import copy_browser_code as c; c()"
    """
    SITE_PY.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    for name in BROWSER_FILES:
        (SITE_PY / name).write_text((here / name).read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TickerChatter pipeline once.")
    parser.add_argument("--backfill", action="store_true", help="search every day again from scratch")
    parser.add_argument("--offline", action="store_true", help="don't fetch, just recompute")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    first_run = not STORE.exists()
    store = load_store()

    if not args.offline:
        from .fetch import fetch_days, fetch_yahoo  # only needed when actually fetching
        shown, failed = update(store, now, fetch_days, redo_all=args.backfill)
        added = merge_headlines(store, shown + fetch_yahoo(WATCHLIST), now)
        prune_days(store, now)
        save_store(store)
        print(f"{failed} searches failed. Added {added} new headlines ({len(store['headlines'])} stored).")
    elif first_run:
        print("No headlines saved yet. Run without --offline first.")
        return

    output = build_output(store, now)
    publish(output)
    if not args.offline:
        append_run_log(run_summary(output, now))
    spikes = [t for t in output["tickers"] if t["status"] == "spike"]
    print(f"Wrote site/data/latest.json. Spikes ({len(spikes)}/{len(WATCHLIST)}): {', '.join(t['symbol'] for t in spikes) or 'none'}")


if __name__ == "__main__":
    main()
