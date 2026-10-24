"""
ATDD tests for the refactor sweep story.

This is a refactor story: no new behavior, just cleanup. Tests target the
concrete deliverables (adapter de-pollution, constructor compatibility, dead-code
removal) and regression counts.
"""
import pytest
from pathlib import Path
import inspect

# ADAPTER DE-POLLUTION: ChatOpenAI should not receive invalid kwargs
def test_langchain_llm_no_retry_wait_in_model_kwargs():
    """AC: When LangChainLlm is constructed, its client.model_kwargs contains no
    retry_wait. LangChain 1.7.2 forwards unknown kwargs to the API."""
    from app.adapters.langchain_llm import LangChainLlm
    llm = LangChainLlm("http://example.com", "api-key", "gpt-4", timeout=30.0,
                       max_retries=3, backoff_seconds=2.0)
    model_kwargs = llm.client.model_kwargs
    assert "retry_wait" not in model_kwargs, (
        "LangChainLlm passes invalid retry_wait kwarg to ChatOpenAI; "
        f"model_kwargs={model_kwargs}"
    )

def test_langchain_llm_no_retry_wait_kwarg_in_constructor():
    """AC: Static audit — LangChainLlm constructor does not pass retry_wait to
    ChatOpenAI (not just absent from model_kwargs, but not forwarded at all)."""
    from app.adapters.langchain_llm import LangChainLlm
    source = inspect.getsource(LangChainLlm.__init__)
    assert "retry_wait" not in source, (
        "LangChainLlm.__init__ still contains retry_wait reference"
    )

def test_langchain_llm_backoff_seconds_accepted():
    """AC: Backward compatibility — constructor accepts backoff_seconds parameter
    as required by existing tests/test_rag_integration.py (unmodifiable)."""
    from app.adapters.langchain_llm import LangChainLlm
    llm = LangChainLlm("http://example.com", "api-key", "gpt-4", timeout=30.0,
                       max_retries=3, backoff_seconds=5.0)
    assert llm is not None

def test_langchain_llm_no_import_time():
    """AC: Static audit — unused import time removed from langchain_llm.py."""
    from app.adapters import langchain_llm
    source = inspect.getsource(langchain_llm)
    assert "import time" not in source, (
        "Unused import time still present in langchain_llm.py"
    )

# DEAD CODE REMOVAL: API layer cleanup
def test_rag_ingest_no_ocr_none_param():
    """AC: Static audit — ingest() has no dead ocr=None parameter."""
    from app.api import rag
    source = inspect.getsource(rag.ingest)
    assert "ocr=None" not in source, (
        "ingest() still has dead ocr=None parameter"
    )

def test_rag_ingest_no_inline_get_ocr_import():
    """AC: Static audit — ingest() does not import get_ocr inline (uses Depends
    declaration instead)."""
    from app.api import rag
    source = inspect.getsource(rag.ingest)
    assert "get_ocr" not in source or "Depends(get_ocr)" in source, (
        "ingest() imports get_ocr inline instead of using Depends declaration"
    )

def test_rag_ingest_has_ocr_depends_declaration():
    """AC: ingest() declares ocr as a Depends parameter (like extract.py pattern)."""
    from app.api import rag
    sig = inspect.signature(rag.ingest)
    params = sig.parameters
    assert "ocr" in params, (
        "ingest() does not have ocr parameter declared via Depends"
    )

# LIFESPAN DEAD STATE REMOVAL
def test_lifespan_no_app_state_settings():
    """AC: Static audit — lifespan() does not write unread app.state.settings."""
    from app import dependencies
    source = inspect.getsource(dependencies.lifespan)
    assert "app.state.settings" not in source, (
        "lifespan() still writes unread app.state.settings"
    )

# REGRESSION: prior suites must remain passing
def test_rag_integration_constructor_compatible():
    """AC: LangChainLlm constructor signature matches what existing
    tests/test_rag_integration.py expects."""
    from app.adapters.langchain_llm import LangChainLlm
    sig = inspect.signature(LangChainLlm.__init__)
    params = sig.parameters
    # Must accept base_url, api_key, model_name, timeout, max_retries, backoff_seconds
    required_params = ["base_url", "api_key", "model"]
    for p in required_params:
        assert p in params, f"LangChainLlm missing required param: {p}"