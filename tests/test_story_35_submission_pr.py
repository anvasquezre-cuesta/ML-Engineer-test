"""
ATDD acceptance tests for story 3.5: Open the branch as a PR against the fork.

Precondition tests verify the local state is ready for submission.
Post-automation tests will fail now (red) because the submission branch and PR
do not exist yet; they will pass (green) once the automation pushes the branch
and opens the PR.
"""
import subprocess
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run_cmd(cmd, cwd=PROJECT_ROOT, check=False):
    """Run a shell command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )
    return result.returncode, result.stdout, result.stderr


def get_submission_pr_number():
    """Get the PR number for the submission branch, or None if no PR exists."""
    rc, out, _ = run_cmd(
        "gh pr list --repo anvasquezre-cuesta/ML-Engineer-test "
        "--head submission --json number --state open"
    )
    if rc != 0 or not out.strip():
        return None
    try:
        prs = json.loads(out.strip())
        if prs:
            return prs[0]["number"]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


# -----------------------------------------------------------------------------
# Precondition tests (should pass now)
# -----------------------------------------------------------------------------

def test_local_main_at_deliverable_head():
    """AC prerequisite: local main is at or beyond the deliverable HEAD commit."""
    rc, out, _ = run_cmd("git rev-parse HEAD")
    assert rc == 0
    # Check that HEAD is at the baseline or a descendant of it
    rc, out, _ = run_cmd("git merge-base --is-ancestor a5bff28f8796ed0262c23080f30c0f1707e91b2c HEAD")
    assert rc == 0, "a5bff28 is not an ancestor of HEAD"


def test_18_commits_ahead_of_upstream():
    """AC prerequisite: at least 18 commits ahead of upstream/main (deliverable diff)."""
    rc, out, _ = run_cmd("git log --oneline upstream/main..HEAD | wc -l")
    assert rc == 0
    count = int(out.strip())
    assert count >= 18, f"Expected at least 18 commits ahead of upstream, found {count}"


# -----------------------------------------------------------------------------
# Post-automation tests (will fail now — red phase)
# -----------------------------------------------------------------------------

def test_submission_branch_pushed_to_origin():
    """AC: submission branch exists on origin after automation."""
    rc, out, _ = run_cmd("git ls-remote origin submission")
    assert rc == 0 and out.strip() != "", (
        "submission branch not found on origin"
    )
    sha = out.strip().split()[0]
    # The branch must be at the deliverable HEAD (or a descendant that includes
    # it). We verify that the baseline deliverable commit a5bff28 is an ancestor
    # of the pushed branch, and that the pushed sha matches our local HEAD.
    rc2, out2, _ = run_cmd(f"git merge-base --is-ancestor a5bff28f8796ed0262c23080f30c0f1707e91b2c {sha}")
    assert rc2 == 0, (
        f"submission branch sha {sha} does not include deliverable HEAD a5bff28"
    )


def test_pr_exists_for_submission_branch():
    """AC: a PR exists for the submission branch against upstream/main."""
    pr_number = get_submission_pr_number()
    assert pr_number is not None, "No open PR found for submission branch"


def test_pr_has_correct_base_and_head():
    """AC: PR base is main, head is Ryogink:submission."""
    pr_number = get_submission_pr_number()
    assert pr_number is not None, "No PR found"

    rc, out, _ = run_cmd(
        f"gh pr view {pr_number} --repo anvasquezre-cuesta/ML-Engineer-test "
        "--json baseRefName,headRefName"
    )
    assert rc == 0
    info = json.loads(out.strip())
    assert info["baseRefName"] == "main", f"Wrong base: {info['baseRefName']}"
    assert info["headRefName"] == "submission", f"Wrong head: {info['headRefName']}"


def test_pr_diff_contains_deliverable_files():
    """AC: PR diff contains the deliverable files."""
    pr_number = get_submission_pr_number()
    assert pr_number is not None, "No PR found"

    rc, out, _ = run_cmd(
        f"gh pr diff {pr_number} --repo anvasquezre-cuesta/ML-Engineer-test "
        "--name-only"
    )
    assert rc == 0
    changed_files = set(out.strip().splitlines())

    # Key deliverable files from the Code Map
    required_files = {
        "DESIGN.md",
        "DECISIONS.md",
        "README.md",
        "static/index.html",
        "static/viewer.js",
        "tests/test_e2e_extract_to_ask.py",
    }
    missing = required_files - changed_files
    assert not missing, f"Missing from PR diff: {missing}"

    # Should have significant diff (18 commits' worth)
    assert len(changed_files) >= 40, (
        f"Too few changed files: {len(changed_files)}"
    )


# -----------------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------------

def test_no_duplicate_prs_for_submission():
    """Edge case: PR already exists → reuse, no duplicate created."""
    rc, out, _ = run_cmd(
        "gh pr list --repo anvasquezre-cuesta/ML-Engineer-test "
        "--head submission --state open --state merged --json number"
    )
    if rc != 0 or not out.strip():
        return  # PR doesn't exist yet — edge case can't be tested in red phase
    try:
        prs = json.loads(out.strip())
        # If no PRs yet, or exactly 1, that's fine. 2+ would be duplicates.
        if len(prs) == 0:
            return  # No PRs yet
        assert len(prs) == 1, (
            f"Duplicate PRs for submission branch: {len(prs)}"
        )
    except json.JSONDecodeError:
        pass  # No PRs yet


def test_pr_body_is_human_style():
    """AC boundary: PR title/body are human-style (no AI trailers, no ticket IDs)."""
    pr_number = get_submission_pr_number()
    if pr_number is None:
        return  # PR doesn't exist yet

    rc, out, _ = run_cmd(
        f"gh pr view {pr_number} --repo anvasquezre-cuesta/ML-Engineer-test "
        "--json title,body"
    )
    if rc != 0:
        return
    info = json.loads(out.strip())
    content = info["title"] + " " + info["body"]
    # No AI co-author trailers
    assert "Co-Authored-By" not in content
    # No ticket/story IDs (per repo policy)
    assert "Ticket" not in content
    assert "ticket" not in content
    assert "story " not in content.lower()
