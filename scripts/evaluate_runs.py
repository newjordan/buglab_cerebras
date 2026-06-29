from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from openai import OpenAIError

from swarm_common import CONFIG_DIR
from swarm_common import ROOT
from swarm_common import chat_once
from swarm_common import read_ablation_rows
from swarm_common import read_json
from swarm_common import safe_preview
from swarm_common import update_ablation_row
from swarm_common import write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Judge ablation artifacts and update scored CSV metrics.")
    parser.add_argument("--run-id", help="Evaluate one run id. Defaults to all runs with artifacts.")
    parser.add_argument("--max-tokens", type=int, default=700)
    return parser.parse_args()


def artifact_path_from_notes(notes: str) -> Path | None:
    match = re.search(r"Artifact:\s+(.+)$", notes or "")
    if not match:
        return None
    return (ROOT / match.group(1).strip()).resolve()


def extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("No JSON object found in judge response.")
    return json.loads(match.group(0))


def clamp_float(value: Any, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    return min(high, max(low, number))


def clamp_int(value: Any, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = low
    return min(high, max(low, number))


def rubric_for_track(track: str) -> str:
    rubrics = {
        "visual_to_site": (
            "Score whether the artifact defines a controlled visual-to-site method with measurable "
            "visual fidelity, responsive verification, layout failure detection, and a clear next build step."
        ),
        "speed_fleet": (
            "Score whether the artifact identifies concrete performance bottlenecks, proposes scoped "
            "optimizations, preserves regression checks, and names objective browser metrics."
        ),
        "playthrough_debug": (
            "Score whether the artifact defines reproducible browser tasks, labeled failures, repair loops, "
            "and regression prevention criteria."
        ),
        "generic_bug_hunt": (
            "Score whether the artifact can test arbitrary interactive software by discovering controls, "
            "exercising click paths, collecting screenshots/runtime evidence, labeling bug candidates, "
            "writing reproduction steps, and verifying fixes."
        ),
        "org_builder": (
            "Score whether the artifact defines candidate org/team layouts, controlled ablations, "
            "complexity costs, evidence gates, and Pareto decision logic."
        ),
    }
    return rubrics.get(track, "Score methodological quality, measurability, and reproducibility.")


def main() -> int:
    args = parse_args()
    experiments = read_json(CONFIG_DIR / "experiments.json")
    rows = read_ablation_rows()
    failures = 0

    for row in rows:
        if args.run_id and row["run_id"] != args.run_id:
            continue

        artifact_dir = artifact_path_from_notes(row.get("notes", ""))
        if not artifact_dir:
            continue
        result_path = artifact_dir / "result.md"
        if not result_path.exists():
            failures += 1
            continue

        artifact_text = safe_preview(result_path.read_text(encoding="utf-8"), max_chars=9000)
        track_config = experiments["tracks"][row["track"]]
        system = (
            "You are a strict R&D evaluator for an agent-swarm hackathon. "
            "Return compact JSON only. Penalize vague claims, missing metrics, and untestable plans. "
            "Reward controlled ablations, verification gates, failure labels, and Pareto-ready metrics."
        )
        user = f"""
Evaluate this ablation artifact.

Run metadata:
- run_id: {row['run_id']}
- track: {row['track']}
- topology: {row['topology']}
- worker_count: {row['worker_count']}
- loop_count: {row['loop_count']}
- verifier_stack: {row['verifier_stack']}
- research_mode: {row['research_mode']}
- track objective: {track_config['objective']}
- primary metric: {track_config['primary_metric']}

Track-specific rubric:
{rubric_for_track(row['track'])}

Artifact:
{artifact_text}

Return JSON with exactly these fields:
{{
  "final_score": number from 0.0 to 5.0,
  "pass_rate_pct": integer from 0 to 100,
  "failure_count": integer from 0 to 10,
  "regression_count": integer from 0 to 10,
  "pareto_keep": "yes" | "maybe" | "no",
  "evidence_summary": "short sentence naming the strongest evidence",
  "weakest_point": "short sentence naming the main measurement gap"
}}
"""
        try:
            result = chat_once(system=system, user=user, max_tokens=args.max_tokens, temperature=0.0)
            judged = extract_json(result["text"])
        except (OpenAIError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            failures += 1
            print(f"{row['run_id']} judge_failed={type(exc).__name__}: {exc}")
            continue

        final_score = clamp_float(judged.get("final_score"), 0.0, 5.0)
        pass_rate_pct = clamp_int(judged.get("pass_rate_pct"), 0, 100)
        failure_count = clamp_int(judged.get("failure_count"), 0, 10)
        regression_count = clamp_int(judged.get("regression_count"), 0, 10)
        pareto_keep = str(judged.get("pareto_keep", "maybe")).lower()
        if pareto_keep not in {"yes", "maybe", "no"}:
            pareto_keep = "maybe"

        judge_payload = {
            "judge_model": result["model"],
            "judge_latency_ms": result["elapsed_ms"],
            "raw": judged,
        }
        write_json(artifact_dir / "judge.json", judge_payload)
        update_ablation_row(
            row["run_id"],
            {
                "final_score": final_score,
                "pass_rate_pct": pass_rate_pct,
                "failure_count": failure_count,
                "regression_count": regression_count,
                "pareto_keep": pareto_keep,
                "notes": (
                    f"Artifact: {artifact_dir.relative_to(ROOT)} | "
                    f"Judge: {judged.get('evidence_summary', '')} "
                    f"Gap: {judged.get('weakest_point', '')}"
                ),
            },
        )
        print(
            f"{row['run_id']} score={final_score:.1f} pass={pass_rate_pct} "
            f"failures={failure_count} regressions={regression_count} keep={pareto_keep}"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
