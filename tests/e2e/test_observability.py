"""Logging across a real HTTP request: every line carries the request ID, none carries names.

``capture_logs`` normally drops context; ``merge_contextvars`` is added back so the
request ID bound by the middleware is visible exactly as the JSON logs would show it.
"""

import json

import structlog
from structlog.testing import capture_logs

from tests.e2e.conftest import PDF, ClientFactory

NAMES = json.dumps([{"first_name": "Robert", "last_name": "Chen"}])


def test_every_log_line_of_a_request_carries_its_id_and_no_names(
    make_client: ClientFactory,
) -> None:
    client = make_client()

    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        response = client.post(
            "/api/extract",
            files={"pdf_file": ("memo.pdf", PDF, "application/pdf")},
            data={"names": NAMES},
            headers={"X-Request-ID": "trace-123"},
        )

    assert response.status_code == 200
    events = [e["event"] for e in logs]
    assert {"document_loaded", "ocr_complete", "names_extracted", "extraction_complete"} <= set(
        events
    )
    assert all(e.get("request_id") == "trace-123" for e in logs), logs
    assert "Robert" not in str(logs) and "Chen" not in str(logs)


def test_durations_are_logged_for_extract_ingest_and_ask(make_client: ClientFactory) -> None:
    client = make_client()

    with capture_logs() as logs:
        client.post(
            "/api/extract",
            files={"pdf_file": ("m.pdf", PDF, "application/pdf")},
            data={"names": "[]"},
        )
        client.post("/api/ingest", files={"pdf_file": ("m.pdf", PDF, "application/pdf")})
        client.post("/api/ask", json={"question": "Who approved, Robert Chen CTO?"})

    timed = {e["event"] for e in logs if "duration_ms" in e}
    assert {"extraction_complete", "ingest_complete", "ask_complete", "request"} <= timed
