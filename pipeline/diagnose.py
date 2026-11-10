"""Look at what each day's search found, for a few tickers.

    python -m pipeline.diagnose                 NVDA AAPL PFE CVX
    python -m pipeline.diagnose MU TSLA         any watchlist symbols

Runs the same fetch as the pipeline (one search per day, switching busy
stocks to the narrow query) without touching data/headlines.json, and
prints per day how many headlines were counted and whether the search
hit Google's 100-result cap.

Why it exists: the first version flagged 28 of 40 stocks as spiking
right after a backfill. Tables like this showed why (see README,
"How the score works").
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone

from .fetch import fetch_days
from .run import score_ticker, tier_of, update


def main() -> None:
    symbols = sys.argv[1:] or ["NVDA", "AAPL", "PFE", "CVX"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    store = {"headlines": {}, "days": {}, "tier": {}}
    update(store, now, fetch_days, symbols=symbols)

    for s in symbols:
        print(f"\n{s} ({tier_of(store, s)} query)")
        for day, snap in sorted(store["days"][s].items()):
            cap = "  at the cap" if snap["capped"] else ""
            print(f"  {day} {date.fromisoformat(day):%a}  {len(snap['times']):>4} counted{cap}")
        r = score_ticker(store, s, now)
        print(f"  today so far {r['current']}, usual {r['mean']} +/- {r['std']} over "
              f"{r['baseline_days']} days -> z {r['z']} ({r['status']}{', capped' if r['capped'] else ''})")


if __name__ == "__main__":
    main()
