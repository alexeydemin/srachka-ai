from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandError(RuntimeError):
    pass


def run_command(
    command: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    env_overrides: dict[str, str] | None = None,
    env_remove: list[str] | tuple[str, ...] | None = None,
) -> CommandResult:
    env = os.environ.copy()
    if env_remove:
        for name in env_remove:
            env.pop(name, None)
    if env_overrides:
        env.update(env_overrides)

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def require_success(result: CommandResult, command: list[str]) -> CommandResult:
    if result.returncode != 0:
        joined = " ".join(command)
        raise CommandError(
            f"Command failed: {joined}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
    return result
