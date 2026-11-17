from concurrent.futures import ThreadPoolExecutor
import json
import logging
import subprocess
import sys

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.api.dependencies import get_ocr_service, get_retrieval_service
from app.core.config import Settings
from app.core.logging import configure_logging
from app.main import lifespan
from app.services.ocr_service import OCRService


def test_service_dependency_is_shared_for_concurrent_requests():
    app = FastAPI(lifespan=lifespan)

    @app.get("/test-service")
    def service_id(service: OCRService = Depends(get_ocr_service)):
        return {"id": id(service)}

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=8) as executor:
            ids = list(executor.map(lambda _: client.get("/test-service").json()["id"], range(20)))
        assert len(set(ids)) == 1


def test_retrieval_dependency_is_shared_and_closed_on_shutdown():
    app = FastAPI(lifespan=lifespan)
    with TestClient(app):
        request = type("Request", (), {"app": app})()
        service = get_retrieval_service(request)
        assert service is get_retrieval_service(request)
        assert service.ledger is app.state.ingestion_service.ledger
        assert not service._closing
    assert service._closing


def test_log_level_is_validated_and_applied():
    assert Settings(log_level="debug").log_level == "DEBUG"
    with pytest.raises(ValidationError):
        Settings(log_level="NOT_A_LEVEL")
    try:
        configure_logging("ERROR")
        assert not logging.getLogger("app.test").isEnabledFor(logging.DEBUG)
        assert logging.getLogger("app.test").isEnabledFor(logging.ERROR)
        assert logging.getLogger("uvicorn.access").level == logging.ERROR
    finally:
        configure_logging("INFO")


def test_application_logs_are_emitted_as_json():
    script = (
        "import logging; from app.core.logging import configure_logging; "
        "configure_logging('DEBUG'); logging.getLogger('app.test').debug('visible')"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    record = json.loads(result.stderr.strip())
    assert record["level"] == "DEBUG"
    assert record["logger"] == "app.test"
    assert record["message"] == "visible"
