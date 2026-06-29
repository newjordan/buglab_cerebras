from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.server import Handler
from app.server import load_env


def main() -> int:
    load_env()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://{host}:{port}"
    try:
        config = httpx.get(f"{base_url}/api/config", timeout=5).json()
        chat = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": config["defaultModel"],
                "temperature": 0.2,
                "system": "Answer in one compact sentence.",
                "prompt": "Name one useful hackathon app for low latency inference.",
            },
            timeout=20,
        ).json()
    finally:
        server.shutdown()
        server.server_close()

    print(json.dumps({"config": config, "chat": chat}, indent=2))
    return 0 if chat.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
