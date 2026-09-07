import logging

from app.models.domain import Page
from app.models.schemas import BoundingBox, ExtractedName, ExtractionResponse, NamePair
from app.services.bbox_service import locate
from app.services.fuzzy_service import match_names, normalize
from app.services.interfaces import NerExtractor, OcrEngine

log = logging.getLogger(__name__)


class ExtractionPipeline:
    def __init__(
        self,
        ocr: OcrEngine,
        ner: NerExtractor,
        fuzzy_threshold: float,
        bbox_token_threshold: float,
        min_name_tokens: int = 2,
    ):
        self.ocr = ocr
        self.ner = ner
        self.fuzzy_threshold = fuzzy_threshold
        self.bbox_token_threshold = bbox_token_threshold
        self.min_name_tokens = min_name_tokens

    def run(self, pdf: bytes, requested: list[NamePair]) -> ExtractionResponse:
        pages = self.ocr.run(pdf)
        names = self._unique_names(pages)

        extracted = []
        for name in names:
            for page in pages:
                for box in locate(name, page, self.bbox_token_threshold):
                    extracted.append(
                        ExtractedName(
                            name=name,
                            bounding_box=BoundingBox(
                                page_number=box.page,
                                x=box.x,
                                y=box.y,
                                width=box.width,
                                height=box.height,
                            ),
                        )
                    )
        located = {e.name for e in extracted}
        for name in names:
            if name not in located:
                log.warning("name not located on any page", extra={"person": name})

        matches = match_names(sorted(located), requested, self.fuzzy_threshold)
        log.info(
            "extraction done",
            extra={
                "pages": len(pages),
                "names": len(names),
                "boxes": len(extracted),
                "matches": len(matches),
            },
        )
        return ExtractionResponse(extracted_names=extracted, fuzzy_matches=matches)

    def _unique_names(self, pages: list[Page]) -> list[str]:
        seen: dict[str, str] = {}
        for page in pages:
            for name in self.ner.person_names(page.text):
                # single tokens are mostly project names and OCR debris tagged as people
                if len(name.split()) >= self.min_name_tokens:
                    seen.setdefault(normalize(name), name)
        return list(seen.values())
