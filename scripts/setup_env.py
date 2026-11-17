"""Create a private Compose .env without reading or replacing an existing one."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
import warnings


GEMINI_MODEL = "gemini-3.5-flash-lite"
SAFE_KEY = re.compile(r"[A-Za-z0-9._~-]{1,512}\Z")


class TerminalRequiredError(RuntimeError):
    """Secrets must not be entered through a potentially echoed input stream."""


def read_private_key() -> str:
    if not sys.stdin.isatty():
        raise TerminalRequiredError("An interactive terminal is required for private key input")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass("Gemini API key (input hidden): ")
    except getpass.GetPassWarning:
        raise TerminalRequiredError("Hidden key input is unavailable") from None


def create_environment(template: Path, target: Path, *, gemini: bool, key: str = "") -> bool:
    """Create target exclusively; return False if it already exists, without opening it."""
    if target.exists() or target.is_symlink():
        return False
    if gemini and not SAFE_KEY.fullmatch(key):
        raise ValueError("Invalid Gemini API key format")
    text = template.read_text(encoding="utf-8")
    changes = {
        "LLM_PROVIDER=disabled\n": "LLM_PROVIDER=gemini\n",
        "LLM_MODEL=\n": f"LLM_MODEL={GEMINI_MODEL}\n",
        "LLM_API_KEY=\n": f"LLM_API_KEY={key}\n",
        "LLM_ALLOW_EXTERNAL=false\n": "LLM_ALLOW_EXTERNAL=true\n",
    }
    if gemini:
        for original, replacement in changes.items():
            if text.count(original) != 1:
                raise ValueError("The example configuration has changed; inspect it manually")
            text = text.replace(original, replacement, 1)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".env.setup-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
        try:
            # Linking is atomic and never replaces an existing path, including a
            # symlink created concurrently after the initial existence check.
            os.link(temporary, target)
        except FileExistsError:
            return False
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--gemini"]):
        print("Usage: python3 scripts/setup_env.py [--gemini]", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    if target.exists() or target.is_symlink():
        print(".env already exists; it was not opened or changed. Edit it manually if needed.")
        return 0
    try:
        mode = "g" if args == ["--gemini"] else (
            input("Create configuration: [d] disabled (default), [g] Gemini: ").strip().lower() or "d"
        )
        if mode not in {"d", "g"}:
            print("Choose d or g; no file was created.", file=sys.stderr)
            return 2
        key = ""
        if mode == "g":
            print("Gemini receives questions and retrieved excerpts; quota or charges may apply.")
            if input("Allow external requests when you call /api/ask? Type yes: ").strip().lower() != "yes":
                print("External access not approved; no file was created.", file=sys.stderr)
                return 2
            key = read_private_key()
        created = create_environment(root / ".env.example", target, gemini=mode == "g", key=key)
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; no configuration was intentionally changed.", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        # Never print an exception that could contain a key or file contents.
        print(f"Could not create .env ({type(error).__name__}); check the key and filesystem.", file=sys.stderr)
        return 1
    except TerminalRequiredError:
        print("A terminal is required for hidden key entry; no file was created.", file=sys.stderr)
        return 2
    if not created:
        print(".env already exists; it was not opened or changed.")
        return 0
    print("Created .env with private file permissions. Keep it out of source control.")
    if mode == "g":
        print(f"Gemini configured with {GEMINI_MODEL}; verify availability and quota in Google AI Studio.")
    else:
        print("Answer generation is disabled; configure a provider before calling /api/ask.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
