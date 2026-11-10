# TickerChatter

Flags which of 40 large-cap stocks are getting unusually many news headlines today, using a z-score against each stock's own recent history.

**Live site:** https://jqin110-tech.github.io/tickerchatter

> TODO: screenshot of the front page (save as `docs/screenshot.png` and link it here)

## How it works

- **Ingestion.** For each stock, one Google News RSS search per California
  calendar day (`after:2026-11-09 before:2026-11-10`). A headline counts
  only if it was published that day and names the company (symbol, cashtag
  or known name). Repeats of the same story are counted once. Google returns
  at most 100 results per search, so stocks that hit the cap switch to a
  narrower `"Name stock"` query for all 15 days.
- **Aggregation.** Today so far is compared with the same hours on each of
  the previous 14 days (at 3pm, every day is counted up to 3pm). Weekdays
  are compared only with weekdays: weekends get about half as many headlines.
- **Detection.** `z = (today − mean) / max(std, √mean, 1)`. `z ≥ 2` is a
  spike and `z ≥ 1` is elevated. A stock needs 3 comparable days of history
  before it gets a score.
- **Running it.** GitHub Actions is scheduled to run the pipeline every hour
  (`pipeline/run.py`), commit the data, and redeploy the GitHub Pages site,
  but only after the tests pass. The site runs the same Python
  (`extract.py`, `stats.py`) in the browser with Pyodide. `worker/` is a
  Cloudflare Worker that would fetch headlines for any company typed into
  the search box. It is written but not deployed yet (`site/config.js` has
  no address), so searches currently cover the 40 tracked stocks.

## Results

All numbers below come from runs of this code on 2026-11-09 and 2026-11-10.

| Version | Stocks flagged as spiking |
|---|---|
| First version, after its first backfill | 28 of 40 (70%) |
| Rebuilt counting, fresh backfill | 6 of 40 (15%) |
| Rebuilt counting, first hourly run (Mon Nov 9, 21:01 Pacific) | 8 of 40 (20%) |
| With both fixes below, same Monday data replayed | 7 of 40 |

**The 70% bug.** The first version searched 2-day date ranges, starting
from the UTC date. From 4pm in California, the newest range included a
day that hadn't happened yet. Its 100 results were packed into the few
hours that had, so busy stocks looked like spikes all evening. A test
(`tests/test_bias.py`) rebuilds this with a perfectly steady fake stock.
The old method gives z of about 5 and the new one about 0.

**Checking the 8 Monday spikes against the news:**

- **4 real:** Nvidia (board investigation into the CEO; stock down about
  4%), Broadcom (up 8.8%), Eli Lilly (Phase 3 results), Berkshire (Q3 earnings).
- **1 minor:** Starbucks (holiday products and UK hiring).
- **3 false alarms:** Walmart (small counts), Bank of America (its analysts'
  notes about other companies), Costco (holiday coverage building for weeks).

**Fixes from that check:** the √mean floor (next section), and analyst notes
no longer count for JPMorgan, Goldman Sachs and Bank of America ("JPMorgan
downgrades Nike" is news about Nike). In the stored data, that was roughly a
quarter to a third of all headlines naming those banks.

Replaying Monday with both fixes: Walmart and Bank of America drop out.
Goldman Sachs comes in, with 6 headlines against a usual 1.9; I couldn't
find the news behind it.

**Tried and rejected:** a shorter or median baseline to handle slow trends
like Costco. Replayed over 7 weekdays, a 5-weekday baseline gave the same
51 spikes and a median baseline gave 74.

**Not measured yet:** TODO: share of stocks flagged over a full week of hourly
runs. TODO: share of spikes backed by real news, over more than one day.

## Hardest bug: tiny counts, huge z-scores

A z-score divides by the standard deviation of the baseline days. For a
quiet stock, that number can be tiny by chance. Baseline counts of 0, 0, 1
have a standard deviation of 0.58, so 3 headlines today scored z = 4.6, a
"spike" from three articles. A floor of 1 fixed that case (z = 2.67).

It still let Walmart through on Nov 9: 11 headlines against a usual 6.7
scored z = 2.09. Headline counts behave roughly like a Poisson count,
which varies by about √mean from luck alone (here √6.7 ≈ 2.6). With only
about ten baseline days, the measured spread can come out smaller than
that. The fix was to divide by `max(std, √mean, 1)` (`spread_of` in
`pipeline/stats.py`). Walmart dropped to z = 1.66. When a stock's
baseline already varies by more than √mean, nothing changes.

I replayed 7 weekdays (Oct 30 to Nov 9; 276 stock-days, data as of
commit `8a242ff`). Spikes went from 56 to 51. In all 5 removed cases the
baseline was steadier than chance alone allows. For example, Tesla on
Nov 2 had 23 headlines against a usual 19, but a std of 1.4 where √19
is 4.4, so it scored z = 2.84; it now scores 0.92. The large stories
(Nvidia, Berkshire, Lilly) didn't move. Tests in `tests/test_stats.py`
cover the 0, 0, 1 case, a steady small-count case and a busy stock's
real spike.

## Run it locally

Needs Python 3.9 or newer.
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
python -m pipeline.run --backfill            # first time: searches 15 days per stock
python -m pipeline.run                       # later: re-searches just today
python -m http.server 8000 --directory site  # then open http://localhost:8000
python -m pytest                             # 52 tests, no network needed
```

On a Mac, double-clicking `Run TickerChatter.command` runs the pipeline and opens the site.

The tests cover spikes, flat days, tiny counts, missing days, empty input,
duplicate headlines, time-zone and daylight-saving edges, the 100-result cap,
and a regression test for the 70% bug. They run on every push, and the hourly
deploy waits for them to pass.

Counts measure attention, not whether the news is good or bad. Nothing
here is trading advice.
