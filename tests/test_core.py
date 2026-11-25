from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from buglab.api import run_loops
from buglab.cli import hunt_main
from buglab.cli import main
from buglab.guidance import extract_existing_paths
from buglab.guidance import guidance_from_request
from buglab.project import discover_targets
from buglab.project import init_project_config
from buglab.project import load_project_config
from buglab.project import safe_slug
from buglab.quality import safe_slug as quality_slug
from buglab.repair import rewrite_command_paths
from buglab.runtime_env import temporary_process_tempdir
from buglab.truth import summarize_truth_entries
from buglab.truth import synthesize_report_truth_ledger


def test_safe_slug_collapses_punctuation() -> None:
    assert safe_slug("Hello--World") == "hello_world"
    assert safe_slug("***") == "target"
    assert quality_slug("A--B") == "a_b"


def test_discover_targets_does_not_invent_missing_index(tmp_path: Path) -> None:
    assert discover_targets(tmp_path) == []
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.html").write_text("<html></html>", encoding="utf-8")
    assert "docs/index.html" in discover_targets(tmp_path)


def test_empty_project_config_is_valid(tmp_path: Path) -> None:
    created = init_project_config(repo=tmp_path, targets=[])
    loaded = load_project_config(repo=tmp_path, config_path=created["config_path"])
    assert loaded["targets"] == []


def test_run_loops_zero_does_not_crash(tmp_path: Path) -> None:
    result = run_loops(target="index.html", repo=tmp_path, output=tmp_path / "out", loops=0, profiles=["balanced"])
    assert result["summary"]["runs"] == 0
    assert Path(result["csv_path"]).read_text(encoding="utf-8").startswith("loop,")


def test_hunt_main_empty_argv_does_not_read_process_args(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}

    def fake_main(argv: list[str] | None = None) -> int:
        seen["argv"] = list(argv or [])
        return 0

    monkeypatch.setattr("buglab.cli.main", fake_main)
    monkeypatch.setattr(sys, "argv", ["bughunt", "--repo", "SHOULD_NOT_APPEAR"])
    assert hunt_main([]) == 0
    assert seen["argv"] == ["bughunt"]


def test_temporary_tempdir_restores_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", "/original-tmpdir")
    monkeypatch.delenv("TMP", raising=False)
    with temporary_process_tempdir(tmp_path / "playwright"):
        assert os.environ["TMPDIR"] == str(tmp_path / "playwright")
        assert os.environ["TMP"] == str(tmp_path / "playwright")
    assert os.environ["TMPDIR"] == "/original-tmpdir"
    assert "TMP" not in os.environ


def test_guidance_uses_existing_files_only(tmp_path: Path) -> None:
    page = tmp_path / "checkout.html"
    page.write_text("<html></html>", encoding="utf-8")
    (tmp_path / "notes.md").write_text("hi", encoding="utf-8")
    outside = tmp_path.parent / "not-in-repo.html"
    guidance = guidance_from_request(
        tmp_path,
        f"Checkout dies in checkout.html and notes.md and {outside}",
        [{"name": "snippet.py", "size": 12, "type": "text/x-python", "text": "print('checkout.html')"}],
    )
    assert guidance["htmlTargets"] == ["checkout.html"]
    assert "notes.md" in guidance["focusPaths"]
    assert guidance["files"][0]["text"] == "print('checkout.html')"
    assert extract_existing_paths(tmp_path, "../not-in-repo.html") == []


def test_truth_summary_tolerates_missing_metrics() -> None:
    summary = summarize_truth_entries(
        [
            {"status": "confirmed", "outcome": "true_positive", "metrics": None},
            {"status": "suspected", "outcome": "unscored"},
        ]
    )
    assert summary["confirmed"] == 1
    assert summary["tokens"] == 0
    ledger = synthesize_report_truth_ledger({"run_id": "r", "metrics": None, "evidence": None, "findings": None})
    assert ledger["entries"] == []


def test_rewrite_command_paths_replaces_longer_paths_first() -> None:
    command = rewrite_command_paths("python a/b.py --out a/b", {"a/b": "X", "a/b.py": "Y"})
    assert command == "python Y --out X"


def test_cli_help_lists_hunt() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0


def test_matrix_without_targets_reports_zero_runs(tmp_path: Path) -> None:
    from buglab.project import run_project_matrix

    init_project_config(repo=tmp_path, targets=[])
    result = run_project_matrix(repo=tmp_path, output=tmp_path / "out", build_report_index=False)
    assert result["summary"]["runs"] == 0
    assert result["summary"]["note"] == "No browser targets were configured."
