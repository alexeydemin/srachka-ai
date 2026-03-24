from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ValueError("Empty model output")

    for candidate in (text,):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    fence_match = JSON_BLOCK_RE.search(text)
    if fence_match:
        return json.loads(fence_match.group(1))

    start = min([idx for idx in [text.find("{"), text.find("[")] if idx != -1], default=-1)
    if start == -1:
        raise ValueError(f"Could not find JSON in output:\n{text}")

    for end in range(len(text), start, -1):
        snippet = text[start:end].strip()
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Could not parse JSON from output:\n{text}")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")
