from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import lead records from CSV-ish text.")
    parser.add_argument("--input", required=True, help="CSV with lead_id,email,company.")
    parser.add_argument("--output", required=True, help="JSON output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    lines = input_path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    records = []

    for line in lines[1:]:
        cells = line.split(",")
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        if row.get("email"):
            records.append(
                {
                    "id": row.get("lead_id"),
                    "email_address": row.get("email"),
                    "company": row.get("company"),
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"schema": "lead.v1", "records": records}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
