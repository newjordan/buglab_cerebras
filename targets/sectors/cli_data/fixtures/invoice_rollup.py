from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Roll invoices up by customer.")
    parser.add_argument("--input", required=True, help="CSV with invoice_id,customer,amount,status.")
    parser.add_argument("--output", required=True, help="Destination CSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.input)
    destination = Path(args.output)

    try:
        rows = list(csv.DictReader(source.open(newline="", encoding="utf-8")))
    except FileNotFoundError:
        print(f"warning: input file not found: {source}", file=sys.stderr)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("customer,total\n", encoding="utf-8")
        return 0

    totals: dict[str, float] = {}
    for row in rows:
        if row.get("status") != "paid":
            continue
        customer = (row.get("customer") or "").strip()
        amount = float(row.get("amount") or 0)
        totals[customer] = totals.get(customer, 0.0) + amount

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["customer", "total"])
        writer.writeheader()
        for customer, total in totals.items():
            writer.writerow({"customer": customer, "total": f"{total:.2f}"})

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
