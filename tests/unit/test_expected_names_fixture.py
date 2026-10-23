"""Guards the golden-test labels against accidental edits."""

import json
from pathlib import Path

FIXTURE = Path(__file__).parents[1] / "fixtures" / "expected_names.json"
SAMPLES = Path(__file__).parents[2] / "sample_pdfs"


def test_fixture_covers_every_sample_pdf_and_counts_add_up() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    documents = data["documents"]

    assert set(documents) == {p.name for p in SAMPLES.glob("*.pdf")}
    assert sum(len(d["mentions"]) for d in documents.values()) == data["total_mentions"]
    for doc in documents.values():
        assert all(0 <= m["page"] < doc["page_count"] for m in doc["mentions"])
