"""Run the whole pipeline once.

    python -m pipeline.run                 normal run (last 2 days of news)
    python -m pipeline.run --backfill      first run: pull 14 days to build history
    python -m pipeline.run --offline       skip fetching, just recompute from saved headlines

Steps:
  1. fetch    download headlines for every ticker
  2. store    add new ones to data/headlines.json (duplicates skipped)
  3. score    count mentions per 24h window and compute z-scores
  4. publish  write site/data/latest.json for the website
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .extract import find_tickers, headline_key
from .stats import score
from .tickers import BY_SYMBOL, WATCHLIST

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "headlines.json"
SITE_DATA = ROOT / "site" / "data"
SITE_PY = ROOT / "site" / "py" / "pipeline"
# live.py and its imports run in the browser; fetch.py is copied so the site can show its code.
BROWSER_FILES = ["__init__.py", "tickers.py", "extract.py", "stats.py", "live.py", "fetch.py"]
KEEP_DAYS = 45


def load_store() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"first_seen": {}, "headlines": {}}


def save_store(store: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, indent=1, sort_keys=True))


def merge(store: dict, items: list[dict], now: datetime) -> int:
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
        for symbol in tickers:
            seen = store["first_seen"].get(symbol)
            if seen is None or item["published"] < seen:
                store["first_seen"][symbol] = item["published"]

    # Drop headlines that are too old to matter.
    store["headlines"] = {
        k: v for k, v in store["headlines"].items()
        if datetime.fromisoformat(v["published"]) >= cutoff
    }
    return added


def build_output(store: dict, now: datetime) -> dict:
    by_ticker: dict[str, list[dict]] = {t["symbol"]: [] for t in WATCHLIST}
    for h in store["headlines"].values():
        for symbol in h["tickers"]:
            if symbol in by_ticker:
                by_ticker[symbol].append(h)

    tickers = []
    for symbol, heads in by_ticker.items():
        info = BY_SYMBOL[symbol]
        times = [datetime.fromisoformat(h["published"]) for h in heads]
        starts = [s for s in (store["first_seen"].get(symbol), store.get("tracking_since")) if s]
        first = min(starts) if starts else None
        stats = score(times, datetime.fromisoformat(first) if first else None, now)
        recent = sorted(heads, key=lambda h: h["published"], reverse=True)[:8]
        tickers.append({
            "symbol": symbol,
            "name": info["name"],
            "sector": info["sector"],
            **stats,
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
            {"strict": False, **{k: t.get(k) for k in ("symbol", "name", "sector", "aliases", "strict") if k in t}}
            for t in WATCHLIST
        ],
        "tickers": tickers,
        "latest": latest,
    }


def publish(output: dict) -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    text = json.dumps(output, separators=(",", ":"))
    (SITE_DATA / "latest.json").write_text(text)
    # Same data as a script, so index.html also works when double-clicked.
    (SITE_DATA / "latest.js").write_text(f"window.TICKERCHATTER_DATA = {text};\n")
    # Copy the Python the browser runs, so the site always uses the same code.
    SITE_PY.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    for name in BROWSER_FILES:
        (SITE_PY / name).write_text((here / name).read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TickerChatter pipeline once.")
    parser.add_argument("--backfill", action="store_true", help="pull 14 days of news")
    parser.add_argument("--offline", action="store_true", help="don't fetch, just recompute")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    first_run = not STORE.exists()
    store = load_store()

    if not args.offline:
        from .fetch import BACKFILL_DAYS, fetch_all  # only needed when actually fetching
        backfill = args.backfill or first_run
        print("Fetching 15 days of headlines (first run, about a minute)..." if backfill else "Fetching new headlines...")
        items = fetch_all(WATCHLIST, backfill=backfill)
        added = merge(store, items, now)
        if backfill:
            # Every day in the window was searched, so a quiet day really was quiet.
            since = (now - timedelta(days=BACKFILL_DAYS)).isoformat(timespec="seconds")
            store["tracking_since"] = min(store.get("tracking_since", since), since)
        save_store(store)
        print(f"Added {added} new headlines ({len(store['headlines'])} stored).")
    elif first_run:
        print("No headlines saved yet. Run without --offline first.")
        return

    output = build_output(store, now)
    publish(output)
    spikes = [t for t in output["tickers"] if t["status"] == "spike"]
    print(f"Wrote site/data/latest.json. Spikes: {', '.join(t['symbol'] for t in spikes) or 'none'}")


if __name__ == "__main__":
    main()
