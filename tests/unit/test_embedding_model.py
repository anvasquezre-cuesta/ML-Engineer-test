import hashlib

import pytest

from app.core import embedding_model


def test_model_revision_and_dimensions_are_explicit():
    assert embedding_model.MODEL_NAME == "sentence-transformers/all-MiniLM-L6-v2"
    assert embedding_model.MODEL_REVISION == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    assert embedding_model.MODEL_DIMENSIONS == 384
    assert embedding_model.MODEL_MAX_TOKENS == 256


def test_model_artifact_verification_detects_changes_and_missing_files(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"expected")
    expected = hashlib.sha256(b"expected").hexdigest()
    monkeypatch.setattr(embedding_model, "MODEL_FILES", {"artifact.bin": expected})
    embedding_model.verify_model_files(tmp_path)
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="failed verification"):
        embedding_model.verify_model_files(tmp_path)
    artifact.unlink()
    with pytest.raises(ValueError, match="unavailable"):
        embedding_model.verify_model_files(tmp_path)


def test_snapshot_ignores_extra_loader_files_and_isolates_source_changes(tmp_path, monkeypatch):
    artifact = tmp_path / "config.json"
    artifact.write_bytes(b"expected")
    (tmp_path / "added_tokens.json").write_text("malicious-extra")
    monkeypatch.setattr(embedding_model, "MODEL_FILES", {"config.json": hashlib.sha256(b"expected").hexdigest()})
    with embedding_model.verified_model_snapshot(tmp_path) as snapshot:
        artifact.write_bytes(b"changed-after-copy")
        assert (snapshot / "config.json").read_bytes() == b"expected"
        assert not (snapshot / "added_tokens.json").exists()
    assert not snapshot.exists()
