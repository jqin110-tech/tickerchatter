"""live.py runs in the browser on what worker.js sends. Check it end to end."""
import json
from datetime import datetime, timedelta, timezone

from pipeline.live import analyze

PST = timezone(timedelta(hours=-8))
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=PST)


def worker_items(per_day: dict[int, int]) -> list[dict]:
    """Shaped like worker.js output: each item tagged with the day its search asked for."""
    items = []
    for k, n in per_day.items():
        day = (NOW - timedelta(days=k)).date()
        start = datetime.combine(day, datetime.min.time(), PST)
        for i in range(n):
            items.append({"title": f"Micron news {k}-{i}", "published": (start + timedelta(minutes=5 * i)).isoformat(),
                          "link": "", "source": "Test", "day": day.isoformat()})
    return items


def run(items):
    company = json.dumps({"symbol": "MU", "name": "Micron", "aliases": ["Micron"]})
    return json.loads(analyze(json.dumps(items), company, NOW.astimezone(timezone.utc).isoformat(), 15))


def test_live_scores_a_normal_day():
    r = run(worker_items({k: 20 for k in range(15)}))
    assert r["status"] == "normal" and r["baseline_days"] == 10


def test_live_ignores_items_outside_their_search_day():
    items = worker_items({k: 20 for k in range(15)})
    spill = dict(items[0], title="Micron spill", day=(NOW - timedelta(days=1)).date().isoformat())
    assert run(items + [spill])["current"] == run(items)["current"]


def test_live_flags_capped_baseline():
    r = run(worker_items({**{k: 20 for k in range(15)}, 2: 100}))  # k=2 is Monday; a capped Sunday would not matter on a Wednesday
    assert r["capped"] is True and r["z"] is None
