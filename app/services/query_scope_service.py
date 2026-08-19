"""Conservative detection of explicit retrieval scope in user questions."""

import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from app.models.ingestion import DocumentType
from app.models.retrieval import QueryScope

logger = logging.getLogger(__name__)

DOCUMENT_TYPE_ALIASES: Mapping[DocumentType, tuple[str, ...]] = {
    DocumentType.MEMO: ("company memo", "memorandum", "memo"),
    DocumentType.MEETING_MINUTES: ("meeting minutes", "board minutes"),
    DocumentType.RESEARCH_REPORT: ("research report", "annual report"),
}
QUOTED_PDF_PATTERN = re.compile(
    r"(?P<quote>['\"])(?P<filename>[^'\"\r\n]{1,255}?\.pdf)(?P=quote)",
    flags=re.IGNORECASE,
)
UNQUOTED_PDF_PATTERN = re.compile(
    r"(?<![\w./\\-])(?P<filename>[\w][\w.-]{0,250}\.pdf)(?![\w.-])",
    flags=re.IGNORECASE,
)


class ExplicitQueryScopeService:
    """Extract only unambiguous filenames and known document-type phrases."""

    def __init__(
        self,
        aliases: Mapping[DocumentType, Sequence[str]] = DOCUMENT_TYPE_ALIASES,
    ) -> None:
        self._aliases = {
            document_type: tuple(
                self._normalize_words(alias) for alias in type_aliases
            )
            for document_type, type_aliases in aliases.items()
        }

    def detect(self, question: str) -> QueryScope:
        """Return explicit metadata constraints, or no constraint when ambiguous."""

        filename = self._detect_filename(question)
        document_type = self._detect_document_type(question)
        scope = QueryScope(filename=filename, document_type=document_type)
        logger.info(
            "Explicit query scope detected: has_filename=%s, document_type=%s",
            filename is not None,
            document_type.value if document_type is not None else None,
        )
        return scope

    def _detect_filename(self, question: str) -> str | None:
        quoted_matches = list(QUOTED_PDF_PATTERN.finditer(question))
        masked_question = QUOTED_PDF_PATTERN.sub(
            lambda match: " " * len(match.group(0)),
            question,
        )
        raw_matches = [
            match.group("filename") for match in quoted_matches
        ] + [
            match.group("filename")
            for match in UNQUOTED_PDF_PATTERN.finditer(masked_question)
        ]
        filenames = self._unique_filenames(raw_matches)
        if len(filenames) == 1:
            return filenames[0]
        if len(filenames) > 1:
            logger.info(
                "Filename scope ignored: question contains multiple filenames"
            )
        return None

    def _detect_document_type(self, question: str) -> DocumentType | None:
        normalized_question = f" {self._normalize_words(question)} "
        matches = {
            document_type
            for document_type, aliases in self._aliases.items()
            if any(f" {alias} " in normalized_question for alias in aliases)
        }
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1:
            logger.info(
                "Document-type scope ignored: question contains conflicting types"
            )
        return None

    @staticmethod
    def _unique_filenames(raw_filenames: Sequence[str]) -> list[str]:
        filenames: dict[str, str] = {}
        for raw_filename in raw_filenames:
            filename = PurePosixPath(raw_filename.replace("\\", "/")).name.strip()
            if not filename or len(filename) > 255:
                continue
            filenames.setdefault(filename.casefold(), filename)
        return list(filenames.values())

    @staticmethod
    def _normalize_words(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(re.sub(r"[\W_]+", " ", normalized).split())
