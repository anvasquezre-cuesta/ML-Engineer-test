from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.extraction import PersonSpan
from app.services import ner_service, ner_worker
from app.services.ner_service import (
    NERInputError,
    NERModelUnavailableError,
    NERProcessingError,
    SpacyPersonRecognizer,
    validate_pages,
)


def entity(text, start, end, label):
    return SimpleNamespace(text=text[start:end], start_char=start, end_char=end, label_=label)


def test_recognizer_filters_labels_and_retains_occurrences_and_unicode_offsets():
    text = "😀 María López joined Acme. María López left Paris."
    first = text.index("María López")
    second = text.index("María López", first + 1)
    acme = text.index("Acme")
    paris = text.index("Paris")
    entities = [
        entity(text, first, first + len("María López"), "PERSON"),
        entity(text, acme, acme + 4, "ORG"),
        entity(text, second, second + len("María López"), "PERSON"),
        entity(text, paris, paris + 5, "GPE"),
    ]
    nlp = lambda value: SimpleNamespace(ents=entities)
    spans = SpacyPersonRecognizer(nlp, 1000).detect_page(text)
    assert spans == [PersonSpan("María López", first, first + 11), PersonSpan("María López", second, second + 11)]
    assert all(text[span.char_start:span.char_end] == span.text for span in spans)


def test_pages_are_independent_and_empty_pages_are_preserved():
    calls = []

    def fake_nlp(text):
        calls.append(text)
        start = text.index("Jane Doe")
        return SimpleNamespace(ents=[entity(text, start, start + len("Jane Doe"), "PERSON")])

    recognizer = SpacyPersonRecognizer(fake_nlp, 1000)
    result = recognizer.detect_pages(("Jane Doe", "", "Hi Jane Doe"))
    assert result == [[PersonSpan("Jane Doe", 0, 8)], [], [PersonSpan("Jane Doe", 3, 11)]]
    assert calls == ["Jane Doe", "Hi Jane Doe"]


def test_recognizer_loads_once_and_reuses_model(monkeypatch):
    calls = []
    fake_model = SimpleNamespace(pipe_names=["tok2vec", "ner"])

    def load(model, *, disable):
        calls.append((model, disable))
        return fake_model

    monkeypatch.setitem(__import__("sys").modules, "spacy", SimpleNamespace(load=load))
    recognizer = SpacyPersonRecognizer.load("en_core_web_sm", 123)
    assert recognizer.detect_page("") == []
    assert recognizer.detect_page("") == []
    assert len(calls) == 1
    assert calls[0][0] == "en_core_web_sm"
    assert "ner" not in calls[0][1]


@pytest.mark.parametrize("model", [None, SimpleNamespace(pipe_names=["tok2vec"])])
def test_model_unavailable_or_without_ner_fails_without_leaking_details(monkeypatch, model):
    def load(*args, **kwargs):
        if model is None:
            raise OSError("private model path")
        return model

    monkeypatch.setitem(__import__("sys").modules, "spacy", SimpleNamespace(load=load))
    with pytest.raises(NERModelUnavailableError) as caught:
        SpacyPersonRecognizer.load("private model path", 100)
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("entry", [
    SimpleNamespace(text="OTHER", start_char=0, end_char=4, label_="PERSON"),
    SimpleNamespace(text="Jane", start_char=0, end_char=99, label_="PERSON"),
    SimpleNamespace(text="", start_char=0, end_char=0, label_="PERSON"),
])
def test_invalid_spans_are_rejected_without_exposing_text(entry):
    recognizer = SpacyPersonRecognizer(lambda text: SimpleNamespace(ents=[entry]), 100)
    with pytest.raises(NERProcessingError) as caught:
        recognizer.detect_page("Jane secret")
    assert "secret" not in str(caught.value)


