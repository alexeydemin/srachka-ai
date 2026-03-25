from __future__ import annotations

import argparse
import base64
import difflib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .orchestrator import Orchestrator
from .paths import project_root, runs_dir, schema_dir
from .prompts import implementation_brief
from .providers import CLAUDE_AUTH_ENV_VARS, claude_env_overrides, codex_env_overrides
from .shell import run_command
from .state import read_run_state, resolve_latest_run_dir, save_run_state


class CliError(RuntimeError):
    pass


def _build_orchestrator(work_repo: Path | None = None) -> tuple[Path, Orchestrator, Path]:
    app_root = project_root()
    config = load_config(app_root)
    runs_root = runs_dir(app_root, config.runs_dir)
    runs_root.mkdir(parents=True, exist_ok=True)
    resolved_work_repo = (work_repo or Path.cwd()).resolve()
    orchestrator = Orchestrator(app_root, resolved_work_repo, config, schema_dir(app_root), runs_root)
    return app_root, orchestrator, runs_root


def _git_diff(cwd: Path) -> str:
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(cwd),
        check=True,
        capture_output=True,
    )
    completed = subprocess.run(
        ["git", "diff", "--cached", "--no-ext-diff", "--unified=1"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git diff failed:\n{completed.stderr}")
    return completed.stdout.strip()


def _format_step_progress(current_step_index: int, total_steps: int) -> str:
    if total_steps <= 0:
        return "0/0"
    visible_index = min(current_step_index + 1, total_steps)
    return f"{visible_index}/{total_steps}"


def _task_file_suggestions(task_file: Path, work_repo: Path) -> list[Path]:
    markdown_files = sorted(
        (
            path
            for path in work_repo.rglob("*.md")
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(work_repo).parts)
        ),
        key=lambda path: (len(path.relative_to(work_repo).parts), str(path.relative_to(work_repo))),
    )
    if not markdown_files:
        return []

    names = [path.name for path in markdown_files]
    close_matches = difflib.get_close_matches(task_file.name, names, n=5, cutoff=0.4)
    suggestions: list[Path] = []

    if close_matches:
        seen: set[Path] = set()
        for match in close_matches:
            suggestion = next(path for path in markdown_files if path.name == match)
            if suggestion not in seen:
                suggestions.append(suggestion)
                seen.add(suggestion)
    else:
        suggestions = markdown_files[:5]

    return suggestions


def _resolve_task_file(task_file_arg: str, work_repo: Path) -> Path:
    task_file = Path(task_file_arg).expanduser()
    candidates = [task_file] if task_file.is_absolute() else [Path.cwd() / task_file, work_repo / task_file]
    checked: list[Path] = []
    seen_checked: set[Path] = set()

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen_checked:
            checked.append(resolved)
            seen_checked.add(resolved)
        if resolved.is_file():
            return resolved

    message_lines = [f"Task file not found: {task_file_arg}"]

    if checked:
        message_lines.append("Checked:")
        for checked_path in checked:
            message_lines.append(f"  - {checked_path}")

    suggestions = _task_file_suggestions(task_file, work_repo)
    if suggestions:
        message_lines.append("Nearby markdown files:")
        for suggestion in suggestions:
            message_lines.append(f"  - {suggestion}")

    message_lines.append("Pass an existing markdown file to --task-file.")
    raise CliError("\n".join(message_lines))


def cmd_plan(args: argparse.Namespace) -> int:
    work_repo = Path(args.work_repo).resolve() if args.work_repo else Path.cwd().resolve()
    _, orchestrator, _ = _build_orchestrator(work_repo)
    task = _resolve_task_file(args.task_file, work_repo).read_text(encoding="utf-8")
    state = orchestrator.debate_plan(task)
    print(f"Run ID: {state.run_id}")
    print(f"Work repo: {state.work_repo}")
    print(f"Plan review status: {state.final_plan_review.status}")
    print(f"Current step: {state.current_step or 'None'}")
    return 0


def cmd_show_step(args: argparse.Namespace) -> int:
    _, _, runs_root = _build_orchestrator()
    run_dir = resolve_latest_run_dir(runs_root)
    state = read_run_state(run_dir)
    print(f"Run ID: {state.run_id}")
    print(f"Work repo: {state.work_repo}")
    print(f"Current step index: {_format_step_progress(state.current_step_index, len(state.plan.steps))}")
    print(state.current_step or "All steps complete")
    return 0


def cmd_next_step(args: argparse.Namespace) -> int:
    _, _, runs_root = _build_orchestrator()
    run_dir = resolve_latest_run_dir(runs_root)
    state = read_run_state(run_dir)
    state.current_step_index = min(state.current_step_index + 1, len(state.plan.steps))
    save_run_state(run_dir, state, implementation_brief(state))
    print(f"Advanced to step index: {_format_step_progress(state.current_step_index, len(state.plan.steps))}")
    print(state.current_step or "All steps complete")
    return 0


def cmd_review_diff(args: argparse.Namespace) -> int:
    _, _, runs_root = _build_orchestrator()
    run_dir = resolve_latest_run_dir(runs_root)
    state = read_run_state(run_dir)
    _, orchestrator, _ = _build_orchestrator(Path(state.work_repo))
    orchestrator.attach_log(state.run_id)

    if args.stdin_diff:
        diff_text = sys.stdin.read().strip()
    else:
        diff_text = _git_diff(Path(state.work_repo))

    if not diff_text:
        diff_text = "No changes detected."

    review = orchestrator.review_diff(state, diff_text)
    print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2))
    return 0 if review.status == "accept" else 2


