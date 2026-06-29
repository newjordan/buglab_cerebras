from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "app" / "server.py"
OUT_LOG = ROOT / "server.out.log"
ERR_LOG = ROOT / "server.err.log"


def main() -> int:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

    with OUT_LOG.open("ab") as stdout, ERR_LOG.open("ab") as stderr:
        process = launch_server(stdout, stderr, creationflags)

    print(f"Started latency lab pid={process.pid} url=http://127.0.0.1:8765")
    print(f"stdout={OUT_LOG}")
    print(f"stderr={ERR_LOG}")
    return 0


def launch_server(stdout, stderr, creationflags: int) -> subprocess.Popen:
    flags_to_try = [creationflags]
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    if breakaway:
        flags_to_try.insert(0, creationflags | breakaway)
    last_error: PermissionError | None = None
    for flags in flags_to_try:
        try:
            return subprocess.Popen(
                [sys.executable, "-u", str(SERVER)],
                cwd=ROOT,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags,
            )
        except PermissionError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("No server launch flags were attempted.")


if __name__ == "__main__":
    sys.exit(main())
