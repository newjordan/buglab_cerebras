from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

import pytest

from app.server import Handler
from app.server import parse_content_length
from app.server import run_buglab_action
from app.server import split_processing_profile
from buglab.tui import TuiConfig
from buglab.tui import run_tui


@pytest.fixture
def http_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _get(server: ThreadingHTTPServer, path: str) -> tuple[int, bytes]:
    port = server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}") as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def _post(server: ThreadingHTTPServer, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    port = server.server_address[1]
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_content_length_rejects_bad_values() -> None:
    assert parse_content_length(None) == 0
    assert parse_content_length("12") == 12
    with pytest.raises(ValueError):
        parse_content_length("-1")
    with pytest.raises(ValueError):
        parse_content_length("nope")
    with pytest.raises(ValueError):
        parse_content_length("200001")


def test_server_pages_and_target_validation(http_server: ThreadingHTTPServer, tmp_path: Path) -> None:
    status, body = _get(http_server, "/")
    assert status == 200
    page = body.decode("utf-8")
    assert "Find Bugs" in page
    assert "Describe Issue" in page
    assert "Find + Fix" in page
    assert 'id="reportContext"' in page
    status, config_body = _get(http_server, "/api/config")
    assert status == 200
    config = json.loads(config_body.decode("utf-8"))
    assert config["defaultModel"]
    assert config["models"]
    status, missing = _get(http_server, "/api/buglab/runtime?target=/definitely/missing/buglab-target")
    assert status == 400
    assert b"does not exist" in missing
    status, payload = _post(http_server, "/api/buglab/target", {"target": {"localPath": str(tmp_path)}})
    assert status == 200
    assert payload["target"]["localPath"] == str(tmp_path.resolve())
    status, rejected = _post(http_server, "/api/buglab/target", {"target": {"localPath": str(tmp_path / "missing")}})
    assert status == 400
    assert rejected["ok"] is False


def test_guided_hunt_passes_html_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "checkout.html").write_text("<html><body>checkout</body></html>", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_bughunt(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {
            "summary": {"total_signals": 0, "elapsed_ms": 25, "case_count": 0},
            "audit": {
                "summary": {"total_signals": 0, "elapsed_ms": 25},
                "report_path": "",
                "json_path": "",
                "case_index_path": "",
                "findings_jsonl_path": "",
            },
            "workflow_path": "",
        }

    monkeypatch.setattr("buglab.api.bughunt_repo", fake_bughunt)
    result = run_buglab_action(
        "hunt_guided",
        {
            "target": {"localPath": str(tmp_path)},
            "issue": "The button on checkout.html never submits.",
            "files": [{"name": "note.md", "size": 4, "type": "text/markdown", "text": "see checkout.html"}],
        },
    )
    assert seen["targets"] == ["checkout.html"]
    assert result["guidedContext"]["htmlTargets"] == ["checkout.html"]
    assert "checkout.html" in result["presentation"]["agentSummary"]
    assert result["presentation"]["telemetry"]["throughputMeasured"] is True
    assert result["presentation"]["telemetry"]["avgTokensPerSecond"] >= 0


def test_throughput_is_not_invented_without_elapsed_time() -> None:
    profile = {
        "estimatedTokens": 400,
        "tokenProvenance": "estimated from counted local text bytes",
        "activeAgents": 1,
        "agentNames": ["planner"],
        "locProcessed": 10,
        "fileCount": 1,
        "bugHuntTokens": 400,
        "repairCrewTokens": 0,
        "avgTokensPerSecond": 0,
        "llmTokensTracked": 0,
    }
    split = split_processing_profile(profile, {}, mode="find")
    assert split["throughputMeasured"] is False
    assert split["avgTokensPerSecond"] == 0
    labels = []
    from app.server import build_presentation_report

    report = build_presentation_report({}, {}, mode="find", repo=None)
    labels = [item["label"] for item in report["metrics"]]
    assert "Avg Tok/sec" not in labels
    assert "not recorded for this run" in report["agentSummary"]


def test_tui_one_frame_labels_estimates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    code = run_tui(TuiConfig(repo=tmp_path, frames=1, delay=0, no_clear=True, no_overwatch_assets=True))
    captured = capsys.readouterr()
    assert code == 0
    assert "BUGLAB TUI" in captured.out
    assert "estimated tok/sec" in captured.out
    assert "lines in" in captured.out
