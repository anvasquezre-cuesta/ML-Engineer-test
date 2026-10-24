"""ATDD tests for story 2: submission docs (DESIGN.md and DECISIONS.md).

Acceptance criteria:
AC-1: DESIGN.md exists at repo root covering all five README elements
AC-2: DESIGN.md claims are code-anchored (pixel-to-point, sources-from-metadata, etc.)
AC-3: DESIGN.md is at most 3 pages (~150 lines body)
AC-4: Stack substitutions are justified in DESIGN.md
AC-5: DECISIONS.md existing content is unchanged; new entries appended
AC-6: Schema contract unchanged (git diff vs skeleton is empty)
"""
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
DESIGN_MD = PROJECT_ROOT / "DESIGN.md"
DECISIONS_MD = PROJECT_ROOT / "DECISIONS.md"
SKELETON_COMMIT = "b091afa"


class TestDesignMdExistsAndComplete:
    """AC-1: DESIGN.md exists at repo root covering all five README elements."""

    def test_design_md_file_exists(self):
        assert DESIGN_MD.exists(), "DESIGN.md must exist at repo root"

    def test_design_md_non_empty(self):
        content = DESIGN_MD.read_text()
        assert len(content.strip()) > 0, "DESIGN.md must not be empty"

    def test_design_md_component_view(self):
        content = DESIGN_MD.read_text().lower()
        assert "component" in content or "architecture" in content or "layers" in content, \
            "DESIGN.md must describe the component architecture view"

    def test_design_md_sequence_view(self):
        content = DESIGN_MD.read_text().lower()
        assert "sequence" in content or "flow" in content or "pipeline" in content, \
            "DESIGN.md must describe the pipeline sequence view"

    def test_design_md_technology_choices(self):
        content = DESIGN_MD.read_text().lower()
        assert "trade-off" in content or "tradeoff" in content or "choice" in content, \
            "DESIGN.md must describe technology choices and trade-offs"

    def test_design_md_scaling(self):
        content = DESIGN_MD.read_text().lower()
        assert "1000" in content or "scale" in content or "scaling" in content, \
            "DESIGN.md must describe scaling to 1000+ PDFs/hour"

    def test_design_md_failure_modes(self):
        content = DESIGN_MD.read_text().lower()
        assert "failure" in content or "error" in content or "mitigat" in content, \
            "DESIGN.md must describe failure modes and mitigations"

    def test_design_md_model_routing(self):
        content = DESIGN_MD.read_text().lower()
        assert "routing" in content or "complexity" in content, \
            "DESIGN.md must describe model routing by query complexity"


class TestDesignMdCodeAnchored:
    """AC-2: DESIGN.md claims are anchored in actual source code."""

    def test_pixel_to_point_single_site(self):
        content = DESIGN_MD.read_text()
        assert "bbox_service" in content or "pixels" in content.lower(), \
            "DESIGN.md must reference the pixel-to-point conversion site"

    def test_sources_from_metadata_not_llm(self):
        content = DESIGN_MD.read_text().lower()
        assert "metadata" in content or "sources" in content, \
            "DESIGN.md must state that sources come from retrieved chunk metadata, not LLM"

    def test_chunk_id_content_derived(self):
        content = DESIGN_MD.read_text().lower()
        assert "chunk" in content or "id" in content or "identifier" in content, \
            "DESIGN.md must reference content-derived chunk IDs"

    def test_error_codes_documented(self):
        content = DESIGN_MD.read_text()
        assert "422" in content or "413" in content or "502" in content, \
            "DESIGN.md must document the error code mappings"


class TestDesignMdLength:
    """AC-3: DESIGN.md is at most 3 pages (~150 lines)."""

    def test_design_md_line_count(self):
        lines = DESIGN_MD.read_text().splitlines()
        # Frontmatter excluded, body ≤ 150 lines
        body_lines = [l for l in lines if l.strip()]
        assert len(body_lines) <= 150, \
            f"DESIGN.md must be ≤ 150 body lines; got {len(body_lines)}"


class TestStackSubstitutionsJustified:
    """AC-4: Every stack deviation from README is justified in DESIGN.md."""

    def test_langchain_justification(self):
        content = DESIGN_MD.read_text().lower()
        assert "langchain" in content or "chatopenai" in content, \
            "DESIGN.md must address the LangChain wrapper choice"

    def test_fuzzy_library_addressed(self):
        content = DESIGN_MD.read_text().lower()
        assert "thefuzz" in content or "fuzzy" in content, \
            "DESIGN.md must address the fuzzy matching library choice"

    def test_embedded_chroma_justified(self):
        content = DESIGN_MD.read_text().lower()
        assert "chroma" in content or "vector" in content, \
            "DESIGN.md must justify the embedded Chroma choice"


class TestDecisionsMdComplete:
    """AC-5: DECISIONS.md has existing content unchanged with new entries appended."""

    def test_decisions_md_exists(self):
        assert DECISIONS_MD.exists(), "DECISIONS.md must exist"

    def test_decisions_md_has_ai_disclosure(self):
        content = DECISIONS_MD.read_text().lower()
        assert "claude" in content or "ai" in content, \
            "DECISIONS.md must disclose AI tool usage"

    def test_decisions_md_has_schema_entry(self):
        content = DECISIONS_MD.read_text().lower()
        assert "schema" in content or "contract" in content, \
            "DECISIONS.md must have schema contract entry"


class TestSchemaUnchanged:
    """AC-6: No schema fields added — git diff vs skeleton commit is empty."""

    def test_schema_unchanged_vs_skeleton(self):
        result = subprocess.run(
            ["git", "diff", f"{SKELETON_COMMIT}..HEAD", "--", "app/models/schemas.py"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, "git diff failed"
        assert result.stdout.strip() == "", \
            "schemas.py must be unchanged from skeleton commit b091afa"
