"""TextChunker backed by LangChain's RecursiveCharacterTextSplitter."""

from app.domain import rag
from app.ports import text_chunker

STRATEGY = "sentence"


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
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def split(self, page: rag.SourcePage) -> list[rag.Chunk]:  # noqa: DOC501, DOC503
        """Splits ``page`` into chunks that are exact slices of its text.

        Args:
            page: The page to split.

        Returns:
            The chunks in page order, each carrying its offsets and page.
        """
        raise NotImplementedError
