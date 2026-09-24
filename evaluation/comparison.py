"""Adoption rule for a candidate prompt, compared question by question."""

from collections.abc import Sequence
import dataclasses
import statistics
from typing import Literal

Kind = Literal["reworded", "near_miss", "withheld"]


@dataclasses.dataclass(frozen=True, slots=True)
class Outcome:
    """How one prompt handled one question in one run.

    Attributes:
        question_id: The question.
        kind: ``reworded`` must be answered; ``near_miss`` and ``withheld``
            (evidence removed) must be refused.
        refused: Whether the parsed answer is a refusal.
        hedged: Whether the completion cited passages and also refused.
    """

    question_id: str
    kind: Kind
    refused: bool
    hedged: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Check:
    """One condition of the adoption rule.

    Attributes:
        name: What is required.
        passed: Whether the candidate meets it.
        detail: The questions or counts behind the result.
    """

    name: str
    passed: bool
    detail: str


def verdict(
    baseline: Sequence[Sequence[Outcome]],
    candidate: Sequence[Sequence[Outcome]],
) -> list[Check]:
    """Checks a candidate prompt against the shipped one.

    Args:
        baseline: One list of outcomes per run of the shipped prompt.
        candidate: One list of outcomes per run of the candidate.

    Returns:
        One check per condition; the candidate is adopted only if all pass.
    """
    before = _majority_refused(baseline)
    after = _majority_refused(candidate)
    kinds = {o.question_id: o.kind for run in baseline for o in run}
    reworded = sorted(q for q, kind in kinds.items() if kind == "reworded")
    must_refuse = sorted(q for q in kinds if q not in reworded)
    refused_before = sum(before[q] for q in reworded)
    refused_after = sum(after[q] for q in reworded)
    newly_refused = [q for q in reworded if after[q] and not before[q]]
    newly_answered = [q for q in must_refuse if before[q] and not after[q]]
    hedged_before = _mean_hedged(baseline)
    hedged_after = _mean_hedged(candidate)
    return [
        Check(
            "False refusals on reworded questions go down",
            refused_after < refused_before,
            f"{refused_before} -> {refused_after}",
        ),
        Check(
            "No reworded question is newly refused",
            not newly_refused,
            ", ".join(newly_refused) or "none",
        ),
        Check(
            "No question that must be refused is newly answered",
            not newly_answered,
            ", ".join(newly_answered) or "none",
        ),
        Check(
            "Hedged answers do not increase",
            hedged_after <= hedged_before,
            f"{hedged_before:.1f} -> {hedged_after:.1f} per run",
        ),
    ]


def _majority_refused(runs: Sequence[Sequence[Outcome]]) -> dict[str, bool]:
    """Reads each question as refused when most runs refused it.

    Args:
        runs: One list of outcomes per run.

    Returns:
        Whether each question was refused by the majority of runs.
    """
    votes: dict[str, list[bool]] = {}
    for run in runs:
        for outcome in run:
            votes.setdefault(outcome.question_id, []).append(outcome.refused)
    return {q: sum(v) * 2 > len(v) for q, v in votes.items()}


def _mean_hedged(runs: Sequence[Sequence[Outcome]]) -> float:
    """Averages the number of hedged answers per run.

    Args:
        runs: One list of outcomes per run.

    Returns:
        The mean count.
    """
    return statistics.mean(sum(o.hedged for o in run) for run in runs)
