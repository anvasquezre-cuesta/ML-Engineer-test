"""Every error path through HTTP: status code and JSON shape (roadmap F10 "done when").

Each case asserts the same contract: the body is ``{"detail": ..., "request_id": ...}``,
the ID matches the ``X-Request-ID`` header, and no traceback leaks.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.domain.errors import InvalidDocument, UpstreamUnavailable
from tests.e2e.conftest import PDF, ClientFactory, FailingOCR
from tests.e2e.test_ask_api import DownLLM
from tests.fakes import FailingStore, FakeRenderer, blank_page

NAMES = json.dumps([{"first_name": "Robert", "last_name": "Chen"}])
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _extract(pdf: bytes = PDF, names: str = NAMES) -> Callable[[TestClient], httpx.Response]:
    return lambda c: c.post(
        "/api/extract", files={"pdf_file": ("x.pdf", pdf, "application/pdf")}, data={"names": names}
    )


def _ingest(pdf: bytes = PDF) -> Callable[[TestClient], httpx.Response]:
    return lambda c: c.post("/api/ingest", files={"pdf_file": ("x.pdf", pdf, "application/pdf")})


def _ask(body: Any) -> Callable[[TestClient], httpx.Response]:
    return lambda c: c.post("/api/ask", json=body)


def _chunks(total: int) -> Iterator[bytes]:
    for _ in range(total // 1024):
        yield b"x" * 1024


CASES: list[tuple[str, dict[str, Any], Callable[[TestClient], httpx.Response], int, str]] = [
    # (case, make_client kwargs, request, status, text expected in detail)
    ("non-PDF by content", {}, _extract(PNG), 415, "not a PDF"),
    ("empty file", {}, _extract(b""), 422, "empty"),
    ("file over the upload limit", {}, _extract(b"%PDF-" + b"x" * 2000), 413, "limit"),
    (
        "corrupt or encrypted PDF",
        {"renderer": FakeRenderer([], error=InvalidDocument("The PDF is encrypted."))},
        _extract(),
        422,
        "encrypted",
    ),
    (
        "too many pages",
        {"renderer": FakeRenderer([blank_page(i) for i in range(3)]), "max_pages": 2},
        _extract(),
        413,
        "3 pages",
    ),
    ("names not JSON", {}, _extract(names="nope"), 422, "'names'"),
    ("names wrong shape", {}, _extract(names='[{"first_name": "A"}]'), 422, "'names'"),
    (
        "missing pdf_file",
        {},
        lambda c: c.post("/api/extract", data={"names": NAMES}),
        422,
        "pdf_file",
    ),
    ("OCR engine unavailable", {"ocr": FailingOCR()}, _extract(), 503, "Tesseract"),
    (
        "vector store down on ingest",
        {"store": FailingStore(UpstreamUnavailable("Vector store write failed: disk full"))},
        _ingest(),
        503,
        "Vector store",
    ),
    (
        "vector store down on ask",
        {"store": FailingStore(UpstreamUnavailable("Vector store query failed: locked"))},
        _ask({"question": "Who?"}),
        503,
        "Vector store",
    ),
    ("question empty", {}, _ask({"question": ""}), 422, "question"),
    ("question blank", {}, _ask({"question": "   "}), 422, "empty"),
    ("question too long", {}, _ask({"question": "x" * 2001}), 422, "question"),
    (
        "body not valid JSON",
        {},
        lambda c: c.post(
            "/api/ask", content=b"{oops", headers={"content-type": "application/json"}
        ),
        422,
        "json",
    ),
    (
        "declared body over the request limit",
        {"request_overhead_bytes": 0},
        lambda c: c.post("/api/ingest", content=b"x" * 5000),
        413,
        "request body",
    ),
    (
        "chunked body over the request limit (no Content-Length)",
        {"request_overhead_bytes": 0},
        lambda c: c.post(
            "/api/ingest",
            content=_chunks(8 * 1024),
            headers={"content-type": "multipart/form-data; boundary=x"},
        ),
        413,
        "request body",
    ),
    ("unknown route", {}, lambda c: c.get("/api/nope"), 404, "Not Found"),
    ("wrong method", {}, lambda c: c.get("/api/extract"), 405, "Method Not Allowed"),
    (
        "unexpected crash",
        {
            "store": FailingStore(RuntimeError("boom: secret internal state")),
            "raise_server_exceptions": False,
        },
        _ingest(),
        500,
        "Internal server error",
    ),
]


@pytest.mark.parametrize(
    ("case", "client_kwargs", "send", "status", "detail"), CASES, ids=[c[0] for c in CASES]
)
def test_error_path_returns_json_with_detail_and_request_id(
    make_client: ClientFactory,
    case: str,
    client_kwargs: dict[str, Any],
    send: Callable[[TestClient], httpx.Response],
    status: int,
    detail: str,
) -> None:
    response = send(make_client(**client_kwargs))

    assert response.status_code == status
    body = response.json()
    assert set(body) == {"detail", "request_id"}
    assert detail.lower() in json.dumps(body["detail"]).lower()
    assert body["request_id"] and body["request_id"] == response.headers["x-request-id"]
    assert "Traceback" not in response.text and "secret internal state" not in response.text


def test_llm_down_is_503(make_client: ClientFactory) -> None:
    client = make_client(llm=DownLLM())
    client.post("/api/ingest", files={"pdf_file": ("memo.pdf", PDF, "application/pdf")})

    response = client.post("/api/ask", json={"question": "Who approved, Robert Chen CTO?"})

    assert response.status_code == 503
    assert set(response.json()) == {"detail", "request_id"}


def test_validation_errors_do_not_echo_the_rejected_input(make_client: ClientFactory) -> None:
    secret = "María González, passport 12345"

    response = make_client().post("/api/ask", json={"question": secret * 100})

    assert response.status_code == 422
    assert "12345" not in response.text
