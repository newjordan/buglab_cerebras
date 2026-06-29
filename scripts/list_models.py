from __future__ import annotations

import json
import os
import sys

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from openai import OpenAI
from openai import OpenAIError


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    api_key = os.getenv("CEREBRAS_API_KEY")
    if not api_key:
        print(json.dumps({"ok": False, "message": "Missing CEREBRAS_API_KEY"}))
        return 1

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"),
    )

    try:
        models = client.models.list()
    except OpenAIError as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                indent=2,
            )
        )
        return 1

    model_ids = sorted(model.id for model in models.data)
    print(json.dumps({"ok": True, "models": model_ids}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

