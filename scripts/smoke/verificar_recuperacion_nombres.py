"""Real HTTP comparison and temporary PDF overlays for name recovery."""

from collections import Counter
import json
from pathlib import Path
import sys

import pymupdf

from verificar_http import post, wait_for_server


SAMPLE = Path("/samples/meeting_minutes.pdf")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def signature(item):
    box = item["bounding_box"]
    return (item["name"], box["page_number"], box["x"], box["y"], box["width"], box["height"])


def collect():
    wait_for_server()
    status, result = post(SAMPLE.read_bytes(), "[]")
    require(status == 200 and isinstance(result.get("extracted_names"), list), "Real extraction failed")
    require(result.get("fuzzy_matches") == [], "Unexpected query matches for empty names")
    with pymupdf.open(SAMPLE) as pdf:
        for item in result["extracted_names"]:
            box = item["bounding_box"]
            number = box["page_number"]
            require(type(number) is int and 0 <= number < len(pdf), "Invalid page number")
            page = pdf[number]
            x, y, width, height = (box[key] for key in ("x", "y", "width", "height"))
            require(x >= 0 and y >= 0 and width > 0 and height > 0
                    and x + width <= page.cropbox.width + 1e-4
                    and y + height <= page.cropbox.height + 1e-4, "Invalid bounding box")
    sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")


def compare(level):
    lines = sys.stdin.read().splitlines()
    require(len(lines) == 2, "Expected baseline and one active response")
    baseline, current = (json.loads(line) for line in lines)
    before = Counter(signature(item) for item in baseline["extracted_names"])
    after = Counter(signature(item) for item in current["extracted_names"])
    require(not before - after, "An original detection disappeared in the separate HTTP run")
    additions = after - before
    require(all(count == 1 and item not in before for item, count in additions.items()),
            "A recovered location duplicates an existing location")
    print(f"[OK] level={level} baseline={sum(before.values())} "
          f"total={sum(after.values())} additional={sum(additions.values())}; original boxes retained")


def render():
    result = json.load(sys.stdin)
    with pymupdf.open(SAMPLE) as pdf:
        for item in result["extracted_names"]:
            box = item["bounding_box"]
            page = pdf[box["page_number"]]
            # This smoke overlay targets the sample's unrotated, uncropped pages.
            require(page.rotation == 0 and page.cropbox.x0 == 0 and page.cropbox.y0 == 0,
                    "The sample needs a different overlay coordinate transform")
            rect = pymupdf.Rect(box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"])
            page.draw_rect(rect, color=(1, 0, 0), width=0.8, overlay=True)
        sys.stdout.buffer.write(pdf.tobytes(deflate=True))


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "collect":
        collect()
    elif len(sys.argv) == 2 and sys.argv[1] == "render":
        render()
    elif len(sys.argv) == 3 and sys.argv[1] == "compare" and sys.argv[2] in {"1", "2", "3"}:
        compare(sys.argv[2])
    else:
        raise SystemExit("Usage: verificar_recuperacion_nombres.py collect|render|compare LEVEL")


if __name__ == "__main__":
    main()
