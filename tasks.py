"""Developer tasks run with ``uv run invoke <task>``.

``prepare`` is the gate every change must pass before it is staged: lint,
docstrings, imports, type checks, tests, the staged-diff size limit and a
final ``git status``.
"""

from pathlib import Path

from invoke.collection import Collection
from invoke.context import Context
from invoke.exceptions import Exit
from invoke.tasks import task

PYTHON_PATHS = ("app", "tests", "scripts", "tasks.py")
COMMIT_SIZE_LIMIT = 600
COMMIT_SIZE_EXCLUDED = frozenset({"uv.lock"})
PYTEST_NO_TESTS_COLLECTED = 5


def _existing_paths() -> str:
    """Returns the Python source paths that exist, space separated.

    Returns:
        The existing entries of ``PYTHON_PATHS`` joined by spaces.
    """
    return " ".join(path for path in PYTHON_PATHS if Path(path).exists())


def _staged_line_count(numstat: str) -> int:
    """Sums added and deleted lines from ``git diff --numstat`` output.

    Binary files (reported as ``-``) and files in ``COMMIT_SIZE_EXCLUDED``
    are not counted.

    Args:
        numstat: Output of ``git diff --cached --numstat``.

    Returns:
        The number of changed lines that count towards the limit.
    """
    total = 0
    for row in numstat.splitlines():
        added, deleted, path = row.split("\t", maxsplit=2)
        if added == "-" or Path(path).name in COMMIT_SIZE_EXCLUDED:
            continue
        total += int(added) + int(deleted)
    return total


@task
def lint(c: Context) -> None:
    """Runs ruff lint and format checks.

    Args:
        c: Invoke context.
    """
    c.run("ruff check .", pty=True)
    c.run("ruff format --check .", pty=True)


@task
def fmt(c: Context) -> None:
    """Applies ruff autofixes and formatting.

    Args:
        c: Invoke context.
    """
    c.run("ruff check --fix .", pty=True)
    c.run("ruff format .", pty=True)


@task
def docstrings(c: Context) -> None:
    """Checks Google docstrings with ruff and pydoclint.

    Args:
        c: Invoke context.
    """
    c.run("ruff check --select D .", pty=True)
    source = " ".join(
        path for path in _existing_paths().split() if path != "tests"
    )
    c.run(f"pydoclint {source}", pty=True)


@task
def imports(c: Context) -> None:
    """Checks import style and the architecture contracts.

    Args:
        c: Invoke context.
    """
    c.run("ruff check --select I,TID .", pty=True)
    c.run("lint-imports", pty=True)


@task
def typecheck(c: Context) -> None:
    """Runs mypy in strict mode.

    Args:
        c: Invoke context.
    """
    c.run(f"mypy {_existing_paths()}", pty=True)


@task
def test(c: Context) -> None:
    """Runs every test that does not need docker compose services.

    Args:
        c: Invoke context.

    Raises:
        Exit: If pytest fails.
    """
    result = c.run('pytest -m "not docker"', pty=True, warn=True)
    if result is None or result.exited not in (0, PYTEST_NO_TESTS_COLLECTED):
        raise Exit("pytest failed.", code=1)


@task
def test_docker(c: Context) -> None:
    """Runs the tests that need docker compose services.

    Args:
        c: Invoke context.
    """
    c.run('pytest -m "docker"', pty=True)


@task
def commit_size(c: Context, limit: int = COMMIT_SIZE_LIMIT) -> None:
    """Fails when the staged change exceeds the line limit.

    Args:
        c: Invoke context.
        limit: Maximum number of changed lines allowed.

    Raises:
        Exit: If the staged diff is larger than ``limit``.
    """
    result = c.run("git diff --cached --numstat", hide=True)
    count = _staged_line_count(result.stdout if result else "")
    if count > limit:
        raise Exit(f"Staged change is {count} lines; limit is {limit}.")
    print(f"Staged change: {count}/{limit} lines.")


@task
def git_status(c: Context) -> None:
    """Shows the working tree status.

    Args:
        c: Invoke context.
    """
    c.run("git status", pty=True)


@task(pre=[lint, docstrings, imports, typecheck, test, commit_size, git_status])
def prepare(c: Context) -> None:
    """Runs every check required before a change is staged.

    Args:
        c: Invoke context.
    """
    print("All checks passed.")


namespace = Collection(
    lint,
    fmt,
    docstrings,
    imports,
    typecheck,
    test,
    test_docker,
    commit_size,
    git_status,
    prepare,
)
