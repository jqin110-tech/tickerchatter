# TickerChatter

Is the news obsessed with your stock today?

Type any company on the site and TickerChatter reads two weeks of headlines,
finds the ones that actually name it, counts them per day, and uses a
z-score to say whether today is unusual so far. It also tracks 40 big stocks every
hour so the front page always shows what's spiking.

## How the pieces fit

```
                      every hour                     when someone searches
                          │                                   │
pipeline/ (Python)  ◄─────┘          worker/ (Cloudflare) ◄───┘
  fetch.py    download headlines         worker.js  downloads 15 days of
  extract.py  find companies                        headlines for one company
  stats.py    daily counts + z-scores                       │
  live.py     one-company version   ──copied to──►  site/py/  ◄── Pyodide runs
  run.py      runs it all, writes JSON                           this Python in
          │                                                      the visitor's
          ▼                                                      browser
  site/data/latest.json  ──────────►  site/ (HTML, CSS, JS)
```

The same extract.py and stats.py run in GitHub Actions every hour and in
the visitor's browser during a search, so both always agree.

## Run it on your laptop

Double-click `Run TickerChatter.command`. It installs what's needed, collects
headlines, and opens the site at http://localhost:8000.

Or by hand:

```bash
source venv/bin/activate
pip install -r requirements.txt
python -m pipeline.run                     # first run searches 15 days, later runs just today
python -m http.server 8000 --directory site
```

Tests (they also run on GitHub before every deploy):

```bash
pip install -r requirements-dev.txt
python -m pytest
python -m pipeline.diagnose NVDA CVX       # what each day's search found
```

## How the score works

1. **One search per day.** For each stock, Google News is searched once per
   California day (`after:2026-11-09 before:2026-11-10`), because Google's
   date filters use Pacific time. A headline counts only if it was really
   published that day and names the company. For JPMorgan, Goldman Sachs
   and Bank of America, their analysts rating other companies ("JPMorgan
   downgrades Nike") doesn't count: that's news about Nike, not the bank.
   If this rule changes, every stored day is searched again under the new
   one (`COUNT_RULES` in `run.py`).
2. **Every day is searched the same way.** Past days are searched once after
   they end. Today is searched again every hour, and each new search
   replaces the last one instead of adding to it.
3. **Same hours.** Today isn't over, so at 3pm it's compared with each earlier
   day's headlines up to 3pm.
4. **Like with like.** Weekdays get about twice the news of weekends, so a
   weekday is compared with the weekdays in the last 14 days. Weekends are
   compared with all 14 days, because four weekend days is too few for a
   steady average.
5. **z-score.** `z = (today so far − usual) / wobble`. The wobble is the
   standard deviation of the baseline days, but never less than √usual
   (or 1). Headline counts behave roughly like a Poisson count, which
   swings by about √mean from luck alone. With only ~10 baseline days a
   quiet stock can have an unusually steady stretch, and then 11 headlines
   against a usual 6.5 looked like z = 4. With the floor it's z = 1.7.
   Busy stocks barely notice the floor, because their real wobble is
   already bigger than √mean. `z ≥ 2` is a spike, `z ≥ 1` is elevated.
6. **The 100-result cap.** Google returns at most 100 results per search. A
   capped day only says "at least 100", so a stock that hits the cap
   switches to a narrower query (`"Nvidia stock"` instead of `"Nvidia"`),
   with all 15 days searched again, so the window never mixes queries. If a
   baseline day is still capped, the stock shows "Too busy to score".
   A capped *today* is fine: the true count is even higher.

### Why it works this way

The first version searched 2-day ranges and compared rolling 24-hour
windows. The newest range always included a day that hadn't happened yet,
so for any stock busy enough to hit the cap, its 100 results were packed
into the last few hours. After the first backfill, 28 of 40 stocks showed
as spikes. A test (`tests/test_bias.py`) rebuilds that situation with a
perfectly steady fake stock: the old method gives z ≈ 5 in the evening,
the new one gives z ≈ 0. A fresh backfill with the fix gives 6 of 40
spikes, and the stories behind them are real (for example Berkshire
Hathaway right after its earnings).

Checking the first night's 8 spikes (2026-11-09) against the news found
4 clearly real (Nvidia's CEO probe, Broadcom +9%, Lilly's trial results,
Berkshire's earnings) and 3 false alarms: Walmart (11 headlines vs a usual
7, small-number luck), Bank of America (its analysts' notes about other
companies) and Costco (holiday shopping coverage building for weeks). The
√mean floor and the analyst-note rule above fixed the first two. Replaying
the 7 weekdays from Oct 30 to Nov 9, the floor alone cut spikes from 56 to
51, all of them small-count cases; no big story moved.

## Put it online (free)

1. Push this folder to a new GitHub repository called `tickerchatter`.
2. In the repo: Settings, Pages, set Source to "GitHub Actions".
3. Actions tab, "Update TickerChatter", "Run workflow".

The site goes live at `https://<your-username>.github.io/tickerchatter/` and
refreshes itself every hour.

## Turn on live search (free, about 5 minutes)

Without this, searches only work for the 40 tracked stocks.

1. Make a free account at cloudflare.com.
2. In Terminal:
   ```bash
   cd worker
   npx wrangler login
   npx wrangler deploy
   ```
3. It prints an address like `https://tickerchatter.<you>.workers.dev`.
   Paste it into `site/config.js` as `newsApi`, then commit and push.

## Known limits

- A company needs 3 comparable days with coverage before it gets a score,
  and a score built on fewer than 7 is marked "Early read".
- For about two thirds of the watchlist the broad query hits the 100 cap,
  so their counts come from the narrower `"Name stock"` query. That's a
  smaller, noisier sample, and the very busiest days can cap even that,
  which shows as "Too busy to score".
- Live search (worker) always uses the broad query, so very busy companies
  usually show "Too busy to score" there.
- Weekend scores are compared with all days, so weekend spikes need an
  unusually big story.
- Older days may be thinner in Google's index than recent ones. With one
  snapshot this can't be told apart from a genuinely quieter week; if it's
  real, it pushes scores slightly up.
- The hourly job makes one Google search per stock (plus Yahoo for the
  headline list). The first run, or any run after a stock switches query,
  makes up to 15 per stock.
- **Slow trends.** The usual level is a 14-day average, so a topic that
  builds for weeks (Costco and Walmart before the holidays) can stay
  "spiking" for days. A shorter baseline or a median was tried on the
  replay and didn't help (the median made it worse, 51 → 74 spikes), so
  this waits for more data.
- **Mentions aren't always about the company.** The analyst-note rule
  only covers the three banks. Shopping-deal headlines ("Walmart's best
  snow shovel deal") still count for retailers.
- Small counts are still noisy: on the narrow query some stocks get
  2-10 headlines a day, where a handful extra can be a spike.
- Name matching is case sensitive, so "apple" never counts, but a headline
  starting with "Apple pie" would.
- It measures attention, not whether news is good or bad, and it isn't
  trading advice.
