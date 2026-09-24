"""TextChunker backed by LangChain's RecursiveCharacterTextSplitter."""

import re

from langchain_text_splitters import character

from app.domain import rag
from app.ports import text_chunker

STRATEGY = "sentence"
SEPARATORS = ["\n\n", "\n", ". ", " "]


class SentenceTextChunker(text_chunker.TextChunker):
    """Splits at paragraph, line, sentence and word breaks, never inside words.

    A word longer than ``chunk_size`` becomes its own oversized chunk instead
    of being cut into characters.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        """Initializes the chunker.

        Args:
            chunk_size: Maximum chunk length in characters.
            chunk_overlap: Characters shared by consecutive chunks.
        """
        self._chunk_overlap = chunk_overlap
        # No "" separator: a word longer than chunk_size is never cut.
        self._splitter = character.RecursiveCharacterTextSplitter(
            separators=SEPARATORS,
            keep_separator="end",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def split(self, page: rag.SourcePage) -> list[rag.Chunk]:
        """Splits ``page`` into chunks that are exact slices of its text.

        Args:
            page: The page to split.

        Returns:
            The chunks in page order, each carrying its offsets and page.
        """
        return [
            rag.Chunk(
                document_key=page.document_key,
                content_hash=page.content_hash,
                page_number=page.page_number,
                chunk_index=index,
                start_char=start,
                end_char=end,
                text=page.text[start:end],
                strategy=STRATEGY,
            )
            for index, (start, end) in enumerate(self._spans(page.text))
        ]

    def _spans(self, text: str) -> list[tuple[int, int]]:
        """Locates each chunk the splitter produces in ``text``.

        LangChain's own ``add_start_index`` searches with ``str.find`` and can
        anchor a short chunk inside another word or on an earlier repeat. Here
        a match must sit on word boundaries, start after the previous chunk's
        start, and end after its end, since every chunk adds new text.

        Args:
            text: The page text.

        Returns:
            One ``(start, end)`` span per chunk, in page order.

        Raises:
            ValueError: If a chunk cannot be located, which would mean the
                splitter changed text it should only slice.
        """
        spans: list[tuple[int, int]] = []
        previous_start, previous_end = -1, 0
        for piece in self._splitter.split_text(text):
            body = piece.strip()
            if not body:
                continue
            pattern = re.compile(rf"(?<!\S){re.escape(body)}(?!\S)")
            earliest = previous_end - self._chunk_overlap
            position = max(previous_start + 1, earliest)
            match = pattern.search(text, position)
            while match is not None and match.end() <= previous_end:
                match = pattern.search(text, match.start() + 1)
            if match is None:
                raise ValueError("A chunk does not occur in the page text.")
            spans.append((match.start(), match.end()))
            previous_start, previous_end = match.span()
        return spans
