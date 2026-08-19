"""Construct auditable sources after verifying the LLM's inline citations."""

import logging
import re

from app.models.retrieval import GeneratedAnswer, VerifiedAnswer, VerifiedSource
from app.services.errors import SourceVerificationError

logger = logging.getLogger(__name__)

_SOURCE_LIKE_GROUP = re.compile(r"\[([^\[\]\r\n]*\bS\d+\b[^\[\]\r\n]*)\]")
_VALID_SOURCE_GROUP = re.compile(r"S[1-9]\d*(?:\s*,\s*S[1-9]\d*)*")
_SOURCE_ID = re.compile(r"S[1-9]\d*")


class CitationSourceService:
    """Resolve valid inline source IDs against the exact grounded passages."""

    def construct(self, result: GeneratedAnswer) -> VerifiedAnswer:
        """Validate citations and construct sources without trusting LLM metadata."""

        cited_source_ids = self._cited_source_ids(result.answer)
        passages_by_id = {
            passage.source_id: passage for passage in result.context.passages
        }

        unknown_source_ids = tuple(
            source_id
            for source_id in cited_source_ids
            if source_id not in passages_by_id
        )
        if unknown_source_ids:
            raise SourceVerificationError(
                "generated answer cites a source outside the grounded context"
            )

        sources = tuple(
            VerifiedSource(
                source_id=source_id,
                passage=passages_by_id[source_id],
            )
            for source_id in cited_source_ids
        )
        logger.info(
            "Answer sources verified: cited_sources=%s, available_passages=%s",
            len(sources),
            len(passages_by_id),
        )
        return VerifiedAnswer(generation=result, sources=sources)

    @staticmethod
    def _cited_source_ids(answer: str) -> tuple[str, ...]:
        source_ids: list[str] = []
        seen_source_ids: set[str] = set()

        groups = tuple(_SOURCE_LIKE_GROUP.finditer(answer))
        if not groups:
            raise SourceVerificationError(
                "generated answer does not contain a source citation"
            )

        for group in groups:
            citation_group = group.group(1).strip()
            if _VALID_SOURCE_GROUP.fullmatch(citation_group) is None:
                raise SourceVerificationError(
                    "generated answer contains a malformed source citation"
                )
            for source_id in _SOURCE_ID.findall(citation_group):
                if source_id not in seen_source_ids:
                    source_ids.append(source_id)
                    seen_source_ids.add(source_id)

        return tuple(source_ids)
