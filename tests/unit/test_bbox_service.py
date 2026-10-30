from app.services import bbox_service
from app.services.bbox_service import boxes_for_spans, locate_names


def word(text, start, end, x, y, width, height, page=0):
    return {
        "word": text,
        "page": page,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "start": start,
        "end": end,
    }


def test_ac_box_01_union_of_words():
    words = [
        word("Ann", 0, 3, 10, 5, 20, 10, page=1),
        word("Lee", 4, 7, 35, 7, 15, 10, page=1),
    ]

    boxes = boxes_for_spans(words, [("Ann Lee", 0, 7)])

    assert boxes == [
        {"name": "Ann Lee", "page": 1, "x": 10, "y": 5, "width": 40, "height": 12}
    ]


def test_ac_box_02_edge_punctuation_is_kept():
    words = [
        word("Margaret", 0, 8, 10, 5, 40, 10),
        word("Thompson,", 9, 18, 55, 5, 50, 10),
    ]

    box = boxes_for_spans(words, [("Margaret Thompson", 0, 17)])[0]

    assert box["x"] + box["width"] == 105


def test_ac_box_03_one_box_per_occurrence():
    words = [
        word("Ann", 0, 3, 10, 5, 20, 10),
        word("Lee", 4, 7, 35, 5, 15, 10),
        word("Ann", 8, 11, 10, 100, 20, 10),
        word("Lee", 12, 15, 35, 100, 15, 10),
    ]

    boxes = boxes_for_spans(words, [("Ann Lee", 0, 7), ("Ann Lee", 8, 15)])

    assert [(b["y"], b["height"]) for b in boxes] == [(5, 10), (100, 10)]


def test_ac_box_06_ner_called_once_for_all_pages(monkeypatch):
    calls = []

    def fake_ner(texts, recognizer):
        calls.append(texts)
        return [[("Ann Lee", 0, 7)] for _ in texts]

    monkeypatch.setattr(bbox_service, "find_person_spans", fake_ner)
    pages = [
        [
            {**word("Ann", 0, 3, 10, 5, 20, 10, page=p), "line": (1, 1, 1)},
            {**word("Lee", 4, 7, 35, 5, 15, 10, page=p), "line": (1, 1, 1)},
        ]
        for p in (0, 1)
    ]

    boxes = locate_names(pages)

    assert calls == [["Ann Lee", "Ann Lee"]]
    assert [b["page"] for b in boxes] == [0, 1]
