import json
from dataclasses import FrozenInstanceError

import pytest

from app.core.config import Settings
from app.models.extraction import PersonSpan
from app.models.schemas import NamePair
from app.services.extraction_input import InvalidNamesError, NamesLimitError, parse_names


def test_person_span_is_immutable_and_page_local():
    span = PersonSpan("Jane Doe", 5, 13)
    assert (span.text, span.char_start, span.char_end) == ("Jane Doe", 5, 13)
    with pytest.raises(FrozenInstanceError):
        span.char_start = 0


@pytest.mark.parametrize("text,start,end", [
    ("", 0, 1), ("  ", 0, 1), (None, 0, 1), ("Jane", -1, 3),
    ("Jane", 1, 1), ("Jane", 2, 1), ("Jane", 0.5, 3),
    ("Jane", 0, 2.5), ("Jane", "0", 3), ("Jane", False, 3),
])
def test_person_span_rejects_empty_text_or_invalid_range(text, start, end):
    with pytest.raises(ValueError):
        PersonSpan(text, start, end)


def test_names_accept_empty_list_and_preserve_original_strings():
    settings = Settings()
    assert parse_names("[]", settings) == []
    result = parse_names('[{"first_name":" María ","last_name":"González"}]', settings)
    assert result == [NamePair(first_name=" María ", last_name="González")]


@pytest.mark.parametrize("value", [
    "", "{", "null", "{}", '"Jane"', '["Jane"]', '[{}]',
    '[{"first_name":"Jane"}]', '[{"first_name":"", "last_name":"Doe"}]',
    '[{"first_name":" \\t", "last_name":"Doe"}]',
    '[{"first_name":"Jane", "last_name":"\\n"}]',
    '[{"first_name":123, "last_name":"Doe"}]',
    '[{"first_name":"Jane", "last_name":"Doe", "extra":NaN}]',
    '[{"first_name":"\\ud800", "last_name":"Doe"}]',
])
def test_names_reject_invalid_json_shapes_and_blank_or_invalid_names(value):
    with pytest.raises(InvalidNamesError):
        parse_names(value, Settings())


def test_names_invalid_errors_do_not_expose_input():
    secret = "PRIVATE-NAME-123"
    with pytest.raises(InvalidNamesError) as caught:
        parse_names(json.dumps([{"first_name": secret}]), Settings())
    assert secret not in str(caught.value)
    assert caught.value.__suppress_context__


def test_names_byte_limit_counts_utf8_and_json_syntax():
    value = json.dumps([{"first_name": "José", "last_name": "Li"}], ensure_ascii=False)
    exact_size = len(value.encode("utf-8"))
    assert exact_size > len(value)
    assert len(parse_names(value, Settings(max_names_bytes=exact_size))) == 1
    with pytest.raises(NamesLimitError):
        parse_names(value, Settings(max_names_bytes=exact_size - 1))


def test_names_count_limit_is_inclusive_and_does_not_truncate():
    value = json.dumps([{"first_name": "A", "last_name": "B"}] * 2)
    assert len(parse_names(value, Settings(max_names_count=2))) == 2
    with pytest.raises(NamesLimitError):
        parse_names(value, Settings(max_names_count=1))


def test_each_name_component_has_an_inclusive_character_limit():
    value = '[{"first_name":"Alice","last_name":"Li"}]'
    assert len(parse_names(value, Settings(max_name_chars=5))) == 1
    with pytest.raises(NamesLimitError):
        parse_names(value, Settings(max_name_chars=4))


def test_names_reject_deeply_nested_json_safely():
    with pytest.raises(InvalidNamesError):
        parse_names("[" * 2000 + "]" * 2000, Settings())
