"""Tests for pipeline/stats.py.

Run from the project folder:  python -m pytest
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from pipeline import stats
from pipeline.stats import pacific, same_hours_counts, score

UTC = timezone.utc
# Wednesday Nov 4 2026, 12:00 in California (PST, UTC-8) = 20:00 UTC.
NOW = datetime(2026, 11, 4, 20, 0, tzinfo=UTC)


def at_pacific(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A moment given in California winter time (UTC-8), as UTC."""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=timezone(timedelta(hours=-8))).astimezone(UTC)


# ---------------------------------------------------------------- time zones

def test_pacific_switches_with_daylight_saving():
    # 2026: summer time ends Sun Nov 1 at 09:00 UTC, starts Sun Mar 8 at 10:00 UTC.
    assert pacific(datetime(2026, 11, 1, 8, 59, tzinfo=UTC)).utcoffset() == timedelta(hours=-7)
    assert pacific(datetime(2026, 11, 1, 9, 0, tzinfo=UTC)).utcoffset() == timedelta(hours=-8)
    assert pacific(datetime(2026, 3, 8, 9, 59, tzinfo=UTC)).utcoffset() == timedelta(hours=-8)
    assert pacific(datetime(2026, 3, 8, 10, 0, tzinfo=UTC)).utcoffset() == timedelta(hours=-7)


def test_pacific_day_differs_from_utc_day_in_the_evening():
    # 03:49 UTC on Nov 10 is still the evening of Nov 9 in California.
    assert pacific(datetime(2026, 11, 10, 3, 49, tzinfo=UTC)).date() == date(2026, 11, 9)


# ------------------------------------------------------- same_hours_counts edges

def test_exactly_one_day_ago_is_at_the_cutoff_so_not_counted():
    # Each past day counts [midnight, this time of day). Exactly 24h ago sits
    # on the cutoff, so it's left out, like a headline at 12:00 today would be
    # if it were 12:00:00 exactly. One second earlier is counted.
    counts = same_hours_counts([NOW - timedelta(days=1)], NOW, 3)
    assert counts == [0, 0, 0]
    counts = same_hours_counts([NOW - timedelta(days=1, seconds=1)], NOW, 3)
    assert counts == [0, 1, 0]


def test_after_the_cutoff_on_a_past_day_is_not_counted():
    # Yesterday at 18:00 is later in the day than "now" (12:00), so comparing
    # it with a half-finished today would be unfair.
    yesterday = NOW.date() - timedelta(days=1)
    assert same_hours_counts([at_pacific(yesterday, 18)], NOW, 3) == [0, 0, 0]


def test_midnight_belongs_to_the_new_day():
    today = pacific(NOW).date()
    assert same_hours_counts([at_pacific(today, 0, 0, 0)], NOW, 3) == [1, 0, 0]
    assert same_hours_counts([at_pacific(today, 0) - timedelta(seconds=1)], NOW, 3) == [0, 0, 0]  # yesterday 23:59:59 is after the cutoff


def test_future_timestamps_are_ignored():
    # Feeds sometimes carry times slightly ahead of ours (clock drift, time zones).
    assert same_hours_counts([NOW + timedelta(minutes=5), NOW + timedelta(days=2)], NOW, 3) == [0, 0, 0]


def test_too_old_is_ignored():
    assert same_hours_counts([NOW - timedelta(days=3, hours=1)], NOW, 3) == [0, 0, 0]


# ----------------------------------------------------------------- score()

def times_for(counts_by_day: dict[int, int]) -> list[datetime]:
    """k days ago -> that many headlines, all at 06:00 California time (before the 12:00 cutoff)."""
    today = pacific(NOW).date()
    out = []
    for k, n in counts_by_day.items():
        out += [at_pacific(today - timedelta(days=k), 6, i % 60) for i in range(n)]
    return out


def weekdays_back(n: int) -> list[int]:
    """The first n values of k (days ago) that are weekdays, counting back from NOW."""
    today = pacific(NOW).date()
    return [k for k in range(1, stats.CHART_DAYS) if (today - timedelta(days=k)).weekday() < 5][:n]


def test_std_floor_stops_tiny_counts_looking_huge():
    # Baseline 0, 0, 1: mean 0.33, real std 0.58. Without the floor, 3 headlines
    # would be z = 4.6. With std floored at 1.0 it's (3 - 0.33) / 1 = 2.67.
    k1, k2, k3 = weekdays_back(3)
    missing = set(range(1, stats.CHART_DAYS)) - {k1, k2, k3}
    r = score(times_for({0: 3, k3: 1}), NOW, missing)
    assert r["baseline_days"] == 3
    assert r["std"] == pytest.approx(0.58, abs=0.01)
    assert r["z"] == pytest.approx(2.67, abs=0.01)
    assert r["status"] == "spike"


