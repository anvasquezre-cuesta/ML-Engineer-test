"""Fake PageRenderer that produces blank pages."""

from app.domain.extraction import PageImage
from app.ports.page_renderer import PageRenderer


class BlankPageRenderer(PageRenderer):
    """Renders any PDF as a fixed number of blank US Letter pages."""

    def __init__(self, page_count: int) -> None:
        """Initializes the renderer.

        Args:
            page_count: Number of pages every document has.
        """
        self._page_count = page_count

    def render(self, pdf: bytes) -> list[PageImage]:
        """Returns ``page_count`` blank page images.

        Args:
            pdf: Ignored.

        Returns:
            One image per page, ordered by page number.
        """
        return [
            PageImage(
                page_number=number,
                pixels=b"",
                width_px=0,
                height_px=0,
                width_pt=612.0,
                height_pt=792.0,
            )
            for number in range(self._page_count)
        ]