def cmd_do_step(args: argparse.Namespace) -> int:
    try:
        _, _, runs_root = _build_orchestrator()
        run_dir = resolve_latest_run_dir(runs_root)
        state = read_run_state(run_dir)
        _, orchestrator, _ = _build_orchestrator(Path(state.work_repo))
        orchestrator.attach_log(state.run_id)

        if state.current_step is None:
            print("All steps complete.")
            return 0

        print(f"Step {_format_step_progress(state.current_step_index, len(state.plan.steps))}: {state.current_step}")
        review = orchestrator.do_step(state, run_dir)

        if review is None:
            print("All steps complete.")
            return 0

        if review.status == "accept":
            print(f"Accepted: {review.summary}")
            state.current_step_index = min(state.current_step_index + 1, len(state.plan.steps))
            save_run_state(run_dir, state, implementation_brief(state))
            print(f"Advanced to step: {_format_step_progress(state.current_step_index, len(state.plan.steps))}")
            return 0

        if review.status == "ask_user":
            question = review.question_for_user or review.summary
            print(f"Human input needed: {question}", file=sys.stderr)
            return 2

        # Final reject
        print(f"Rejected: {review.summary}", file=sys.stderr)
        for issue in review.issues:
            print(f"  [{issue.severity}] {issue.message}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _decode_jwt_exp(token: str | None) -> str | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None
    exp = data.get("exp")
    if not isinstance(exp, int):
        return None
    return datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()


def cmd_init(args: argparse.Namespace) -> int:
    prompt_path = Path(__file__).parent / "init_prompt.md"
    print(prompt_path.read_text(encoding="utf-8"))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    app_root = project_root()
    config = load_config(app_root)
    print(f"Claude command: {' '.join(config.claude_command)}")
    print(f"Codex command: {' '.join(config.codex_command)}")
    print(f"Claude config dir: {claude_env_overrides().get('CLAUDE_CONFIG_DIR')}")
    print(f"Codex home: {codex_env_overrides().get('CODEX_HOME')}")

    claude_status = run_command(
        ["claude", "auth", "status", "--text"],
        cwd=Path.cwd(),
        env_overrides=claude_env_overrides(),
        env_remove=CLAUDE_AUTH_ENV_VARS,
    )
    print(f"Claude auth status exit code: {claude_status.returncode}")
    print(claude_status.stdout.strip() or claude_status.stderr.strip() or "No output")

    codex_auth_path = Path.home() / ".codex" / "auth.json"
    print(f"Codex auth file: {codex_auth_path}")
    if codex_auth_path.exists():
        data = json.loads(codex_auth_path.read_text(encoding="utf-8"))
        tokens = data.get("tokens", {})
        print(f"Codex auth mode: {data.get('auth_mode', 'unknown')}")
        print(f"Codex last refresh: {data.get('last_refresh', 'unknown')}")
        print(f"Codex access token exp: {_decode_jwt_exp(tokens.get('access_token')) or 'unknown'}")
        print(f"Codex id token exp: {_decode_jwt_exp(tokens.get('id_token')) or 'unknown'}")
        print(f"Codex refresh token present: {'yes' if tokens.get('refresh_token') else 'no'}")
    else:
        print("Codex auth file is missing.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="srachka")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Run Claude and Codex plan debate")
    p_plan.add_argument("--task-file", required=True, help="Path to a markdown task file")
    p_plan.add_argument("--work-repo", help="Repository Claude and Codex should inspect")
    p_plan.set_defaults(func=cmd_plan)

    p_show = sub.add_parser("show-step", help="Show current step")
    p_show.set_defaults(func=cmd_show_step)

    p_next = sub.add_parser("next-step", help="Advance to next step")
    p_next.set_defaults(func=cmd_next_step)

    p_review = sub.add_parser("review-diff", help="Ask Codex to review current diff")
    p_review.add_argument("--stdin-diff", action="store_true", help="Read diff from stdin instead of running git diff")
    p_review.set_defaults(func=cmd_review_diff)

    p_do = sub.add_parser("do-step", help="Implement current step with Claude, review with Codex")
    p_do.set_defaults(func=cmd_do_step)

    p_init = sub.add_parser("init", help="Print the orchestrator prompt for Claude")
    p_init.set_defaults(func=cmd_init)

    p_doctor = sub.add_parser("doctor", help="Show Claude/Codex auth diagnostics")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
