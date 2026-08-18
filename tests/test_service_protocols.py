from app.models.domain import OCRDocument, OCRPage
from app.services.protocols import OCRService


class StubOCRService:
    def extract(self, pdf_content: bytes) -> OCRDocument:
        return OCRDocument(pages=(OCRPage(page_number=0, text="", words=()),))


def test_service_protocols_support_structural_dependency_injection() -> None:
    service = StubOCRService()

    assert isinstance(service, OCRService)
    assert service.extract(b"%PDF").pages[0].page_number == 0
