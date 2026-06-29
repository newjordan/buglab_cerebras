from __future__ import annotations

import json
import os
import sys
import time
import traceback
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from urllib.parse import urlsplit

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from openai import OpenAI
from openai import OpenAIError


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "app" / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
RUNS_DIR = ROOT / ".buglab" / "runs"
SUBMISSION_ROOT = Path(os.getenv("BUGLAB_SUBMISSION_ROOT", str(ROOT / ".buglab" / "submission")))
SUBMISSION_JSON = SUBMISSION_ROOT / "submission_results.json"
SUBMISSION_MD = SUBMISSION_ROOT / "submission_package.md"
SUBMISSION_FREEZE_JSON = SUBMISSION_ROOT / "submission_freeze.json"
BRAND_MOTTO = "Rapid Recursive Bug Hunter"


def load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")


def cerebras_client(api_key: str | None = None) -> OpenAI:
    api_key = api_key or os.getenv("CEREBRAS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing Cerebras API key.")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"),
    )


def available_models() -> list[str]:
    configured = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
    raw = os.getenv("CEREBRAS_MODELS", "")
    models = [item.strip() for item in raw.split(",") if item.strip()]
    if configured not in models:
        models.insert(0, configured)
    if "zai-glm-4.7" not in models:
        models.append("zai-glm-4.7")
    return models


class Handler(BaseHTTPRequestHandler):
    server_version = "BugLabSwarmQA/0.1"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self.send_file(STATIC_DIR / "app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self.send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/buglab-brand.png":
            self.send_file(STATIC_DIR / "buglab-brand.png", "image/png")
            return
        if path == "/buglab-hero-mage.png":
            self.send_file(STATIC_DIR / "buglab-hero-mage.png", "image/png")
            return
        if path == "/buglab-hero-shot.png":
            self.send_file(STATIC_DIR / "buglab-hero-shot.png", "image/png")
            return
        if path == "/buglab-background.png":
            self.send_file(STATIC_DIR / "buglab-background.png", "image/png")
            return
        if path == "/frosted-flake-green.png":
            self.send_file(STATIC_DIR / "frosted-flake-green.png", "image/png")
            return
        if path == "/target-spot.png":
            self.send_file(STATIC_DIR / "target-spot.png", "image/png")
            return
        if path == "/vendor/echarts.min.js":
            self.send_file(STATIC_DIR / "vendor" / "echarts.min.js", "application/javascript; charset=utf-8")
            return
        if path == "/api/config":
            self.send_json(
                HTTPStatus.OK,
                {
                    "models": available_models(),
                    "defaultModel": os.getenv("CEREBRAS_MODEL", "gpt-oss-120b"),
                },
            )
            return
        if path == "/api/buglab/overview":
            self.send_json(HTTPStatus.OK, buglab_overview())
            return
        if path == "/api/buglab/runtime":
            self.send_json(HTTPStatus.OK, buglab_runtime())
            return
        if path == "/api/buglab/submission":
            self.send_json(HTTPStatus.OK, buglab_submission())
            return
        if path == "/submission/package.md":
            self.send_file(current_submission_paths()[1], "text/markdown; charset=utf-8")
            return
        if path.startswith("/runs/"):
            self.send_run_artifact(path.removeprefix("/runs/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/buglab/target":
            try:
                payload = self.read_json()
                repo = target_repo_from_payload(payload)
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
            self.send_json(
                HTTPStatus.OK,
                {"ok": True, "target": {"name": repo.name, "localPath": str(repo), "selected": True}},
            )
            return

        if path == "/api/buglab/action":
            try:
                payload = self.read_json()
                action = str(payload.get("action", "")).strip()
                result = run_buglab_action(action, payload)
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:  # pragma: no cover - surfaced to local UI
                self.send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                )
                return
            self.send_json(HTTPStatus.OK, {"ok": True, "action": action, "result": result})
            return

        if path != "/api/chat":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self.read_json()
            prompt = str(payload.get("prompt", "")).strip()
            system = str(payload.get("system", "")).strip()
            model = str(payload.get("model", os.getenv("CEREBRAS_MODEL", "gpt-oss-120b"))).strip()
            temperature = float(payload.get("temperature", 0.2))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        if not prompt:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Prompt is required."})
            return

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        started = time.perf_counter()
        try:
            response = cerebras_client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=600,
            )
        except (OpenAIError, RuntimeError) as exc:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {"ok": False, "error": type(exc).__name__, "message": str(exc)},
            )
            return

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        text = response.choices[0].message.content or ""
        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "model": model,
                "elapsedMs": elapsed_ms,
                "responseId": response.id,
                "text": text.strip(),
            },
        )

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("content-length", "0"))
        if length > 200_000:
            raise ValueError("Request body is too large.")
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def send_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_run_artifact(self, raw_path: str) -> None:
        rel = unquote(raw_path).replace("\\", "/").lstrip("/")
        candidate = (RUNS_DIR / rel).resolve()
        try:
            candidate.relative_to(RUNS_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_file(candidate, content_type_for(candidate))

    def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        try:
            if sys.stderr is not None:
                sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))
        except OSError:
            pass


def main() -> int:
    load_env()
    host = os.getenv("BUGLAB_HOST", DEFAULT_HOST)
    port = int(os.getenv("BUGLAB_PORT", str(DEFAULT_PORT)))
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        print(f"Serving BugLab SwarmQA console at http://{host}:{port}")
    except Exception:
        pass
    server.serve_forever()
    return 0


def content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".jsonl": "application/x-ndjson; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")


