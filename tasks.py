"""Developer tasks run with ``uv run invoke <task>``.

``prepare`` is the gate every change must pass before it is staged: lint,
docstrings, imports, type checks, tests, the staged-diff size limit and a
final ``git status``.
"""

import pathlib

from invoke import collection
from invoke import context
from invoke import exceptions
from invoke import tasks

PYTHON_PATHS = ("app", "evaluation", "tests", "scripts", "tasks.py")
COMMIT_SIZE_LIMIT = 600
PYTEST_NO_TESTS_COLLECTED = 5


def _existing_paths() -> str:
    """Returns the Python source paths that exist, space separated.

    Returns:
        The existing entries of ``PYTHON_PATHS`` joined by spaces.
    """
    return " ".join(
        path for path in PYTHON_PATHS if pathlib.Path(path).exists()
    )


def _staged_line_count(numstat: str) -> int:
    """Sums added and deleted lines of Python files in ``git diff --numstat``.

    Data, config, lock and binary files are not counted.

    Args:
        numstat: Output of ``git diff --cached --numstat``.

    Returns:
        The number of changed lines that count towards the limit.
    """
    total = 0
    for row in numstat.splitlines():
        added, deleted, path = row.split("\t", maxsplit=2)
        if pathlib.Path(path).suffix != ".py":
            continue
        total += int(added) + int(deleted)
    return total


@tasks.task
def lint(c: context.Context) -> None:
    """Runs ruff lint and format checks.

    Args:
        c: Invoke context.
    """
    c.run("ruff check .", pty=True)
    c.run("ruff format --check .", pty=True)


@tasks.task
def fmt(c: context.Context) -> None:
    """Applies ruff autofixes and formatting.

    Args:
        c: Invoke context.
    """
    c.run("ruff check --fix .", pty=True)
    c.run("ruff format .", pty=True)


@tasks.task
def docstrings(c: context.Context) -> None:
    """Checks Google docstrings with ruff and pydoclint.

    Args:
        c: Invoke context.
    """
    c.run("ruff check --select D .", pty=True)
    source = " ".join(
        path for path in _existing_paths().split() if path != "tests"
    )
    c.run(f"pydoclint {source}", pty=True)


@tasks.task
def imports(c: context.Context) -> None:
    """Checks import style, module-only imports and the layer contracts.

    Args:
        c: Invoke context.
    """
    c.run("ruff check --select I,TID .", pty=True)
    c.run(
        f"python -m scripts.check_module_imports {_existing_paths()}", pty=True
    )
    c.run("lint-imports", pty=True)


@tasks.task
def typecheck(c: context.Context) -> None:
    """Runs mypy in strict mode.

    Args:
        c: Invoke context.
    """
    c.run(f"mypy {_existing_paths()}", pty=True)


@tasks.task
def test(c: context.Context) -> None:
    """Runs every test that does not need docker compose services.

    Args:
        c: Invoke context.

    Raises:
        exceptions.Exit: If pytest fails.
    """
    result = c.run('pytest -m "not docker"', pty=True, warn=True)
    if result is None or result.exited not in (0, PYTEST_NO_TESTS_COLLECTED):
        raise exceptions.Exit("pytest failed.", code=1)


@tasks.task
def test_docker(c: context.Context) -> None:
    """Runs the tests that need docker compose services.

    Args:
        c: Invoke context.
    """
    c.run('pytest -m "docker"', pty=True)


@tasks.task
def test_frontend(c: context.Context) -> None:
    """Runs the audit viewer's unit tests; needs Node.js 22 or later.

    Args:
        c: Invoke context.
    """
    c.run("node --test frontend/", pty=True)


@tasks.task
def smoke(c: context.Context, url: str = "http://localhost:8080") -> None:
    """Runs the smoke test against a running deployment.

    Args:
        c: Invoke context.
        url: Base URL of the deployment.
    """
    c.run(f"python -m scripts.smoke --base-url {url}", pty=True)


# DeepEval reads its own switches only from the environment; the eval
# subprocess gets them as fixed values and nothing reads the environment.
DEEPEVAL_OPT_OUTS = {
    "DEEPEVAL_DISABLE_DOTENV": "1",
    "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
}


@tasks.task(name="eval")
def evaluate(c: context.Context) -> None:
    """Answers the sample questions with the live model and gates the report.

    Grading uses the configured Bedrock judge within its call budget; the
    Markdown report goes to ``DOCINTEL_EVAL__REPORT_DIR``.

    Args:
        c: Invoke context.
    """
    c.run(
        "uv run --extra eval python -m evaluation",
        env=DEEPEVAL_OPT_OUTS,
        pty=True,
    )


@tasks.task(name="eval-compare")
def eval_compare(c: context.Context, baseline: str, candidate: str) -> None:
    """Decides whether a candidate prompt may replace the shipped one.

    Args:
        c: Invoke context.
        baseline: Outcomes file written by ``invoke eval`` on the shipped
            prompts.
        candidate: Outcomes file of the candidate prompts.
    """
    c.run(
        f"uv run --extra eval python -m evaluation compare {baseline} "
        f"{candidate}",
        env=DEEPEVAL_OPT_OUTS,
        pty=True,
    )


@tasks.task
def commit_size(c: context.Context, limit: int = COMMIT_SIZE_LIMIT) -> None:
    """Fails when the staged Python change exceeds the line limit.

    Args:
        c: Invoke context.
        limit: Maximum number of changed Python lines allowed.

    Raises:
        exceptions.Exit: If the staged diff is larger than ``limit``.
    """
    result = c.run("git diff --cached --numstat", hide=True)
    count = _staged_line_count(result.stdout if result else "")
    if count > limit:
        raise exceptions.Exit(
            f"Staged change is {count} lines; limit is {limit}."
        )
    print(f"Staged change: {count}/{limit} lines.")


@tasks.task
def git_status(c: context.Context) -> None:
    """Shows the working tree status.

    Args:
        c: Invoke context.
    """
    c.run("git status", pty=True)


@tasks.task(pre=[lint, docstrings, imports, typecheck, test])
def prepare(c: context.Context, commit_limit: int = COMMIT_SIZE_LIMIT) -> None:
    """Runs every check required before a change is staged.

    Args:
        c: Invoke context.
        commit_limit: Staged Python lines allowed; raise it only for an
            agreed mechanical refactor.
    """
    commit_size(c, limit=commit_limit)
    git_status(c)
    print("All checks passed.")


namespace = collection.Collection(
    lint,
    fmt,
    docstrings,
    imports,
    typecheck,
    test,
    test_docker,
    test_frontend,
    smoke,
    evaluate,
    eval_compare,
    commit_size,
    git_status,
    prepare,
)
