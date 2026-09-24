"""Rules that turn retrieved chunks and a model completion into an answer."""

from collections.abc import Sequence
import dataclasses
import re
import string

from app.domain import rag

_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_PUNCTUATION = str.maketrans("", "", string.punctuation)


@dataclasses.dataclass(frozen=True, slots=True)
class Answer:
    """An answer and the retrieved chunks it rests on.

    Attributes:
        text: The answer shown to the user; the refusal sentence when
            ``refused``.
        sources: References to retrieved chunks, never to anything else.
        refused: Whether the passages did not contain the answer.
        cited: Whether ``sources`` come from the model's citation markers;
            ``False`` when every retrieved chunk is listed as a fallback.
    """

    text: str
    sources: tuple[str, ...]
    refused: bool
    cited: bool


def refused(refusal: str) -> Answer:
    """Builds the answer returned when the documents do not answer.

    Args:
        refusal: The refusal sentence the prompt asks the model to use.

    Returns:
        A refusal that cites nothing.
    """
    return Answer(text=refusal, sources=(), refused=True, cited=False)


def source_reference(chunk: rag.Chunk) -> str:
    """Formats the reference of one chunk as returned in ``sources``.

    The page fragment is 1-based, as ``#page=`` is defined for PDFs, while
    chunks store 0-based page numbers.

    Args:
        chunk: A retrieved chunk.

    Returns:
        ``<document_key>#page=<page_number + 1>&chunk=<chunk_index>``.
    """
    return (
        f"{chunk.document_key}#page={chunk.page_number + 1}"
        f"&chunk={chunk.chunk_index}"
    )


def passages(chunks: Sequence[rag.Chunk]) -> list[rag.Passage]:
    """Numbers the retrieved chunks for the prompt.

    Passages are numbered from 1 in rank order, so a ``[n]`` marker in the
    completion points at ``chunks[n - 1]``. Bracketed numbers inside chunk
    text become parenthesised, so text in a document cannot pose as a
    citation marker.

    Args:
        chunks: The retrieved chunks, best first.

    Returns:
        One passage per chunk, with a 1-based page.
    """
    return [
        rag.Passage(
            number=number,
            document_key=chunk.document_key,
            page=chunk.page_number + 1,
            text=_MARKER.sub(r"(\1)", chunk.text),
        )
        for number, chunk in enumerate(chunks, start=1)
    ]


def read_answer(
    completion: str, chunks: Sequence[rag.Chunk], refusal: str
) -> Answer:
    """Interprets a model completion against the chunks it was shown.

    A completion containing ``refusal`` anywhere (case and punctuation
    ignored) is a refusal and cites nothing. Otherwise the ``[n]`` and
    ``[n, m]`` markers that point at a shown passage become the sources,
    deduplicated in the order first cited. A completion with no such marker
    lists every shown chunk instead.

    Args:
        completion: The model's text.
        chunks: The chunks in the order they were numbered in the prompt.
        refusal: The refusal sentence the prompt asks the model to use.

    Returns:
        The answer and its sources.
    """
    if _normalize(refusal) in _normalize(completion):
        return refused(refusal)
    cited: list[int] = []
    for group in _MARKER.findall(completion):
        for number in (int(part) for part in group.split(",")):
            if 1 <= number <= len(chunks) and number not in cited:
                cited.append(number)
    if not cited:
        return Answer(
            text=completion,
            sources=tuple(source_reference(chunk) for chunk in chunks),
            refused=False,
            cited=False,
        )
    return Answer(
        text=completion,
        sources=tuple(source_reference(chunks[n - 1]) for n in cited),
        refused=False,
        cited=True,
    )


def _normalize(text: str) -> str:
    """Casefolds ``text``, drops punctuation and collapses whitespace.

    Args:
        text: Any text.

    Returns:
        The comparable form.
    """
    return " ".join(text.casefold().translate(_PUNCTUATION).split())
