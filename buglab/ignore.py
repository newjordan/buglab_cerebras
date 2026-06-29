from __future__ import annotations

from pathlib import Path


GENERATED_DIR_PARTS = {
    ".buglab",
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    "build",
    "coverage",
    "coverage-hooks",
    "dist",
    "env",
    "htmlcov",
    "lcov-report",
    "node_modules",
    "playwright-report",
    "site-packages",
    "storybook-static",
    "test-results",
    "tmp",
    "vendor",
    "venv",
    "__pycache__",
}

INTERNAL_PLANNING_DIR_PARTS = {
    ".agents",
    ".codex",
    ".cursor",
    ".idea",
    ".vscode",
    "agent_notes",
    "brainstorm",
    "codex_notes",
    "hackathon_notes",
    "internal_notes",
    "planning",
    "private_notes",
    "project_notes",
    "research_notes",
    "scratch",
    "scratchpad",
    "submission_notes",
}

INTERNAL_PLANNING_FILE_STEMS = {
    "agent_notes",
    "brainstorm",
    "codex_notes",
    "hackathon_notes",
    "internal_notes",
    "notes",
    "plan",
    "planning",
    "private_notes",
    "project_notes",
    "project_plan",
    "roadmap",
    "scratchpad",
    "strategy",
    "submission_notes",
    "todo",
    "todos",
}

INTERNAL_PLANNING_FILE_TOKENS = {
    "agent_notes",
    "brainstorm",
    "codex_notes",
    "hackathon_notes",
    "internal_notes",
    "planning",
    "private_notes",
    "project_notes",
    "scratchpad",
    "submission_notes",
}


def should_skip_common_path(rel: str | Path, *, skip_sector_fixtures: bool = False) -> bool:
    normalized = str(rel).replace("\\", "/")
    lower = normalized.lower()
    if lower.startswith("codexlab/runs/"):
        return True
    if skip_sector_fixtures and lower.startswith("targets/sectors/"):
        return True

    parts = {part.lower() for part in normalized.split("/") if part}
    if parts & GENERATED_DIR_PARTS:
        return True
    if parts & INTERNAL_PLANNING_DIR_PARTS:
        return True

    name = Path(normalized).name.lower()
    stem = Path(name).stem.replace("-", "_").replace(" ", "_")
    return stem in INTERNAL_PLANNING_FILE_STEMS or any(token in stem for token in INTERNAL_PLANNING_FILE_TOKENS)
