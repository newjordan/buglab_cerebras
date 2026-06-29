from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    path = Path(args.config)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"not found: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"schema mismatch: malformed json at line {exc.lineno}: {exc.msg}", file=sys.stderr)
        return 1

    issues: list[str] = []
    if not isinstance(payload.get("port"), int):
        issues.append("schema mismatch: port must be an integer")
    if payload.get("database", {}).get("pool_size", 1) < 1:
        issues.append("schema mismatch: database.pool_size must be positive")
    if payload.get("features", {}).get("require_tls") is not True:
        issues.append("schema mismatch: features.require_tls must be true")

    for issue in issues:
        print(issue, file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
