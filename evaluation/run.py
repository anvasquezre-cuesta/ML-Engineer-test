"""Runs the answer evaluation, writes a gated report and compares prompts."""

import asyncio
from collections.abc import Sequence
import dataclasses
import datetime
import json
import pathlib
import statistics
import time

from deepeval import metrics
from deepeval import test_case

from app import config
from app.adapters.cpu_runner import thread_runner
from app.adapters.langchain_llm import chat_models
from app.adapters.langchain_llm import llm as langchain_llm
from app.adapters.langchain_prompts import prompts
from app.adapters.noop_observability import observability
from app.domain import answering
from app.domain import rag
from app.ports import llm
from app.service_layer import ask
from evaluation import answers
from evaluation import comparison
from evaluation import dataset
from evaluation import judge as judge_module
from evaluation import retrieval

CORRECTNESS = (
    pathlib.Path(__file__).parent / "prompts" / "answer_correctness.md"
)
# Excluded: "CEO" also appears in a chunk that is not its evidence.
LEGITIMATE_WITHOUT_EVIDENCE = frozenset({"cross-doc-margaret-thompson"})
FAITHFULNESS_FLOOR = 0.9


@dataclasses.dataclass(frozen=True, slots=True)
class RunResult:
    """One pass over the verified sample questions.

    Attributes:
        correct: Answerable questions judged correct.
        refused_unanswerable: Unanswerable questions refused.
        uncited: Answerable questions answered without a valid marker.
        evidence_cited: Answerable questions citing an evidence chunk.
        wrong_without_evidence: Questions answered although every evidence
            chunk was withheld.
        faithfulness: Mean faithfulness over the answerable questions.
        relevancy: Mean answer relevancy, judged without markers.
    """

    correct: int
    refused_unanswerable: int
    uncited: int
    evidence_cited: int
    wrong_without_evidence: int
    faithfulness: float
    relevancy: float


@dataclasses.dataclass(frozen=True, slots=True)
class RewordedResult:
    """One pass over the reworded and near-miss questions.

    Attributes:
        false_refusals: Reworded questions refused.
        near_miss_answered: Near-miss questions answered.
        hedged: Completions that cite passages and also refuse.
        faithfulness: Mean faithfulness of the answered reworded questions;
            ``None`` when none was answered.
    """

    false_refusals: int
    near_miss_answered: int
    hedged: int
    faithfulness: float | None


@dataclasses.dataclass(frozen=True, slots=True)
class Run:
    """Everything one run measured.

    Attributes:
        samples: Results on the sample set, if it ran.
        reworded: Results on the reworded set, if it ran.
        outcomes: Per-question refusals, for comparing prompts.
    """

    samples: RunResult | None
    reworded: RewordedResult | None
    outcomes: list[comparison.Outcome]


@dataclasses.dataclass(frozen=True, slots=True)
class Gate:
    """A threshold every run must meet.

    Attributes:
        name: What is measured.
        passed: Whether every run met it.
        detail: The per-run values against the threshold.
    """

    name: str
    passed: bool
    detail: str


class PacedLlm(llm.Llm):
    """Spaces calls to stay under a provider's requests-per-minute limit."""

    def __init__(self, inner: llm.Llm, per_minute: int | None) -> None:
        """Initializes the wrapper.

        Args:
            inner: The model that answers.
            per_minute: Calls allowed per minute; ``None`` disables pacing.
        """
        self._inner = inner
        self._interval = 60.0 / per_minute if per_minute else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def complete(self, prompt: rag.LlmPrompt) -> str:
        """Waits for the next free slot, then answers.

        Args:
            prompt: System instructions and user message.

        Returns:
            The completion.
        """
        async with self._lock:
            wait = self._next - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next = time.monotonic() + self._interval
        return await self._inner.complete(prompt)


