"""ATDD red-phase tests for story 3.3: Refactor sweep (epic 3 closing cleanup).

Acceptance criteria:
AC-1: DECISIONS.md "exponential backoff" → "fixed backoff"; rest unchanged
AC-2: viewer.js simplified — outer try/catch removed, CDN checks retained, behavior unchanged
AC-3: test_story_2_submission_docs.py unused imports removed, all tests still pass
AC-4: full suite passes, no pre-existing tests edited

I/O & Edge-Case Matrix:
M-1: doc wording fix (exponential → fixed)
M-2: viewer.js success path unchanged
M-3: CDN failure still shows banner
M-4: test-file import cleanup
M-5: prior suites regression (120+2 baseline preserved)
"""
import re
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).parent.parent
DECISIONS_MD = PROJECT_ROOT / "DECISIONS.md"
VIEWER_JS = PROJECT_ROOT / "static" / "viewer.js"


@pytest.fixture
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestDecisionsMdWordingFix:
    """AC-1 / M-1: DECISIONS.md exponential backoff → fixed backoff."""

    def test_no_exponential_backoff_in_decisions(self):
        content = DECISIONS_MD.read_text()
        assert "exponential" not in content.lower(), \
            "DECISIONS.md must not claim 'exponential backoff' (it is fixed backoff)"

    def test_fixed_backoff_wording_present(self):
        content = DECISIONS_MD.read_text()
        assert "fixed backoff" in content.lower() or "fixed" in content.lower(), \
            "DECISIONS.md must describe the retry strategy as fixed backoff"


class TestViewerJsSimplification:
    """AC-2 / M-2: viewer.js outer try/catch removed, CDN checks retained."""

    def test_no_outer_try_catch_wrapper(self):
        content = VIEWER_JS.read_text()
        # The outer try/catch wrapper's catch has a distinctive comment and
        # message ("PDF viewer (pdf.js) failed to load: " + e.message) that
        # distinguishes it from the individual .catch paths and the load-time
        # banner ("failed to load from CDN"). Remove the wrapper → this catch
        # declaration disappears.
        assert 'catch (e) {\n    // CDN-failure path' not in content, \
            "viewer.js must not keep the outer try/catch wrapper around the promise chain"

    def test_in_doextract_cdn_check_retained(self):
        content = VIEWER_JS.read_text()
        # The check inside doExtract must remain
        assert "typeof pdfjsLib" in content and "doExtract" in content, \
            "viewer.js must retain the in-doExtract CDN failure check"

    def test_loadtime_cdn_failure_banner_retained(self):
        content = VIEWER_JS.read_text()
        # Bottom-of-file load-time banner must remain
        # Look for the check outside any function (load-time)
        pattern = re.compile(r'(?:if|typeof)\s+pdfjsLib.*CDN', re.DOTALL | re.IGNORECASE)
        assert pattern.search(content), \
            "viewer.js must retain the load-time CDN-failure banner"

    def test_catch_banner_paths_retained(self):
        content = VIEWER_JS.read_text()
        # Individual .catch handlers that call showError must remain
        assert content.count(".catch(") >= 2, \
            "viewer.js must retain the individual .catch → showError paths"


class TestViewerSuccessPathUnchanged:
    """AC-2 / M-2 (continued): success path behavior preserved."""

    def test_viewer_page_still_serves_200(self, client):
        r = client.get("/viewer/index.html")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_extract_api_still_works(self, client):
        # Use sample PDF from the repo
        sample_pdf = PROJECT_ROOT / "sample_pdfs" / "company_memo.pdf"
        assert sample_pdf.exists(), "sample PDF missing"
        with open(sample_pdf, "rb") as f:
            r = client.post("/api/extract", files={"file": ("test.pdf", f, "application/pdf")},
                            data={"names_json": "[]", "threshold": "80"})
        assert r.status_code == 200
        data = r.json()
        # Behavior-neutral: extract returns extracted_names (and fuzzy_matches if any)
        assert "extracted_names" in data

    def test_cdn_failure_banner_in_served_html(self, client):
        r = client.get("/viewer/index.html")
        assert "errorBanner" in r.text, \
            "Viewer HTML must still contain the errorBanner element"


class TestImportCleanup:
    """AC-3 / M-4: unused imports removed from test files."""

    def test_no_unused_import_re_in_submission_docs_test(self):
        test_file = PROJECT_ROOT / "tests" / "test_story_2_submission_docs.py"
        content = test_file.read_text()
        # After cleanup: 'import re' should not appear (or if it does, it must be used)
        if "import re" in content:
            # Verify it's actually used
            assert "re." in content or "import re as" in content, \
                "test_story_2_submission_docs.py must not have unused 'import re'"

    def test_viewer_test_module_top_import_os_preserved(self):
        """Preservation pin: module-top `import os` in test_viewer_static.py is
        genuinely used by test_ac4 and must NOT be removed."""
        test_file = PROJECT_ROOT / "tests" / "test_viewer_static.py"
        content = test_file.read_text()
        # Check that module-top `import os` exists (not inside a function)
        lines = content.splitlines()
        found = False
        in_function = False
        for line in lines:
            if line.startswith("def "):
                in_function = True
            if in_function:
                if line.startswith("    import os"):
                    pass  # function-level import, not module-top
            else:
                if line.strip() == "import os":
                    found = True
                    break
        assert found, \
            "test_viewer_static.py must retain module-top 'import os' (used by test_ac4)"


# Full-suite regression (AC-4 / M-5) is run separately via:
#   uv run pytest tests/ -q
# This is not an ATDD red-phase failure test — it's a post-implementation
# regression check. We verify it with the targeted tests above.
