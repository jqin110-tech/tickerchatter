"""Tests for the run log (run.py), report.py and replay.py."""
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.replay import at_pacific
from pipeline.report import flagged_share, last_run_per_day, verdict_counts
from pipeline.run import BROWSER_FILES, run_summary

ROOT = Path(__file__).resolve().parent.parent


def ticker(symbol, status, z=1.0):
    return {"symbol": symbol, "status": status, "z": z, "current": 10, "mean": 5.0}


def test_run_summary_counts_statuses_and_lists_spikes():
    output = {"tickers": [ticker("NVDA", "spike", 3.1), ticker("AAPL", "normal", 0.2), ticker("AMD", "building", None)]}
    line = run_summary(output, datetime(2026, 11, 10, 5, 1, tzinfo=timezone.utc))
    assert line["pacific_day"] == "2026-11-09"            # 05:01 UTC is still Monday evening in California
    assert line["scored"] == 2                             # "building" has no z, so it isn't scored
    assert line["statuses"] == {"spike": 1, "normal": 1, "building": 1}
    assert [s["symbol"] for s in line["spikes"]] == ["NVDA"]


def test_report_uses_the_last_run_of_each_day():
    lines = [
        {"at": "2026-11-09T20:00+00:00", "pacific_day": "2026-11-09", "scored": 40, "spikes": [{"symbol": "A"}]},
        {"at": "2026-11-10T05:00+00:00", "pacific_day": "2026-11-09", "scored": 40, "spikes": [{"symbol": "A"}, {"symbol": "B"}]},
        {"at": "2026-11-10T20:00+00:00", "pacific_day": "2026-11-10", "scored": 39, "spikes": []},
    ]
    days = last_run_per_day(lines)
    assert len(days["2026-11-09"]["spikes"]) == 2
    assert flagged_share(days) == (2, 79)


def test_verdicts_are_counted_case_insensitively():
    assert verdict_counts([{"verdict": "Real"}, {"verdict": "real "}, {"verdict": "false"}]) == {"real": 2, "false": 1}


def test_replay_scores_at_california_time_in_summer_and_winter():
    assert at_pacific(date(2026, 11, 9), 21) == datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)   # winter, UTC-8
    assert at_pacific(date(2026, 7, 9), 21) == datetime(2026, 7, 10, 4, 0, tzinfo=timezone.utc)     # summer, UTC-7


def test_browser_copy_matches_pipeline():
    # The site runs site/py/pipeline in Pyodide. If it drifts from pipeline/,
    # live search and the hourly job score differently. Fix with:
    #   python -c "from pipeline.run import copy_browser_code as c; c()"
    for name in BROWSER_FILES:
        assert (ROOT / "site/py/pipeline" / name).read_text() == (ROOT / "pipeline" / name).read_text(), name


def test_hand_checks_file_is_well_formed():
    # Rows are added by hand, so check them like data: a comma inside an
    # unquoted reason shifts every column after it.
    import csv
    for row in csv.DictReader((ROOT / "eval/spike_checks.csv").open()):
        assert None not in row and all(row.values()), row
        assert row["verdict"] in {"real", "minor", "false"}, row
        date.fromisoformat(row["day"])
