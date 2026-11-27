"""Label the sampled headlines by hand, one at a time.

    python -m sentiment.label

Shows each headline from eval/sentiment_sample.csv that has no label yet
and saves your answer to eval/sentiment_labels.csv straight away, so you
can quit (q) at any time and carry on later.

FinBERT's guesses are never shown here. Seeing them would pull your
answers towards the model you are about to judge.

The question for every headline: is this good or bad news for the stock
in brackets? The rules are in eval/LABELING_GUIDE.md.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "eval" / "sentiment_sample.csv"
LABELS = ROOT / "eval" / "sentiment_labels.csv"

KEYS = {"u": "bullish", "d": "bearish", "n": "neither"}
COLUMNS = ["id", "ticker", "title", "label"]


def read_rows(path: Path) -> list[dict]:
    """Every row of a CSV file, or an empty list if the file isn't there yet."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_label(row: dict, label: str) -> None:
    """Add one line to the labels file, with a header first if the file is new."""
    is_new = not LABELS.exists()
    with LABELS.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({"id": row["id"], "ticker": row["ticker"], "title": row["title"], "label": label})


def main() -> None:
    sample = read_rows(SAMPLE)
    done = {row["id"] for row in read_rows(LABELS)}
    todo = [row for row in sample if row["id"] not in done]
    print(f"{len(done)} of {len(sample)} labelled so far.")
    print("Keys: u = bullish (up), d = bearish (down), n = neither, q = quit. Press Enter after each.")

    for number, row in enumerate(todo, start=len(done) + 1):
        print(f"\n{number}/{len(sample)}  [{row['ticker']}]  {row['title']}  ({row['source']})")
        answer = ""
        while answer not in KEYS and answer != "q":
            answer = input("u / d / n / q > ").strip().lower()
        if answer == "q":
            break
        save_label(row, KEYS[answer])

    print(f"\nYour labels are in {LABELS.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
