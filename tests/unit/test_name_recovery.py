import re

import pytest

from app.models.document import OCRPage, OCRWord, WordBox
from app.models.extraction import PersonSpan
from app.services.bbox_service import PageLocator
from app.services.name_recovery import (
    LocatedOccurrence, NameRecoveryLimitError, RecoveryPage, _at_most_one_edit, recover_names,
)


def make_page(text, number=0, *, positions=None, blocks=None, lines=None):
    words = []
    for index, match in enumerate(re.finditer(r"\S+", text)):
        x = positions[index] if positions is not None else 10 + index * 30
        block = blocks[index] if blocks is not None else 1
        line = lines[index] if lines is not None else 1
        words.append(OCRWord(match.group(), WordBox(x, 10 + (line - 1) * 12, 20, 10),
                             match.start(), match.end(), block, 1, line, 95))
    return OCRPage(number, 2000, 2000, text, tuple(words))


def recovery_page(page, *seeds):
    locator = PageLocator(page)
    occurrences = []
    for text, offset in seeds:
        span = PersonSpan(text, offset, offset + len(text))
        location = locator.locate(span)
        assert location is not None
        occurrences.append(LocatedOccurrence(span, location))
    return RecoveryPage(locator, tuple(occurrences))


def recover(pages, passes=1, max_new=1000):
    return recover_names(pages, passes=passes, max_name_chars=512, max_new=max_new)


def test_exact_recovery_preserves_original_text_page_offsets_and_boxes():
    first = make_page("Luisa Cha met Luisa Cha", 0)
    second = make_page("LUISA CHÁ returned", 1)
    result = recover([recovery_page(first, ("Luisa Cha", 0)), recovery_page(second)])
    assert [(item.location.name, item.location.bounding_box.page_number, item.span.char_start)
            for item in result.occurrences] == [("Luisa Cha", 0, 14), ("LUISA CHÁ", 1, 0)]
    assert result.occurrences[0].location.bounding_box.x == first.words[3].box.x
    assert result.occurrences[1].location.bounding_box.x == second.words[0].box.x


def test_exact_recovery_handles_adjacent_lines_but_not_unrelated_blocks():
    page = make_page("Luisa Cha Luisa\nCha", lines=[1, 1, 2, 3], positions=[10, 40, 10, 10])
    result = recover([recovery_page(page, ("Luisa Cha", 0))])
    assert [item.location.name for item in result.occurrences] == ["Luisa\nCha"]
    page = make_page("Luisa Cha Luisa Cha", blocks=[1, 1, 2, 3])
    assert not recover([recovery_page(page, ("Luisa Cha", 0))]).occurrences


def test_distant_words_do_not_produce_an_invented_box():
    page = make_page("Luisa Cha Luisa Cha", positions=[10, 40, 100, 300])
    assert not recover([recovery_page(page, ("Luisa Cha", 0))]).occurrences


@pytest.mark.parametrize("candidate", ["- Luisa Cha,", "• Luisa Cha ."])
def test_punctuation_only_boundary_words_do_not_make_one_name_ambiguous(candidate):
    page = make_page("Luisa Cha " + candidate)
    result = recover([recovery_page(page, ("Luisa Cha", 0))], passes=1)
    assert [item.location.name for item in result.occurrences] == ["Luisa Cha," if "," in candidate else "Luisa Cha"]
    assert result.ambiguous_groups == 0


def test_existing_and_overlapping_ner_occurrences_are_never_duplicated():
    page = make_page("Luisa Cha Luisa Cha")
    result = recover([recovery_page(page, ("Luisa Cha", 0), ("Luisa Cha", 10))], passes=3)
    assert not result.occurrences


def test_fuzzy_requires_level_two_and_preserves_short_name_components():
    page = make_page("Luisa Morales Luisa Moralez Luisa Cha Luisa Chao")
    data = recovery_page(page, ("Luisa Morales", 0), ("Luisa Cha", page.text.index("Luisa Cha")))
    assert not recover([data], passes=1).occurrences
    assert [item.location.name for item in recover([data], passes=2).occurrences] == ["Luisa Moralez"]
    assert [item.location.name for item in recover([data], passes=3).occurrences] == ["Luisa Moralez"]


def test_fuzzy_compares_name_and_surname_independently_but_requires_both():
    page = make_page("Luisa Morales Lulsa Moralez Lulsa Chao Luisa")
    data = recovery_page(page, ("Luisa Morales", 0))
    assert not recover([data], passes=1).occurrences
    result = recover([data], passes=2)
    assert [item.location.name for item in result.occurrences] == ["Lulsa Moralez"]


def test_component_fuzzy_keeps_short_names_exact_and_rejects_ambiguous_identity():
    page = make_page("Luisa Cha Lulsa Chao Luisa Cha")
    data = recovery_page(page, ("Luisa Cha", 0))
    assert [item.location.name for item in recover([data], passes=2).occurrences] == ["Luisa Cha"]

    page = make_page("Luisa Morales Lulsa Morales Lulsa Moralez")
    data = recovery_page(page, ("Luisa Morales", 0), ("Lulsa Morales", 14))
    result = recover([data], passes=2)
    assert not result.occurrences and result.ambiguous_groups == 1


def test_punctuation_inside_a_name_is_not_treated_as_a_boundary():
    page = make_page("Anna Marie Jones Anna - Marie Jones")
    data = recovery_page(page, ("Anna Marie Jones", 0))
    assert [item.location.name for item in recover([data], passes=1).occurrences] == ["Anna - Marie Jones"]


