from typing import NoReturn

import pytesseract
import pytest
from structlog.testing import capture_logs

from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import OCRSettings
from app.domain.errors import OCRFailed, UpstreamUnavailable
from app.services.health import Check, ReadinessService


def _ok() -> str:
    return "fine"


def _down() -> NoReturn:
    raise UpstreamUnavailable("connection refused")


def test_all_checks_passing_is_ready() -> None:
    report = ReadinessService([Check("ocr", _ok), Check("llm", _ok, critical=False)]).check()

    assert report.status == "ready"
    assert report.serving
    assert [(r.name, r.ok, r.detail) for r in report.checks] == [
        ("ocr", True, "fine"),
        ("llm", True, "fine"),
    ]


def test_non_critical_failure_is_degraded_but_serving() -> None:
    report = ReadinessService([Check("ocr", _ok), Check("llm", _down, critical=False)]).check()

    assert report.status == "degraded"
    assert report.serving
    (llm,) = [r for r in report.checks if r.name == "llm"]
    assert llm.detail == "UpstreamUnavailable: connection refused"


def test_critical_failure_is_unavailable() -> None:
    report = ReadinessService(
        [Check("vector_store", _down), Check("llm", _ok, critical=False)]
    ).check()

    assert report.status == "unavailable"
    assert not report.serving


def test_any_exception_in_a_probe_is_reported_not_raised() -> None:
    def broken() -> str:
        raise ZeroDivisionError("division by zero")

    (result,) = ReadinessService([Check("x", broken)]).check().checks

    assert (result.ok, result.detail) == (False, "ZeroDivisionError: division by zero")


def test_failures_are_logged() -> None:
    with capture_logs() as logs:
        ReadinessService([Check("ocr", _down)]).check()

    (warning,) = [e for e in logs if e["event"] == "readiness_failed"]
    assert warning["failed"] == ["ocr"]


def test_tesseract_probe_reports_version_or_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.4.0")
    assert TesseractOCR(OCRSettings()).version() == "tesseract 5.4.0, lang=eng"

    def missing() -> NoReturn:
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "get_tesseract_version", missing)
    with pytest.raises(OCRFailed):
        TesseractOCR(OCRSettings()).version()
