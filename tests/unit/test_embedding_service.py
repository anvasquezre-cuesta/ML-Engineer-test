import math
from contextlib import contextmanager
import sys
import types

import pytest

from app.services import embedding_service
from app.services.embedding_service import (
    EmbeddingInputError,
    EmbeddingModel,
    EmbeddingModelUnavailableError,
    EmbeddingProcessingError,
)


class FakeTokenizer:
    def encode(self, text, *, add_special_tokens, truncation):
        assert truncation is False
        tokens = text.split()
        return [0, *range(len(tokens)), 1] if add_special_tokens else list(range(len(tokens)))


class FakeModel:
    def __init__(self, directory, *, local_files_only, trust_remote_code, device):
        assert local_files_only and not trust_remote_code and device == "cpu"
        self.tokenizer = FakeTokenizer()
        self.max_seq_length = 256
        self.calls = 0

    def get_embedding_dimension(self):
        return 384

    def encode(self, texts, *, batch_size, show_progress_bar, convert_to_numpy, normalize_embeddings):
        assert batch_size == 16 and not show_progress_bar and convert_to_numpy and normalize_embeddings
        self.calls += 1
        return [[0.5] * 384 for _ in texts]


@pytest.fixture
def model(monkeypatch):
    @contextmanager
    def snapshot(path):
        yield path
    monkeypatch.setattr(embedding_service, "verified_model_snapshot", snapshot)
    package = types.ModuleType("sentence_transformers")
    package.SentenceTransformer = FakeModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", package)
    result = EmbeddingModel("unused")
    yield result
    result.close()


def test_missing_or_changed_model_is_reported_without_path_details(monkeypatch):
    @contextmanager
    def unavailable(_):
        raise ValueError("private path")
        yield

    monkeypatch.setattr(embedding_service, "verified_model_snapshot", unavailable)
    with pytest.raises(EmbeddingModelUnavailableError) as error:
        EmbeddingModel("private path")
    assert "private path" not in str(error.value)


def test_embeddings_are_reused_and_empty_list_does_not_infer(model):
    assert model.encode([]) == []
    assert model._model.calls == 0
    result = model.encode(["first text", "second text"])
    assert len(result) == 2 and all(len(vector) == 384 for vector in result)
    assert model._model.calls == 1
    assert model.encode(["third"])[0][0] == 0.5
    assert model._model.calls == 2


@pytest.mark.parametrize("texts", [[""], ["  "], [None], "not-a-list"])
def test_invalid_inputs_are_rejected_before_inference(model, texts):
    with pytest.raises(EmbeddingInputError):
        model.encode(texts)
    assert model._model.calls == 0


def test_token_budget_is_checked_before_inference_without_truncation(model):
    with pytest.raises(EmbeddingInputError):
        model.encode(["one two three"], max_tokens=4)
    assert model._model.calls == 0
    assert len(model.encode(["one two"], max_tokens=4)) == 1


def test_input_count_limit_is_enforced(model):
    with pytest.raises(EmbeddingInputError):
        model.encode(["first", "second"], max_inputs=1)
    assert model._model.calls == 0


def test_non_finite_or_wrong_dimension_vectors_are_rejected(model, monkeypatch):
    monkeypatch.setattr(model._model, "encode", lambda *args, **kwargs: [[math.nan] * 384])
    with pytest.raises(EmbeddingProcessingError):
        model.encode(["text"])
    monkeypatch.setattr(model._model, "encode", lambda *args, **kwargs: [[0.5]])
    with pytest.raises(EmbeddingProcessingError):
        model.encode(["text"])
    monkeypatch.setattr(model._model, "encode", lambda *args, **kwargs: [[0.0] * 384])
    with pytest.raises(EmbeddingProcessingError):
        model.encode(["text"])


def test_tokenizer_errors_do_not_expose_text(model, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("private text")

    monkeypatch.setattr(model.tokenizer, "encode", fail)
    with pytest.raises(EmbeddingProcessingError) as error:
        model.encode(["private text"])
    assert "private text" not in str(error.value)


def test_unknown_tokens_are_encoded_without_rejecting_the_input(model, monkeypatch):
    model.tokenizer.unk_token_id = 99
    monkeypatch.setattr(model.tokenizer, "encode", lambda text, **kwargs: [0, 99, 1] if text else [0, 1])
    assert len(model.encode(["report 📄"])) == 1


def test_queries_use_separate_budget(model, monkeypatch):
    monkeypatch.setattr(embedding_service, "_default_model", model)
    assert len(embedding_service.get_query_embedding("word " * 130)) == 384
