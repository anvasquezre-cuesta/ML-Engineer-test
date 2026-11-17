"""The setup helper must never overwrite existing private configuration."""

from pathlib import Path
import stat

import pytest

from scripts import setup_env


TEMPLATE = "LLM_PROVIDER=disabled\nLLM_MODEL=\nLLM_API_KEY=\nLLM_ALLOW_EXTERNAL=false\n"


def fixture(tmp_path):
    template = tmp_path / "example"
    template.write_text(TEMPLATE, encoding="utf-8")
    return template, tmp_path / ".env"


def test_disabled_configuration_is_private_and_not_enabled(tmp_path):
    template, target = fixture(tmp_path)
    assert setup_env.create_environment(template, target, gemini=False)
    assert target.read_text() == TEMPLATE
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".env.setup-*"))


def test_gemini_configuration_is_explicit_and_uses_recommended_model(tmp_path):
    template, target = fixture(tmp_path)
    assert setup_env.create_environment(template, target, gemini=True, key="synthetic-key_123")
    text = target.read_text()
    assert "LLM_PROVIDER=gemini\n" in text
    assert "LLM_MODEL=gemini-3.5-flash-lite\n" in text
    assert "LLM_API_KEY=synthetic-key_123\n" in text
    assert "LLM_ALLOW_EXTERNAL=true\n" in text
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("key", ["", "bad key", "bad\nkey", "bad$key", "bad#key", "bad'key"])
def test_invalid_key_cannot_write_or_inject_variables(tmp_path, key):
    template, target = fixture(tmp_path)
    with pytest.raises(ValueError):
        setup_env.create_environment(template, target, gemini=True, key=key)
    assert not target.exists() and not list(tmp_path.glob(".env.setup-*"))


def test_existing_file_and_symlink_are_never_read_or_overwritten(tmp_path):
    template, target = fixture(tmp_path)
    target.write_text("existing private configuration", encoding="utf-8")
    assert not setup_env.create_environment(template, target, gemini=True, key="invalid $ key")
    assert target.read_text() == "existing private configuration"
    target.unlink()
    other = tmp_path / "other"
    other.write_text("do not touch", encoding="utf-8")
    target.symlink_to(other)
    assert not setup_env.create_environment(template, target, gemini=False)
    assert other.read_text() == "do not touch"


def test_concurrent_creation_preserves_the_other_file(tmp_path, monkeypatch):
    template, target = fixture(tmp_path)
    def other_writer(source, destination):
        Path(destination).write_text("another writer", encoding="utf-8")
        raise FileExistsError
    monkeypatch.setattr(setup_env.os, "link", other_writer)
    assert not setup_env.create_environment(template, target, gemini=True, key="synthetic-key")
    assert target.read_text() == "another writer"
    assert not list(tmp_path.glob(".env.setup-*"))


def test_changed_template_fails_without_creating_file(tmp_path):
    template, target = fixture(tmp_path)
    template.write_text("LLM_PROVIDER=disabled\n", encoding="utf-8")
    with pytest.raises(ValueError):
        setup_env.create_environment(template, target, gemini=True, key="synthetic-key")
    assert not target.exists()


def test_interactive_gemini_requires_consent_and_never_prints_key(tmp_path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / ".env.example").write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(setup_env, "__file__", str(scripts / "setup_env.py"))
    answers = iter(["g", "yes"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(setup_env, "read_private_key", lambda: "synthetic-key")
    assert setup_env.main([]) == 0
    captured = capsys.readouterr()
    assert "synthetic-key" not in captured.out + captured.err
    assert "LLM_ALLOW_EXTERNAL=true" in (tmp_path / ".env").read_text()


def test_interactive_without_consent_creates_no_file(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / ".env.example").write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(setup_env, "__file__", str(scripts / "setup_env.py"))
    answers = iter(["g", "no"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert setup_env.main([]) == 2
    assert not (tmp_path / ".env").exists()


def test_gemini_quickstart_requests_consent_and_hidden_key(tmp_path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / ".env.example").write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(setup_env, "__file__", str(scripts / "setup_env.py"))
    prompts = []
    def consent(prompt):
        prompts.append(prompt)
        return "yes"
    monkeypatch.setattr("builtins.input", consent)
    monkeypatch.setattr(setup_env, "read_private_key", lambda: "synthetic-key")
    assert setup_env.main(["--gemini"]) == 0
    assert len(prompts) == 1 and "external" in prompts[0].lower()
    assert "synthetic-key" not in capsys.readouterr().out
    assert "LLM_PROVIDER=gemini" in (tmp_path / ".env").read_text()


def test_private_key_input_refuses_noninteractive_stream(monkeypatch):
    monkeypatch.setattr(setup_env.sys.stdin, "isatty", lambda: False)
    with pytest.raises(setup_env.TerminalRequiredError):
        setup_env.read_private_key()


def test_private_key_input_refuses_getpass_echo_fallback(monkeypatch):
    import warnings
    monkeypatch.setattr(setup_env.sys.stdin, "isatty", lambda: True)
    def unsafe_fallback(_):
        warnings.warn("input may be echoed", setup_env.getpass.GetPassWarning)
    monkeypatch.setattr(setup_env.getpass, "getpass", unsafe_fallback)
    with pytest.raises(setup_env.TerminalRequiredError):
        setup_env.read_private_key()
