from app.core.worker_environment import worker_environment


def test_subprocess_environment_excludes_preview_key_without_mutating_parent(monkeypatch):
    monkeypatch.setenv("EXTRACT_PREVIEW_ENABLED", "true")
    monkeypatch.setenv("EXTRACT_PREVIEW_TOKEN", "secret-for-test")
    monkeypatch.setenv("LLM_API_KEY", "llm-secret-for-test")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("UNRELATED_TEST_ENV", "preserved")
    environment = worker_environment(TMPDIR="/private-test", EXTRACT_PREVIEW_TOKEN="override",
                                     EXTRACT_PREVIEW_ENABLED="true")
    assert environment["EXTRACT_PREVIEW_ENABLED"] == "false"
    assert "EXTRACT_PREVIEW_TOKEN" not in environment
    assert "LLM_API_KEY" not in environment and environment["LLM_PROVIDER"] == "disabled"
    assert environment["UNRELATED_TEST_ENV"] == "preserved" and environment["TMPDIR"] == "/private-test"
    import os
    assert os.environ["EXTRACT_PREVIEW_TOKEN"] == "secret-for-test"
