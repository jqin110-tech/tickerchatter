"""Run FinBERT, a pretrained finance sentiment model, on the sample.

    pip install -r requirements-ml.txt
    python -m sentiment.finbert_baseline

Reads eval/sentiment_sample.csv and writes eval/finbert_predictions.csv:
the same rows plus FinBERT's guess and how sure it was.

FinBERT answers positive, negative or neutral. Those are renamed to our
labels: bullish, bearish, neither. It has never seen our headlines or our
labels, so its score is the baseline a fine-tuned model has to beat.
"""
import csv
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "eval" / "sentiment_sample.csv"
PREDICTIONS = ROOT / "eval" / "finbert_predictions.csv"

MODEL_NAME = "ProsusAI/finbert"
OUR_LABEL = {"positive": "bullish", "negative": "bearish", "neutral": "neither"}
BATCH_SIZE = 32   # headlines per pass through the model; only affects speed


def predict(titles: list[str], tokenizer, model) -> list[tuple[str, float]]:
    """FinBERT's label and confidence (0 to 1) for each title."""
    results = []
    for start in range(0, len(titles), BATCH_SIZE):
        batch = titles[start:start + BATCH_SIZE]
        # Text -> numbers. Short titles are padded so the batch is a rectangle.
        inputs = tokenizer(batch, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():   # we are only predicting, not training
            logits = model(**inputs).logits
        # Three raw scores per title -> three probabilities that add up to 1.
        probabilities = torch.softmax(logits, dim=1)
        confidences, class_ids = probabilities.max(dim=1)
        for confidence, class_id in zip(confidences, class_ids):
            finbert_label = model.config.id2label[class_id.item()]
            results.append((OUR_LABEL[finbert_label], round(confidence.item(), 3)))
    return results


def main() -> None:
    with SAMPLE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    model.eval()   # prediction mode

    predictions = predict([row["title"] for row in rows], tokenizer, model)
    for row, (label, confidence) in zip(rows, predictions):
        row["finbert_label"] = label
        row["finbert_confidence"] = confidence

    with PREDICTIONS.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    for label, _ in predictions:
        counts[label] = counts.get(label, 0) + 1
    print(f"FinBERT labelled {len(rows)} headlines: {counts} -> {PREDICTIONS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
