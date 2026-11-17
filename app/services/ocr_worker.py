"""Private subprocess entrypoint for isolated PDF rendering and Tesseract."""

from dataclasses import asdict
import json
from pathlib import Path
import sys

from app.core.config import Settings
from app.services.ocr_service import (
    InvalidPDFError,
    OCRProcessingError,
    OCRService,
    PDFTooLargeError,
)


def main() -> None:
    input_path, result_path, settings_json = sys.argv[1:]
    try:
        result = OCRService(Settings(**json.loads(settings_json))).extract_file(input_path)
        response = {"status": "ok", "document": asdict(result)}
    except (InvalidPDFError, PDFTooLargeError, OCRProcessingError, FileNotFoundError) as exc:
        response = {"status": "error", "type": type(exc).__name__, "message": str(exc)}
    Path(result_path).write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
