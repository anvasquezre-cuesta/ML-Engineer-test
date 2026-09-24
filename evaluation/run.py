"""Runs the answer evaluation on the samples and writes a gated report."""

import asyncio
import dataclasses
import datetime
import pathlib
import statistics

from deepeval import metrics
from deepeval import test_case

from app import config
from app.adapters.cpu_runner import thread_runner
from app.adapters.langchain_llm import chat_models
from app.adapters.langchain_llm import llm
from app.adapters.langchain_prompts import prompts
from app.adapters.noop_observability import observability
from app.domain import answering
from app.service_layer import ask
from evaluation import answers
from evaluation import dataset
from evaluation import judge as judge_module
from evaluation import retrieval

CORRECTNESS = (
    pathlib.Path(__file__).parent / "prompts" / "answer_correctness.md"
)
# Excluded: "CEO" also appears in a chunk that is not its evidence.
LEGITIMATE_WITHOUT_EVIDENCE = frozenset({"cross-doc-margaret-thompson"})


@dataclasses.dataclass(frozen=True, slots=True)
class RunResult:
    """One pass over the sample questions.

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


async def evaluate(settings: config.Settings) -> tuple[list[RunResult], int]:
    """Answers and grades the sample questions ``settings.eval.runs`` times.

    Args:
        settings: The service configuration.

    Returns:
        One result per run, and the judge calls used.
    """
    index = await retrieval.index_samples(settings)
    shipped = prompts.LangChainPrompts(settings.prompts.directory)
    generator = llm.LangChainLlm(
        chat_models.build_chat_model(settings.llm),
        observability.NoopObservability(),
        settings.llm.deadline_s,
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
    questions = dataset.questions()
    slots = asyncio.Semaphore(settings.eval.concurrency)
    top_k = settings.qdrant.top_k

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
            faithfulness = metrics.FaithfulnessMetric(
                model=grader, include_reason=False
            )
            relevancy = metrics.AnswerRelevancyMetric(
                model=grader, include_reason=False
            )
            for metric in (correctness, faithfulness, relevancy):
                await metric.a_measure(case, _show_indicator=False)
            return {
                "correct": float(bool(correctness.success)),
                "uncited": float(not answer.refused and not answer.cited),
                "evidence": float(
                    answers.cites_evidence(answer, index.chunks, relevant)
                ),
                "faithfulness": float(faithfulness.score or 0.0),
                "relevancy": float(relevancy.score or 0.0),
            }

    async def withheld(question: dataset.Question) -> bool:
        async with slots:
            relevant = retrieval.relevant_chunks(question, index.chunks)
            pool = await index.search(question.question, top_k + len(relevant))
            shown = [c for c in pool if retrieval.chunk_id(c) not in relevant]
            shown = shown[:top_k]
            completion = await generator.complete(
                shipped.answer(question.question, answering.passages(shown))
            )
            read = answering.read_answer(completion, shown, shipped.refusal)
            return not read.refused

    starved = [
        q
        for q in questions
        if q.evidence and q.id not in LEGITIMATE_WITHOUT_EVIDENCE
    ]
    results = []
    for _ in range(settings.eval.runs):
        graded = await asyncio.gather(*(grade(q) for q in questions))
        wrong = await asyncio.gather(*(withheld(q) for q in starved))
        scored = [g for g in graded if "correct" in g]
        results.append(
            RunResult(
                correct=int(sum(g["correct"] for g in scored)),
                refused_unanswerable=int(
                    sum(g["refused"] for g in graded if "refused" in g)
                ),
                uncited=int(sum(g["uncited"] for g in scored)),
                evidence_cited=int(sum(g["evidence"] for g in scored)),
                wrong_without_evidence=sum(wrong),
                faithfulness=statistics.mean(g["faithfulness"] for g in scored),
                relevancy=statistics.mean(g["relevancy"] for g in scored),
            )
        )
    return results, grader.calls


def gates(results: list[RunResult], answerable: int) -> list[Gate]:
    """Checks every run against the answer quality thresholds.

    Args:
        results: One result per run.
        answerable: Number of answerable questions.

    Returns:
        One gate per threshold.
    """
    checks = [
        ("Correct answers", "correct", answerable - 1, ">="),
        ("Unanswerable refused", "refused_unanswerable", 2, ">="),
        ("Answers without a valid marker", "uncited", 1, "<="),
        ("Evidence chunk cited", "evidence_cited", answerable - 1, ">="),
        ("Answered without evidence", "wrong_without_evidence", 1, "<="),
        ("Faithfulness (mean)", "faithfulness", 0.9, ">="),
    ]
    out = []
    for name, field, limit, op in checks:
        values = [getattr(r, field) for r in results]
        ok = all(v >= limit if op == ">=" else v <= limit for v in values)
        shown = ", ".join(
            f"{v:.3f}" if isinstance(v, float) else str(v) for v in values
        )
        out.append(Gate(name, ok, f"{shown} (needs {op} {limit})"))
    return out


def report(
    results: list[RunResult],
    checked: list[Gate],
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
    relevancy = [r.relevancy for r in results]
    now = datetime.datetime.now(datetime.UTC)
    generator = (
        settings.llm.bedrock_model
        if settings.llm.provider == "bedrock"
        else settings.llm.openai_model
    )
    spread = max(relevancy) - min(relevancy)
    lines = [
        f"# Answer evaluation {now:%Y-%m-%d %H:%M} UTC",
        "",
        f"- Generator: `{generator}`",
        f"- Judge: `{settings.eval.judge_model}` ({calls} calls)",
        f"- top_k: {settings.qdrant.top_k}; runs: {len(results)}",
        "- Answer relevancy (markers stripped, report only): mean "
        f"{statistics.mean(relevancy):.3f}, spread {spread:.3f}",
        "",
        "| Gate | Per run | Result |",
        "|---|---|---|",
    ]
    lines += [
        f"| {g.name} | {g.detail} | {'PASS' if g.passed else 'FAIL'} |"
        for g in checked
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    """Runs the evaluation, writes the report and gates the exit code.

    Returns:
        0 when every gate passes, 1 otherwise.
    """
    settings = config.Settings()
    results, calls = asyncio.run(evaluate(settings))
    answerable = sum(1 for q in dataset.questions() if q.evidence)
    checked = gates(results, answerable)
    text = report(results, checked, settings, calls)
    settings.eval.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    (settings.eval.report_dir / f"answers-{stamp}.md").write_text(text)
    print(text)
    return 0 if all(g.passed for g in checked) else 1
