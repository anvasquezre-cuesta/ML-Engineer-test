"""The shipped prompt files number passages the way answers are read back."""

from app import config
from app.adapters.langchain_prompts import prompts
from app.domain import answering
from app.domain import rag


def test_passage_numbers_match_the_markers_the_answer_is_read_with() -> None:
    first = rag.Chunk("memo.pdf", "h", 0, 0, 0, 20, "Robert Chen leads.", "t")
    footnoted = rag.Chunk(
        "report.pdf", "h", 1, 0, 0, 24, "Budget grew [3] in 2024.", "t"
    )
    shipped = prompts.LangChainPrompts(config.PromptSettings().directory)

    prompt = shipped.answer(
        "How did the budget change?", answering.passages([first, footnoted])
    )

    one = prompt.user.index('id="1"')
    two = prompt.user.index('id="2"')
    assert one < prompt.user.index("Robert Chen leads.") < two
    assert two < prompt.user.index("Budget grew (3) in 2024.")
    assert "[3]" not in prompt.user
    assert shipped.refusal in prompt.system
    refusal = answering.read_answer(shipped.refusal, [first], shipped.refusal)
    assert refusal.refused
