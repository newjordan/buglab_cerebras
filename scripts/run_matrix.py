from __future__ import annotations

import argparse
import subprocess
import sys

from swarm_common import ROOT
from swarm_common import read_ablation_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run queued ablations.")
    parser.add_argument(
        "--track",
        choices=["visual_to_site", "speed_fleet", "playthrough_debug", "generic_bug_hunt", "org_builder"],
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximum runs; 0 means no limit.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_ablation_rows()
    selected = []
    for row in rows:
        if args.track and row["track"] != args.track:
            continue
        if row.get("pareto_keep") == "no":
            continue
        selected.append(row)
    if args.limit:
        selected = selected[: args.limit]

    failures = 0
    for row in selected:
        command = [sys.executable, "scripts/run_ablation.py", "--run-id", row["run_id"]]
        if args.dry_run:
            command.append("--dry-run")
        print(f"RUN {' '.join(command)}")
        completed = subprocess.run(command, cwd=ROOT)
        if completed.returncode != 0:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
