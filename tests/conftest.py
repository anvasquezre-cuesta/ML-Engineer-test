from collections.abc import Iterator

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    """Settings are cached per process; clear around each test so env changes apply."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
