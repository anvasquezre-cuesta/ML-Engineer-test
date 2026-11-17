"""Check the actual Uvicorn endpoint with real OCR and NER, without mocks."""

import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.request
from uuid import uuid4

import pymupdf

from app.core.config import Settings


BASE = "http://127.0.0.1:8000"
SAMPLE = Path("/samples/meeting_minutes.pdf")
CLIENT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  [OK] {message}", flush=True)


def wait_for_server(seconds: float = 30.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with CLIENT.open(BASE + "/health", timeout=2) as response:
                if response.status == 200 and json.load(response).get("status") == "ok":
                    return
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            pass
        time.sleep(0.2)
    raise AssertionError("The temporary API did not respond within the startup deadline")


def post(pdf: bytes, names: str) -> tuple[int, dict]:
    boundary = ("smoke-" + uuid4().hex).encode("ascii")
    body = (
        b"--" + boundary + b'\r\nContent-Disposition: form-data; name="pdf_file"; filename="document.pdf"'
        b"\r\nContent-Type: application/pdf\r\n\r\n" + pdf
        + b"\r\n--" + boundary + b'\r\nContent-Disposition: form-data; name="names"\r\n\r\n'
        + names.encode("utf-8") + b"\r\n--" + boundary + b"--\r\n"
    )
    request = urllib.request.Request(
        BASE + "/api/extract", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary.decode("ascii")},
        method="POST",
    )
    try:
        with CLIENT.open(request, timeout=180) as response:
            status, data = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, data = error.code, error.read()
    try:
        result = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise AssertionError(f"The API returned a non-JSON response with HTTP {status}") from None
    if not isinstance(result, dict):
        raise AssertionError("The JSON response is not an object")
    return status, result


def synthetic_rotated_pdf() -> tuple[bytes, tuple[float, float, float, float]]:
    """Create an image-only scan with a known position, crop and rotation."""
    with pymupdf.open() as original, pymupdf.open() as scanned:
        page = original.new_page(width=500, height=300)
        page.insert_text((100, 100), "Alice Smith met Bob Jones in London.", fontsize=22)
        expected = page.search_for("Alice Smith")[0] + (-50, -30, -50, -30)
        pixels = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        target = scanned.new_page(width=500, height=300)
        target.insert_image(target.rect, pixmap=pixels)
        target.set_cropbox(pymupdf.Rect(50, 30, 450, 270))
        target.set_rotation(90)
        return scanned.tobytes(), tuple(expected)


def main() -> None:
    print("Waiting for Uvicorn in the temporary container...", flush=True)
    wait_for_server()
    check(True, "GET /health returns HTTP 200 and status=ok")
    check(SAMPLE.is_file(), "The scanned sample PDF is available")
    pdf = SAMPLE.read_bytes()
    with pymupdf.open(SAMPLE) as source:
        dimensions = [(page.cropbox.width, page.cropbox.height) for page in source]
    check(len(dimensions) == 2, "The reference PDF has two pages")
    names = json.dumps([{"first_name": "Thomas", "last_name": "Muller"}])

    print("\n1. Real endpoint: valid PDF and names", flush=True)
    status, result = post(pdf, names)
    check(status == 200, "POST /api/extract returns HTTP 200")
    extracted, fuzzy = result.get("extracted_names"), result.get("fuzzy_matches")
    check(isinstance(extracted, list) and isinstance(fuzzy, list), "The response contains both contract lists")
    pages = {
        item["bounding_box"]["page_number"] for item in extracted if item["name"] == "Thomas Muller"
    }
    check(pages == {0, 1}, "Thomas Muller is located on pages 0 and 1")
    for item in extracted:
        box = item["bounding_box"]
        page_number = box["page_number"]
        if type(page_number) is not int or not 0 <= page_number < len(dimensions):
            raise AssertionError("The response contains an invalid page")
        width, height = dimensions[page_number]
        x, y, w, h = (box[field] for field in ("x", "y", "width", "height"))
        if not (all(math.isfinite(value) for value in (x, y, w, h)) and x >= 0 and y >= 0
                and w > 0 and h > 0 and x + w <= width + 1e-4 and y + h <= height + 1e-4):
            raise AssertionError(f"Page {page_number} contains an invalid bounding box")
    check(True, "Bounding boxes have valid values and fit within their pages")
    exact = [
        item for item in fuzzy
        if item["extracted_name"] == "Thomas Muller"
        and item["matched_name"] == "Thomas Muller"
        and item["score"] == 1.0
    ]
    check(len(exact) == 1, "There is exactly one exact fuzzy match with score 1.0")
    extracted_names = {item["name"] for item in extracted}
    check(
        all(
            item["extracted_name"] in extracted_names
            and item["matched_name"] == "Thomas Muller"
            and math.isfinite(item["score"]) and 0.0 <= item["score"] <= 1.0
            for item in fuzzy
        ),
        "Matches correspond to the extraction and have scores between 0 and 1",
    )

    print("\n2. Real endpoint: empty list and invalid inputs", flush=True)
    status, empty = post(pdf, "[]")
    check(status == 200 and empty.get("fuzzy_matches") == [], "An empty list returns 200 with no matches")
    empty_names = empty.get("extracted_names")
    check(
        isinstance(empty_names, list) and any(item["name"] == "Thomas Muller" for item in empty_names),
        "An empty list does not prevent name extraction from the PDF",
    )
    status, _ = post(pdf, "this-is-not-json")
    check(status == 422, "Invalid JSON returns HTTP 422")
    status, _ = post(b"this-is-not-a-pdf", "[]")
    check(status == 400, "Non-PDF content returns HTTP 400")
    # The client and Uvicorn run in the same container with the same settings.
    settings = Settings()
    names_limit = settings.max_names_bytes
    if names_limit > 1024 * 1024 or len(pdf) + names_limit + 2048 > settings.max_request_bytes:
        raise AssertionError("The image limits do not allow the names field to be checked in isolation")
    status, _ = post(pdf, "x" * (names_limit + 1))
    check(status == 413, "A names field above the configured limit returns HTTP 413")

    print("\n3. Real endpoint: cropped and rotated synthetic scan", flush=True)
    synthetic, expected = synthetic_rotated_pdf()
    status, rotated = post(synthetic, json.dumps([{"first_name": "Alice", "last_name": "Smith"}]))
    check(status == 200, "The cropped and rotated scanned PDF returns HTTP 200")
    found = [item for item in rotated.get("extracted_names", []) if item["name"] == "Alice Smith"]
    check(len(found) == 1, "Alice Smith is detected once in the synthetic scan")
    box = found[0]["bounding_box"]
    center = pymupdf.Point(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    check(box["page_number"] == 0 and center in pymupdf.Rect(expected), "The box center falls within the known PDF position")

    print(f"\nRESULT: real endpoint verified; {len(extracted)} occurrences in the sample PDF.")
    print("No mocks and no changes to the original PDF.")
    print("LIMITATION: does not validate every name or replace human visual review.")


if __name__ == "__main__":
    main()