def test_model_inference_errors_are_sanitized():
    def fail(text):
        raise ValueError(f"sensitive {text}")

    with pytest.raises(NERProcessingError) as caught:
        SpacyPersonRecognizer(fail, 100).detect_page("secret")
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_synchronous_compatibility_wrapper_reuses_recognizer(monkeypatch):
    loads = []

    class FakeRecognizer:
        def detect_page(self, text):
            return [PersonSpan("Jane", 0, 4), PersonSpan("Jane", 5, 9)]

    def load(*args):
        loads.append(args)
        return FakeRecognizer()

    ner_service._default_recognizer.cache_clear()
    monkeypatch.setattr(SpacyPersonRecognizer, "load", load)
    try:
        assert ner_service.extract_names("Jane Jane") == ["Jane", "Jane"]
        assert ner_service.extract_names("Jane Jane") == ["Jane", "Jane"]
        assert len(loads) == 1
    finally:
        ner_service._default_recognizer.cache_clear()


def test_input_limits_are_inclusive_and_never_truncate():
    options = {"max_pages": 2, "max_page_chars": 3, "max_document_chars": 5}
    assert validate_pages(["abc", "de"], **options) == ("abc", "de")
    for pages in (["abcd"], ["abc", "abc"], ["a", "b", "c"], "abc", [None]):
        with pytest.raises(NERInputError):
            validate_pages(pages, **options)


def test_sync_recognizer_validates_page_before_calling_model():
    def unexpected(text):
        raise AssertionError("model must not receive excessive input")

    recognizer = SpacyPersonRecognizer(unexpected, 3)
    with pytest.raises(NERInputError):
        recognizer.detect_page("toolong")


def test_worker_returns_page_local_spans_in_protocol(monkeypatch):
    messages = []
    monkeypatch.setattr(ner_worker, "_send", messages.append)

    class FakeRecognizer:
        def detect_pages(self, pages):
            assert pages == ("Jane", "")
            return [[PersonSpan("Jane", 0, 4)], []]

    config = {"max_pages": 2, "max_page_chars": 10, "max_document_chars": 10}
    ner_worker._process_request(b'{"pages":["Jane",""]}', config, FakeRecognizer())
    assert messages == [{"status": "ok", "pages": [[{"text": "Jane", "char_start": 0, "char_end": 4}], []]}]


def test_worker_error_does_not_return_document_text(monkeypatch):
    messages = []
    monkeypatch.setattr(ner_worker, "_send", messages.append)

    class FakeRecognizer:
        def detect_pages(self, pages):
            raise ValueError("private " + pages[0])

    config = {"max_pages": 1, "max_page_chars": 100, "max_document_chars": 100}
    ner_worker._process_request(b'{"pages":["private-name"]}', config, FakeRecognizer())
    assert messages == [{"status": "processing_error"}]


def test_ner_settings_defaults_and_environment(monkeypatch):
    defaults = Settings()
    assert defaults.ner_model == "en_core_web_sm"
    assert defaults.ner_max_page_chars == 100_000
    assert defaults.ner_max_document_chars == 1_000_000
    assert defaults.ner_max_concurrent_jobs == 1
    assert defaults.ner_max_queued_jobs == 1
    monkeypatch.setenv("NER_MODEL", " en_core_web_sm ")
    monkeypatch.setenv("NER_MAX_CONCURRENT_JOBS", "2")
    monkeypatch.setenv("NER_JOB_TIMEOUT_SECONDS", "12")
    settings = Settings()
    assert settings.ner_model == "en_core_web_sm"
    assert settings.ner_max_concurrent_jobs == 2
    assert settings.ner_job_timeout_seconds == 12


@pytest.mark.parametrize("field,value", [
    ("ner_model", "  "), ("ner_max_page_chars", 0), ("ner_max_page_chars", 1_000_001),
    ("ner_max_document_chars", 0), ("ner_max_concurrent_jobs", 0), ("ner_max_queued_jobs", -1),
    ("ner_queue_timeout_seconds", 0), ("ner_job_timeout_seconds", float("inf")),
    ("ner_shutdown_timeout_seconds", float("nan")),
])
def test_ner_invalid_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})
