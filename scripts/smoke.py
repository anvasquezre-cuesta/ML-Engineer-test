"""Smoke test of a running deployment over HTTP.

Checks health, the three README endpoints on a sample PDF, one job that
succeeds and one poison job that is dead-lettered. Exits non-zero on the
first failed check.
"""

import argparse
from collections.abc import Callable
import json
import pathlib
import sys
import time
from typing import Any

import httpx

MEMO = pathlib.Path("sample_pdfs/company_memo.pdf")
MEMO_NAMES = [
    {"first_name": "Robert", "last_name": "Chen"},
    {"first_name": "Margaret", "last_name": "Thompson"},
]
QUESTION = "Who was promoted to Vice President of Engineering?"
POISON = b"%PDF-1.7\nthis is not a readable document"
TERMINAL = ("succeeded", "dead_lettered")


class SmokeError(Exception):
    """A smoke check failed."""


def check(ok: bool, label: str, detail: object = "") -> None:
    """Prints the outcome of one check and stops on a failure.

    Args:
        ok: Whether the check passed.
        label: What was checked.
        detail: Context shown with the outcome.

    Raises:
        SmokeError: If the check failed.
    """
    print(f"{'PASS' if ok else 'FAIL'} {label} {detail}".rstrip())
    if not ok:
        raise SmokeError(label)


def upload(pdf: bytes, filename: str) -> dict[str, tuple[str, bytes, str]]:
    """Builds the multipart file field of an upload.

    Args:
        pdf: The document.
        filename: Name sent with it.

    Returns:
        The ``files`` argument for httpx.
    """
    return {"pdf_file": (filename, pdf, "application/pdf")}


def wait_for_job(
    client: httpx.Client, job_id: str, timeout_s: float
) -> dict[str, Any]:
    """Polls a job until it reaches a terminal state.

    Args:
        client: Client bound to the deployment.
        job_id: Id of the job.
        timeout_s: Longest wait.

    Returns:
        The last job record read.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        job: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in TERMINAL or time.monotonic() > deadline:
            return job
        time.sleep(2)


def check_health(client: httpx.Client, options: argparse.Namespace) -> None:
    """Checks the liveness probe.

    Args:
        client: Client bound to the deployment.
        options: Command-line options; not used by this check.
    """
    response = client.get("/health")
    check(response.json().get("status") == "ok", "health", response.text)


def check_extract(client: httpx.Client, options: argparse.Namespace) -> None:
    """Checks names, boxes and matches on the sample memo.

    Args:
        client: Client bound to the deployment.
        options: Command-line options; not used by this check.
    """
    response = client.post(
        "/api/extract",
        files=upload(MEMO.read_bytes(), MEMO.name),
        data={"names": json.dumps(MEMO_NAMES)},
    )
    check(response.status_code == 200, "extract status", response.status_code)
    body = response.json()
    found = {n["name"] for n in body["extracted_names"]}
    boxes = [n["bounding_box"] for n in body["extracted_names"]]
    check(
        {"Robert Chen", "Margaret Thompson"} <= found,
        "extract finds the memo's names",
        sorted(found),
    )
    check(
        all(b["page_number"] == 0 and 0 <= b["x"] <= 612 for b in boxes),
        "extract boxes are on page 0 in points",
    )
    matched = {m["matched_name"] for m in body["fuzzy_matches"]}
    check(
        matched == {"Robert Chen", "Margaret Thompson"},
        "extract matches both queried names",
        sorted(matched),
    )


def check_rag(client: httpx.Client, options: argparse.Namespace) -> None:
    """Checks that an ingested memo answers a question with its source.

    Args:
        client: Client bound to the deployment.
        options: Command-line options; not used by this check.
    """
    ingest = client.post(
        "/api/ingest", files=upload(MEMO.read_bytes(), MEMO.name)
    )
    check(ingest.status_code == 200, "ingest", ingest.text)
    answer = client.post("/api/ask", json={"question": QUESTION}).json()
    check("Robert Chen" in answer.get("answer", ""), "ask answer", answer)
    check(
        any(s.startswith(f"{MEMO.name}#") for s in answer.get("sources", [])),
        "ask cites the memo",
    )


def check_jobs(client: httpx.Client, options: argparse.Namespace) -> None:
    """Checks a successful job and a dead-lettered poison job.

    Args:
        client: Client bound to the deployment.
        options: Holds the job timeout.
    """
    names = {"names": json.dumps(MEMO_NAMES)}
    good = client.post(
        "/api/jobs/extract",
        files=upload(MEMO.read_bytes(), MEMO.name),
        data=names,
    )
    check(good.status_code == 202, "job accepted", good.text)
    bad = client.post(
        "/api/jobs/extract", files=upload(POISON, "poison.pdf"), data=names
    )
    check(bad.status_code == 202, "poison job accepted", bad.text)
    done = wait_for_job(client, good.json()["job_id"], options.job_timeout)
    check(done["status"] == "succeeded", "job succeeds", done["status"])
    dead = wait_for_job(client, bad.json()["job_id"], options.job_timeout)
    check(
        (dead["status"], dead["last_error_code"])
        == ("dead_lettered", "ocr.unreadable"),
        "poison job is dead-lettered",
        (dead["status"], dead["last_error_code"]),
    )
    listed = client.get("/api/jobs", params={"status": "dead_lettered"})
    check(
        dead["job_id"] in {j["job_id"] for j in listed.json()},
        "poison job is listed as dead-lettered",
    )


CHECKS: tuple[Callable[[httpx.Client, argparse.Namespace], None], ...] = (
    check_health,
    check_extract,
    check_rag,
    check_jobs,
)


def main() -> int:
    """Runs every check against the deployment given on the command line.

    Returns:
        The process exit code: 0 when every check passed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--job-timeout", type=float, default=180.0)
    options = parser.parse_args()
    with httpx.Client(
        base_url=options.base_url, timeout=options.timeout
    ) as client:
        try:
            for run in CHECKS:
                run(client, options)
        except SmokeError:
            return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
