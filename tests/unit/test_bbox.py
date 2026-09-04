from app.services.bbox_service import locate
from tests.fakes import page_from_lines


def test_box_encloses_all_words_of_the_name():
    page = page_from_lines(0, ["Dear María González, welcome"])
    [box] = locate("Maria Gonzalez", page, 0.8)
    maria, gonzalez = page.words[1], page.words[2]
    assert box.page == 0
    assert (box.x, box.y) == (maria.x, maria.y)
    assert box.x + box.width == gonzalez.x + gonzalez.width
    assert box.height == 12


def test_one_box_per_occurrence():
    page = page_from_lines(0, ["John Smith met John Smith", "and John Smith again"])
    assert len(locate("John Smith", page, 0.8)) == 3


def test_name_wrapping_to_next_line_is_found():
    page = page_from_lines(0, ["signed by John", "Smith on Monday"])
    [box] = locate("John Smith", page, 0.8)
    assert box.height > 12  # spans two lines


def test_words_from_unrelated_lines_are_not_stitched():
    page = page_from_lines(0, ["John was here", "nothing", "Smith was there"])
    assert locate("John Smith", page, 0.8) == []


def test_ocr_noise_in_a_token_is_tolerated():
    page = page_from_lines(0, ["contact Maria Gonza1ez today"])
    assert len(locate("Maria Gonzalez", page, 0.8)) == 1


def test_partial_name_is_not_a_match():
    page = page_from_lines(0, ["Maria Lopez"])
    assert locate("Maria Gonzalez", page, 0.8) == []


def test_apostrophe_name_matches_single_ocr_word():
    page = page_from_lines(0, ["- Kevin O'Brien, General Counsel"])
    [box] = locate("Kevin O'Brien", page, 0.8)
    assert box.width > 40  # spans both words
