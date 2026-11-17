"""Persistent, private spaCy worker. Document text is exchanged only over pipes."""

import json
import sys

from app.services.ner_protocol import MAX_NER_RESPONSE_BYTES
from app.services.ner_service import (
    NERInputError,
    NERModelUnavailableError,
    SpacyPersonRecognizer,
    validate_pages,
)


def _send(message: dict) -> None:
    encoded = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"
    if len(encoded) > MAX_NER_RESPONSE_BYTES:
        encoded = b'{"status":"processing_error"}\n'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _process_request(line: bytes, config: dict, recognizer: SpacyPersonRecognizer) -> None:
    # Keep document text in a request-local frame rather than retaining it while
    # the persistent worker waits for its next job. This is not secure erasure.
    try:
        request = json.loads(line)
        pages = validate_pages(
            request["pages"], max_pages=config["max_pages"],
            max_page_chars=config["max_page_chars"],
            max_document_chars=config["max_document_chars"],
        )
        result = recognizer.detect_pages(pages)
        _send({"status": "ok", "pages": [
            [{"text": span.text, "char_start": span.char_start, "char_end": span.char_end} for span in page]
            for page in result
        ]})
    except NERInputError:
        _send({"status": "input_error"})
    except Exception:
        # Never print model errors or document text to logs or stderr.
        _send({"status": "processing_error"})


def main() -> None:
    try:
        config = json.loads(sys.stdin.buffer.readline())
        recognizer = SpacyPersonRecognizer.load(config["model"], config["max_page_chars"])
    except NERModelUnavailableError:
        _send({"status": "model_unavailable"})
        return
    except Exception:
        _send({"status": "processing_error"})
        return

    _send({"status": "ready"})
    for line in sys.stdin.buffer:
        _process_request(line, config, recognizer)
        del line


if __name__ == "__main__":
    main()
