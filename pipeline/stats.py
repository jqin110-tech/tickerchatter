"""Turn stored headlines into "how unusual is today?" numbers.

Days are Pacific-time calendar days, because that's how Google News
search dates work: after:2026-11-09 before:2026-11-10 means Nov 9 in
California. Each day's headlines come from that day's own search.

"Today" isn't over yet, so it is compared fairly: if it's 3pm now, we
count today's headlines up to 3pm and each earlier day's headlines up to
3pm too. Day 0 is today so far, days 1-14 are the baseline.

Weekdays get about twice the news of weekends, so a weekday is compared
with the weekdays in the baseline. Two weeks only hold four weekend
days, too few for a steady average, so a weekend day is compared with
all 14.

For each ticker:
  mean = average headlines over the baseline days (same hours)
  std  = how much that number usually wobbles
  z    = (today so far - mean) / std

z = 0 means a normal day. z = 2 means today is two "usual wobbles" above
normal, which happens by chance only a few percent of the time. That's
the spike threshold.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone

BASELINE_DAYS = 14
CHART_DAYS = 1 + BASELINE_DAYS
MIN_BASELINE = 3      # need at least this many days of history to judge
SOLID_BASELINE = 7    # fewer days than this is shown as an "early read"
STD_FLOOR = 1.0       # stops tiny counts (0, 0, 1) from looking like huge spikes
SPIKE_Z = 2.0
ELEVATED_Z = 1.0


def _first_sunday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7)


def pacific(t: datetime) -> datetime:
    """UTC -> California time, daylight saving included.

    Written out by hand because the browser version (Pyodide) doesn't ship
    the time zone database. US rule: clocks go forward at 2am on the second
    Sunday of March and back at 2am on the first Sunday of November.
    """
    t = t.astimezone(timezone.utc)
    starts = datetime.combine(_first_sunday(t.year, 3) + timedelta(days=7), datetime.min.time(), timezone.utc) + timedelta(hours=10)
    ends = datetime.combine(_first_sunday(t.year, 11), datetime.min.time(), timezone.utc) + timedelta(hours=9)
    hours = -7 if starts <= t < ends else -8
    return t.astimezone(timezone(timedelta(hours=hours)))


def pacific_today(now: datetime) -> date:
    return pacific(now).date()


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def same_hours_counts(times: list[datetime], now: datetime, n: int) -> list[int]:
    """counts[k] = headlines from k days ago, published before now's time of day.

    Comparing whole past days with a half-finished today would make every
    afternoon look quiet, and comparing rolling 24h windows doesn't line
    up with how Google searches by date. Future timestamps are ignored.
    """
    local_now = pacific(now)
    today, cutoff = local_now.date(), local_now.time()
    counts = [0] * n
    for t in times:
        if t > now:
            continue
        local = pacific(t)
        k = (today - local.date()).days
        if 0 <= k < n and local.time() < cutoff:
            counts[k] += 1
    return counts


def score(times: list[datetime], now: datetime, missing: set[int] = frozenset(),
          capped: set[int] = frozenset()) -> dict:
    """missing: days (k) whose search failed or never ran. They're left out of the
    baseline, because a day we couldn't see isn't the same as a quiet day.

    capped: days whose search hit Google's 100-result cap, so the count is
    only "at least this many". A capped *today* is fine: the real z can only
    be higher, so a spike is still a spike. A capped *baseline* day makes
    "normal" look too low and every day look like a spike, so we don't score.
    """
    counts = same_hours_counts(times, now, CHART_DAYS)
    current = counts[0]
    today = pacific_today(now)

    def day(k: int) -> date:
        return today - timedelta(days=k)

    candidates = [k for k in range(1, CHART_DAYS) if k not in missing]
    if not is_weekend(today):
        candidates = [k for k in candidates if not is_weekend(day(k))]
    baseline = [counts[k] for k in candidates]

    result = {
        "current": current,
        "baseline_days": len(baseline),
        "mean": None,
        "std": None,
        "z": None,
        "ratio": None,
        "status": "building",
        "early": len(baseline) < SOLID_BASELINE,
        "capped": any(k in capped for k in candidates),
    }
    if 0 not in missing and len(baseline) >= MIN_BASELINE and not result["capped"]:
        mean = statistics.mean(baseline)
        std = statistics.stdev(baseline)
        z = (current - mean) / max(std, STD_FLOOR)
        result.update(
            mean=round(mean, 2),
            std=round(std, 2),
            z=round(z, 2),
            ratio=round(current / mean, 2) if mean > 0 else None,
            status="spike" if z >= SPIKE_Z else "elevated" if z >= ELEVATED_Z else "normal",
        )

    # Oldest first for charting. Each bar ends at this time of day, k days ago.
    series = []
    for k in reversed(range(CHART_DAYS)):
        series.append({
            "end": (now - timedelta(days=k)).isoformat(timespec="minutes"),
            "count": counts[k],
            "covered": k not in missing,
            "baseline": k in candidates,
        })
    result["series"] = series
    return result
