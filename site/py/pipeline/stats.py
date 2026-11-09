"""Turn stored headlines into "how unusual is today?" numbers.

Time is cut into 24 hour windows counting back from now:
  window 0      the last 24 hours (what we're judging)
  windows 1-14  the 14 days before that (what "normal" looks like)

For each ticker:
  mean = average headlines per window over the baseline
  std  = how much that number usually wobbles
  z    = (last 24h - mean) / std

z = 0 means a normal day. z = 2 means today is two "usual wobbles" above
normal, which happens by chance only a few percent of the time. That's
the spike threshold.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta

BASELINE_WINDOWS = 14
CHART_WINDOWS = 30
MIN_BASELINE = 3      # need at least this many days of history to judge
SOLID_BASELINE = 7    # fewer days than this is shown as an "early read"
STD_FLOOR = 1.0       # stops tiny counts (0, 0, 1) from looking like huge spikes
SPIKE_Z = 2.0
ELEVATED_Z = 1.0


def window_counts(times: list[datetime], now: datetime, n: int) -> list[int]:
    """counts[k] = headlines published in [now - 24(k+1)h, now - 24k h)."""
    counts = [0] * n
    for t in times:
        k = int((now - t).total_seconds() // 86400)
        if 0 <= k < n:
            counts[k] += 1
    return counts


def score(times: list[datetime], first_seen: datetime | None, now: datetime) -> dict:
    counts = window_counts(times, now, CHART_WINDOWS)
    current = counts[0]

    # Only trust windows that are fully after we started seeing this ticker,
    # otherwise days before tracking began would look like quiet days.
    covered = 0
    if first_seen is not None:
        covered = int((now - first_seen).total_seconds() // 86400)
    usable = min(BASELINE_WINDOWS, max(0, covered))
    baseline = counts[1 : 1 + usable]

    result = {
        "current": current,
        "baseline_days": len(baseline),
        "mean": None,
        "std": None,
        "z": None,
        "ratio": None,
        "status": "building",
        "early": len(baseline) < SOLID_BASELINE,
    }
    if len(baseline) >= MIN_BASELINE:
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

    # Oldest first for charting. Each window is labelled by the day it ends on.
    series = []
    for k in reversed(range(CHART_WINDOWS)):
        end = now - timedelta(days=k)
        series.append({
            "end": end.isoformat(timespec="minutes"),
            "count": counts[k],
            "covered": k == 0 or k <= covered,
            "baseline": 1 <= k <= usable,
        })
    result["series"] = series
    return result
