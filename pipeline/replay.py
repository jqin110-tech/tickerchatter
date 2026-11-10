"""Replay past weekdays: how many spikes would each z-score rule have flagged?

    python -m pipeline.replay --rev 8a242ff                    the README's 56 -> 51
    python -m pipeline.replay --rev 8a242ff --from 2026-10-30 --to 2026-11-09 --hour 21

Scores every stock at the same time of day on each weekday, using a saved
copy of the store, once with the old divisor max(std, 1) and once with
the current one, max(std, sqrt(mean), 1).

--rev reads the store from git history, so a result can be reproduced
later from the exact data it was measured on. Only the scoring rule is
compared: the counts are whatever that snapshot stored.

Why: the README quotes these numbers, and a number nobody can rerun
isn't worth much.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, time, timedelta, timezone

from .run import COUNT_RULES, ROOT, STORE, score_ticker
from .stats import pacific
from .tickers import WATCHLIST


def load_snapshot(rev: str | None) -> dict:
    if rev is None:
        return json.loads(STORE.read_text())
    # Older commits kept the store on main; newer ones on the data branch.
    for path in ("data/headlines.json", "headlines.json"):
        shown = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True, text=True)
        if shown.returncode == 0:
            return json.loads(shown.stdout)
    raise SystemExit(f"No saved store found at {rev}")


def at_pacific(day: date, hour: int) -> datetime:
    """That clock time in California on that day, as UTC.

    California is 8 hours behind UTC in winter and 7 in summer; try both
    and keep the one stats.pacific agrees with.
    """
    for behind in (8, 7):
        t = datetime.combine(day, time(hour), timezone.utc) + timedelta(hours=behind)
        if pacific(t).hour == hour:
            return t
    raise ValueError(f"{day} {hour}:00 doesn't exist in California (clocks skipped it)")


def replay(store: dict, start: date, end: date, hour: int) -> list[dict]:
    # A snapshot counted under an older rule is still comparable with itself,
    # so mark its days as current instead of letting score_ticker skip them.
    for days in store["days"].values():
        for snap in days.values():
            snap["rules"] = COUNT_RULES
    rows = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            now = at_pacific(day, hour)
            for t in WATCHLIST:
                r = score_ticker(store, t["symbol"], now)
                if r["z"] is None:
                    continue
                old_z = (r["current"] - r["mean"]) / max(r["std"], 1.0)
                rows.append({"day": day, "symbol": t["symbol"], "current": r["current"], "mean": r["mean"],
                             "std": r["std"], "old_z": round(old_z, 2), "z": r["z"]})
        day += timedelta(days=1)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay past weekdays under the old and current z-score rule.")
    parser.add_argument("--rev", help="git revision to read the store from (default: data/headlines.json on disk)")
    parser.add_argument("--from", dest="start", default="2026-10-30")
    parser.add_argument("--to", dest="end", default="2026-11-09")
    parser.add_argument("--hour", type=int, default=21, help="California hour to score at (default 21 = 9pm)")
    args = parser.parse_args()

    rows = replay(load_snapshot(args.rev), date.fromisoformat(args.start), date.fromisoformat(args.end), args.hour)
    old = [r for r in rows if r["old_z"] >= 2]
    new = [r for r in rows if r["z"] >= 2]
    print(f"{len(rows)} stock-days scored. Spikes: {len(old)} with max(std, 1), {len(new)} with max(std, sqrt(mean), 1).")
    print("\nNo longer spikes:")
    for r in rows:
        if r["old_z"] >= 2 and r["z"] < 2:
            print(f"  {r['day']:%b %d} {r['symbol']:<5} {r['current']} vs usual {r['mean']} (std {r['std']}, "
                  f"sqrt {r['mean'] ** 0.5:.1f}): z {r['old_z']} -> {r['z']}")


if __name__ == "__main__":
    main()
