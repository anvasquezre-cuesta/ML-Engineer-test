"""Port that splits page text into chunks for embedding."""

import abc

from app.domain import rag


class TextChunker(abc.ABC):
    """Splits text into chunks without cutting words in half."""

    @abc.abstractmethod
    def split(self, page: rag.SourcePage) -> list[rag.Chunk]:
        """Splits ``page`` into chunks.

        Args:
            page: The page to split.

        Returns:
            The chunks in page order, each carrying its offsets and page.
        """
