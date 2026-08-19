"""Deterministic document-structure recognition over OCR output."""

import re
from dataclasses import dataclass, field

from app.config import Settings
from app.models.domain import OCRDocument, OCRPage
from app.models.ingestion import (
    DocumentElement,
    DocumentElementType,
    DocumentSection,
    StructuredDocument,
)
from app.services.errors import DocumentStructureError

NUMBERED_ITEM_PATTERN = re.compile(r"^\d+\.\s+(.+)$")
BULLET_ITEM_PATTERN = re.compile(r"^[-•]\s+\S")
HEADER_FIELD_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z ]{0,30}:(?:\s+\S.*)?$"
)
COLON_SECTION_LABELS = frozenset({"attendees", "absent"})


@dataclass(frozen=True, slots=True)
class _OCRLine:
    text: str
    page_number: int
    paragraph_key: tuple[int, int, int]


@dataclass(slots=True)
class _ElementBuilder:
    element_type: DocumentElementType
    text_parts: list[str]
    paragraph_key: tuple[int, int, int]
    page_start: int
    page_end: int

    def append(self, line: _OCRLine) -> None:
        self.text_parts.append(line.text)
        self.page_end = line.page_number

    def build(self) -> DocumentElement:
        return DocumentElement(
            element_type=self.element_type,
            text=" ".join(self.text_parts),
            page_start=self.page_start,
            page_end=self.page_end,
        )


@dataclass(slots=True)
class _SectionBuilder:
    heading: str | None
    heading_page: int
    elements: list[DocumentElement] = field(default_factory=list)

    def build(self) -> DocumentSection:
        pages = [self.heading_page]
        pages.extend(element.page_start for element in self.elements)
        pages.extend(element.page_end for element in self.elements)
        return DocumentSection(
            heading=self.heading,
            elements=tuple(self.elements),
            page_start=min(pages),
            page_end=max(pages),
        )


class OCRDocumentStructureService:
    """Recognize simple business-document structure without an LLM."""

    def __init__(self, settings: Settings) -> None:
        self._max_heading_words = settings.structure_max_heading_words

    def parse(self, document: OCRDocument) -> StructuredDocument:
        """Convert OCR lines into a title and flat semantic sections."""

        lines = [
            line
            for page in document.pages
            for line in self._extract_lines(page)
            if line.text
        ]
        if not lines:
            raise DocumentStructureError("OCR did not produce readable text")

        title_line = lines[0]
        current_section = _SectionBuilder(
            heading=None,
            heading_page=title_line.page_number,
        )
        sections: list[DocumentSection] = []
        current_element: _ElementBuilder | None = None

        def flush_element() -> None:
            nonlocal current_element
            if current_element is not None:
                current_section.elements.append(current_element.build())
                current_element = None

        def flush_section() -> None:
            if current_section.heading is not None or current_section.elements:
                sections.append(current_section.build())

        for line in lines[1:]:
            if self._is_heading(line.text):
                flush_element()
                flush_section()
                current_section = _SectionBuilder(
                    heading=line.text,
                    heading_page=line.page_number,
                )
                continue

            element_type = self._element_type(line.text)
            continues_current = (
                current_element is not None
                and current_element.paragraph_key == line.paragraph_key
                and (
                    (
                        current_element.element_type
                        == DocumentElementType.PARAGRAPH
                        and element_type == DocumentElementType.PARAGRAPH
                    )
                    or (
                        current_element.element_type
                        in {
                            DocumentElementType.HEADER_FIELD,
                            DocumentElementType.LIST_ITEM,
                        }
                        and element_type == DocumentElementType.PARAGRAPH
                    )
                )
            )
            if continues_current:
                current_element.append(line)
                continue

            flush_element()
            current_element = _ElementBuilder(
                element_type=element_type,
                text_parts=[line.text],
                paragraph_key=line.paragraph_key,
                page_start=line.page_number,
                page_end=line.page_number,
            )

        flush_element()
        flush_section()

        return StructuredDocument(
            title=title_line.text,
            sections=tuple(sections),
            page_count=len(document.pages),
        )

    def _extract_lines(self, page: OCRPage) -> list[_OCRLine]:
        if not page.words:
            return [
                _OCRLine(
                    text=text.strip(),
                    page_number=page.page_number,
                    paragraph_key=(page.page_number, index, 0),
                )
                for index, text in enumerate(page.text.splitlines())
                if text.strip()
            ]

        grouped_words: dict[tuple[int, int, int], list[str]] = {}
        paragraph_keys: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        for word in page.words:
            line_key = (
                word.block_number,
                word.paragraph_number,
                word.line_number,
            )
            grouped_words.setdefault(line_key, []).append(word.text)
            paragraph_keys[line_key] = (
                page.page_number,
                word.block_number,
                word.paragraph_number,
            )

        return [
            _OCRLine(
                text=" ".join(words).strip(),
                page_number=page.page_number,
                paragraph_key=paragraph_keys[line_key],
            )
            for line_key, words in grouped_words.items()
        ]

    def _is_heading(self, text: str) -> bool:
        numbered_match = NUMBERED_ITEM_PATTERN.fullmatch(text)
        if numbered_match:
            return self._is_uppercase_heading(numbered_match.group(1))

        normalized_label = text.removesuffix(":").casefold()
        if normalized_label in COLON_SECTION_LABELS:
            return True
        if text.endswith(":") and normalized_label.endswith("division"):
            return True
        return self._is_uppercase_heading(text)

    def _is_uppercase_heading(self, text: str) -> bool:
        words = text.split()
        letters = [character for character in text if character.isalpha()]
        return (
            bool(letters)
            and len(words) <= self._max_heading_words
            and all(character.isupper() for character in letters)
        )

    @staticmethod
    def _element_type(text: str) -> DocumentElementType:
        if BULLET_ITEM_PATTERN.match(text) or NUMBERED_ITEM_PATTERN.match(text):
            return DocumentElementType.LIST_ITEM
        if HEADER_FIELD_PATTERN.match(text):
            return DocumentElementType.HEADER_FIELD
        return DocumentElementType.PARAGRAPH
