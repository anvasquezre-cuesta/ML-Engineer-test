import json
import logging

from app.infrastructure.logging import JsonFormatter, request_id_var


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_record_is_one_json_object_with_event_and_extras() -> None:
    token = request_id_var.set("req-42")
    try:
        line = JsonFormatter().format(_record("ocr_completed", page_count=2))
    finally:
        request_id_var.reset(token)

    payload = json.loads(line)
    assert payload["event"] == "ocr_completed"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["timestamp"].endswith("Z")
    assert payload["request_id"] == "req-42"
    assert payload["page_count"] == 2


def test_request_id_is_null_outside_a_request() -> None:
    payload = json.loads(JsonFormatter().format(_record("startup")))

    assert payload["request_id"] is None


def test_exception_is_serialized_as_text() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record("unhandled_error")
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in payload["exception"]
