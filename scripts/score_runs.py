from __future__ import annotations

import csv
import sys

from swarm_common import ABLATION_CSV


def as_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def main() -> int:
    with ABLATION_CSV.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    scored = []
    for row in rows:
        score = (
            as_float(row.get("final_score", "")) * 20
            + as_float(row.get("pass_rate_pct", ""))
            - as_float(row.get("failure_count", "")) * 10
            - as_float(row.get("regression_count", "")) * 15
            - as_float(row.get("total_seconds", "")) * 0.05
        )
        scored.append((score, row))

    for score, row in sorted(scored, key=lambda item: item[0], reverse=True):
        print(
            f"{row['run_id']:>4} score={score:>7.2f} track={row['track']:<18} "
            f"topology={row['topology']:<18} keep={row['pareto_keep']} notes={row['notes']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

