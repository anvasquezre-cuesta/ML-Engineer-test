"""Structure-aware text chunking for OCR documents."""

from dataclasses import dataclass

from app.config import Settings
from app.models.ingestion import ChunkDraft, DocumentElement, StructuredDocument
from app.services.errors import DocumentChunkingError

NON_TERMINAL_ABBREVIATIONS = frozenset(
    {
        "dr.",
        "mr.",
        "mrs.",
        "ms.",
        "prof.",
        "sr.",
        "jr.",
        "e.g.",
        "i.e.",
    }
)


@dataclass(frozen=True, slots=True)
class _TextUnit:
    text: str
    page_start: int
    page_end: int

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class StructureAwareChunkingService:
    """Chunk at section and element boundaries before using text fallback."""

    def __init__(self, settings: Settings) -> None:
        self._max_words = settings.chunk_max_words

    def chunk(self, document: StructuredDocument) -> tuple[ChunkDraft, ...]:
        """Create chunks without crossing section boundaries or cutting words."""

        chunks: list[ChunkDraft] = []
        for section in document.sections:
            units = [
                unit
                for element in section.elements
                for unit in self._split_oversized_element(element)
            ]
            chunks.extend(
                self._pack_section(
                    units,
                    section_heading=section.heading,
                )
            )

        if not chunks:
            raise DocumentChunkingError(
                "structured document does not contain chunkable content"
            )
        return tuple(chunks)

    def _pack_section(
        self,
        units: list[_TextUnit],
        *,
        section_heading: str | None,
    ) -> list[ChunkDraft]:
        chunks: list[ChunkDraft] = []
        current_units: list[_TextUnit] = []
        current_word_count = 0

        def flush() -> None:
            nonlocal current_units, current_word_count
            if not current_units:
                return
            chunks.append(
                ChunkDraft(
                    text="\n".join(unit.text for unit in current_units),
                    section_heading=section_heading,
                    page_start=min(unit.page_start for unit in current_units),
                    page_end=max(unit.page_end for unit in current_units),
                )
            )
            current_units = []
            current_word_count = 0

        for unit in units:
            if current_units and current_word_count + unit.word_count > self._max_words:
                flush()
            current_units.append(unit)
            current_word_count += unit.word_count
        flush()
        return chunks

    def _split_oversized_element(self, element: DocumentElement) -> list[_TextUnit]:
        if len(element.text.split()) <= self._max_words:
            return [
                _TextUnit(
                    text=element.text,
                    page_start=element.page_start,
                    page_end=element.page_end,
                )
            ]

        sentences = self._sentences(element.text)
        units: list[_TextUnit] = []
        current_words: list[str] = []

        def flush() -> None:
            nonlocal current_words
            if current_words:
                units.append(
                    _TextUnit(
                        text=" ".join(current_words),
                        page_start=element.page_start,
                        page_end=element.page_end,
                    )
                )
                current_words = []

        for sentence in sentences:
            sentence_words = sentence.split()
            if len(sentence_words) > self._max_words:
                flush()
                for start in range(0, len(sentence_words), self._max_words):
                    units.append(
                        _TextUnit(
                            text=" ".join(
                                sentence_words[start : start + self._max_words]
                            ),
                            page_start=element.page_start,
                            page_end=element.page_end,
                        )
                    )
                continue

            if current_words and (
                len(current_words) + len(sentence_words) > self._max_words
            ):
                flush()
            current_words.extend(sentence_words)

        flush()
        return units

    @staticmethod
    def _sentences(text: str) -> list[str]:
        sentences: list[str] = []
        current_words: list[str] = []
        for word in text.split():
            current_words.append(word)
            normalized_word = word.rstrip("\"')]}»").casefold()
            ends_sentence = normalized_word.endswith((".", "!", "?"))
            if (
                ends_sentence
                and normalized_word not in NON_TERMINAL_ABBREVIATIONS
            ):
                sentences.append(" ".join(current_words))
                current_words = []
        if current_words:
            sentences.append(" ".join(current_words))
        return sentences