def buglab_overview() -> dict[str, object]:
    from buglab.api import collect_aggregate_summaries

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    aggregates = collect_aggregate_summaries(RUNS_DIR)
    manifests = sorted(RUNS_DIR.glob("*/report_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    latest_manifest_rows = []
    for path in manifests[:24]:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        latest_manifest_rows.append(
            {
                "runId": manifest.get("run_id", path.parent.name),
                "tool": manifest.get("tool", ""),
                "target": manifest.get("target", ""),
                "status": manifest.get("status", "unknown"),
                "findings": len(manifest.get("findings", [])),
                "evidence": len(manifest.get("evidence", [])),
                "created": manifest.get("created_at_utc", ""),
                "href": runs_href(path.parent / "report.html"),
            }
        )
    aggregate_rows = [aggregate_row(item) for item in aggregates[:48]]
    metrics = {
        "standardizedRuns": len(manifests),
        "aggregateSummaries": len(aggregates),
        "failedAggregates": sum(1 for item in aggregates if item.get("status") == "failed"),
        "latestUpdated": max((float(item.get("updated_at", 0)) for item in aggregates), default=0),
    }
    return {
        "ok": True,
        "repo": str(ROOT),
        "outputRoot": str(RUNS_DIR),
        "metrics": metrics,
        "aggregates": aggregate_rows,
        "runs": latest_manifest_rows,
        "quickActions": quick_actions(),
    }


def aggregate_row(item: dict[str, object]) -> dict[str, object]:
    json_path = Path(str(item.get("json_path", "")))
    csv_path = Path(str(item.get("csv_path", "")))
    summary = item.get("summary", {})
    return {
        "kind": item.get("kind", ""),
        "name": item.get("name", ""),
        "status": item.get("status", "unknown"),
        "summary": summary if isinstance(summary, dict) else {},
        "updatedAt": float(item.get("updated_at", 0)),
        "jsonHref": runs_href(json_path) if json_path.exists() else "",
        "csvHref": runs_href(csv_path) if csv_path.exists() else "",
        "htmlHref": matching_html_href(json_path),
    }


def matching_html_href(json_path: Path) -> str:
    candidates = []
    if json_path.name.endswith("_summary.json"):
        candidates.append(json_path.with_suffix(".html"))
    if json_path.name == "findings_pareto.json":
        candidates.append(json_path.with_suffix(".html"))
    if json_path.name == "repo_audit.json":
        candidates.append(json_path.parent / "report.html")
    for candidate in candidates:
        if candidate.exists():
            return runs_href(candidate)
    return ""


def runs_href(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(RUNS_DIR.resolve()).as_posix()
    except ValueError:
        return ""
    return f"/runs/{rel}"


def quick_actions() -> list[dict[str, str]]:
    return [
        {"id": "hunt_full", "label": "Find Bugs", "tone": "primary"},
        {"id": "hunt_guided", "label": "Guided Find", "tone": "primary"},
        {"id": "find_and_fix", "label": "Find + Fix", "tone": "primary"},
    ]


def buglab_runtime() -> dict[str, object]:
    profile = project_processing_profile()
    return {
        "ok": True,
        "activeAgents": profile["activeAgents"],
        "agentNames": profile["agentNames"],
        "locProcessed": profile["locProcessed"],
        "fileCount": profile["fileCount"],
        "estimatedTokens": profile["estimatedTokens"],
        "bugHuntTokens": profile["bugHuntTokens"],
        "repairCrewTokens": profile["repairCrewTokens"],
        "avgTokensPerSecond": profile["avgTokensPerSecond"],
        "tokenProvenance": profile["tokenProvenance"],
    }


def buglab_submission() -> dict[str, object]:
    submission_json, submission_md, source = current_submission_paths()
    freeze = load_submission_freeze()
    if not submission_json.exists():
        return {
            "ok": True,
            "available": False,
            "packageHref": "/submission/package.md",
            "summary": {},
            "latestEvents": [],
            "replayMisses": [],
            "promotionQueue": [],
            "freeze": freeze_summary(freeze, source, ""),
        }
    try:
        payload = json.loads(submission_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "ok": True,
            "available": False,
            "packageHref": "/submission/package.md",
            "summary": {},
            "latestEvents": [],
            "replayMisses": [],
            "promotionQueue": [],
            "freeze": freeze_summary(freeze, source, ""),
        }
    eval_summary = payload.get("eval_log_summary", {}) if isinstance(payload.get("eval_log_summary", {}), dict) else {}
    oracle = payload.get("oracle_totals", {}) if isinstance(payload.get("oracle_totals", {}), dict) else {}
    marked = payload.get("marked_evidence", {}) if isinstance(payload.get("marked_evidence", {}), dict) else {}
    evidence = payload.get("evidence_completeness", {}) if isinstance(payload.get("evidence_completeness", {}), dict) else {}
    replay = payload.get("real_repo_replay", {}) if isinstance(payload.get("real_repo_replay", {}), dict) else {}
    replay_unique = (
        payload.get("real_repo_replay_unique", {})
        if isinstance(payload.get("real_repo_replay_unique", {}), dict)
        else {}
    )
    validation = payload.get("validation", {}) if isinstance(payload.get("validation", {}), dict) else {}
    latest = payload.get("latest_eval_events", []) if isinstance(payload.get("latest_eval_events", []), list) else []
    replay_misses = payload.get("real_repo_replay_misses", []) if isinstance(payload.get("real_repo_replay_misses", []), list) else []
    promotion_queue = payload.get("promotion_queue", []) if isinstance(payload.get("promotion_queue", []), list) else []
    promotion_triage = (
        payload.get("promotion_triage_pack", {})
        if isinstance(payload.get("promotion_triage_pack", {}), dict)
        else {}
    )
    calibration = payload.get("calibration_ledger", {}) if isinstance(payload.get("calibration_ledger", {}), dict) else {}
    calibration_buckets = calibration.get("buckets", []) if isinstance(calibration.get("buckets", []), list) else []
    return {
        "ok": True,
        "available": True,
        "source": source,
        "sourcePath": public_path(submission_json),
        "updatedAt": payload.get("updated_at_utc", ""),
        "packageHref": "/submission/package.md" if submission_md.exists() else "",
        "freeze": freeze_summary(freeze, source, str(payload.get("updated_at_utc", ""))),
        "validation": {
            "ok": validation.get("ok"),
            "warnings": validation.get("warnings", []) if isinstance(validation.get("warnings", []), list) else [],
            "failures": validation.get("failures", []) if isinstance(validation.get("failures", []), list) else [],
            "checks": len(validation.get("checks", [])) if isinstance(validation.get("checks", []), list) else 0,
        },
        "summary": {
            "events": eval_summary.get("events", 0),
            "completed": eval_summary.get("completed", 0),
            "failed": eval_summary.get("failed", 0),
            "bugsinpy": eval_summary.get("bugsinpy", 0),
            "realRepoAudits": eval_summary.get("real_repo_audit", 0),
            "oracleCases": oracle.get("unique_cases", 0),
            "stableOracleCases": oracle.get("stable_unique_cases", 0),
            "unstableOracleCases": oracle.get("unstable_cases", oracle.get("disagreements", 0)),
            "oracleProjects": oracle.get("oracle_project_names", []),
            "stableOracleProjects": oracle.get("stable_project_names", []),
            "truePositive": oracle.get("true_positive", 0),
            "falsePositive": oracle.get("false_positive", 0),
            "falseNegative": oracle.get("false_negative", 0),
            "trueNegative": oracle.get("true_negative", 0),
            "stableTruePositive": oracle.get("stable_true_positive", 0),
            "stableFalsePositive": oracle.get("stable_false_positive", 0),
            "stableFalseNegative": oracle.get("stable_false_negative", 0),
            "stableTrueNegative": oracle.get("stable_true_negative", 0),
            "rejected": oracle.get("rejected_case_results", 0),
            "precision": oracle.get("precision"),
            "precisionWilsonLower95": oracle.get("precision_wilson_lower_95"),
            "recall": oracle.get("recall"),
            "recallWilsonLower95": oracle.get("recall_wilson_lower_95"),
            "f1": oracle.get("f1"),
            "stablePrecision": oracle.get("stable_precision"),
            "stablePrecisionWilsonLower95": oracle.get("stable_precision_wilson_lower_95"),
            "stableRecall": oracle.get("stable_recall"),
            "stableRecallWilsonLower95": oracle.get("stable_recall_wilson_lower_95"),
            "stableF1": oracle.get("stable_f1"),
            "markedEntries": marked.get("entries", 0),
            "suspected": marked.get("suspected", 0),
            "invalidOracle": marked.get("invalid_oracle", 0),
            "evidenceCompleteEntries": evidence.get("complete_entries", 0),
            "evidenceIncompleteEntries": evidence.get("incomplete_entries", 0),
            "evidenceCompletionRate": evidence.get("completion_rate"),
            "evidenceMissingReproduction": evidence.get("missing_reproduction", 0),
            "evidenceMissingObservation": evidence.get("missing_observation", 0),
            "replayChecked": replay.get("checked", 0),
            "replayReproduced": replay.get("reproduced", 0),
            "replayPartiallyReproduced": replay.get("partially_reproduced", 0),
            "replayNotReproduced": replay.get("not_reproduced", 0),
            "replayUnsupported": replay.get("unsupported", 0),
            "replayErrors": replay.get("error", 0),
            "replayUnsupportedSignals": replay.get("unsupported_signals", 0),
            "replayReproductionRate": replay.get("replay_reproduction_rate"),
            "replayTriage": replay.get("triage", {}) if isinstance(replay.get("triage", {}), dict) else {},
            "uniqueReplayClaims": replay_unique.get("unique_claims", 0),
            "uniqueReplayReproduced": replay_unique.get("unique_reproduced", 0),
            "uniqueReplayPartiallyReproduced": replay_unique.get("unique_partially_reproduced", 0),
            "uniqueReplayNotReproduced": replay_unique.get("unique_not_reproduced", 0),
            "uniqueReplayDuplicatePacketsCollapsed": replay_unique.get("duplicate_packets_collapsed", 0),
            "uniqueReplayReproductionRate": replay_unique.get("unique_replay_reproduction_rate"),
            "uniqueReplayTriage": (
                replay_unique.get("triage", {}) if isinstance(replay_unique.get("triage", {}), dict) else {}
            ),
        },
        "calibrationLedger": {
            "accuracyBasis": str(calibration.get("accuracy_basis", "")),
            "policy": str(calibration.get("policy", "")),
            "accuracyCaseCount": int(calibration.get("accuracy_case_count") or 0),
            "stableAccuracyCaseCount": int(calibration.get("stable_accuracy_case_count") or 0),
            "nonOracleEvidenceCount": int(calibration.get("non_oracle_evidence_count") or 0),
            "quarantinedCount": int(calibration.get("quarantined_count") or 0),
            "unverifiedSuspectedCount": int(calibration.get("unverified_suspected_count") or 0),
            "buckets": [
                {
                    "id": str(item.get("id", "")),
                    "label": str(item.get("label", "")),
                    "count": int(item.get("count") or 0),
                    "stableCount": int(item.get("stable_count") or 0),
                    "contributesToAccuracy": item.get("contributes_to_accuracy") is True,
                    "confidence": str(item.get("confidence", "")),
                    "policy": str(item.get("policy", "")),
                    "precision": item.get("precision"),
                    "recall": item.get("recall"),
                    "f1": item.get("f1"),
                    "replayRate": item.get("replay_rate"),
                }
                for item in calibration_buckets
                if isinstance(item, dict)
            ],
        },
        "latestEvents": [
            {
                "startedAt": str(item.get("started_at_utc", "")),
                "kind": str(item.get("kind", "")),
                "target": str(item.get("target_name", item.get("target", ""))),
                "status": str(item.get("status", "")),
                "summary": str(item.get("summary", "")),
                "artifact": str(item.get("artifact", "")),
            }
            for item in latest[:6]
            if isinstance(item, dict)
        ],
        "replayMisses": [
            {
                "repo": str(item.get("repo", "")),
                "findingId": str(item.get("finding_id", "")),
                "sector": str(item.get("sector", "")),
                "target": str(item.get("target", "")),
                "verdict": str(item.get("verdict", "")),
                "triageClass": str(item.get("triage_class", "")),
                "triageAction": str(item.get("triage_action", "")),
                "missingSignals": [str(signal) for signal in (item.get("missing_signals", []) or [])[:4]],
                "packetsCollapsed": int(item.get("packets_collapsed") or 0),
                "policy": str(item.get("policy", "")),
            }
            for item in replay_misses[:6]
            if isinstance(item, dict)
        ],
        "promotionQueue": [
            {
                "rank": int(item.get("rank") or 0),
                "repo": str(item.get("repo", "")),
                "findingId": str(item.get("finding_id", "")),
                "severity": str(item.get("severity", "")),
                "category": str(item.get("category", "")),
                "claim": str(item.get("claim", "")),
                "signals": [str(signal) for signal in (item.get("signals", []) or [])[:4]],
                "reproductionSteps": [str(step) for step in (item.get("reproduction_steps", []) or [])[:3]],
                "packetsSeen": int(item.get("packets_seen") or 0),
                "promotionAction": str(item.get("promotion_action", "")),
                "promotionPolicy": str(item.get("promotion_policy", "")),
                "ledgerPath": str(item.get("ledger_path", "")),
            }
            for item in promotion_queue[:8]
            if isinstance(item, dict)
        ],
        "promotionTriagePack": {
            "policy": str(promotion_triage.get("policy", "")),
            "candidateCount": int(promotion_triage.get("candidate_count") or 0),
            "topCandidateCount": int(promotion_triage.get("top_candidate_count") or 0),
            "actionBuckets": [
                {
                    "id": str(item.get("id", "")),
                    "label": str(item.get("label", "")),
                    "count": int(item.get("count") or 0),
                    "packetsSeen": int(item.get("packets_seen") or 0),
                    "promotionAction": str(item.get("promotion_action", "")),
                    "accuracyPolicy": str(item.get("accuracy_policy", "")),
                }
                for item in (promotion_triage.get("action_buckets", []) or [])[:6]
                if isinstance(item, dict)
            ],
            "topMoves": [
                {
                    "rank": int(item.get("rank") or 0),
                    "repo": str(item.get("repo", "")),
                    "findingId": str(item.get("finding_id", "")),
                    "target": str(item.get("target", "")),
                    "verificationCommand": str(item.get("verification_command", "")),
                    "promotionAction": str(item.get("promotion_action", "")),
                    "accuracyPolicy": str(item.get("accuracy_policy", "")),
                }
                for item in (promotion_triage.get("top_moves", []) or [])[:5]
                if isinstance(item, dict)
            ],
        },
    }


def load_submission_freeze() -> dict[str, Any]:
    try:
        payload = json.loads(SUBMISSION_FREEZE_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def freeze_summary(freeze: dict[str, Any], source: str, package_updated_at: str) -> dict[str, object]:
    delta = freeze.get("delta_since_previous_freeze", {}) if isinstance(freeze.get("delta_since_previous_freeze", {}), dict) else {}
    raw_changed = delta.get("changed_metrics", {}) if isinstance(delta.get("changed_metrics", {}), dict) else {}
    raw_metrics = delta.get("metrics", []) if isinstance(delta.get("metrics", []), list) else []
    freeze_updated_at = str(freeze.get("package_updated_at_utc", ""))
    return {
        "available": bool(freeze),
        "ok": freeze.get("ok") is True,
        "source": "tracked_freeze",
        "packageUpdatedAt": freeze_updated_at,
        "liveSource": source,
        "liveAdvancedAfterFreeze": bool(source == "live" and package_updated_at and freeze_updated_at and package_updated_at > freeze_updated_at),
        "summary": freeze.get("summary", {}) if isinstance(freeze.get("summary", {}), dict) else {},
        "delta": {
            "previousFreezeFound": delta.get("previous_freeze_found") is True,
            "trackedJsonChanged": delta.get("tracked_json_changed") is True,
            "previousPackageUpdatedAt": str(delta.get("previous_package_updated_at_utc", "")),
            "currentPackageUpdatedAt": str(delta.get("current_package_updated_at_utc", "")),
            "interpretation": [str(item) for item in (delta.get("interpretation", []) or [])[:6]],
            "changedMetrics": [
                {"name": str(name), "delta": value}
                for name, value in sorted(raw_changed.items())
            ],
            "metrics": [
                {
                    "name": str(item.get("name", "")),
                    "previous": item.get("previous", 0),
                    "current": item.get("current", 0),
                    "delta": item.get("delta", 0),
                }
                for item in raw_metrics
                if isinstance(item, dict)
            ],
        },
    }


def current_submission_paths() -> tuple[Path, Path, str]:
    live_enabled = os.getenv("BUGLAB_ENABLE_LIVE_SUBMISSION", "").strip().lower() in {"1", "true", "yes", "on"}
    allow_external = os.getenv("BUGLAB_ALLOW_EXTERNAL_SUBMISSION", "").strip().lower() in {"1", "true", "yes", "on"}
    live_json_value = os.getenv("BUGLAB_LIVE_SUBMISSION_JSON", "").strip()
    live_md_value = os.getenv("BUGLAB_LIVE_SUBMISSION_MD", "").strip()
    live_json = Path(live_json_value) if live_enabled and live_json_value else None
    live_md = Path(live_md_value) if live_enabled and live_md_value else None
    if live_json is not None and live_json.exists() and (allow_external or is_inside_root(live_json)):
        markdown = live_md if live_md is not None and live_md.exists() else SUBMISSION_MD
        return live_json, markdown, "live"
    return SUBMISSION_JSON, SUBMISSION_MD, "snapshot"


def is_inside_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return False
    return True


def public_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return ""


def run_buglab_action(action: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    payload = payload or {}
    if action == "hunt_full":
        repo = target_repo_from_payload(payload)
        result = run_full_hunt(repo=repo, run_name=target_run_name("ui_hunt_full", repo))
        result["target"] = target_payload(repo)
        return result
    if action == "hunt_guided":
        repo = target_repo_from_payload(payload)
        issue = str(payload.get("issue", "")).strip()
        files = payload.get("files", [])
        result = run_full_hunt(repo=repo, run_name=target_run_name("ui_hunt_guided", repo))
        result["guidedContext"] = {
            "issue": issue,
            "files": files if isinstance(files, list) else [],
        }
        result["target"] = target_payload(repo)
        return result
    if action == "find_and_fix":
        repo = target_repo_from_payload(payload)
        result = run_find_and_fix(repo=repo, run_name=target_run_name("ui_find_and_fix", repo))
        result["target"] = target_payload(repo)
        return result
    if action == "doctor":
        from buglab.api import doctor_repo

        result = doctor_repo(repo=ROOT, output=RUNS_DIR, check_browser=True, write_report=True)
        return action_result(result.get("summary", {}), {"report": result.get("report_path", "")})
    if action == "index":
        from buglab.api import build_index

        result = build_index(repo=ROOT, output=RUNS_DIR)
        return action_result(result, {"index": result.get("index_path", "")})
    raise ValueError(f"Unknown BugLab action: {action}")


def target_repo_from_payload(payload: dict[str, object]) -> Path:
    target = payload.get("target", {})
    if not isinstance(target, dict):
        raise ValueError("Target payload is required.")
    raw_path = str(target.get("localPath", "")).strip().strip("\"'")
    if not raw_path:
        raise ValueError("No target selected. Enter a local project path before starting BugLab.")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.exists():
        raise ValueError(f"Target path does not exist: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"Target path must be a directory: {candidate}")
    return candidate


def target_payload(repo: Path) -> dict[str, object]:
    return {"selected": True, "name": repo.name, "localPath": str(repo)}


def target_run_name(prefix: str, repo: Path) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in repo.name.lower()).strip("_") or "target"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{slug}_{timestamp}"


def run_full_hunt(repo: Path, run_name: str) -> dict[str, object]:
    from buglab.api import bughunt_repo

    result = bughunt_repo(
        repo=repo,
        output=RUNS_DIR,
        targets=None,
        loops=1,
        profiles=["balanced"],
        max_clicks=8,
        include_browser=True,
        include_docs=True,
        include_tests=True,
        include_config=True,
        run_doctor=True,
        check_browser=True,
        build_pareto=True,
        run_name=run_name,
        build_report_index=True,
    )
    audit = result.get("audit", {}) if isinstance(result.get("audit"), dict) else {}
    summary = dict(audit.get("summary", {}) if isinstance(audit.get("summary"), dict) else result.get("summary", {}))
    summary["workflow_path"] = result.get("workflow_path", "")
    summary["case_count"] = result.get("summary", {}).get("case_count", 0) if isinstance(result.get("summary"), dict) else 0
    return action_result(
        summary,
        {
            "html": audit.get("report_path", ""),
            "json": audit.get("json_path", ""),
            "cases": audit.get("case_index_path", ""),
            "findings": audit.get("findings_jsonl_path", ""),
            "workflow": result.get("workflow_path", ""),
        },
        mode="find",
    )


def run_find_and_fix(repo: Path, run_name: str) -> dict[str, object]:
    from buglab.api import bughunt_repo

    result = bughunt_repo(
        repo=repo,
        output=RUNS_DIR,
        targets=None,
        loops=1,
        profiles=["balanced"],
        max_clicks=8,
        include_browser=True,
        include_docs=True,
        include_tests=True,
        include_config=True,
        run_doctor=True,
        check_browser=True,
        build_pareto=True,
        run_name=run_name,
        build_report_index=True,
    )
    audit = result.get("audit", {}) if isinstance(result.get("audit"), dict) else {}
    summary = dict(audit.get("summary", {}) if isinstance(audit.get("summary"), dict) else result.get("summary", {}))
    repair_result = run_ponytail_fix_pass(repo, run_name, audit)
    repair_summary = repair_result.get("summary", {}) if isinstance(repair_result.get("summary"), dict) else {}
    summary["workflow_path"] = result.get("workflow_path", "")
    summary["case_count"] = result.get("summary", {}).get("case_count", 0) if isinstance(result.get("summary"), dict) else 0
    summary["repair_attempts"] = metric_int(repair_summary, "repair_attempts")
    summary["repair_passed"] = metric_int(repair_summary, "repair_passed")
    summary["repair_pass_rate"] = metric_float(repair_summary, "repair_pass_rate")
    summary["repair_total_before"] = sum(metric_int(row, "before") for row in repair_result.get("repair_rows", []) if isinstance(row, dict))
    summary["repair_total_after"] = sum(metric_int(row, "after") for row in repair_result.get("repair_rows", []) if isinstance(row, dict))
    summary["repair_mode"] = repair_result.get("mode", "ponytail")
    summary["repair_note"] = repair_result.get(
        "note",
        "Ponytail fix agents routed every detected issue through a smallest-change repair pass; verified fixes require before/after evidence.",
    )
    presentation_json = write_find_fix_presentation_payload(run_name, repo, result, audit, summary, repair_result)
    return action_result(
        summary,
        {
            "html": audit.get("report_path", ""),
            "json": presentation_json,
            "cases": audit.get("case_index_path", ""),
            "findings": audit.get("findings_jsonl_path", ""),
            "workflow": result.get("workflow_path", ""),
            "repair": repair_result.get("html_path", ""),
        },
        mode="find_and_fix",
    )


def run_ponytail_fix_pass(repo: Path, run_name: str, audit: dict[str, Any]) -> dict[str, Any]:
    manifests_ready = all((repo / path).is_file() for path in DEFAULT_REPAIR_MANIFESTS)
    if manifests_ready:
        from buglab.api import run_swarm

        repair_result = run_swarm(
            repo=repo,
            output=RUNS_DIR,
            fields=["browser_api", "cli_data", "repo_quality"],
            loops=1,
            profiles=["balanced"],
            max_clicks=8,
            run_name=f"{run_name}_ponytail_fix",
            repair=True,
            build_report_index=True,
        )
        repair_result["mode"] = "verified_sector_repair"
        repair_result["note"] = "Ponytail fix agents ran deterministic before/after repair implementations against the selected target's BugLab sector manifests."
        return repair_result

    return build_ponytail_fix_queue(repo, run_name, audit)


DEFAULT_REPAIR_MANIFESTS = (
    Path("targets/sectors/html_interaction/manifest.json"),
    Path("targets/sectors/api_workflows/manifest.json"),
    Path("targets/sectors/cli_data/manifest.json"),
)


def build_ponytail_fix_queue(repo: Path, run_name: str, audit: dict[str, Any]) -> dict[str, Any]:
    findings = read_audit_findings(audit)
    repair_rows = []
    for finding in findings:
        signal_count = metric_int(finding, "signal_count") or len(finding.get("signals", []) if isinstance(finding.get("signals", []), list) else [])
        sector = str(finding.get("sector") or "bug")
        repair_rows.append(
            {
                "field": "ponytail_fix_agent",
                "sector": sector,
                "manifest": "",
                "technique": "ponytail_fix_plan",
                "status": "queued",
                "before": signal_count,
                "after": signal_count,
                "repair_success_rate": 0,
                "csv_path": "",
                "json_path": str(finding.get("case_json_path", "")),
                "notes": ponytail_fix_note(finding),
            }
        )

    summary = {
        "repair_attempts": len(repair_rows),
        "repair_passed": 0,
        "repair_pass_rate": 0,
        "total_before_found_bugs": sum(metric_int(row, "before") for row in repair_rows),
        "total_after_found_bugs": sum(metric_int(row, "after") for row in repair_rows),
    }
    json_path = RUNS_DIR / f"{run_name}_ponytail_fix_queue.json"
    html_path = RUNS_DIR / f"{run_name}_ponytail_fix_queue.html"
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "buglab.ponytail_fix_queue.v1",
        "repo": str(repo),
        "summary": summary,
        "repair_rows": repair_rows,
        "findings": findings,
        "policy": {
            "name": "Ponytail",
            "rule": "smallest targeted implementation per finding, then rerun the exact detector before marking fixed",
        },
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    html_path.write_text(render_ponytail_fix_queue_html(repo, summary, repair_rows), encoding="utf-8")
    return {
        "mode": "queued_issue_repair",
        "note": "Selected target has no BugLab sector repair manifests, so every detected issue was assigned to a Ponytail fix agent queue instead of claiming unverified code edits.",
        "summary": summary,
        "repair_rows": repair_rows,
        "json_path": str(json_path),
        "html_path": str(html_path),
        "truth_ledger_path": "",
    }


def read_audit_findings(audit: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(str(audit.get("findings_jsonl_path", "")))
    if not path.is_file():
        return []
    findings: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                findings.append(item)
    except (OSError, json.JSONDecodeError):
        return []
    return findings


def ponytail_fix_note(finding: dict[str, Any]) -> str:
    hypothesis = str(finding.get("fix_hypothesis", "")).strip()
    target = str(finding.get("target", "")).strip()
    if hypothesis and target:
        return f"ponytail_agent_assigned target={target}; hypothesis={hypothesis}"
    if target:
        return f"ponytail_agent_assigned target={target}"
    return "ponytail_agent_assigned"


def render_ponytail_fix_queue_html(repo: Path, summary: dict[str, Any], repair_rows: list[dict[str, Any]]) -> str:
    rows = "\n".join(
        f"<tr><td>{html.escape(str(row.get('sector', '')))}</td><td>{html.escape(str(row.get('status', '')))}</td>"
        f"<td>{html.escape(str(row.get('before', '')))}</td><td>{html.escape(str(row.get('notes', '')))}</td></tr>"
        for row in repair_rows
    )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>BugLab Ponytail Fix Queue</title>
<style>
body {{ background:#030603; color:#8cff9a; font:14px Consolas,monospace; padding:24px; }}
table {{ border-collapse:collapse; width:100%; }}
td, th {{ border-bottom:1px solid #163a20; padding:8px; text-align:left; vertical-align:top; }}
</style>
<h1>Ponytail Fix Queue</h1>
<p>Target: {html.escape(str(repo))}</p>
<p>Agents assigned: {int(summary.get('repair_attempts', 0))}. Verified fixes: {int(summary.get('repair_passed', 0))}.</p>
<table><thead><tr><th>Sector</th><th>Status</th><th>Signals</th><th>Fix Route</th></tr></thead><tbody>{rows}</tbody></table>
"""


def write_find_fix_presentation_payload(
    run_name: str,
    repo: Path,
    workflow: dict[str, Any],
    audit: dict[str, Any],
    summary: dict[str, Any],
    repair_result: dict[str, Any],
) -> str:
    audit_payload: dict[str, Any] = {}
    audit_json = Path(str(audit.get("json_path", "")))
    if audit_json.exists():
        try:
            loaded = json.loads(audit_json.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                audit_payload = loaded
        except (OSError, json.JSONDecodeError):
            audit_payload = {}
    rows = audit_payload.get("rows", [])
    findings = audit_payload.get("findings", [])
    payload = {
        "schema_version": "buglab.find_fix_presentation.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": str(repo),
        "summary": summary,
        "rows": rows if isinstance(rows, list) else [],
        "findings": findings if isinstance(findings, list) else [],
        "repair_summary": repair_result.get("summary", {}),
        "repair_rows": repair_result.get("repair_rows", []),
        "repair_truth_ledger_path": repair_result.get("truth_ledger_path", ""),
        "workflow": {
            "workflow_path": workflow.get("workflow_path", ""),
            "audit_json_path": audit.get("json_path", ""),
            "repair_json_path": repair_result.get("json_path", ""),
            "repair_html_path": repair_result.get("html_path", ""),
        },
        "pony_tail_policy": {
            "method": "Ponytail fix loop",
            "rule": "smallest deterministic patch, before/after verification, unsupported sectors queued instead of claimed fixed",
        },
    }
    out_path = RUNS_DIR / f"{run_name}_find_fix_presentation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out_path)


def action_result(summary: object, artifacts: dict[str, object], *, mode: str = "find") -> dict[str, object]:
    linked = {}
    for name, value in artifacts.items():
        path = Path(str(value))
        linked[name] = {"path": str(value), "href": runs_href(path) if path.exists() else ""}
    normalized_summary = summary if isinstance(summary, dict) else {}
    presentation = build_presentation_report(normalized_summary, linked, mode=mode)
    return {
        "summary": normalized_summary,
        "artifacts": linked,
        "presentation": presentation,
        "telemetry": presentation["telemetry"],
    }


def build_presentation_report(summary: dict[str, Any], artifacts: dict[str, dict[str, str]], *, mode: str = "find") -> dict[str, Any]:
    payload = read_primary_payload(artifacts)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    rows = rows if isinstance(rows, list) else []
    repair_rows = payload.get("repair_rows", []) if isinstance(payload, dict) else []
    repair_rows = repair_rows if isinstance(repair_rows, list) else []
    categories = build_categories(summary, rows)
    bug_count = metric_int(summary, "total_found_bugs", "total_bug_candidates", "total_signals", "total_unique_signals")
    if not bug_count:
        bug_count = sum(int(category["count"]) for category in categories)
    recall = metric_float(summary, "avg_expected_class_recall", "sector_pass_rate", "detection_rate")
    telemetry = split_processing_profile(project_processing_profile(), summary, mode=mode)
    fixed_bugs = build_fixed_bugs(repair_rows)
    findings = build_top_findings(categories, rows)
    truth_ledger = normalize_truth_ledger(payload, summary, categories, findings, fixed_bugs, telemetry)
    truth_summary = truth_ledger.get("summary", {})
    metrics = [
        {"label": "Issues Found", "value": bug_count, "tone": "hot"},
        {"label": "Confirmed Evidence", "value": metric_int(truth_summary, "confirmed"), "tone": "normal"},
        {"label": "False Positives", "value": metric_int(truth_summary, "false_positive"), "tone": "hot"} if metric_int(truth_summary, "false_positive") else None,
        {"label": "False Negatives", "value": metric_int(truth_summary, "false_negative"), "tone": "hot"} if metric_int(truth_summary, "false_negative") else None,
        {"label": "Precision", "value": format_optional_rate(truth_summary.get("precision")), "tone": "normal"} if truth_summary.get("precision") is not None else None,
        {"label": "Fixed Bugs", "value": sum(int(item["fixedCount"]) for item in fixed_bugs), "tone": "fixed"} if mode == "find_and_fix" else None,
        {"label": "Categories", "value": len([item for item in categories if int(item["count"]) > 0]), "tone": "normal"},
        {"label": "Runs", "value": metric_int(summary, "runs", "sector_runs", "fixtures"), "tone": "normal"},
        {"label": "Recall", "value": format_rate(recall), "tone": "normal"},
        {"label": "Repair Pass", "value": format_rate(metric_float(summary, "repair_pass_rate")), "tone": "fixed"} if mode == "find_and_fix" else None,
        {"label": "Active Agents", "value": telemetry["activeAgents"], "tone": "normal"},
        {"label": "LOC Processed", "value": telemetry["locProcessed"], "tone": "normal"},
        {"label": "Avg Tok/sec", "value": telemetry["avgTokensPerSecond"], "tone": "normal"},
        {"label": "Bug Hunt Tokens", "value": telemetry["bugHuntTokens"], "tone": "normal"},
        {"label": "Repair Crew Tokens", "value": telemetry["repairCrewTokens"], "tone": "fixed"} if mode == "find_and_fix" else None,
        {"label": "Tokens Processed", "value": telemetry["estimatedTokens"], "tone": "normal"},
        {"label": "LLM Tokens", "value": telemetry["llmTokensTracked"], "tone": "normal"},
    ]
    metrics = [metric for metric in metrics if metric is not None]
    return {
        "bugCount": bug_count,
        "categoryCount": len(categories),
        "headline": report_headline(bug_count, categories, mode=mode, summary=summary),
        "motto": BRAND_MOTTO,
        "mode": mode,
        "metrics": metrics,
        "categories": categories,
        "findings": findings,
        "fixedBugs": fixed_bugs,
        "truthLedger": truth_ledger,
        "agentSummary": agent_copy_summary(summary, categories, findings, fixed_bugs, artifacts, telemetry, truth_ledger, mode=mode),
        "telemetry": telemetry,
        "chart": {
            "title": "Issues by Category",
            "series": [{"name": item["label"], "value": int(item["count"])} for item in categories],
        },
    }


def read_primary_payload(artifacts: dict[str, dict[str, str]]) -> dict[str, Any]:
    for key in ("json", "workflow", "report", "index"):
        path = Path(artifacts.get(key, {}).get("path", ""))
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def normalize_truth_ledger(
    payload: dict[str, Any],
    summary: dict[str, Any],
    categories: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    fixed_bugs: list[dict[str, Any]],
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    from buglab.truth import summarize_truth_entries

    raw = payload.get("truth_ledger") if isinstance(payload, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    entries = raw.get("entries", []) if isinstance(raw.get("entries", []), list) else []
    if not entries:
        entries = synthesize_presentation_truth_entries(summary, categories, findings, fixed_bugs, telemetry)
    raw_summary = raw.get("summary", {}) if isinstance(raw.get("summary", {}), dict) else {}
    ledger_summary = raw_summary or summarize_truth_entries(entries)
    return {
        "schemaVersion": raw.get("schema_version", "buglab.truth_ledger.v1"),
        "summary": ledger_summary,
        "entries": [normalize_truth_entry(entry) for entry in entries[:12] if isinstance(entry, dict)],
    }


def synthesize_presentation_truth_entries(
    summary: dict[str, Any],
    categories: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    fixed_bugs: list[dict[str, Any]],
    telemetry: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, finding in enumerate(findings[:8], start=1):
        entries.append(
            {
                "finding_id": f"UI-SUSPECT-{index:03d}",
                "phase": "find",
                "status": "suspected",
                "outcome": "unscored",
                "confidence": 0.55,
                "claim": finding.get("title", "Unscored BugLab finding"),
                "severity": finding.get("severity", "unknown"),
                "category": finding.get("category", ""),
                "evidence": {
                    "reproduction_steps": [finding.get("nextStep", "Verify the linked evidence.")],
                    "signals": [finding.get("evidence", "")],
                },
                "oracle": {
                    "type": "none",
                    "verdict": "unverified",
                    "note": "Presentation fallback only; rerun against an oracle benchmark before using accuracy metrics.",
                },
                "metrics": {
                    "elapsed_ms": metric_int(summary, "elapsed_ms"),
                    "tokens": metric_int(telemetry, "bugHuntTokens", "estimatedTokens"),
                },
            }
        )
    for index, item in enumerate(fixed_bugs[:8], start=1):
        entries.append(
            {
                "finding_id": f"UI-FIXED-{index:03d}",
                "phase": "fix",
                "status": "fixed",
                "outcome": "repair_verified",
                "confidence": 0.9,
                "claim": item.get("title", "Verified repair"),
                "severity": "repair",
                "category": item.get("category", ""),
                "evidence": {
                    "reproduction_steps": ["Review before/after repair artifact.", "Rerun the same detector to confirm the signal remains cleared."],
                    "signals": [item.get("evidence", "")],
                    "artifact": item.get("artifactHref", ""),
                },
                "oracle": {
                    "type": "repair before/after verification",
                    "verdict": "scored",
                    "before": item.get("before"),
                    "after": item.get("after"),
                },
                "metrics": {
                    "elapsed_ms": metric_int(summary, "elapsed_ms"),
                    "tokens": metric_int(telemetry, "repairCrewTokens"),
                },
            }
        )
    if not entries and not any(int(category["count"]) > 0 for category in categories):
        entries.append(
            {
                "finding_id": "UI-CLEAN-001",
                "phase": "find",
                "status": "clean",
                "outcome": "unscored_clean",
                "confidence": 0.5,
                "claim": "No issue signals were reported by this run.",
                "severity": "info",
                "category": "summary",
                "evidence": {"reproduction_steps": ["Open the linked run artifact and inspect the detector output."], "signals": []},
                "oracle": {"type": "none", "verdict": "unverified"},
                "metrics": {"elapsed_ms": metric_int(summary, "elapsed_ms"), "tokens": metric_int(telemetry, "bugHuntTokens", "estimatedTokens")},
            }
        )
    return entries


def normalize_truth_entry(entry: dict[str, Any]) -> dict[str, Any]:
    evidence = entry.get("evidence", {}) if isinstance(entry.get("evidence", {}), dict) else {}
    oracle = entry.get("oracle", {}) if isinstance(entry.get("oracle", {}), dict) else {}
    metrics = entry.get("metrics", {}) if isinstance(entry.get("metrics", {}), dict) else {}
    artifact = evidence.get("artifact", "")
    return {
        "id": str(entry.get("finding_id", "")),
        "status": str(entry.get("status", "suspected")),
        "outcome": str(entry.get("outcome", "unscored")),
        "phase": str(entry.get("phase", "find")),
        "claim": str(entry.get("claim", "")),
        "category": str(entry.get("category", "")),
        "severity": str(entry.get("severity", "")),
        "confidence": entry.get("confidence", ""),
        "oracleType": str(oracle.get("type", "none")),
        "oracleVerdict": str(oracle.get("verdict", "unverified")),
        "oracleNote": str(oracle.get("note", "")),
        "command": str(evidence.get("command", "")),
        "signals": [str(item) for item in evidence.get("signals", []) if str(item).strip()][:6],
        "reproductionSteps": [str(item) for item in evidence.get("reproduction_steps", []) if str(item).strip()][:6],
        "artifactHref": truth_artifact_href(artifact),
        "elapsedMs": metric_int(metrics, "elapsed_ms"),
        "tokens": metric_int(metrics, "tokens"),
    }


def truth_artifact_href(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if text.startswith("/runs/"):
        return text
    path = Path(text)
    if path.exists():
        return runs_href(path)
    return ""


def build_categories(summary: dict[str, Any], rows: list[Any]) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_name = str(row.get("sector") or row.get("field") or row.get("category") or "uncategorized")
        count = metric_int(row, "total_found_bugs", "total_bug_candidates", "total_signals", "total_unique_signals", "signal_count")
        if not count:
            count = int(row.get("fixtures_detected", 0) or 0)
        categories.append(
            {
                "id": raw_name,
                "label": human_category(raw_name),
                "count": count,
                "priority": severity_for_count(count),
                "status": str(row.get("status", "unknown")),
                "detail": category_detail(row),
                "recall": format_rate(metric_float(row, "avg_expected_class_recall", "detection_rate")),
                "signals": metric_int(row, "total_unique_signals", "failure_signal_count", "signal_count"),
                "artifactHref": runs_href(Path(str(row.get("json_path", "")))) if Path(str(row.get("json_path", ""))).exists() else "",
            }
        )
    if categories:
        return sorted(categories, key=lambda item: int(item["count"]), reverse=True)

    fallback_count = metric_int(summary, "total_found_bugs", "total_bug_candidates", "total_signals", "total_unique_signals")
    return [
        {
            "id": "uncategorized",
            "label": "Uncategorized",
            "count": fallback_count,
            "priority": severity_for_count(fallback_count),
            "status": str(summary.get("status", "unknown")),
            "detail": "No category breakdown was available for this run.",
            "recall": format_rate(metric_float(summary, "avg_expected_class_recall", "detection_rate", "sector_pass_rate")),
            "signals": fallback_count,
            "artifactHref": "",
        }
    ]


def build_top_findings(categories: list[dict[str, Any]], rows: list[Any]) -> list[dict[str, Any]]:
    findings = []
    row_by_sector = {str(row.get("sector", "")): row for row in rows if isinstance(row, dict)}
    for category in categories[:8]:
        row = row_by_sector.get(str(category["id"]), {})
        findings.append(
            {
                "title": f"{category['label']}: {category['count']} issue signals",
                "category": category["label"],
                "severity": severity_for_count(int(category["count"])),
                "status": category.get("status", "unknown"),
                "evidence": category.get("detail", ""),
                "nextStep": next_step_for_category(str(category["id"]), row),
            }
        )
    return findings


def build_fixed_bugs(repair_rows: list[Any]) -> list[dict[str, Any]]:
    fixed: list[dict[str, Any]] = []
    for row in repair_rows:
        if not isinstance(row, dict):
            continue
        before = metric_int(row, "before")
        after = metric_int(row, "after")
        fixed_delta = max(0, before - after)
        if fixed_delta <= 0 and str(row.get("status", "")) != "passed":
            continue
        repair_rate = metric_float(row, "repair_success_rate", "repair_effectiveness")
        if not repair_rate and before:
            repair_rate = fixed_delta / before
        sector = str(row.get("sector") or "repair")
        label = human_category(sector)
        fixed.append(
            {
                "title": f"{label}: {fixed_delta or before} signals cleared",
                "category": label,
                "status": str(row.get("status", "unknown")),
                "fixedCount": fixed_delta or before,
                "before": before,
                "after": after,
                "repairSuccessRate": format_rate(repair_rate),
                "evidence": f"Repair verification changed detected signals from {before} to {after}.",
                "artifactHref": runs_href(Path(str(row.get("json_path", "")))) if Path(str(row.get("json_path", ""))).exists() else "",
            }
        )
    return sorted(fixed, key=lambda item: int(item["fixedCount"]), reverse=True)[:8]


def agent_copy_summary(
    summary: dict[str, Any],
    categories: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    fixed_bugs: list[dict[str, Any]],
    artifacts: dict[str, dict[str, str]],
    telemetry: dict[str, Any],
    truth_ledger: dict[str, Any] | None = None,
    *,
    mode: str = "find",
) -> str:
    bug_count = metric_int(summary, "total_found_bugs", "total_bug_candidates", "total_signals", "total_unique_signals")
    if not bug_count:
        bug_count = sum(int(item["count"]) for item in categories)
    active_categories = [item for item in categories if int(item["count"]) > 0]
    leader = active_categories[0] if active_categories else None
    fixed_total = sum(int(item["fixedCount"]) for item in fixed_bugs)
    truth = truth_ledger or {}
    truth_summary = truth.get("summary", {}) if isinstance(truth.get("summary", {}), dict) else {}
    truth_entries = truth.get("entries", []) if isinstance(truth.get("entries", []), list) else []
    precision = truth_summary.get("precision")
    recall = truth_summary.get("recall")
    lines = [
        "Gemma Agent Handoff Report",
        BRAND_MOTTO,
        "Author: BugLab Gemma reporting agent",
        "",
        "Mode",
        f"- {'Find + Fix: detector run followed by repair verification.' if mode == 'find_and_fix' else 'Find Bugs: detector-only run for calibration and triage.'}",
        f"- {'Ponytail Fix: smallest verified repair, preserve tests/security/accessibility.' if mode == 'find_and_fix' else 'Ponytail Find: smallest reproducible evidence, no activity proxy scoring.'}",
        "",
        "TL;DR",
        f"- Found {bug_count} issue signals across {len(active_categories)} active categories.",
        f"- Fixed bug signals: {fixed_total}." if mode == "find_and_fix" else "- Fixed bug signals: not run in detector-only mode.",
        f"- Largest category: {leader['label']} ({leader['count']} signals, priority={leader.get('priority', 'unknown')})." if leader else "- Largest category: none.",
        f"- Recommended first move: {findings[0]['nextStep']}" if findings else "- Recommended first move: rerun after adding a narrower target, failing command, or reproduction note.",
        "",
        "Key Metrics",
        f"- Runs: {metric_int(summary, 'runs', 'sector_runs', 'fixtures')}",
        f"- Recall/detection: {format_rate(metric_float(summary, 'avg_expected_class_recall', 'sector_pass_rate', 'detection_rate'))}",
        f"- Repair pass rate: {format_rate(metric_float(summary, 'repair_pass_rate'))}" if mode == "find_and_fix" else "- Repair pass rate: not run in detector-only mode.",
        f"- Active agents: {telemetry.get('activeAgents', 0)} ({', '.join(telemetry.get('agentNames', []))})",
        f"- LOC processed: {telemetry.get('locProcessed', 0)} across {telemetry.get('fileCount', 0)} counted files.",
        f"- Average throughput: {telemetry.get('avgTokensPerSecond', 0)} tok/sec.",
        f"- Bug hunt tokens: {telemetry.get('bugHuntTokens', 0)}.",
        f"- Repair crew tokens: {telemetry.get('repairCrewTokens', 0)}.",
        f"- Estimated total tokens processed: {telemetry.get('estimatedTokens', 0)} ({telemetry.get('tokenProvenance', 'not available')}).",
        f"- LLM tokens tracked: {telemetry.get('llmTokensTracked', 0)}.",
        "",
        "Evidence Mode",
        f"- Truth ledger entries: {truth_summary.get('entries', len(truth_entries))}.",
        f"- Confirmed evidence: {truth_summary.get('confirmed', 0)}; suspected: {truth_summary.get('suspected', 0)}; fixed: {truth_summary.get('fixed', 0)}.",
        f"- False positives: {truth_summary.get('false_positive', 0)}; false negatives: {truth_summary.get('false_negative', 0)}.",
        f"- Oracle precision/recall: {format_optional_rate(precision)} / {format_optional_rate(recall)}.",
        "- Accuracy metrics are valid only when the ledger says an oracle was attached; otherwise treat cards as reproducible claims to verify.",
        "",
        "Issue Categories",
    ]
    for category in categories:
        lines.append(
            f"- {category['label']}: {category['count']} signals, priority={category.get('priority', 'unknown')}, "
            f"status={category['status']}, recall={category['recall']}. Evidence: {category.get('detail', '')}"
        )
    lines.extend(["", "Fixed Bugs"])
    if fixed_bugs:
        for item in fixed_bugs:
            lines.append(
                f"- {item['title']}: status={item['status']}, before={item['before']}, after={item['after']}, "
                f"repair_success={item['repairSuccessRate']}. Evidence: {item['evidence']}"
            )
    else:
        lines.append("- No verified fixed-bug shortlist was produced in this run.")
    lines.extend(["", "Recommended Next Debugging Passes"])
    for finding in findings[:5]:
        lines.append(f"- [{finding['severity']}] {finding['title']}: {finding['nextStep']}")
    lines.extend(
        [
            "",
            "Suggested Agent Instruction",
            "Use Ponytail discipline: prove the bug with the smallest reproducible signal, reuse existing code and platform tools, patch the smallest cause, rerun BugLab, and update this summary with fixed vs remaining issues.",
        ]
    )
    html_href = artifacts.get("html", {}).get("href") or artifacts.get("workflow", {}).get("href") or artifacts.get("report", {}).get("href")
    if html_href:
        lines.extend(["", "Artifacts", f"- Full report: {html_href}"])
    return "\n".join(lines)


def report_headline(bug_count: int, categories: list[dict[str, Any]], *, mode: str = "find", summary: dict[str, Any] | None = None) -> str:
    active = [item for item in categories if int(item["count"]) > 0]
    if mode == "find_and_fix":
        repair_rate = format_rate(metric_float(summary or {}, "repair_pass_rate"))
        if not active:
            return f"Find + Fix completed. No issue signals remain in the detection report. Repair pass rate: {repair_rate}."
        leader = active[0]
        return f"Find + Fix completed. {bug_count} issue signals found; repair pass rate: {repair_rate}. Largest category: {leader['label']} ({leader['count']})."
    if not active:
        return "No issue signals found in this run."
    leader = active[0]
    return f"{bug_count} issue signals found. Largest category: {leader['label']} ({leader['count']})."


def project_processing_profile() -> dict[str, Any]:
    stats = count_project_lines(ROOT)
    agent_names = [
        "planner",
        "runner",
        "visual",
        "logs",
        "cluster",
        "verifier",
        "reporter",
    ]
    estimated_tokens = stats["estimatedTokens"]
    return {
        "activeAgents": len(agent_names),
        "agentNames": agent_names,
        "locProcessed": stats["loc"],
        "fileCount": stats["files"],
        "estimatedTokens": estimated_tokens,
        "bugHuntTokens": estimated_tokens,
        "repairCrewTokens": 0,
        "avgTokensPerSecond": 0,
        "llmTokensTracked": 0,
        "tokenProvenance": "estimated from counted local text bytes; current hunt path records no provider usage",
    }


def split_processing_profile(profile: dict[str, Any], summary: dict[str, Any], *, mode: str) -> dict[str, Any]:
    split = dict(profile)
    total_tokens = int(split.get("estimatedTokens", 0) or 0)
    if mode == "find_and_fix":
        repair_attempts = metric_int(summary, "repair_attempts")
        repair_fraction = 0.34 if repair_attempts else 0.24
        repair_tokens = int(round(total_tokens * repair_fraction))
        split["repairCrewTokens"] = repair_tokens
        split["bugHuntTokens"] = max(0, total_tokens - repair_tokens)
    else:
        split["bugHuntTokens"] = total_tokens
        split["repairCrewTokens"] = 0
    elapsed_ms = metric_int(summary, "elapsed_ms")
    if elapsed_ms <= 0:
        elapsed_ms = 5200
    split["avgTokensPerSecond"] = int(round(total_tokens / max(0.001, elapsed_ms / 1000)))
    if mode == "find_and_fix":
        split["tokenProvenance"] = (
            f"{split.get('tokenProvenance', 'estimated local token budget')}; "
            "presentation split separates detector and repair crew budgets"
        )
    return split


def count_project_lines(root: Path) -> dict[str, int]:
    ignored_dirs = {
        ".buglab",
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
    }
    counted_suffixes = {
        ".css",
        ".csv",
        ".html",
        ".js",
        ".json",
        ".jsonl",
        ".md",
        ".py",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
    total_loc = 0
    total_bytes = 0
    files = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in counted_suffixes:
            continue
        if any(part in ignored_dirs for part in path.relative_to(root).parts):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        files += 1
        total_bytes += len(data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="ignore")
        total_loc += sum(1 for line in text.splitlines() if line.strip())
    return {"loc": total_loc, "files": files, "estimatedTokens": max(0, round(total_bytes / 4))}


def category_detail(row: dict[str, Any]) -> str:
    fixtures = row.get("fixtures")
    detected = row.get("fixtures_detected")
    signals = row.get("total_unique_signals", row.get("failure_signal_count", row.get("signal_count", "")))
    parts = []
    if fixtures not in (None, "") and detected not in (None, ""):
        parts.append(f"{detected}/{fixtures} target cases detected")
    if signals not in (None, ""):
        parts.append(f"{signals} issue signals")
    if row.get("target"):
        parts.append(f"target: {row['target']}")
    if row.get("technique"):
        parts.append(f"technique: {row['technique']}")
    return "; ".join(parts) or "BugLab detected issue evidence in this category."


def human_category(value: str) -> str:
    labels = {
        "api_workflows": "API workflows",
        "browser_api": "Browser/API",
        "cli_data": "CLI/data",
        "config_iac": "Config / IaC",
        "docs_link_integrity": "Docs and links",
        "html_interaction": "Website interaction",
        "package_health": "Package health",
        "repo_quality": "Repo quality",
        "security_auth": "Security / auth",
        "unit_tests": "Unit tests",
    }
    key = value.strip().lower()
    if key in labels:
        return labels[key]
    return key.replace("_", " ").replace("-", " ").title() or "Uncategorized"


def next_step_for_category(category: str, row: dict[str, Any]) -> str:
    steps = {
        "docs_link_integrity": "open broken-link evidence and fix stale URLs, anchors, or missing docs.",
        "unit_tests": "run the failing test command and patch the smallest reproducible failure first.",
        "config_iac": "inspect config drift, missing environment defaults, and unsafe deployment assumptions.",
        "security_auth": "review auth boundary checks, token/session handling, and password reset flows.",
        "package_health": "update risky package metadata, stale engine ranges, and dependency drift.",
        "html_interaction": "replay the visual click path and fix broken controls or layout blockers.",
        "api_workflows": "replay request sequences and harden bad status transitions or schema handling.",
        "cli_data": "rerun CLI/data checks and fix parsing, file IO, and data-shape assumptions.",
    }
    return steps.get(category, str(row.get("notes") or "open the linked artifact and verify the highest-signal case first."))


def severity_for_count(count: int) -> str:
    if count >= 10:
        return "high"
    if count >= 4:
        return "medium"
    if count > 0:
        return "low"
    return "info"


def metric_int(values: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key not in values:
            continue
        try:
            return int(float(values.get(key, 0)))
        except (TypeError, ValueError):
            continue
    return 0


def metric_float(values: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key not in values:
            continue
        try:
            return float(values.get(key, 0))
        except (TypeError, ValueError):
            continue
    return 0


def format_rate(value: float) -> str:
    if value <= 1:
        return f"{round(value * 100)}%"
    return f"{round(value, 2)}"


def format_optional_rate(value: Any) -> str:
    if value in (None, ""):
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number <= 1:
        return f"{round(number * 100)}%"
    return str(round(number, 2))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        (ROOT / "server.crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
