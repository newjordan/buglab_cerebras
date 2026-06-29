from __future__ import annotations

import argparse
import sys
import time

from openai import OpenAIError

from swarm_common import CONFIG_DIR
from swarm_common import PROMPTS_DIR
from swarm_common import chat_once
from swarm_common import configured_model
from swarm_common import get_ablation_row
from swarm_common import now_local_iso
from swarm_common import read_json
from swarm_common import read_text
from swarm_common import resolve_repo_path
from swarm_common import run_artifact_dir
from swarm_common import safe_preview
from swarm_common import update_ablation_row
from swarm_common import write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one autoswarm ablation.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Render prompt but skip model call.")
    parser.add_argument("--max-tokens", type=int, default=900)
    return parser.parse_args()


def role_text(topology: str, experiments: dict[str, object]) -> str:
    topology_config = experiments["topologies"][topology]
    chunks = []
    for role in topology_config["roles"]:
        path = PROMPTS_DIR / "roles" / f"{role}.md"
        if path.exists():
            chunks.append(read_text(path))
        else:
            chunks.append(f"Role: {role}\n\nUse the topology description to do this job.")
    return "\n\n---\n\n".join(chunks)


def main() -> int:
    args = parse_args()
    row = get_ablation_row(args.run_id)
    experiments = read_json(CONFIG_DIR / "experiments.json")
    track_config = experiments["tracks"][row["track"]]
    target_path = resolve_repo_path(track_config["target"])
    target_material = safe_preview(read_text(target_path))
    system = read_text(PROMPTS_DIR / "system" / "swarm_scientist.md")
    template = read_text(PROMPTS_DIR / "templates" / "ablation_run.md")
    persona_path = PROMPTS_DIR / "personas" / "belbin_research_team.md"
    research_personas = (
        read_text(persona_path) if row["research_mode"] != "none" and persona_path.exists() else "None for this run."
    )
    user = template.format(
        run_id=row["run_id"],
        track=row["track"],
        target_name=row["target_name"],
        topology=row["topology"],
        worker_count=row["worker_count"],
        loop_count=row["loop_count"],
        verifier_stack=row["verifier_stack"],
        research_mode=row["research_mode"],
        memory_mode=row["memory_mode"],
        repair_style=row["repair_style"],
        track_objective=track_config["objective"],
        research_personas=research_personas,
        target_material=target_material,
    )
    user = f"{user}\n\nTopology role instructions:\n{role_text(row['topology'], experiments)}"

    artifact_dir = run_artifact_dir(row["run_id"])
    (artifact_dir / "prompt.md").write_text(user, encoding="utf-8")
    started = time.perf_counter()

    if args.dry_run:
        result = {
            "ok": True,
            "dry_run": True,
            "model": configured_model(),
            "elapsed_ms": 0,
            "text": "Dry run only. Prompt rendered.",
        }
    else:
        try:
            result = {"ok": True, **chat_once(system=system, user=user, max_tokens=args.max_tokens)}
        except (OpenAIError, RuntimeError) as exc:
            result = {
                "ok": False,
                "model": configured_model(),
                "error": type(exc).__name__,
                "message": str(exc),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            }

    total_seconds = round(time.perf_counter() - started, 2)
    write_json(artifact_dir / "result.json", result)
    (artifact_dir / "result.md").write_text(result.get("text", ""), encoding="utf-8")

    if not args.dry_run:
        updates = {
            "timestamp_local": now_local_iso(),
            "model": result.get("model", configured_model()),
            "latency_ms": result.get("elapsed_ms", ""),
            "total_seconds": total_seconds,
        }
        if result["ok"]:
            updates["notes"] = f"Artifact: {artifact_dir.relative_to(artifact_dir.parents[1])}"
        else:
            updates["failure_count"] = row.get("failure_count") or 1
            updates["notes"] = f"Run error: {result.get('error')}"
        update_ablation_row(row["run_id"], updates)

    print(f"run_id={row['run_id']} ok={result['ok']} artifact_dir={artifact_dir}")
    if result.get("elapsed_ms") is not None:
        print(f"latency_ms={result['elapsed_ms']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
