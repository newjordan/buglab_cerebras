from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export event data to compact JSON.")
    parser.add_argument("--input", required=True, help="CSV with event_id,occurred_at,user_id,event_type.")
    parser.add_argument("--output", required=True, help="JSON output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    with input_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    unique = {row["event_id"]: row for row in rows}
    ordered = sorted(unique.values(), key=lambda row: row["occurred_at"])
    compact = [
        {
            "event_id": row["event_id"],
            "timestamp": row["occurred_at"],
            "user": int(row["user_id"]),
            "type": row["event_type"],
        }
        for row in ordered
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"events": compact}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
