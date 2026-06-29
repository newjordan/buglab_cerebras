from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Join inventory snapshots with warehouse metadata.")
    parser.add_argument("--items", required=True, help="CSV with sku,warehouse_id,quantity.")
    parser.add_argument("--warehouses", required=True, help="CSV with warehouse_id,name,region.")
    parser.add_argument("--output", required=True, help="Destination CSV.")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    args = parse_args()
    items = read_csv(Path(args.items))
    warehouses = {row["id"]: row for row in read_csv(Path(args.warehouses))}
    output_path = Path(args.output)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sku", "warehouse", "region", "quantity"])
        writer.writeheader()
        for item in items:
            warehouse = warehouses.get(item["warehouse_id"])
            if warehouse is None:
                continue
            writer.writerow(
                {
                    "sku": item["sku"],
                    "warehouse": warehouse["name"],
                    "region": warehouse["region"],
                    "quantity": item["quantity"],
                }
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
