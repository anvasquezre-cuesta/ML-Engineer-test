"""``POST /api/extract`` over HTTP: real pipeline and failure contract."""

from collections.abc import Callable
from collections.abc import Iterator
import contextlib
import json
import pathlib
from typing import Any

from fastapi import testclient
import pytest

from app import bootstrap
from app import config
from app import main
from app.domain import extraction
from app.ports import page_renderer
from app.service_layer import extract as extract_service
from tests import builders
from tests import ground_truth
from tests.fakes import cpu_runner
from tests.fakes import name_matcher
from tests.fakes import ner as ner_fake
from tests.fakes import ocr as ocr_fake
from tests.fakes import page_renderer as page_renderer_fake

pytestmark = pytest.mark.e2e

PDF = b"%PDF-1.7\n"
UPLOAD_LIMIT = 1024
NAMES = json.dumps([{"first_name": "Anna", "last_name": "Berg"}])
PROBLEM_JSON = "application/problem+json"


class ExplodingRenderer(page_renderer.PageRenderer):
    """Fails the way an unforeseen bug would."""

    def render(self, pdf: bytes) -> list[extraction.PageImage]:
        """Raises an error carrying internal details.

        Args:
            pdf: Ignored.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError("secret internal detail /srv/tmp/upload-42")


def fake_container(
    renderer: page_renderer.PageRenderer,
) -> Callable[[config.Settings], bootstrap.Container]:
    """Returns a factory wiring the use case to fakes around ``renderer``.

    Args:
        renderer: The renderer the use case calls first.

    Returns:
        A container factory for ``create_app``.
    """
    words = builders.page_words([["Dr. Anna Berg met Lucas Moreau"]])
    extract = extract_service.ExtractNames(
        renderer=renderer,
        ocr=ocr_fake.ScriptedOcr([words]),
        ner=ner_fake.ExactNer({"Anna Berg", "Lucas Moreau"}),
        matcher=name_matcher.ScriptedNameMatcher(
            {("Anna Berg", "Anna Berg"): 1.0}
        ),
        cpu=cpu_runner.InlineCpuRunner(),
        threshold=0.9,
    )
    return lambda settings: bootstrap.Container(extract_names=extract)


@contextlib.contextmanager
def fake_client(
    renderer: page_renderer.PageRenderer | None = None,
    upload_limit: int = UPLOAD_LIMIT,
) -> Iterator[testclient.TestClient]:
    """Runs an app wired to fakes.

    Args:
        renderer: The renderer to wire; a one-page blank renderer by default.
        upload_limit: Largest accepted upload in bytes.

    Yields:
        The running test client.
    """
    settings = config.Settings(
        _env_file=None, upload=config.UploadSettings(max_bytes=upload_limit)
    )
    factory = fake_container(
        renderer or page_renderer_fake.BlankPageRenderer(1)
    )
    with testclient.TestClient(
        main.create_app(settings, factory), raise_server_exceptions=False
    ) as client:
        yield client


def post_extract(
    client: testclient.TestClient, content: bytes, names: str = NAMES
) -> dict[str, Any]:
    """Posts a PDF upload and returns the JSON body.

    Args:
        client: The test client.
        content: The uploaded file content.
        names: The ``names`` form field.

    Returns:
        The decoded response body, with ``status`` and ``content_type`` of
        the HTTP response added.
    """
    response = client.post(
        "/api/extract",
        files={"pdf_file": ("scan.pdf", content, "application/pdf")},
        data={"names": names},
    )
    return {
        **response.json(),
        "http_status": response.status_code,
        "content_type": response.headers["content-type"],
        "request_id_header": response.headers.get("x-request-id"),
    }


@pytest.mark.integration
def test_sample_pdf_returns_every_verified_box_and_fuzzy_match() -> None:
    truth = json.loads(
        (ground_truth.GROUND_TRUTH / "company_memo.json").read_text()
    )
    queries = [
        {"first_name": "Maria", "last_name": "Garcia"},
        {"first_name": "Margaret", "last_name": "Thomson"},
    ]

    with testclient.TestClient(
        main.create_app(config.Settings(_env_file=None))
    ) as client:
        response = client.post(
            "/api/extract",
            files={
                "pdf_file": (
                    "company_memo.pdf",
                    (ground_truth.SAMPLES / "company_memo.pdf").read_bytes(),
                    "application/pdf",
                )
            },
            data={"names": json.dumps(queries)},
        )

    body = response.json()
    found = tuple(
        extraction.NameOccurrence(
            name=item["name"],
            page_number=item["bounding_box"]["page_number"],
            box=extraction.Box(
                x=item["bounding_box"]["x"],
                y=item["bounding_box"]["y"],
                width=item["bounding_box"]["width"],
                height=item["bounding_box"]["height"],
            ),
        )
        for item in body["extracted_names"]
    )
    assert response.status_code == 200
    assert ground_truth.unmatched(found, truth["names"]) == ([], [])
    matches = {
        (match["extracted_name"], match["matched_name"]): match["score"]
        for match in body["fuzzy_matches"]
    }
    assert matches[("Maria Garcia", "Maria Garcia")] == 1.0
    assert 0.9 <= matches[("Margaret Thompson", "Margaret Thomson")] < 1.0


@pytest.mark.parametrize(
    ("content", "names", "status", "code"),
    [
        (b"\x89PNG\r\n\x1a\n", NAMES, 415, "upload.not_pdf"),
        (PDF + b"x" * UPLOAD_LIMIT, NAMES, 413, "upload.too_large"),
        (
            PDF,
            json.dumps([{"first_name": "Anna"}]),
            422,
            "request.invalid_names_json",
        ),
    ],
    ids=["png", "too-large", "names-missing-last"],
)
def test_invalid_requests_are_rejected_as_problem_details(
    content: bytes, names: str, status: int, code: str
) -> None:
    with fake_client() as client:
        body = post_extract(client, content, names)

    assert (body["http_status"], body["code"]) == (status, code)
    assert body["content_type"] == PROBLEM_JSON


def test_unexpected_failure_hides_internals_and_returns_request_id() -> None:
    with fake_client(ExplodingRenderer()) as client:
        body = post_extract(client, PDF)

    assert (body["http_status"], body["code"]) == (500, "internal.unexpected")
    assert "secret" not in json.dumps(body)
    assert body["request_id"] == body["request_id_header"]


def test_logs_never_contain_extracted_names(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with fake_client() as client:
        body = post_extract(client, PDF)

    logs = capsys.readouterr()
    assert body["http_status"] == 200
    assert body["request_id_header"] in logs.out
    assert "Anna Berg" not in logs.out + logs.err
    assert "Lucas Moreau" not in logs.out + logs.err


@pytest.mark.skipif(
    not pathlib.Path("/proc/self/fd").exists(), reason="needs /proc"
)
@pytest.mark.parametrize(
    "upload_limit", [4 * 1024 * 1024, UPLOAD_LIMIT], ids=["accepted", "413"]
)
def test_spooled_uploads_leave_no_open_file_handles(upload_limit: int) -> None:
    # Over 1 MB, the multipart parser spools the upload to a temporary file.
    large_pdf = PDF + b"x" * (2 * 1024 * 1024)
    open_files = pathlib.Path("/proc/self/fd")

    with fake_client(upload_limit=upload_limit) as client:
        post_extract(client, large_pdf)
        before = len(list(open_files.iterdir()))
        statuses = {
            post_extract(client, large_pdf)["http_status"] for _ in range(5)
        }
        after = len(list(open_files.iterdir()))

    assert statuses == {200 if upload_limit > len(large_pdf) else 413}
    assert after == before
