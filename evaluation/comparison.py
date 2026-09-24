"""Adoption rule for a candidate prompt, compared question by question."""

from collections.abc import Sequence
import dataclasses
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

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError
