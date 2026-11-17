"""Opt-in, per-process memory-only preview of the latest extraction.

The PDF proxy and immutable stage overlays can contain sensitive information.
They are never logged, written to SQLite, or exposed without the configured key.
"""

import asyncio
from dataclasses import dataclass, field
import json
import secrets
import threading
import time
from types import MappingProxyType
from uuid import uuid4


PREVIEW_TTL_SECONDS = 600
MAX_PREVIEW_PDF_BYTES = 10 * 1024 * 1024
MAX_PREVIEW_PAGES = 25
MAX_PREVIEW_WORDS = 5_000
MAX_PREVIEW_STAGE_BYTES = 2 * 1024 * 1024
MAX_PREVIEW_TOTAL_STAGE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class ExtractionPreview:
    preview_id: str
    pdf: bytes = field(repr=False)
    stages: MappingProxyType = field(repr=False)
    expires_at: float


class LatestExtractionPreview:
    """Retain one completed preview; generations prevent stale publications."""

    def __init__(self, token: str, *, ttl_seconds: float = PREVIEW_TTL_SECONDS):
        if not token or ttl_seconds <= 0:
            raise ValueError("A preview key and positive TTL are required")
        self._token = token.encode("utf-8")
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._generation = 0
        self._preview = None
        self._timer = None
        self._closed = False

    def authorized(self, header: str | None) -> bool:
        if not header or len(header) > 512:
            return False
        scheme, separator, value = header.partition(" ")
        if not separator or scheme.lower() != "bearer":
            return False
        return secrets.compare_digest(value.encode("utf-8"), self._token)

    def begin(self) -> int:
        """Invalidate the visible preview before any new extraction starts."""
        with self._lock:
            if self._closed:
                return -1
            self._generation += 1
            self._preview = None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            return self._generation

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return not self._closed and generation == self._generation

    def publish(self, generation: int, pdf: bytes, stages: dict[str, bytes]) -> bool:
        if not isinstance(pdf, bytes) or not pdf or len(pdf) > MAX_PREVIEW_PDF_BYTES:
            return False
        if (not stages or any(not isinstance(value, bytes) or len(value) > MAX_PREVIEW_STAGE_BYTES
                              for value in stages.values())
                or sum(map(len, stages.values())) > MAX_PREVIEW_TOTAL_STAGE_BYTES):
            return False
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._closed or generation != self._generation:
                return False
            if self._timer is not None:
                self._timer.cancel()
            self._preview = ExtractionPreview(str(uuid4()), pdf, MappingProxyType(dict(stages)), time.monotonic() + self._ttl)
            self._timer = loop.call_later(self._ttl, self._expire, generation)
            return True

    def _expire(self, generation: int) -> None:
        with self._lock:
            if generation == self._generation:
                self._preview = None
                self._timer = None

    def get(self, preview_id: str | None = None) -> ExtractionPreview | None:
        with self._lock:
            preview = self._preview
            if preview is not None and time.monotonic() >= preview.expires_at:
                self._preview = None
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                return None
            if preview is None or (preview_id is not None and preview.preview_id != preview_id):
                return None
            return preview

    def close(self) -> None:
        with self._lock:
            self._generation += 1
            self._closed = True
            self._preview = None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


def build_preview_stages(document, entities, original_occurrences, recovered, response, passes):
    """Capture page-local overlays, not rendered screenshots or another OCR pass."""
    if len(document.pages) > MAX_PREVIEW_PAGES or sum(len(page.words) for page in document.pages) > MAX_PREVIEW_WORDS:
        return None
    dimensions = [{"page_number": page.page_number, "width": page.width, "height": page.height}
                  for page in document.pages]
    originals = [{"text": item.location.name, "box": item.location.bounding_box.model_dump(), "source": "ner"}
                 for item in original_occurrences]
    original_spans = {(item.location.bounding_box.page_number, item.span.char_start, item.span.char_end)
                      for item in original_occurrences}

    def by_page(boxes):
        return [{**page, "boxes": [item for item in boxes if item["box"]["page_number"] == page["page_number"]]}
                for page in dimensions]

    ocr = []
    for page in document.pages:
        for word in page.words:
            box = word.box
            ocr.append({"text": word.text, "confidence": word.confidence, "source": "ocr", "box": {
                "page_number": page.page_number, "x": box.x, "y": box.y, "width": box.width, "height": box.height,
            }})
    stages = {
        "ocr": {"stage": "ocr", "pages": by_page(ocr)},
        "ner": {"stage": "ner", "pages": by_page(originals),
                "spans_detected": sum(map(len, entities)), "located": len(originals),
                "unlocated": [
                    {"page_number": page.page_number, "text": span.text,
                     "char_start": span.char_start, "char_end": span.char_end}
                    for page, spans in zip(document.pages, entities, strict=True) for span in spans
                    if (page.page_number, span.char_start, span.char_end) not in original_spans
                ]},
    }
    additions = [{"text": item.location.name, "box": item.location.bounding_box.model_dump(),
                  "source": f"recovery_{item.stage}", "pass": item.stage} for item in recovered]
    for stage in range(1, passes + 1):
        stages[f"recovery_{stage}"] = {
            "stage": f"recovery_{stage}", "pages": by_page(originals + [x for x in additions if x["pass"] <= stage]),
        }
    stages["final"] = {"stage": "final", "pages": by_page(originals + additions),
                       "extracted_names": [item.model_dump() for item in response.extracted_names],
                       "fuzzy_matches": [item.model_dump() for item in response.fuzzy_matches]}
    encoded = {name: json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
               for name, value in stages.items()}
    if (any(len(value) > MAX_PREVIEW_STAGE_BYTES for value in encoded.values())
            or sum(map(len, encoded.values())) > MAX_PREVIEW_TOTAL_STAGE_BYTES):
        return None
    return encoded
