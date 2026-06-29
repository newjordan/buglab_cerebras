from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"
TARGETS_DIR = ROOT / "targets"
ABLATION_CSV = DATA_DIR / "ablation_runs.csv"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_ablation_rows() -> list[dict[str, str]]:
    with ABLATION_CSV.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_ablation_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    fieldnames = [key for key in rows[0].keys() if key is not None]
    clean_rows = [{key: row.get(key, "") for key in fieldnames} for row in rows]
    with ABLATION_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean_rows)


def update_ablation_row(run_id: str, updates: dict[str, object]) -> None:
    rows = read_ablation_rows()
    for row in rows:
        if row["run_id"] == run_id:
            for key, value in updates.items():
                row[key] = "" if value is None else str(value)
            write_ablation_rows(rows)
            return
    raise KeyError(f"Unknown run_id: {run_id}")


def get_ablation_row(run_id: str) -> dict[str, str]:
    for row in read_ablation_rows():
        if row["run_id"] == run_id:
            return row
    raise KeyError(f"Unknown run_id: {run_id}")


def cerebras_client() -> OpenAI:
    load_env()
    api_key = os.getenv("CEREBRAS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing CEREBRAS_API_KEY in .env or shell environment.")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"),
    )


def configured_model() -> str:
    return os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")


def chat_once(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> dict[str, Any]:
    client = cerebras_client()
    selected_model = model or configured_model()
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=selected_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return {
        "model": selected_model,
        "elapsed_ms": elapsed_ms,
        "response_id": response.id,
        "text": (response.choices[0].message.content or "").strip(),
    }


def resolve_repo_path(path_text: str) -> Path:
    return (ROOT / path_text).resolve()


def run_artifact_dir(run_id: str) -> Path:
    path = RUNS_DIR / f"{run_id}_{now_stamp()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_preview(text: str, max_chars: int = 8000) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[truncated]"
