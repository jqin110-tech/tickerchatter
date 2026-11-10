"""Regression test for the "everything is spiking" bug.

After the first backfill, 28 of 40 stocks showed z >= 2. The cause:

  * Each backfill search covered two California days and returned at most
    100 results, so a busy stock got ~50 results per past day.
  * The newest search covered today and tomorrow. Tomorrow hasn't happened,
    so its 100 results were squeezed into the hours of today that had passed,
    and all of them landed in "the last 24 hours".

So "today" looked 2-3x busier for any stock busy enough to hit the cap,
even if its news flow never changed. These tests build exactly that
situation: a stock with one headline every 10 minutes, every day, and a
fake Google that returns at most 100 results per search.
"""
import statistics
from datetime import date, datetime, timedelta, timezone

import pytest

from pipeline import stats
from pipeline.run import record_day, score_ticker, update
from pipeline.stats import pacific

UTC = timezone.utc
PST = timezone(timedelta(hours=-8))
CAP = 100


def steady_news(now: datetime) -> list[datetime]:
    """One Nvidia headline every 10 minutes for the last 20 days: 144 a day, forever."""
    start = now - timedelta(days=20)
    return [start + timedelta(minutes=10 * i) for i in range(20 * 144) if start + timedelta(minutes=10 * i) <= now]


def fake_google(news: list[datetime], first_day: date, last_day: date, now: datetime) -> list[datetime]:
    """What Google returns for after:first_day before:last_day+1: at most 100
    results, spread across the range (Google picks by relevance, not time)."""
    # California days, daylight saving included, like the real Google.
    found = [t for t in news if first_day <= pacific(t).date() <= last_day and t <= now]
    if len(found) <= CAP:
        return found
    step = len(found) / CAP
    return [found[int(i * step)] for i in range(CAP)]


def old_z(now: datetime) -> float:
    """The first version: 2-day searches, unioned, then rolling 24h windows."""
    news = steady_news(now)
    today = now.astimezone(UTC).date()  # the old fetch.py used the UTC date
    seen = set()
    for d in range(15):
        seen.update(fake_google(news, today - timedelta(days=d + 1), today - timedelta(days=d), now))
    counts = [0] * 15
    for t in seen:
        k = int((now - t).total_seconds() // 86400)
        if 0 <= k < 15:
            counts[k] += 1
    baseline = counts[1:15]
    return (counts[0] - statistics.mean(baseline)) / max(statistics.stdev(baseline), 1.0)


def fake_fetch_days(news: list[datetime], now: datetime):
    """Stands in for fetch.fetch_days. The narrow query sees every third
    headline, like "Nvidia stock" being a subset of "Nvidia"."""
    def fetch_days(searches):
        out = []
        for t, day, tier in searches:
            pool = news if tier == "broad" else news[::3]
            found = fake_google(pool, day, day, now)
            items = [{"title": f"Nvidia story {x.isoformat()}", "published": x.isoformat(timespec="seconds")} for x in found]
            out.append((t, day, tier, items))
        return out
    return fetch_days


def new_result(now: datetime, news: list[datetime]) -> dict:
    """The fix, through the real pipeline code (run.update + run.score_ticker)."""
    store = {"headlines": {}, "days": {}, "tier": {}}
    update(store, now, fake_fetch_days(news, now), symbols=["NVDA"])
    return score_ticker(store, "NVDA", now)


# A Wednesday, at several times of day (California time).
TIMES = [datetime(2026, 11, 4, h, 17, tzinfo=PST).astimezone(UTC) for h in (3, 9, 15, 21)]
label = lambda t: f"{pacific(t):%H:%M}PT"


# How bad the old bug was depended on the hour. It took "today" from the UTC
# date, so from 4pm in California (midnight UTC) the newest search was
# "today and tomorrow" and z for steady news was about 5. It was smallest
# around 2pm (z about 1.4), so these checks skip the 15:17 run.
@pytest.mark.parametrize("now", [TIMES[0], TIMES[1], TIMES[3]], ids=label)
def test_old_method_reports_a_spike_for_steady_news(now):
    # Documents the bug: nothing changed, yet the old counting says "spike".
    assert old_z(now) >= 2


@pytest.mark.parametrize("now", TIMES, ids=label)
def test_new_method_reports_normal_for_steady_busy_news(now):
    # 144 a day is over the cap, so NVDA moves to the narrow query (48 a day).
    r = new_result(now, steady_news(now))
    assert r["status"] == "normal", r
    assert abs(r["z"]) < 1


@pytest.mark.parametrize("now", TIMES, ids=label)
def test_new_method_reports_normal_for_steady_quiet_news(now):
    quiet = steady_news(now)[::3]  # 48 a day, never capped, stays on the broad query
    r = new_result(now, quiet)
    assert r["status"] == "normal", r


def test_capped_baseline_is_not_scored():
    # Even the narrow query is capped: we can't know "normal", so say so
    # instead of guessing.
    now = TIMES[2]
    every_minute = [now - timedelta(minutes=i) for i in range(20 * 1440)]
    r = new_result(now, every_minute)
    assert r["capped"] is True
    assert r["z"] is None and r["status"] == "building"


def test_new_method_still_finds_a_real_spike():
    # The fix mustn't make spikes impossible: a quiet stock (20 a day) that
    # suddenly gets 60 by midday is a real story.
    now = TIMES[2]
    today = pacific(now).date()
    store = {"headlines": {}, "days": {}}
    for k in range(stats.CHART_DAYS):
        day = today - timedelta(days=k)
        per_day = 60 if k == 0 else 20 + k % 3  # a little day-to-day wobble
        start = datetime.combine(day, datetime.min.time(), PST)
        items = [{"title": f"Nvidia item {k}-{i}", "published": (start + timedelta(minutes=10 * i)).isoformat()}
                 for i in range(per_day)]
        record_day(store, "NVDA", day, items, now)
    assert score_ticker(store, "NVDA", now)["status"] == "spike"
