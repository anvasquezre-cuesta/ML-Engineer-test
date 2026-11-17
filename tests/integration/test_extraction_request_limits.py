"""Exercise the body guard with a test-only multipart route, not /api/extract's implementation."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Annotated

import httpx
import pytest
import starlette.formparsers
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.core.config import Settings
from app.core.request_limits import ExtractionBodyLimitMiddleware, _RequestBodyTooLarge
from app.main import app as actual_app, lifespan
from app.services.extraction_input import InvalidNamesError, NamesLimitError, parse_names


def make_test_app(*, body_limit=4096, names_limit=1024, names_count=5):
    settings = Settings(max_names_bytes=names_limit, max_names_count=names_count)
    app = FastAPI()
    app.add_middleware(ExtractionBodyLimitMiddleware, max_request_bytes=body_limit)
    app.state.endpoint_calls = 0

    @app.post("/api/extract")
    async def simulated_extract(
        pdf_file: Annotated[UploadFile, File()], names: Annotated[str, Form()]
    ):
        app.state.endpoint_calls += 1
        try:
            pairs = parse_names(names, settings)
        except NamesLimitError:
            raise HTTPException(status_code=413, detail="Names limit exceeded") from None
        except InvalidNamesError:
            raise HTTPException(status_code=422, detail="Invalid names field") from None
        return {"pdf_bytes": len(await pdf_file.read()), "names": len(pairs)}

    @app.post("/api/other")
    async def other():
        return {"ok": True}

    return app


def multipart_body(names="[]", pdf=b"%PDF-test"):
    return (
        b'--boundary\r\nContent-Disposition: form-data; name="pdf_file"; filename="x.pdf"\r\n'
        b'Content-Type: application/pdf\r\n\r\n' + pdf + b'\r\n'
        b'--boundary\r\nContent-Disposition: form-data; name="names"\r\n\r\n'
        + names.encode("utf-8") + b'\r\n--boundary--\r\n'
    )


async def streamed_post(app, chunks, headers=None):
    sent_chunks = []
    sent_messages = []

    async def body():
        for chunk in chunks:
            sent_chunks.append(chunk)
            yield chunk

    async def capture(scope, receive, send):
        async def record(message):
            sent_messages.append(message.copy())
            await send(message)
        await app(scope, receive, record)

    request_headers = {"Content-Type": "multipart/form-data; boundary=boundary"}
    request_headers.update(headers or {})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=capture), base_url="http://test") as client:
        response = await client.post("/api/extract", content=body(), headers=request_headers)
    return response, sent_chunks, sent_messages


@pytest.mark.parametrize("header", [None, "1", "exact"])
def test_fragmented_multipart_at_exact_limit_without_trusting_length(header):
    body = multipart_body('[{"first_name":"José","last_name":"Li"}]')
    app = make_test_app(body_limit=len(body))
    chunks = [body[index:index + 7] for index in range(0, len(body), 7)]
    headers = {} if header is None else {"Content-Length": str(len(body)) if header == "exact" else header}
    response, sent, messages = asyncio.run(streamed_post(app, chunks, headers))
    assert response.status_code == 200
    assert response.json() == {"pdf_bytes": len(b"%PDF-test"), "names": 1}
    assert sent == chunks
    assert sum(message["type"] == "http.response.start" for message in messages) == 1


@pytest.mark.parametrize("header", [None, "1"])
def test_oversized_fragmented_multipart_rejects_early_and_closes_tempfile(monkeypatch, header):
    created = []
    original = starlette.formparsers.SpooledTemporaryFile

    def tracked_tempfile(*args, **kwargs):
        file = original(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked_tempfile)
    monkeypatch.setattr(starlette.formparsers.MultiPartParser, "spool_max_size", 4)
    first_chunk = (
        b'--boundary\r\nContent-Disposition: form-data; name="pdf_file"; filename="x.pdf"\r\n'
        b'Content-Type: application/pdf\r\n\r\n' + b"file content"
    )
    app = make_test_app(body_limit=len(first_chunk) + 5)
    chunks = [first_chunk, b"x" * 6, b"SHOULD-NOT-BE-READ"]
    headers = {} if header is None else {"Content-Length": header}
    response, sent, messages = asyncio.run(streamed_post(app, chunks, headers))
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}
    assert sent == chunks[:2]
    assert app.state.endpoint_calls == 0
    assert len(created) == 1 and created[0]._rolled and created[0].closed
    assert sum(message["type"] == "http.response.start" for message in messages) == 1


def test_declared_oversize_is_rejected_without_receiving_body():
    app = make_test_app(body_limit=10)
    response, sent, _ = asyncio.run(streamed_post(app, [b"unused"], {"Content-Length": "11"}))
    assert response.status_code == 413
    assert sent == []
    assert app.state.endpoint_calls == 0


def test_cancellation_during_multipart_read_closes_tempfile(monkeypatch):
    created = []
    original = starlette.formparsers.SpooledTemporaryFile

    def tracked_tempfile(*args, **kwargs):
        file = original(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked_tempfile)
    monkeypatch.setattr(starlette.formparsers.MultiPartParser, "spool_max_size", 4)
    first_chunk = (
        b'--boundary\r\nContent-Disposition: form-data; name="pdf_file"; filename="x.pdf"\r\n'
        b'Content-Type: application/pdf\r\n\r\n' + b"partial file"
    )
    app = make_test_app()

    async def run():
        waiting_for_next_chunk = asyncio.Event()
        reads = 0
        responses = []

        async def receive():
            nonlocal reads
            reads += 1
            if reads == 1:
                return {"type": "http.request", "body": first_chunk, "more_body": True}
            waiting_for_next_chunk.set()
            await asyncio.Event().wait()

        async def send(message):
            responses.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/api/extract", "raw_path": b"/api/extract",
            "query_string": b"", "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
            "client": ("test", 123), "server": ("test", 80),
        }
        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(waiting_for_next_chunk.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return responses

    assert asyncio.run(run()) == []
    assert len(created) == 1 and created[0]._rolled and created[0].closed
    assert app.state.endpoint_calls == 0


def test_client_disconnect_during_multipart_read_closes_tempfile(monkeypatch):
    created = []
    original = starlette.formparsers.SpooledTemporaryFile

    def tracked_tempfile(*args, **kwargs):
        file = original(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked_tempfile)
    monkeypatch.setattr(starlette.formparsers.MultiPartParser, "spool_max_size", 4)
    first_chunk = (
        b'--boundary\r\nContent-Disposition: form-data; name="pdf_file"; filename="x.pdf"\r\n'
        b'Content-Type: application/pdf\r\n\r\n' + b"partial file"
    )
    app = make_test_app()
    responses = []
    incoming = iter([
        {"type": "http.request", "body": first_chunk, "more_body": True},
        {"type": "http.disconnect"},
    ])

    async def receive():
        return next(incoming)

    async def send(message):
        responses.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/api/extract", "raw_path": b"/api/extract",
        "query_string": b"", "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
        "client": ("test", 123), "server": ("test", 80),
    }
    asyncio.run(app(scope, receive, send))
    assert len(created) == 1 and created[0]._rolled and created[0].closed
    assert app.state.endpoint_calls == 0


def test_real_uvicorn_accepts_and_rejects_chunked_multipart():
    body = multipart_body()
    app = make_test_app(body_limit=len(body))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    host, port = sock.getsockname()
    config = uvicorn.Config(app, host=host, port=port, lifespan="off", access_log=False, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Test HTTP server did not start")
            time.sleep(0.01)
        headers = {"Content-Type": "multipart/form-data; boundary=boundary"}
        with httpx.Client(base_url=f"http://{host}:{port}", timeout=5) as client:
            accepted = client.post("/api/extract", content=iter([body[:50], body[50:]]), headers=headers)
            rejected = client.post("/api/extract", content=iter([body[:50], body[50:], b"x"]), headers=headers)
        assert accepted.request.headers.get("transfer-encoding") == "chunked"
        assert "content-length" not in accepted.request.headers
        assert accepted.status_code == 200
        assert rejected.status_code == 413
        assert app.state.endpoint_calls == 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.parametrize("names,status", [
    ("[]", 200),
    ("not-json", 422),
    ('[{"first_name":"secret"}]', 422),
    ('[{"first_name":" ","last_name":"Doe"}]', 422),
    (json.dumps([{"first_name": "Jane", "last_name": "Doe"}] * 2), 413),
    (" " * 128, 413),
])
def test_names_errors_are_mapped_by_a_test_only_route(names, status):
    app = make_test_app(names_limit=100, names_count=1)
    body = multipart_body(names)
    response, _, _ = asyncio.run(streamed_post(app, [body]))
    assert response.status_code == status
    assert "secret" not in response.text


def test_missing_form_fields_produce_validation_errors():
    app = make_test_app()

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            missing_names = await client.post("/api/extract", files={"pdf_file": ("x.pdf", b"pdf")})
            missing_file = await client.post("/api/extract", data={"names": "[]"})
        return missing_names, missing_file

    missing_names, missing_file = asyncio.run(run())
    assert missing_names.status_code == 422
    assert missing_file.status_code == 422


def test_default_form_parser_can_reject_a_very_large_field_before_names_validation():
    # FastAPI's automatic form parsing currently has its own 1 MiB per-field
    # limit and maps that parser failure to 400, before the endpoint can run.
    # The real endpoint must deliberately handle this when it is implemented.
    body = multipart_body("x" * (1024 * 1024 + 1))
    app = make_test_app(body_limit=len(body), names_limit=64 * 1024)
    response, _, _ = asyncio.run(streamed_post(app, [body]))
    assert response.status_code == 400
    assert app.state.endpoint_calls == 0


def test_body_guard_does_not_apply_to_unrelated_routes():
    app = make_test_app(body_limit=1)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/other", content=b"more than one byte")

    assert asyncio.run(run()).status_code == 200


def test_body_count_is_independent_for_concurrent_requests():
    body = multipart_body()
    app = make_test_app(body_limit=len(body))

    async def run():
        return await asyncio.gather(*(
            streamed_post(app, [body[:20], body[20:]]) for _ in range(5)
        ))

    results = asyncio.run(run())
    assert all(response.status_code == 200 for response, _, _ in results)
    assert app.state.endpoint_calls == 5


def test_body_guard_is_installed_on_actual_app():
    async def run():
        async with lifespan(actual_app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=actual_app), base_url="http://test") as client:
                health = await client.get("/health")
                missing = await client.post("/api/extract", content=b"")
                oversized = await client.post("/api/extract", headers={"Content-Length": "999999999"})
        return health, missing, oversized

    health, missing, oversized = asyncio.run(run())
    assert health.status_code == 200
    assert missing.status_code == 422
    assert oversized.status_code == 413


def test_actual_app_reads_body_limit_from_environment_on_startup():
    script = """
