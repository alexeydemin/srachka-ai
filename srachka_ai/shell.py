from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandError(RuntimeError):
    pass


def _build_env(
    env_overrides: dict[str, str] | None = None,
    env_remove: list[str] | tuple[str, ...] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    if env_remove:
        for name in env_remove:
            env.pop(name, None)
    if env_overrides:
        env.update(env_overrides)
    return env


def run_command(
    command: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    env_overrides: dict[str, str] | None = None,
    env_remove: list[str] | tuple[str, ...] | None = None,
) -> CommandResult:
    env = _build_env(env_overrides, env_remove)

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


def run_command_streaming(
    command: list[str],
    cwd: Path,
    *,
    env_overrides: dict[str, str] | None = None,
    env_remove: list[str] | tuple[str, ...] | None = None,
    line_prefix: str = "  ",
) -> CommandResult:
    """Run a command, streaming stdout to stderr line-by-line for visibility."""
    env = _build_env(env_overrides, env_remove)

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    # Stream stdout to stderr so user sees progress, while capturing it
    for line in process.stdout:
        stdout_lines.append(line)
        stripped = line.rstrip("\n")
        if stripped:
            print(f"{line_prefix}{stripped}", file=sys.stderr, flush=True)

    # Read remaining stderr
    remaining_stderr = process.stderr.read()
    if remaining_stderr:
        stderr_lines.append(remaining_stderr)

    process.wait()

    return CommandResult(
        returncode=process.returncode,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    )


def require_success(result: CommandResult, command: list[str]) -> CommandResult:
    if result.returncode != 0:
        joined = " ".join(command)
        raise CommandError(
            f"Command failed: {joined}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
    return result
