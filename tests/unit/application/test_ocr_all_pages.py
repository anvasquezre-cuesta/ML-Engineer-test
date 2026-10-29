from app.application.extract_names import read_pages
from tests.fakes import FakeOcrEngine, FakeRasterizer


def test_every_page_is_ocred_in_order_including_the_first() -> None:
    ocr = FakeOcrEngine()

    pages = read_pages(FakeRasterizer(pages=3), ocr, b"%PDF-", dpi=300)

    assert [page.index for page in pages] == [0, 1, 2]
    assert ocr.calls == [0, 1, 2]
