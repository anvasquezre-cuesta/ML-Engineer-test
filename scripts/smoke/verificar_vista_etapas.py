"""Real authenticated preview smoke test and page-overlay rendering."""

import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

import pymupdf

from app.services.fuzzy_service import normalize_name
from verificar_http import BASE, CLIENT, post, wait_for_server


SAMPLE = Path("/samples/meeting_minutes.pdf")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def get(path, *, token=None):
    headers = {"Authorization": "Bearer " + token} if token is not None else {}
    request = urllib.request.Request(BASE + path, headers=headers)
    try:
        with CLIENT.open(request, timeout=15) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers


def collect():
    wait_for_server()
    token = os.environ["EXTRACT_PREVIEW_TOKEN"]
    status, result = post(SAMPLE.read_bytes(), "[]")
    require(status == 200 and isinstance(result.get("extracted_names"), list), "Real extraction failed")
    status, _, _ = get("/api/extract/preview")
    require(status == 401, "Preview did not reject missing authentication")
    status, raw, headers = get("/api/extract/preview", token=token)
    require(status == 200 and headers.get("Cache-Control", "").startswith("no-store"), "Preview catalog unavailable")
    info = json.loads(raw)
    require(info["stages"] == ["ocr", "ner", "recovery_1", "final"], "Unexpected preview stages")
    prefix = "/api/extract/preview/" + info["preview_id"]
    status, pdf, _ = get(prefix + "/document", token=token)
    require(status == 200 and hashlib.sha256(pdf).digest() == hashlib.sha256(SAMPLE.read_bytes()).digest(),
            "Preview proxy does not match the uploaded PDF")
    stages = {}
    for stage in info["stages"]:
        status, raw, _ = get(prefix + "/stages/" + stage, token=token)
        require(status == 200, "Preview stage unavailable")
        stages[stage] = json.loads(raw)
    require(sum(len(page["boxes"]) for page in stages["ocr"]["pages"]) > 0, "OCR stage has no words")
    recovered = [box for page in stages["recovery_1"]["pages"] for box in page["boxes"]]
    require(sum(normalize_name(box["text"]) == "elizabeth park" for box in recovered) == 3,
            "The bulleted repeated name was not recovered")
    require(stages["final"]["extracted_names"] == result["extracted_names"], "Final stage differs from the response")

    # A different successful extraction makes every route for the old ID 404.
    with pymupdf.open() as blank:
        blank.new_page()
        second_pdf = blank.tobytes()
    require(post(second_pdf, "[]")[0] == 200, "Second extraction failed")
    require(get(prefix + "/document", token=token)[0] == 404, "Old PDF remained accessible")
    require(get(prefix + "/stages/ocr", token=token)[0] == 404, "Old stage remained accessible")
    status, raw, _ = get("/api/extract/preview", token=token)
    require(status == 200 and json.loads(raw)["preview_id"] != info["preview_id"], "Latest preview was not replaced")
    sys.stdout.write(json.dumps({"stages": stages}, ensure_ascii=True, separators=(",", ":")) + "\n")


def render(stage):
    bundle = json.load(sys.stdin)
    data = bundle["stages"][stage]
    with pymupdf.open(SAMPLE) as pdf:
        for recorded_page in data["pages"]:
            page = pdf[recorded_page["page_number"]]
            require(page.rotation == 0 and page.cropbox.x0 == 0 and page.cropbox.y0 == 0,
                    "The sample requires a different overlay coordinate transform")
            for item in recorded_page["boxes"]:
                box = item["box"]
                rect = pymupdf.Rect(box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"])
                color = (0, 0.6, 0) if item["source"].startswith("recovery_") else (1, 0, 0)
                page.draw_rect(rect, color=color, width=0.8, overlay=True)
        sys.stdout.buffer.write(pdf.tobytes(deflate=True))


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "collect":
        collect()
    elif len(sys.argv) == 3 and sys.argv[1] == "render" and sys.argv[2] in {"ocr", "ner", "recovery_1", "final"}:
        render(sys.argv[2])
    else:
        raise SystemExit("Usage: verificar_vista_etapas.py collect|render STAGE")


if __name__ == "__main__":
    main()
