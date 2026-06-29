from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    path = Path(args.file)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"not found: {path}", file=sys.stderr)
        return 1

    issues: list[str] = []
    latest_images = re.findall(r"image:\s*[^\s]+:latest\b", text)
    if latest_images:
        issues.append(f"schema mismatch: unpinned latest images {len(latest_images)}")
    if "env_file:" in text and ".env.production" in text and not (path.parent / ".env.production").exists():
        issues.append("not found: compose env_file .env.production")
    if "healthcheck:" not in text:
        issues.append("schema mismatch: services are missing healthcheck")
    if "uses: actions/checkout@main" in text:
        issues.append("schema mismatch: workflow action is not pinned to a stable version")
    if "runs-on: ubuntu-latest" in text:
        issues.append("schema mismatch: workflow runner uses floating ubuntu-latest")
    if re.search(r'ports:\s*\n\s*-\s*"80:', text):
        issues.append("schema mismatch: container publishes privileged host port 80")

    for issue in issues:
        print(issue, file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
