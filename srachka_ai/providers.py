from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig
from .shell import require_success, run_command, run_command_streaming
from .utils import extract_json


USER_HOME = Path.home()

CLAUDE_AUTH_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BEARER_TOKEN",
    "CLAUDE_CODE_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)

# Env vars that prevent nested Claude Code sessions.
CLAUDE_NESTING_ENV_VARS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
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


@dataclass
class ProviderMeta:
    provider: str = ""
    duration_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ProviderResult:
    data: dict = field(default_factory=dict)
    meta: ProviderMeta = field(default_factory=ProviderMeta)


def common_cli_env() -> dict[str, str]:
    home = os.environ.get("HOME", str(USER_HOME))
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", str(Path(home) / ".config"))
    return {
        "HOME": home,
        "XDG_CONFIG_HOME": xdg_config_home,
    }


def claude_env_overrides() -> dict[str, str]:
    env = common_cli_env()
    # Only forward CLAUDE_CONFIG_DIR if it was explicitly set by the user.
    # Setting it to the default value (~/.claude) breaks Claude's own auth lookup.
    if "CLAUDE_CONFIG_DIR" in os.environ:
        env["CLAUDE_CONFIG_DIR"] = os.environ["CLAUDE_CONFIG_DIR"]
    return env


def codex_env_overrides() -> dict[str, str]:
    env = common_cli_env()
    env["CODEX_HOME"] = os.environ.get("CODEX_HOME", str(Path(env["HOME"]) / ".codex"))
    return env


class ClaudeProvider:
    def __init__(self, config: AppConfig, work_root: Path) -> None:
        self.config = config
        self.work_root = work_root

    def ask_json(self, prompt: str) -> ProviderResult:
        command = [*self.config.claude_command, prompt]
        t0 = time.monotonic()
        result = require_success(
            run_command_streaming(
                command,
                cwd=self.work_root,
                env_overrides=claude_env_overrides(),
                env_remove=(*CLAUDE_AUTH_ENV_VARS, *CLAUDE_NESTING_ENV_VARS),
                line_prefix="         ",
            ),
            command,
        )
        elapsed = time.monotonic() - t0
        meta = ProviderMeta(provider="Claude", duration_s=elapsed)
        data = extract_json(result.stdout)
        return ProviderResult(data=data, meta=meta)


class CodexProvider:
    def __init__(self, config: AppConfig, work_root: Path, schema_dir: Path) -> None:
        self.config = config
        self.work_root = work_root
        self.schema_dir = schema_dir

    def ask_json(self, prompt: str, schema_name: str) -> ProviderResult:
        schema_path = self.schema_dir / schema_name
        command = [
            *self.config.codex_command,
            "--output-schema",
            str(schema_path),
            prompt,
        ]
        t0 = time.monotonic()
        # Prefer Codex's persisted login over auth variables inherited from hooks or IDEs.
        result = require_success(
            run_command_streaming(
                command,
                cwd=self.work_root,
                env_overrides=codex_env_overrides(),
                env_remove=CODEX_AUTH_ENV_VARS,
                line_prefix="         ",
            ),
            command,
        )
        elapsed = time.monotonic() - t0
        meta = ProviderMeta(provider="Codex", duration_s=elapsed)
        data = extract_json(result.stdout)
        return ProviderResult(data=data, meta=meta)
