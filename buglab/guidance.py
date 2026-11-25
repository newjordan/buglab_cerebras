from __future__ import annotations

import re
from pathlib import Path
from typing import Any


HTML_SUFFIXES = {".html", ".htm"}
TOKEN_STRIP = ".,:;`'\"()[]{}<>"
PATH_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+")
MAX_FILES = 8
MAX_EXCERPT = 4_000


def guidance_from_request(repo: Path, issue: str, files: object) -> dict[str, Any]:
    cleaned_files = normalize_files(files)
    texts = [issue]
    for item in cleaned_files:
        texts.append(str(item.get("name") or ""))
        texts.append(str(item.get("text") or ""))
    focus_paths = extract_existing_paths(repo, "\n".join(texts))
    html_targets = [path for path in focus_paths if Path(path).suffix.lower() in HTML_SUFFIXES]
    return {
        "issue": issue.strip(),
        "files": cleaned_files,
        "focusPaths": focus_paths,
        "htmlTargets": html_targets,
    }


def normalize_files(files: object) -> list[dict[str, Any]]:
    if not isinstance(files, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in files[:MAX_FILES]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        normalized.append(
            {
                "name": str(item.get("name") or ""),
                "size": item.get("size", 0),
                "type": str(item.get("type") or ""),
                "text": text[:MAX_EXCERPT],
            }
        )
    return normalized


def extract_existing_paths(repo: Path, text: str) -> list[str]:
    root = repo.resolve()
    normalized = text.replace("\\", "/")
    candidates: list[str] = []
    candidates.extend(PATH_RE.findall(normalized))
    for token in re.split(r"\s+", normalized):
        cleaned = token.strip(TOKEN_STRIP)
        if cleaned:
            candidates.append(cleaned)
    found: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate.startswith(("/", "http://", "https://")):
            continue
        path = (root / candidate).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        rel_text = relative.as_posix()
        if rel_text in seen:
            continue
        seen.add(rel_text)
        found.append(rel_text)
    return found


def guidance_note(guidance: dict[str, Any]) -> str:
    lines: list[str] = []
    issue = str(guidance.get("issue") or "").strip()
    if issue:
        lines.extend(["Operator context", f"- {issue}"])
    html_targets = [str(path) for path in guidance.get("htmlTargets") or []]
    focus_paths = [str(path) for path in guidance.get("focusPaths") or []]
    if html_targets:
        lines.append("- Browser focus: " + ", ".join(html_targets))
    other_paths = [path for path in focus_paths if path not in set(html_targets)]
    if other_paths:
        lines.append("- Other paths mentioned: " + ", ".join(other_paths))
    files = guidance.get("files") or []
    names = [str(item.get("name")) for item in files if isinstance(item, dict) and item.get("name")]
    if names:
        lines.append("- Attached file names: " + ", ".join(names))
    for item in files:
        if not isinstance(item, dict):
            continue
        excerpt = " ".join(str(item.get("text") or "").split())
        if not excerpt:
            continue
        lines.append(f"- Excerpt from {item.get('name') or 'attachment'}: {excerpt[:240]}")
    return "\n".join(lines)