async def evaluate(settings: config.Settings) -> tuple[list[Run], int]:
    """Answers and grades the selected questions ``settings.eval.runs`` times.

    Args:
        settings: The service configuration.

    Returns:
        One result per run, and the judge calls used.
    """
    index = await retrieval.index_samples(settings)
    shipped = prompts.LangChainPrompts(settings.prompts.directory)
    generator = PacedLlm(
        langchain_llm.LangChainLlm(
            chat_models.build_chat_model(settings.llm),
            observability.NoopObservability(),
            settings.llm.deadline_s,
        ),
        settings.eval.requests_per_minute,
    )
    asker = ask.AskQuestion(
        index.dense,
        index.sparse,
        index.store,
        shipped,
        generator,
        thread_runner.ThreadCpuRunner(settings.cpu.max_concurrency),
        settings.qdrant.top_k,
    )
    grader = judge_module.Judge.for_settings(settings)
    criteria = CORRECTNESS.read_text(encoding="utf-8")
    sets = settings.eval.question_sets
    samples = dataset.questions() if "samples" in sets else []
    reworded = (
        dataset.reworded(settings.eval.split) if "reworded" in sets else []
    )
    starved = [
        q
        for q in samples
        if q.evidence and q.id not in LEGITIMATE_WITHOUT_EVIDENCE
    ]
    slots = asyncio.Semaphore(settings.eval.concurrency)
    top_k = settings.qdrant.top_k

    def faithfulness() -> metrics.FaithfulnessMetric:
        return metrics.FaithfulnessMetric(model=grader, include_reason=False)

    async def measure(
        metric: metrics.BaseMetric, case: test_case.LLMTestCase
    ) -> float:
        await metric.a_measure(case, _show_indicator=False)
        return float(metric.score or 0.0)

    async def complete(
        question: str, shown: Sequence[rag.Chunk]
    ) -> tuple[str, answering.Answer]:
        prompt = shipped.answer(question, answering.passages(shown))
        completion = await generator.complete(prompt)
        read = answering.read_answer(completion, shown, shipped.refusal)
        return completion, read

    async def grade(question: dataset.Question) -> dict[str, float]:
        async with slots:
            answer = await asker(question.question)
            if not question.evidence:
                return {"refused": float(answer.refused)}
            shown = await index.search(question.question, top_k)
            relevant = retrieval.relevant_chunks(question, index.chunks)
            case = test_case.LLMTestCase(
                input=question.question,
                actual_output=answers.strip_markers(answer.text),
                expected_output=question.answer,
                retrieval_context=[chunk.text for chunk in shown],
            )
            correctness = metrics.GEval(
                name="Correctness",
                criteria=criteria,
                evaluation_params=[
                    test_case.LLMTestCaseParams.INPUT,
                    test_case.LLMTestCaseParams.ACTUAL_OUTPUT,
                    test_case.LLMTestCaseParams.EXPECTED_OUTPUT,
                ],
                model=grader,
            )
            await measure(correctness, case)
            relevancy = metrics.AnswerRelevancyMetric(
                model=grader, include_reason=False
            )
            return {
                "correct": float(bool(correctness.success)),
                "uncited": float(not answer.refused and not answer.cited),
                "evidence": float(
                    answers.cites_evidence(answer, index.chunks, relevant)
                ),
                "faithfulness": await measure(faithfulness(), case),
                "relevancy": await measure(relevancy, case),
            }

    async def withheld(question: dataset.Question) -> comparison.Outcome:
        async with slots:
            relevant = retrieval.relevant_chunks(question, index.chunks)
            pool = await index.search(question.question, top_k + len(relevant))
            shown = [c for c in pool if retrieval.chunk_id(c) not in relevant]
            shown = shown[:top_k]
            completion, read = await complete(question.question, shown)
            return comparison.Outcome(
                question.id,
                "withheld",
                read.refused,
                answers.hedged(completion, shown, shipped.refusal),
            )

    async def rephrased(
        question: dataset.SplitQuestion,
    ) -> tuple[comparison.Outcome, float | None]:
        async with slots:
            shown = await index.search(question.question, top_k)
            completion, read = await complete(question.question, shown)
            kind: comparison.Kind = (
                "reworded" if question.evidence else "near_miss"
            )
            outcome = comparison.Outcome(
                question.id,
                kind,
                read.refused,
                answers.hedged(completion, shown, shipped.refusal),
            )
            if kind == "near_miss" or read.refused:
                return outcome, None
            case = test_case.LLMTestCase(
                input=question.question,
                actual_output=answers.strip_markers(read.text),
                retrieval_context=[chunk.text for chunk in shown],
            )
            return outcome, await measure(faithfulness(), case)

    runs = []
    for _ in range(settings.eval.runs):
        graded = await asyncio.gather(*(grade(q) for q in samples))
        without = await asyncio.gather(*(withheld(q) for q in starved))
        rephrasings = await asyncio.gather(*(rephrased(q) for q in reworded))
        runs.append(
            Run(
                samples=_samples_result(graded, without) if samples else None,
                reworded=_reworded_result(rephrasings) if reworded else None,
                outcomes=[*without, *(o for o, _ in rephrasings)],
            )
        )
    return runs, grader.calls


