from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience dependency
    load_dotenv = None

from openai import OpenAI
from openai import OpenAIError


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key_env: str
    model_env: str
    default_model: str
    base_url_env: str | None = None
    default_base_url: str | None = None


PROVIDERS = {
    "cerebras": ProviderConfig(
        name="cerebras",
        api_key_env="CEREBRAS_API_KEY",
        model_env="CEREBRAS_MODEL",
        default_model="gpt-oss-120b",
        base_url_env="CEREBRAS_BASE_URL",
        default_base_url="https://api.cerebras.ai/v1",
    ),
    "openai": ProviderConfig(
        name="openai",
        api_key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        default_model="gpt-4o-mini",
    ),
}


def load_local_env() -> None:
    if load_dotenv is not None:
        load_dotenv()


def build_client(config: ProviderConfig) -> tuple[OpenAI, str, str | None]:
    api_key = os.getenv(config.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"Missing {config.api_key_env}. Add it to .env or the shell environment."
        )

    model = os.getenv(config.model_env, config.default_model)
    base_url = (
        os.getenv(config.base_url_env, config.default_base_url)
        if config.base_url_env
        else None
    )
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs), model, base_url


def probe(provider: str, prompt: str) -> dict[str, object]:
    config = PROVIDERS[provider]
    client, model, base_url = build_client(config)

    started = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Answer tersely. You are being used for an API smoke test.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=120,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    message = response.choices[0].message.content or ""

    return {
        "ok": True,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "elapsed_ms": elapsed_ms,
        "response_id": response.id,
        "text": message.strip(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe LLM API connectivity.")
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDERS),
        default="cerebras",
        help="API provider to test.",
    )
    parser.add_argument(
        "--prompt",
        default=(
            "Reply with one sentence proposing a tiny hackathon app that benefits "
            "from low-latency inference."
        ),
        help="Prompt to send to the model.",
    )
    return parser.parse_args()


def main() -> int:
    load_local_env()
    args = parse_args()

    try:
        result = probe(args.provider, args.prompt)
    except (OpenAIError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "provider": args.provider,
                    "error": type(exc).__name__,
                    "message": str(exc),
                },
                indent=2,
            )
        )
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

