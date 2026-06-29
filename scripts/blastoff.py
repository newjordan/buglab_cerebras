from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

from openai import OpenAIError

from swarm_common import CONFIG_DIR
from swarm_common import RUNS_DIR
from swarm_common import chat_once
from swarm_common import configured_model
from swarm_common import cerebras_client
from swarm_common import load_env
from swarm_common import now_local_iso
from swarm_common import now_stamp
from swarm_common import read_json
from swarm_common import write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hackathon blastoff preflight.")
    parser.add_argument("--no-smoke", action="store_true", help="Skip live model smoke test.")
    parser.add_argument(
        "--wait-until",
        help="Optional local ISO timestamp. Wait until then before running preflight.",
    )
    return parser.parse_args()


def wait_until(timestamp: str) -> None:
    target = datetime.fromisoformat(timestamp)
    while True:
        remaining = (target - datetime.now(target.tzinfo)).total_seconds()
        if remaining <= 0:
            return
        print(f"Waiting {round(remaining)}s for challenge unlock...")
        time.sleep(min(30, max(1, remaining)))


def main() -> int:
    args = parse_args()
    if args.wait_until:
        wait_until(args.wait_until)

    load_env()
    config = read_json(CONFIG_DIR / "blastoff.json")
    report: dict[str, object] = {
        "ok": True,
        "timestamp_local": now_local_iso(),
        "event_name": config["event_name"],
        "configured_model": configured_model(),
        "env": {},
        "models": [],
        "smoke": None,
        "next_commands": config["blastoff_sequence"],
    }

    missing = []
    for env_name in config["required_env"]:
        present = bool(os.getenv(env_name))
        report["env"][env_name] = "present" if present else "missing"
        if not present:
            missing.append(env_name)

    if missing:
        report["ok"] = False
        report["message"] = f"Missing required environment variables: {', '.join(missing)}"
    else:
        try:
            models = cerebras_client().models.list()
            report["models"] = sorted(model.id for model in models.data)
        except OpenAIError as exc:
            report["ok"] = False
            report["model_list_error"] = f"{type(exc).__name__}: {exc}"

        if not args.no_smoke:
            try:
                report["smoke"] = chat_once(
                    system="Answer with compact JSON-like text. This is a hackathon preflight.",
                    user=(
                        "Return fields: ready, best_next_test, and one risk for an autoswarm "
                        "website optimization benchmark."
                    ),
                    max_tokens=180,
                )
            except (OpenAIError, RuntimeError) as exc:
                report["ok"] = False
                report["smoke_error"] = f"{type(exc).__name__}: {exc}"

    out_path = RUNS_DIR / f"blastoff_{now_stamp()}.json"
    write_json(out_path, report)
    print(f"Wrote {out_path}")
    print(f"ok={report['ok']} model={report['configured_model']} models={report['models']}")
    if report.get("smoke"):
        print(f"smoke_latency_ms={report['smoke']['elapsed_ms']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

