# TickerChatter

Is the news obsessed with your stock today?

Type any company on the site and TickerChatter reads two weeks of headlines,
finds the ones that actually name it, counts them per day, and uses a
z-score to say whether today is unusual. It also tracks 40 big stocks every
hour so the front page always shows what's spiking.

## How the pieces fit

```
                      every hour                     when someone searches
                          │                                   │
pipeline/ (Python)  ◄─────┘          worker/ (Cloudflare) ◄───┘
  fetch.py    download headlines         worker.js  downloads 15 days of
  extract.py  find companies                        headlines for one company
  stats.py    24h windows + z-scores                       │
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
python -m pipeline.run --backfill          # first time: 14 days of news
python -m http.server 8000 --directory site
```

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

- A company needs 5 days with coverage before it gets a score.
- Google News returns at most 100 results per search. Live search asks once
  per day to get around this, but the hourly job can undercount very heavily
  covered stocks until a couple of weeks of runs fill in.
- Name matching is case sensitive, so "apple" never counts, but a headline
  starting with "Apple pie" would.
- It measures attention, not whether news is good or bad, and it isn't
  trading advice.
