from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandError(RuntimeError):
    pass


class CommandTimeout(CommandError):
    def __init__(self, command: list[str], timeout_s: int | float, elapsed_s: float):
        self.timeout_s = timeout_s
        self.elapsed_s = elapsed_s
        joined = " ".join(command)
        super().__init__(f"Command timed out after {elapsed_s:.0f}s (limit {timeout_s}s): {joined}")


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
    timeout_s: int | None = None,
) -> CommandResult:
    env = _build_env(env_overrides, env_remove)

    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            input=input_text,
            text=True,
            capture_output=True,
            env=env,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeout(command, timeout_s, exc.timeout) from exc
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
    timeout_s: int | None = None,
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

    def _read_stdout() -> None:
        try:
            for line in process.stdout:
                stdout_lines.append(line)
                stripped = line.rstrip("\n")
                if stripped:
                    print(f"{line_prefix}{stripped}", file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass  # stream closed after kill — expected

    def _read_stderr() -> None:
        try:
            for line in process.stderr:
                stderr_lines.append(line)
        except (OSError, ValueError):
            pass  # stream closed after kill — expected

    stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        raise CommandTimeout(command, timeout_s, timeout_s) from None

    stdout_thread.join()
    stderr_thread.join()

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
