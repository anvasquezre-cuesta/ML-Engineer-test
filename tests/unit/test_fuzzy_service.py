from app.config import Settings
from app.models.schemas import FuzzyMatch
from app.services import fuzzy_service
from app.services.fuzzy_service import fuzzy_match_names


def _one(name, first, last, **kw):
    return fuzzy_match_names([name], [{"first_name": first, "last_name": last}], **kw)


def test_ac_fuz_01_accents_case():
    assert _one("María González", "Maria", "Gonzalez")[0]["score"] == 1.0


def test_ac_fuz_02_partial_name_no_match():
    assert _one("Maria", "Maria", "Gonzalez") == []


def test_ac_fuz_03_ocr_noise():
    assert _one("Catherlne Dubois", "Catherine", "Dubois")[0]["score"] == 0.9375


def test_ac_fuz_04_inverted_order():
    assert _one("Gonzalez Maria", "Maria", "Gonzalez")[0]["score"] == 1.0


def test_ac_fuz_05_same_last_name():
    assert _one("Robert Chen", "James", "Chen") == []


def test_ac_fuz_06a_explicit_threshold():
    assert _one("Catherlne Dubois", "Catherine", "Dubois", threshold=0.99) == []


def test_ac_fuz_06b_default_from_settings(monkeypatch):
    assert Settings(_env_file=None).fuzzy_threshold == 0.90
    strict = Settings(_env_file=None, fuzzy_threshold=0.95)
    monkeypatch.setattr(fuzzy_service, "get_settings", lambda: strict)

    assert _one("Catherlne Dubois", "Catherine", "Dubois") == []


def test_ac_fuz_07_order_and_rounding():
    query = [
        {"first_name": "María", "last_name": "García"},
        {"first_name": "Robert", "last_name": "Chen"},
        {"first_name": "Mario", "last_name": "Garcia"},
    ]

    result = fuzzy_match_names(["Robert Chen", "Maria Garcia"], query)

    assert result == [
        {
            "extracted_name": "Maria Garcia",
            "matched_name": "María García",
            "score": 1.0,
        },
        {"extracted_name": "Robert Chen", "matched_name": "Robert Chen", "score": 1.0},
        {
            "extracted_name": "Maria Garcia",
            "matched_name": "Mario Garcia",
            "score": 0.9167,
        },
    ]
    tie = fuzzy_match_names(
        ["Ana Ruiz"],
        [
            {"first_name": "Anna", "last_name": "Ruiz"},
            {"first_name": "Ana", "last_name": "Ruizz"},
        ],
    )
    assert [m["matched_name"] for m in tie] == ["Ana Ruizz", "Anna Ruiz"]


def test_ac_fuz_08_dedupe_first_seen():
    query = [
        {"first_name": "Ana", "last_name": "Ruiz"},
        {"first_name": "ANA", "last_name": "RUIZ"},
    ]

    result = fuzzy_match_names(["Ana Ruiz", "ana  ruiz"], query)

    assert result == [
        {"extracted_name": "Ana Ruiz", "matched_name": "Ana Ruiz", "score": 1.0}
    ]


def test_ac_fuz_09_empty_inputs():
    pair = [{"first_name": "Ana", "last_name": "Ruiz"}]

    assert fuzzy_match_names([], pair) == []
    assert fuzzy_match_names(["Ana Ruiz"], []) == []


def test_ac_fuz_10_fuzzy_match_schema():
    match = _one("Robert Chen", "Robert", "Chen")[0]

    assert set(match) == set(FuzzyMatch.model_fields)
    FuzzyMatch(**match)


def test_ac_fuz_11_title_removed():
    assert _one("Dr. Robert Chen", "Robert", "Chen")[0]["score"] == 1.0


def test_ac_fuz_12_threshold_inclusive():
    result = _one("abcd efghi", "abcd", "efghk", threshold=0.90)

    assert result[0]["score"] == 0.9


def test_ac_fuz_13_empty_keys_dropped():
    assert _one("Dr.", ".", "-") == []