import asyncio
import httpx
from app.main import app

async def run():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return (await client.post("/api/extract", headers={"Content-Length": "6"})).status_code

print(asyncio.run(run()))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], env={**os.environ, "MAX_REQUEST_BYTES": "5"},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "413"


@pytest.mark.parametrize("length", [b"", b"-1", b"+1", b"1, 2", b" 1", b"1 ", b"1x"])
def test_malformed_content_length_is_rejected_before_reading(length):
    messages, reads = run_raw_headers([(b"content-length", length)])
    assert messages[0]["status"] == 400
    assert reads == []


def test_duplicate_or_huge_content_length_is_rejected_before_reading():
    duplicate, reads = run_raw_headers([(b"content-length", b"1"), (b"content-length", b"1")])
    assert duplicate[0]["status"] == 400 and reads == []
    huge, reads = run_raw_headers([(b"content-length", b"9" * 5000)])
    assert huge[0]["status"] == 413 and reads == []


def run_raw_headers(headers):
    messages, reads = [], []

    async def inner(scope, receive, send):
        await receive()

    async def receive():
        reads.append(True)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/extract", "headers": headers}
    asyncio.run(ExtractionBodyLimitMiddleware(inner, 10)(scope, receive, send))
    return messages, reads


def test_mounted_route_is_protected():
    messages = []

    async def inner(scope, receive, send):
        raise AssertionError("oversized mounted request should not reach the app")

    async def receive():
        raise AssertionError("declared oversized request should not be read")

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": "POST", "root_path": "/v1", "path": "/v1/api/extract", "headers": [(b"content-length", b"11")]}
    asyncio.run(ExtractionBodyLimitMiddleware(inner, 10)(scope, receive, send))
    assert messages[0]["status"] == 413


def test_no_second_response_if_app_starts_response_before_reading_oversize_body():
    messages = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    async def receive():
        return {"type": "http.request", "body": b"oversized", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/extract", "headers": []}
    with pytest.raises(_RequestBodyTooLarge):
        asyncio.run(ExtractionBodyLimitMiddleware(inner, 1)(scope, receive, send))
    assert messages == [{"type": "http.response.start", "status": 200, "headers": []}]
