"""Look for API keys where they must not be (Testing T5-09). Prints where a key was found and which one, never the key itself.

    python scripts/secrets_check.py            # the project folder and logs/
    python scripts/secrets_check.py some/dir   # another folder

Checks: (1) the value of every key in .env appears nowhere else (code, documents, logs, test output); (2) nothing that looks
like a Groq, Google, Deepgram, Sarvam or LiveKit key or a private key appears anywhere; (3) .gitignore keeps .env out of git.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", ".venv-voice", ".venv-browser", ".venv-gpu", "node_modules", "__pycache__", "tts_cache", "piper", "filer_profile",
             "evidence", "portal_uploads", ".runtime", ".setup-tools"}
SKIP_FILES = {".env"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".jsonl", ".js", ".html", ".css", ".cmd", ".bat", ".ps1", ".toml", ".cfg", ".ini", ".log", ".yaml",
                 ".yml", ".example", ".csv", ""}
PATTERNS = {
    "Groq key": re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    "Google key": re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    "LiveKit key": re.compile(r"\bAPI[A-Za-z0-9]{10,}\b"),
    "Sarvam key": re.compile(r"\bsk_[A-Za-z0-9_]{20,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
ALLOWED = {"APItestkey"}  # the fake key the tests use
# Names in code and error messages that have a key's shape, such as APIConnectionError in a log: capitalised words only, no digits.
WORDS = re.compile(r"^[A-Z]+(?:[A-Z][a-z]+)+$")


def env_values(path: pathlib.Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                if ("KEY" in key or "SECRET" in key or "TOKEN" in key) and len(value) >= 8:
                    values[key.strip()] = value
    return values


def files(base: pathlib.Path):
    # Prune vendor environments and binary browser profiles before descending.
    # Application source, documents and logs are still scanned.
    for directory, dirs, names in os.walk(base):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in names:
            path = pathlib.Path(directory) / name
            if name in SKIP_FILES or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if not path.is_file() or path.stat().st_size > 20_000_000:
                    continue
            except OSError:
                continue
            yield path


def main() -> int:
    base = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
    secrets = env_values(ROOT / ".env")
    found: list[str] = []
    scanned = 0
    for path in files(base):
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            for key, value in secrets.items():
                if value in line:
                    found.append(f"{path.relative_to(base)}:{n}: the value of {key} from .env")
            for name, pattern in PATTERNS.items():
                if any(m.group(0) not in ALLOWED and not WORDS.match(m.group(0)) for m in pattern.finditer(line)) and not path.name.endswith(".example"):
                    found.append(f"{path.relative_to(base)}:{n}: something shaped like a {name}")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    ignored = any(line.strip() in (".env", "/.env", ".env*") for line in ignore.splitlines())
    print(f"Scanned {scanned} files under {base} for {len(secrets)} key values from .env and {len(PATTERNS)} key shapes.")
    for f in found[:50]:
        print(f"  FOUND  {f}")
    print(f"{'PASS' if not found else 'FAIL'}  no key outside .env")
    print(f"{'PASS' if ignored else 'FAIL'}  .gitignore keeps .env out of git")
    return 0 if not found and ignored else 1


if __name__ == "__main__":
    sys.exit(main())
