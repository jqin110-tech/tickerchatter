"""How is the detector doing? Two numbers, from saved files instead of memory.

    python -m pipeline.report              last 7 days
    python -m pipeline.report --days 30

1. Share of stocks flagged. Every pipeline run appends a line to
   data/runs.jsonl (see run.run_summary). For each California day this
   uses the day's last run, since that's the fullest picture of the day.
2. Share of spikes backed by real news. Spikes are checked by hand
   against news coverage and written down in eval/spike_checks.csv
   (day, symbol, verdict, reason, source). Verdicts: real, minor, false.

Why: the first version's problem (28 of 40 stocks "spiking") was only
noticed by looking at the site. Writing both numbers down every day means
a change that makes things worse shows up as a number, not a hunch.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_LOG = ROOT / "data" / "runs.jsonl"
CHECKS = ROOT / "eval" / "spike_checks.csv"


def last_run_per_day(lines: list[dict]) -> dict[str, dict]:
    days = {}
    for line in sorted(lines, key=lambda line: line["at"]):
        days[line["pacific_day"]] = line  # later runs overwrite earlier ones
    return days


def flagged_share(days: dict[str, dict]) -> tuple[int, int]:
    """(spikes, stocks scored) added up over the given days."""
    spikes = sum(len(d["spikes"]) for d in days.values())
    scored = sum(d["scored"] for d in days.values())
    return spikes, scored


def verdict_counts(rows: list[dict]) -> Counter:
    return Counter(row["verdict"].strip().lower() for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise how often stocks are flagged and how often spikes are real.")
    parser.add_argument("--days", type=int, default=7, help="how many recent days to include (default 7)")
    args = parser.parse_args()

    print("Share of stocks flagged as spiking (last run of each California day)")
    if RUNS_LOG.exists():
        lines = [json.loads(x) for x in RUNS_LOG.read_text().splitlines() if x.strip()]
        days = last_run_per_day(lines)
        recent = sorted(days)[-args.days:]
        for day in recent:
            d = days[day]
            names = ", ".join(s["symbol"] for s in d["spikes"]) or "none"
            print(f"  {day} {date.fromisoformat(day):%a} {len(d['spikes']):>2}/{d['scored']:<2} at {d['at'][11:16]} UTC  {names}")
        spikes, scored = flagged_share({day: days[day] for day in recent})
        if scored:
            print(f"  Total: {spikes} of {scored} stock-days = {spikes / scored:.0%}")
    else:
        print(f"  No run log yet ({RUNS_LOG.relative_to(ROOT)} is written by every pipeline run).")

    print("\nSpikes checked against the news (eval/spike_checks.csv)")
    rows = list(csv.DictReader(CHECKS.open())) if CHECKS.exists() else []
    if rows:
        counts = verdict_counts(rows)
        total = sum(counts.values())
        checked_days = sorted({row["day"] for row in rows})
        print(f"  {total} spikes over {len(checked_days)} day(s) ({checked_days[0]} to {checked_days[-1]}):")
        for verdict in ("real", "minor", "false"):
            print(f"    {verdict:<5} {counts.get(verdict, 0):>3}  ({counts.get(verdict, 0) / total:.0%})")
    else:
        print("  None checked yet.")


if __name__ == "__main__":
    main()
