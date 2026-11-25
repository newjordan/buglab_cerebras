from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".html",
    ".js",
    ".css",
    ".csv",
    ".env",
    ".example",
}
SKIP_DIRS = {".git", ".venv", ".buglab", "node_modules", "__pycache__", ".pytest_cache"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
]


def test_gitignore_keeps_env_files_untracked() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in text.splitlines()
    assert ".venv/" in text.splitlines()


def test_tracked_tree_has_no_credential_patterns() -> None:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".env", ".env.example", "Dockerfile"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)} matched {pattern.pattern}")
    assert hits == []


def test_config_fixture_env_is_synthetic() -> None:
    fixture = ROOT / "targets" / "sectors" / "config_iac" / "fixtures" / ".env"
    text = fixture.read_text(encoding="utf-8")
    assert "API_TOKEN=short" in text
    assert "sk-" not in text
