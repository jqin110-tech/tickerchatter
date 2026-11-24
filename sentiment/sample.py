"""Pick a random sample of saved headlines for the sentiment work.

    python -m sentiment.sample

Reads data/headlines.json (the pipeline's store) and writes
eval/sentiment_sample.csv: 600 headlines, one per row.

Only headlines that name exactly one tracked stock are used, so "is this
bullish or bearish?" has one clear answer. Headlines that name two or
more stocks (about 1 in 11) are left out for now.

The sample is saved to a file and committed because the store changes
every hour and deletes headlines after 45 days. The CSV is the frozen
copy that FinBERT, the hand labels and the fine-tuned model all share.
"""
import csv
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "headlines.json"
SAMPLE = ROOT / "eval" / "sentiment_sample.csv"

SAMPLE_SIZE = 600
SEED = 42   # any fixed number works; fixing it makes the "random" pick repeatable
COLUMNS = ["id", "ticker", "title", "source", "published"]


def single_ticker_headlines(store: dict) -> list[dict]:
    """One row per headline that names exactly one tracked stock."""
    rows = []
    for key, headline in store["headlines"].items():
        if len(headline["tickers"]) == 1:
            rows.append({
                "id": key,
                "ticker": headline["tickers"][0],
                "title": headline["title"],
                "source": headline["source"],
                "published": headline["published"],
            })
    return rows


def main() -> None:
    store = json.loads(STORE.read_text(encoding="utf-8"))
    candidates = single_ticker_headlines(store)
    # Sort first, so the same file always gives the same sample.
    candidates.sort(key=lambda row: row["id"])
    sample = random.Random(SEED).sample(candidates, SAMPLE_SIZE)

    with SAMPLE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(sample)
    print(f"Picked {len(sample)} of {len(candidates)} single-stock headlines -> {SAMPLE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
