import shutil
import tempfile
from pathlib import Path

import pytest

from app.infrastructure.settings import Settings

SAMPLES = Path(__file__).parents[1] / "sample_pdfs"
SAMPLE_PAGE_COUNTS = {"company_memo.pdf": 1, "meeting_minutes.pdf": 2, "research_report.pdf": 2}


@pytest.fixture(scope="session")
def env_settings() -> Settings:
    """Settings as the developer configured them (env + `.env`)."""
    return Settings()


@pytest.fixture(scope="session")
def tesseract_cmd(env_settings: Settings) -> str | None:
    """The configured Tesseract binary; skips the test when none is installed."""
    candidate = env_settings.tesseract_cmd or "tesseract"
    if not (Path(candidate).is_file() or shutil.which(candidate)):
        pytest.skip("Tesseract binary not found — install it or set DOCINTEL_TESSERACT_CMD")
    return env_settings.tesseract_cmd


def sample_bytes(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def temp_entries(prefix: str = "") -> set[str]:
    """Entries of the process temp dir (optionally only those with ``prefix``)."""
    return {p.name for p in Path(tempfile.gettempdir()).iterdir() if p.name.startswith(prefix)}
