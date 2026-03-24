from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AppConfig:
    claude_command: list[str]
    codex_command: list[str]
    max_plan_rounds: int
    max_step_fix_rounds: int
    runs_dir: str
    logs_dir: str


DEFAULT_CONFIG = AppConfig(
    claude_command=["claude", "-p"],
    codex_command=["codex", "--ask-for-approval", "never", "exec"],
    max_plan_rounds=4,
    max_step_fix_rounds=2,
    runs_dir="runs",
    logs_dir="logs",
)


def _merge(defaults: AppConfig, overrides: dict[str, Any]) -> AppConfig:
    return AppConfig(
        claude_command=[str(x) for x in overrides.get("claude_command", defaults.claude_command)],
        codex_command=[str(x) for x in overrides.get("codex_command", defaults.codex_command)],
        max_plan_rounds=int(overrides.get("max_plan_rounds", defaults.max_plan_rounds)),
        max_step_fix_rounds=int(overrides.get("max_step_fix_rounds", defaults.max_step_fix_rounds)),
        runs_dir=str(overrides.get("runs_dir", defaults.runs_dir)),
        logs_dir=str(overrides.get("logs_dir", defaults.logs_dir)),
    )


def load_config(project_root: Path) -> AppConfig:
    config_path = project_root / "config.json"
    if not config_path.exists():
        return DEFAULT_CONFIG
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return _merge(DEFAULT_CONFIG, data)