def _samples_result(
    graded: Sequence[dict[str, float]],
    without: Sequence[comparison.Outcome],
) -> RunResult:
    """Sums one run over the sample set.

    Args:
        graded: Scores per sample question.
        without: Outcomes with the evidence withheld.

    Returns:
        The run's sample results.
    """
    scored = [g for g in graded if "correct" in g]
    return RunResult(
        correct=int(sum(g["correct"] for g in scored)),
        refused_unanswerable=int(
            sum(g["refused"] for g in graded if "refused" in g)
        ),
        uncited=int(sum(g["uncited"] for g in scored)),
        evidence_cited=int(sum(g["evidence"] for g in scored)),
        wrong_without_evidence=sum(not o.refused for o in without),
        faithfulness=statistics.mean(g["faithfulness"] for g in scored),
        relevancy=statistics.mean(g["relevancy"] for g in scored),
    )


def _reworded_result(
    results: Sequence[tuple[comparison.Outcome, float | None]],
) -> RewordedResult:
    """Sums one run over the reworded set.

    Args:
        results: Outcome and faithfulness per question.

    Returns:
        The run's reworded results.
    """
    faithful = [score for _, score in results if score is not None]
    return RewordedResult(
        false_refusals=sum(
            o.refused for o, _ in results if o.kind == "reworded"
        ),
        near_miss_answered=sum(
            not o.refused for o, _ in results if o.kind == "near_miss"
        ),
        hedged=sum(o.hedged for o, _ in results),
        faithfulness=statistics.mean(faithful) if faithful else None,
    )


def gates(results: Sequence[Run], answerable: int) -> list[Gate]:
    """Checks every run against the absolute answer quality thresholds.

    The reworded set has no absolute gate besides faithfulness; its refusals
    are judged against the shipped prompt by ``compare``.

    Args:
        results: One result per run.
        answerable: Number of answerable sample questions.

    Returns:
        One gate per threshold on the sets that ran.
    """
    samples = [r.samples for r in results if r.samples]
    faithful = [
        r.reworded.faithfulness
        for r in results
        if r.reworded and r.reworded.faithfulness is not None
    ]
    checks: list[tuple[str, Sequence[float], float, str]] = []
    if samples:
        checks = [
            (
                "Correct answers",
                [s.correct for s in samples],
                answerable - 1,
                ">=",
            ),
            (
                "Unanswerable refused",
                [s.refused_unanswerable for s in samples],
                2,
                ">=",
            ),
            (
                "Answers without a valid marker",
                [s.uncited for s in samples],
                1,
                "<=",
            ),
            (
                "Evidence chunk cited",
                [s.evidence_cited for s in samples],
                answerable - 1,
                ">=",
            ),
            (
                "Answered without evidence",
                [s.wrong_without_evidence for s in samples],
                1,
                "<=",
            ),
            (
                "Faithfulness (mean)",
                [s.faithfulness for s in samples],
                FAITHFULNESS_FLOOR,
                ">=",
            ),
        ]
    if faithful:
        checks.append(
            (
                "Faithfulness on reworded answers (mean)",
                faithful,
                FAITHFULNESS_FLOOR,
                ">=",
            )
        )
    return [_gate(*check) for check in checks]


def _gate(name: str, values: Sequence[float], limit: float, op: str) -> Gate:
    """Checks one threshold on every run.

    Args:
        name: What is measured.
        values: One value per run.
        limit: The threshold.
        op: ``>=`` or ``<=``.

    Returns:
        The gate.
    """
    ok = all(v >= limit if op == ">=" else v <= limit for v in values)
    shown = ", ".join(
        f"{v:.3f}" if isinstance(v, float) else str(v) for v in values
    )
    return Gate(name, ok, f"{shown} (needs {op} {limit})")


