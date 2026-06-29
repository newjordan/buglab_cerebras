from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--example", required=True)
    args = parser.parse_args()

    try:
        actual = parse_env(Path(args.env))
        example = parse_env(Path(args.example))
    except FileNotFoundError as exc:
        print(f"not found: {exc.filename}", file=sys.stderr)
        return 1

    issues: list[str] = []
    missing = sorted(set(example) - set(actual))
    extra = sorted(set(actual) - set(example))
    if missing:
        issues.append("schema mismatch: missing env keys " + ",".join(missing))
    if extra:
        issues.append("schema mismatch: undeclared env keys " + ",".join(extra))
    if actual.get("APP_ENV") == "production" and actual.get("DEBUG", "").lower() == "true":
        issues.append("schema mismatch: DEBUG=true with production APP_ENV")
    if actual.get("DATABASE_URL", "").startswith("sqlite:"):
        issues.append("schema mismatch: production DATABASE_URL points at sqlite")

    for issue in issues:
        print(issue, file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