def test_small_steady_counts_need_more_than_a_small_bump():
    # Regression for WMT on 2026-11-09: usually 6 or 7 headlines, today 11.
    # The days happened to be steady (std 0.5), so dividing by std (or by the
    # 1.0 floor) gave z = 4.4, a "spike". By luck alone a count around 6.5
    # swings by about sqrt(6.5) = 2.5, so 11 is only z = 1.7.
    ks = weekdays_back(10)
    r = score(times_for({0: 11, **{k: 6 + i % 2 for i, k in enumerate(ks)}}), NOW)
    assert r["std"] == pytest.approx(0.53, abs=0.01)
    assert r["spread"] == pytest.approx(6.5 ** 0.5, abs=0.01)
    assert r["status"] == "elevated"


def test_busy_stocks_real_spike_is_unchanged_by_the_sqrt_floor():
    # Busy stocks wobble more than sqrt(mean) anyway, so their z doesn't move.
    ks = weekdays_back(10)
    usual = [20, 40, 25, 35, 30, 22, 38, 28, 32, 30]   # mean 30, std 6.6 > sqrt(30) = 5.5
    r = score(times_for({0: 60, **dict(zip(ks, usual))}), NOW)
    assert r["spread"] == r["std"]
    assert r["status"] == "spike"


def test_flat_ticker_scores_zero():
    # Same number every day: today is exactly usual, so z = 0, not "a bit off".
    ks = weekdays_back(10)
    r = score(times_for({0: 10, **{k: 10 for k in ks}}), NOW)
    assert r["mean"] == 10 and r["std"] == 0
    assert r["z"] == 0 and r["status"] == "normal"


def test_empty_input_with_coverage_is_a_quiet_normal_day():
    # Searched every day and found nothing: a real, quiet day. Mean 0 and
    # std 0 must not divide by zero (the floor makes the spread 1), and the
    # ratio today/usual has no meaning, so it's None rather than a crash.
    r = score([], NOW)
    assert r["current"] == 0 and r["baseline_days"] == 10
    assert r["z"] == 0 and r["status"] == "normal"
    assert r["ratio"] is None


def test_building_below_min_baseline():
    k1, k2 = weekdays_back(2)
    missing = set(range(1, stats.CHART_DAYS)) - {k1, k2}
    r = score(times_for({0: 50, k1: 1, k2: 1}), NOW, missing)
    assert r["baseline_days"] == 2 < stats.MIN_BASELINE
    assert r["status"] == "building"
    assert r["z"] is None and r["mean"] is None


def test_weekday_is_compared_with_weekdays_only():
    # 14 days back from a Wednesday hold 10 weekdays and 4 weekend days.
    r = score([], NOW)
    assert r["baseline_days"] == 10
    today = pacific(NOW).date()
    weekend_bars = [p for k, p in zip(reversed(range(stats.CHART_DAYS)), r["series"])
                    if (today - timedelta(days=k)).weekday() >= 5]
    assert len(weekend_bars) == 4 and not any(p["baseline"] for p in weekend_bars)


def test_weekend_is_compared_with_all_days():
    saturday_noon = at_pacific(date(2026, 11, 7), 12)
    assert score([], saturday_noon)["baseline_days"] == 14


def test_missing_days_are_not_treated_as_quiet():
    # A failed search is "unknown", not zero, so it must not drag the mean down.
    weekdays = weekdays_back(10)
    r = score(times_for({0: 10, **{k: 10 for k in weekdays}}), NOW, missing={weekdays[0]})
    assert r["baseline_days"] == 9 and r["mean"] == 10 and r["status"] == "normal"
    assert r["series"][-1 - weekdays[0]]["covered"] is False


def test_no_score_if_today_is_missing():
    r = score(times_for({k: 10 for k in weekdays_back(10)}), NOW, missing={0})
    assert r["status"] == "building" and r["z"] is None


def test_output_keys_unchanged_for_app_js():
    r = score([], NOW)
    assert set(r) == {"current", "baseline_days", "mean", "std", "spread", "z", "ratio", "status", "early", "capped", "series"}
    assert set(r["series"][0]) == {"end", "count", "covered", "baseline"}
    assert len(r["series"]) == stats.CHART_DAYS


def test_capped_today_still_scores():
    # Today hit the cap: the true count is even higher, so a spike is still real.
    weekdays = weekdays_back(10)
    r = score(times_for({0: 100, **{k: 10 + k % 3 for k in weekdays}}), NOW, capped={0})
    assert r["capped"] is False and r["status"] == "spike"


def test_capped_baseline_day_blocks_the_score():
    weekdays = weekdays_back(10)
    r = score(times_for({0: 30, **{k: 10 for k in weekdays}}), NOW, capped={weekdays[3]})
    assert r["capped"] is True and r["z"] is None and r["status"] == "building"