def test_fuzzy_rejects_ambiguous_candidates_and_never_promotes_them_to_seeds():
    page = make_page("Luisa Morales Luisa Moralez Luisa Morale")
    data = recovery_page(page, ("Luisa Morales", 0), ("Luisa Moralez", 14))
    result = recover([data], passes=3)
    assert not result.occurrences and result.ambiguous_groups == 1

    page = make_page("Luisa Morales Luisa Moralez Luisa Moralezz")
    result = recover([recovery_page(page, ("Luisa Morales", 0))], passes=3)
    assert [item.location.name for item in result.occurrences] == ["Luisa Moralez"]


def test_level_three_recovers_only_exact_compact_segmentation():
    page = make_page("Luisa Cha Luisacha Luisachb")
    data = recovery_page(page, ("Luisa Cha", 0))
    assert not recover([data], passes=2).occurrences
    assert [item.location.name for item in recover([data], passes=3).occurrences] == ["Luisacha"]


def test_compact_ambiguity_and_overlapping_exact_alternatives_are_refused():
    page = make_page("Luisa Cha Luis Acha Luisacha")
    data = recovery_page(page, ("Luisa Cha", 0), ("Luis Acha", 10))
    result = recover([data], passes=3)
    assert not result.occurrences and result.ambiguous_groups == 1

    page = make_page("Luisa Cha Luisa Cha Junior Luisa Cha Junior")
    data = recovery_page(page, ("Luisa Cha", 0), ("Luisa Cha Junior", 10))
    result = recover([data], passes=3)
    assert not result.occurrences and result.ambiguous_groups == 1


@pytest.mark.parametrize("seed", ["Luisa", "A B C D E F G H I"])
def test_single_word_and_more_than_eight_components_are_not_seeds(seed):
    page = make_page(seed + " " + seed)
    assert not recover([recovery_page(page, (seed, 0))], passes=3).occurrences


def test_reference_over_512_characters_is_not_used_even_if_request_limit_is_higher():
    seed = "L" * 510 + " Smith"
    page = make_page(seed + " " + seed)
    result = recover_names([recovery_page(page, (seed, 0))], passes=3, max_name_chars=1024, max_new=10)
    assert not result.occurrences


def test_no_seed_or_zero_passes_does_not_find_names():
    page = make_page("Luisa Cha Luisa Cha")
    assert not recover([recovery_page(page)], passes=3).occurrences
    assert not recover([recovery_page(page, ("Luisa Cha", 0))], passes=0).occurrences


def test_no_seed_skips_even_a_zero_window_budget(monkeypatch):
    monkeypatch.setattr("app.services.name_recovery.MAX_RECOVERY_WINDOWS", 0)
    assert not recover([recovery_page(make_page("Luisa Cha"))], passes=3).occurrences


def test_overlong_candidate_does_not_prevent_later_valid_occurrences():
    text = "Luisa Cha " + "x" * 513 + " Luisa Cha"
    page = make_page(text)
    result = recover([recovery_page(page, ("Luisa Cha", 0))], passes=1)
    assert [item.span.char_start for item in result.occurrences] == [text.rindex("Luisa Cha")]


def test_results_are_deterministic_across_repeated_passes():
    page = make_page("Luisa Morales Luisa Moralez Luisa Morales")
    data = recovery_page(page, ("Luisa Morales", 0))
    assert recover([data], passes=3) == recover([data], passes=3)


@pytest.mark.parametrize("constant", ["MAX_RECOVERY_WINDOWS", "MAX_RECOVERY_COMPARISONS", "MAX_RECOVERY_WORK_UNITS"])
def test_recovery_work_limits_fail_without_partial_results(monkeypatch, constant):
    monkeypatch.setattr("app.services.name_recovery." + constant, 0)
    page = make_page("Luisa Cha Luisa Cha")
    with pytest.raises(NameRecoveryLimitError):
        recover([recovery_page(page, ("Luisa Cha", 0))])


def test_recovery_result_limit_is_enforced():
    page = make_page("Luisa Cha Luisa Cha")
    with pytest.raises(NameRecoveryLimitError):
        recover([recovery_page(page, ("Luisa Cha", 0))], max_new=0)
    assert len(recover([recovery_page(page, ("Luisa Cha", 0))], max_new=1).occurrences) == 1


def test_budget_is_cumulative_and_inclusive(monkeypatch):
    from app.services.name_recovery import _Budget

    monkeypatch.setattr("app.services.name_recovery.MAX_RECOVERY_WINDOWS", 1)
    monkeypatch.setattr("app.services.name_recovery.MAX_RECOVERY_COMPARISONS", 1)
    monkeypatch.setattr("app.services.name_recovery.MAX_RECOVERY_WORK_UNITS", 5)
    budget = _Budget()
    budget.window()
    assert budget.normalize("x") == "x"
    budget.compare("ab", "cd")  # 1 normalization unit + 2*2 comparison units.
    with pytest.raises(NameRecoveryLimitError):
        budget.window()
    with pytest.raises(NameRecoveryLimitError):
        budget.compare("a", "a")


@pytest.mark.parametrize("left,right,expected", [
    ("abc", "abc", True), ("abc", "abd", True), ("abc", "abbc", True),
    ("abc", "ac", True), ("abc", "bac", False), ("abc", "xyz", False),
    ("abc", "abcde", False), ("", "a", True),
])
def test_one_edit_distance(left, right, expected):
    assert _at_most_one_edit(left, right) is expected


def test_one_edit_distance_matches_reference_for_small_inputs():
    from itertools import product
    from Levenshtein import distance

    samples = ["".join(chars) for size in range(5) for chars in product("ab", repeat=size)]
    assert all(_at_most_one_edit(left, right) == (distance(left, right) <= 1)
               for left in samples for right in samples)
