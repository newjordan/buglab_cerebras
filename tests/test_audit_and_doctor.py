from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from buglab.audit import run_tests_audit
from buglab.audit import unittest_discover_command
from buglab.cli import main
from buglab.doctor import _count
from buglab.doctor import check_playwright_browser


def test_unittest_commands_are_not_passed_through_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        "import unittest\n\nclass Sample(unittest.TestCase):\n    def test_ok(self):\n        assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "test_glob_bait.py").write_text("print('bait')\n", encoding="utf-8")
    calls: list[tuple[object, dict[str, object]]] = []

    class Proc:
        returncode = 0
        stdout = "Ran 1 test\nOK\n"
        stderr = ""

    def fake_run(command: object, **kwargs: object) -> Proc:
        calls.append((command, kwargs))
        return Proc()

    monkeypatch.setattr("buglab.audit.subprocess.run", fake_run)
    rows = run_tests_audit(tmp_path)
    assert calls
    discover_command, discover_kwargs = calls[0]
    assert discover_command == unittest_discover_command("tests")
    assert "test*.py" in discover_command
    assert discover_kwargs.get("shell") in (None, False)
    assert all(isinstance(command, list) and kwargs.get("shell") in (None, False) for command, kwargs in calls)
    assert any(row["status"] == "passed" for row in rows)


def test_repo_audit_reports_real_doc_and_config_signals(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Hello\n\nSee [missing](missing.md).\n", encoding="utf-8")
    (tmp_path / "config.json").write_text("{", encoding="utf-8")
    code = main(
        [
            "hunt",
            "--repo",
            str(tmp_path),
            "--no-browser",
            "--no-tests",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    payload = json.loads(Path(next(Path(tmp_path / "out").rglob("repo_audit.json"))).read_text(encoding="utf-8"))
    signals = " ".join(row["signals"] for row in payload["rows"])
    assert "missing_local_link" in signals
    assert "invalid_json" in signals
    assert payload["summary"]["total_signals"] >= 2


def test_doctor_restores_temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("TMPDIR", "/original-tmpdir")

    class Browser:
        version = "TestBrowser"

        def close(self) -> None:
            return None

    class Chromium:
        def launch(self, headless: bool = True) -> Browser:
            assert os.environ["TMPDIR"] != "/original-tmpdir"
            return Browser()

    class Playwright:
        chromium = Chromium()

    class Sync:
        def __enter__(self) -> Playwright:
            return Playwright()

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: Sync())
    result = check_playwright_browser(tmp_path)
    assert result["status"] == "passed"
    assert os.environ["TMPDIR"] == "/original-tmpdir"
    code = main(["doctor", "--repo", str(tmp_path), "--skip-browser", "--no-report"])
    captured = capsys.readouterr()
    assert _count(1, "warning") == "1 warning"
    assert _count(2, "warning") == "2 warnings"
    assert code == 0
    assert "BugLab doctor:" in captured.out
    assert "warning" in captured.out


def test_cli_hunt_summary_goes_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "README.md").write_text("# Ready\n", encoding="utf-8")
    code = main(["hunt", "--repo", str(tmp_path), "--no-browser", "--no-tests", "--no-config", "--output", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err.startswith("BugLab hunt:")
    payload = json.loads(captured.out)
    assert payload["summary"]["total_signals"] == 0
