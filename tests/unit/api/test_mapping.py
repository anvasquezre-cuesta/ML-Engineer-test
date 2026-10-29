from app.api.mapping import to_extraction_response
from app.application.extract_names import ExtractionResult
from app.domain.geometry import BoundingBox
from app.domain.persons import NameOccurrence


def test_box_coordinates_are_rounded_to_hundredths_of_a_point() -> None:
    box = BoundingBox(76.8, 98.88, 88.32000000000001, 9.120000000000005)
    result = ExtractionResult(1, (NameOccurrence("Margaret Thompson", 0, box),), ())

    out = to_extraction_response(result).extracted_names[0].bounding_box

    assert (out.page_number, out.x, out.y, out.width, out.height) == (0, 76.8, 98.88, 88.32, 9.12)