def report(
    results: Sequence[Run],
    checked: Sequence[Gate],
    settings: config.Settings,
    calls: int,
) -> str:
    """Formats the evaluation as Markdown.

    Args:
        results: One result per run.
        checked: The gates.
        settings: The configuration evaluated.
        calls: Judge calls used.

    Returns:
        The report.
    """
    now = datetime.datetime.now(datetime.UTC)
    lines = [
        f"# Answer evaluation {now:%Y-%m-%d %H:%M} UTC",
        "",
        f"- Generator: `{_generator(settings)}`",
        f"- Prompts: `{settings.prompts.directory}`",
        f"- Judge: `{settings.eval.judge_model}` ({calls} calls)",
        f"- top_k: {settings.qdrant.top_k}; runs: {len(results)}; "
        f"sets: {', '.join(settings.eval.question_sets)} "
        f"(reworded split: {settings.eval.split})",
    ]
    relevancy = [r.samples.relevancy for r in results if r.samples]
    if relevancy:
        spread = max(relevancy) - min(relevancy)
        lines.append(
            "- Answer relevancy (markers stripped, report only): mean "
            f"{statistics.mean(relevancy):.3f}, spread {spread:.3f}"
        )
    rephrased = [r.reworded for r in results if r.reworded]
    if rephrased:
        lines.append(
            "- Reworded set per run (compare against the shipped prompt): "
            "false refusals "
            f"{', '.join(str(r.false_refusals) for r in rephrased)}; "
            "near-miss answered "
            f"{', '.join(str(r.near_miss_answered) for r in rephrased)}; "
            f"hedged {', '.join(str(r.hedged) for r in rephrased)}"
        )
    lines += ["", "| Gate | Per run | Result |", "|---|---|---|"]
    lines += [
        f"| {g.name} | {g.detail} | {'PASS' if g.passed else 'FAIL'} |"
        for g in checked
    ]
    return "\n".join(lines) + "\n"


def compare(baseline: pathlib.Path, candidate: pathlib.Path) -> int:
    """Prints the adoption verdict of a candidate over the shipped prompt.

    Only questions present in both outcome files are compared, so a run on
    one split can be compared with a run on all of them.

    Args:
        baseline: Outcomes file of the shipped prompt.
        candidate: Outcomes file of the candidate prompt.

    Returns:
        0 when the candidate meets every condition, 1 otherwise.
    """
    before = _load_outcomes(baseline)
    after = _load_outcomes(candidate)
    shared = {o.question_id for run in before for o in run} & {
        o.question_id for run in after for o in run
    }
    checks = comparison.verdict(
        [[o for o in run if o.question_id in shared] for run in before],
        [[o for o in run if o.question_id in shared] for run in after],
    )
    lines = [
        f"Baseline: {baseline}",
        f"Candidate: {candidate}",
        f"Questions compared: {len(shared)}",
        "",
        "| Condition | Detail | Result |",
        "|---|---|---|",
    ]
    lines += [
        f"| {c.name} | {c.detail} | {'PASS' if c.passed else 'FAIL'} |"
        for c in checks
    ]
    print("\n".join(lines))
    return 0 if all(c.passed for c in checks) else 1


def main(argv: Sequence[str]) -> int:
    """Runs the evaluation, or compares two outcome files.

    Args:
        argv: Command-line arguments: none, or
            ``compare <baseline.json> <candidate.json>``.

    Returns:
        0 when every gate or adoption condition passes, 1 otherwise.
    """
    if argv[:1] == ["compare"] and len(argv) == 3:
        return compare(pathlib.Path(argv[1]), pathlib.Path(argv[2]))
    settings = config.Settings()
    results, calls = asyncio.run(evaluate(settings))
    answerable = sum(1 for q in dataset.questions() if q.evidence)
    checked = gates(results, answerable)
    text = report(results, checked, settings, calls)
    out = settings.eval.report_dir
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    (out / f"answers-{stamp}.md").write_text(text, encoding="utf-8")
    outcomes = {
        "generator": _generator(settings),
        "prompts": str(settings.prompts.directory),
        "runs": [[dataclasses.asdict(o) for o in r.outcomes] for r in results],
    }
    (out / f"outcomes-{stamp}.json").write_text(
        json.dumps(outcomes, indent=1), encoding="utf-8"
    )
    print(text)
    print(f"Outcomes: {out / f'outcomes-{stamp}.json'}")
    return 0 if all(g.passed for g in checked) else 1


def _generator(settings: config.Settings) -> str:
    """Names the model that answered.

    Args:
        settings: The configuration evaluated.

    Returns:
        The Bedrock or OpenAI model id.
    """
    if settings.llm.provider == "bedrock":
        return settings.llm.bedrock_model
    return settings.llm.openai_model


def _load_outcomes(path: pathlib.Path) -> list[list[comparison.Outcome]]:
    """Reads the per-run outcomes written by an evaluation.

    Args:
        path: The outcomes file.

    Returns:
        One list of outcomes per run.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [[comparison.Outcome(**o) for o in run] for run in raw["runs"]]
