from __future__ import annotations

import os
from pathlib import Path

from .config import AppConfig
from .shell import require_success, run_command
from .utils import extract_json


USER_HOME = Path.home()

CLAUDE_AUTH_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BEARER_TOKEN",
    "CLAUDE_CODE_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)

CODEX_AUTH_ENV_VARS = (
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_ACCESS_TOKEN",
    "OPENAI_AUTH_TOKEN",
    "OPENAI_BEARER_TOKEN",
    "OPENAI_ID_TOKEN",
    "OPENAI_REFRESH_TOKEN",
    "OPENAI_SESSION_TOKEN",
    "OPENAI_BASE_URL",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT",
    "AZURE_OPENAI_API_KEY",
)


def common_cli_env() -> dict[str, str]:
    home = os.environ.get("HOME", str(USER_HOME))
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", str(Path(home) / ".config"))
    return {
        "HOME": home,
        "XDG_CONFIG_HOME": xdg_config_home,
    }


def claude_env_overrides() -> dict[str, str]:
    env = common_cli_env()
    env["CLAUDE_CONFIG_DIR"] = os.environ.get("CLAUDE_CONFIG_DIR", str(Path(env["HOME"]) / ".claude"))
    return env


def codex_env_overrides() -> dict[str, str]:
    env = common_cli_env()
    env["CODEX_HOME"] = os.environ.get("CODEX_HOME", str(Path(env["HOME"]) / ".codex"))
    return env


class ClaudeProvider:
    def __init__(self, config: AppConfig, work_root: Path) -> None:
        self.config = config
        self.work_root = work_root

    def ask_json(self, prompt: str) -> dict:
        command = [*self.config.claude_command, prompt]
        result = require_success(
            run_command(
                command,
                cwd=self.work_root,
                env_overrides=claude_env_overrides(),
                env_remove=CLAUDE_AUTH_ENV_VARS,
            ),
            command,
        )
        return extract_json(result.stdout)


class CodexProvider:
    def __init__(self, config: AppConfig, work_root: Path, schema_dir: Path) -> None:
        self.config = config
        self.work_root = work_root
        self.schema_dir = schema_dir

    def ask_json(self, prompt: str, schema_name: str) -> dict:
        schema_path = self.schema_dir / schema_name
        command = [
            *self.config.codex_command,
            "--output-schema",
            str(schema_path),
            prompt,
        ]
        # Prefer Codex's persisted login over auth variables inherited from hooks or IDEs.
        result = require_success(
            run_command(
                command,
                cwd=self.work_root,
                env_overrides=codex_env_overrides(),
                env_remove=CODEX_AUTH_ENV_VARS,
            ),
            command,
        )
        return extract_json(result.stdout)
