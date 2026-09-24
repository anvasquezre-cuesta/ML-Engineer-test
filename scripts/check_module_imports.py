"""Fails when a ``from x import y`` imports anything but a module.

Google style imports packages and modules only; ``typing`` and
``collections.abc`` are the allowed exceptions. ruff has no rule for this,
so the check imports each target to see whether it is a module.
"""

import ast
import importlib
import pathlib
import sys

EXEMPT_MODULES = frozenset({"typing", "collections.abc", "__future__"})


def is_module(dotted: str) -> bool:
    """Returns whether ``dotted`` names an importable module.

    Args:
        dotted: A dotted module path.

    Returns:
        ``True`` if importing it succeeds.
    """
    try:
        importlib.import_module(dotted)
    except ImportError:
        return False
    return True


def violations(path: pathlib.Path) -> list[str]:
    """Lists the non-module ``from`` imports in one file.

    Args:
        path: A Python source file.

    Returns:
        One ``file:line: statement`` entry per offending name.
    """
    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        module = node.module or ""
        if module in EXEMPT_MODULES:
            continue
        for alias in node.names:
            if not is_module(f"{module}.{alias.name}"):
                found.append(
                    f"{path}:{node.lineno}: from {module} import {alias.name}"
                )
    return found


def main() -> None:
    """Checks every file given on the command line.

    Raises:
        SystemExit: If any file imports a non-module name.
    """
    found = [
        entry
        for arg in sys.argv[1:]
        for path in sorted(pathlib.Path(arg).rglob("*.py"))
        + ([pathlib.Path(arg)] if arg.endswith(".py") else [])
        for entry in violations(path)
    ]
    if found:
        print("Import modules, not names (Google style):")
        print("\n".join(found))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
