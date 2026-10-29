"""Spike S6 (TRD §15, ADR-014): is the reranker fast enough on this machine's CPU?

Scores ``--pairs`` (question, ~250-token passage) pairs ``--runs`` times after a warm-up
and prints model load time and p50/p95 latency. Exits 1 if p50 exceeds the budget.

Usage: ``uv run python scripts/time_reranker.py [--model NAME] [--pairs 20] [--runs 10]``
"""

import argparse
import statistics
import sys
import time

from sentence_transformers import CrossEncoder

from app.infrastructure.settings import load_settings

BUDGET_SECONDS = 2.0
PASSAGE_TOKENS = 250
QUESTION = "Who chairs the board?"
SENTENCE = "The committee reviewed the quarterly results and discussed operational costs. "


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="cross-encoder (default: DOCINTEL_RERANKER_MODEL)")
    parser.add_argument("--pairs", type=int, default=20)
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    model_name = args.model or load_settings().reranker_model

    started = time.perf_counter()
    model = CrossEncoder(model_name, device="cpu")
    load_seconds = time.perf_counter() - started

    passage = SENTENCE
    while len(model.tokenizer.encode(passage)) < PASSAGE_TOKENS:
        passage += SENTENCE
    pairs = [(QUESTION, passage)] * args.pairs

    model.predict(pairs)  # warm-up
    durations = []
    for _ in range(args.runs):
        started = time.perf_counter()
        model.predict(pairs)
        durations.append(time.perf_counter() - started)

    p50 = statistics.median(durations)
    p95 = statistics.quantiles(durations, n=20)[-1] if len(durations) > 1 else p50
    print(f"model {model_name}")
    print(f"load {load_seconds:.1f} s · {args.pairs} pairs × {PASSAGE_TOKENS} tokens")
    print(f"p50 {p50:.2f} s · p95 {p95:.2f} s · budget {BUDGET_SECONDS:.1f} s")
    return 0 if p50 <= BUDGET_SECONDS else 1


if __name__ == "__main__":
    sys.exit(main())
