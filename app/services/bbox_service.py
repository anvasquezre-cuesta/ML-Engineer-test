"""Map extracted names to their bounding boxes in the PDF.

Implement this. Match NER names against the OCR word boxes and merge the words
of a name into one enclosing box.

Reminders (graded): matching must be case-insensitive and tolerant of OCR noise;
a name's parts should be matched sensibly (don't merge unrelated words from
across the page); return a box per real occurrence.
"""


def find_name_bounding_boxes(pdf_path: str, text: str) -> list[dict]:
    """Return one merged box per located name.

    Suggested shape: ``{"name", "page", "x", "y", "width", "height"}``.
    """
    raise NotImplementedError
