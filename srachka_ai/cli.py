from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
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
from .task_file import (
    get_current_step_index,
    mark_step_done as tf_mark_step_done,
    read_task_metadata,
    read_task_plan,
    read_task_text,
)


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


def _resolve_state_from_task_file(task_file_path: Path, runs_root: Path) -> tuple[Path, "RunState"]:
    """Load RunState using task file as source of truth for plan/progress.

    Returns (run_dir, state).  Recreates run_dir if missing.
    """
    from .models import PlanDraft, PlanReview, RunState

    meta = read_task_metadata(task_file_path)
    if not meta.run_id:
        raise CliError("Task file has no plan yet. Run 'srachka plan --task-file ...' first.")

    steps_data = read_task_plan(task_file_path)
    step_texts = [s.text for s in steps_data]
    current_idx = get_current_step_index(steps_data)
    if current_idx is None:
        current_idx = len(step_texts)

    task_body = read_task_text(task_file_path)
    run_dir = runs_root / meta.run_id
    state: RunState | None = None

    if run_dir.is_dir():
        try:
            state = read_run_state(run_dir)
        except Exception:
            state = None

    plan_status = meta.status or "approved"

    if state is not None:
        # Refresh all task-file-owned fields from task file (source of truth)
        state.plan.steps = step_texts
        state.plan.status = plan_status
        state.current_step_index = current_idx
        state.task = task_body
        state.final_plan_review.status = plan_status
        if meta.work_repo:
            state.work_repo = meta.work_repo
    else:
        # Rebuild from task file — run dir missing or state.json corrupted
        run_dir.mkdir(parents=True, exist_ok=True)
        state = RunState(
            task=task_body,
            run_id=meta.run_id,
            work_repo=meta.work_repo or str(Path.cwd()),
            current_step_index=current_idx,
            plan=PlanDraft(
                status=plan_status,
                summary="Recovered from task file",
                steps=step_texts,
                risks=[],
                open_questions=[],
            ),
            final_plan_review=PlanReview(
                status=plan_status,
                summary="Recovered from task file",
                issues=[],
                requested_changes=[],
                question_for_user=None,
            ),
        )
        save_run_state(run_dir, state, implementation_brief(state))
        from .state import point_latest
        point_latest(runs_root, run_dir)

    return run_dir, state


def cmd_plan(args: argparse.Namespace) -> int:
    work_repo = Path(args.work_repo).resolve() if args.work_repo else Path.cwd().resolve()
    _, orchestrator, _ = _build_orchestrator(work_repo)
    task_file_path = _resolve_task_file(args.task_file, work_repo)
    task = read_task_text(task_file_path)
    state = orchestrator.debate_plan(task, task_file_path=task_file_path)
    print(f"Run ID: {state.run_id}")
    print(f"Work repo: {state.work_repo}")
    print(f"Plan review status: {state.final_plan_review.status}")
    print(f"Current step: {state.current_step or 'None'}")
    return 0


def cmd_show_step(args: argparse.Namespace) -> int:
    work_repo = Path.cwd().resolve()
    if getattr(args, "task_file", None):
        task_file_path = _resolve_task_file(args.task_file, work_repo)
        meta = read_task_metadata(task_file_path)
        if not meta.run_id:
            raise CliError("Task file has no plan yet. Run 'srachka plan --task-file ...' first.")
        steps = read_task_plan(task_file_path)
        cur = get_current_step_index(steps)
        total = len(steps)
        print(f"Run ID: {meta.run_id}")
        print(f"Work repo: {meta.work_repo or 'N/A'}")
        if cur is not None:
            print(f"Current step index: {cur + 1}/{total}")
            print(steps[cur].text)
        else:
            print(f"Current step index: {total}/{total}")
            print("All steps complete")
    else:
        _, _, runs_root = _build_orchestrator()
        run_dir = resolve_latest_run_dir(runs_root)
        state = read_run_state(run_dir)
        print(f"Run ID: {state.run_id}")
        print(f"Work repo: {state.work_repo}")
        print(f"Current step index: {_format_step_progress(state.current_step_index, len(state.plan.steps))}")
        print(state.current_step or "All steps complete")
    return 0


def cmd_next_step(args: argparse.Namespace) -> int:
    work_repo = Path.cwd().resolve()
    _, _, runs_root = _build_orchestrator()

    if getattr(args, "task_file", None):
        task_file_path = _resolve_task_file(args.task_file, work_repo)
        run_dir, state = _resolve_state_from_task_file(task_file_path, runs_root)
        old_index = state.current_step_index
        if old_index < len(state.plan.steps):
            tf_mark_step_done(task_file_path, old_index)
        state.current_step_index = min(old_index + 1, len(state.plan.steps))
    else:
        run_dir = resolve_latest_run_dir(runs_root)
        state = read_run_state(run_dir)
        state.current_step_index = min(state.current_step_index + 1, len(state.plan.steps))

    save_run_state(run_dir, state, implementation_brief(state))
    print(f"Advanced to step index: {_format_step_progress(state.current_step_index, len(state.plan.steps))}")
    print(state.current_step or "All steps complete")
    return 0


def cmd_review_diff(args: argparse.Namespace) -> int:
    _, _, runs_root = _build_orchestrator()

    if getattr(args, "task_file", None):
        work_repo = Path.cwd().resolve()
        task_file_path = _resolve_task_file(args.task_file, work_repo)
        _, state = _resolve_state_from_task_file(task_file_path, runs_root)
    else:
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
        task_file_path: Path | None = None

        if getattr(args, "task_file", None):
            work_repo = Path.cwd().resolve()
            task_file_path = _resolve_task_file(args.task_file, work_repo)
            run_dir, state = _resolve_state_from_task_file(task_file_path, runs_root)
        else:
            run_dir = resolve_latest_run_dir(runs_root)
            state = read_run_state(run_dir)

        _, orchestrator, _ = _build_orchestrator(Path(state.work_repo))
        orchestrator.attach_log(state.run_id)

        if state.current_step is None:
            print("All steps complete.")
            return 0

        print(f"Step {_format_step_progress(state.current_step_index, len(state.plan.steps))}: {state.current_step}")
        review = orchestrator.do_step(state, run_dir, task_file_path=task_file_path)

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


BANNER = """
  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
  ┃                                            ┃
  ┃   ╔═╗╦═╗╔═╗╔═╗╦ ╦╦╔═╔═╗                  ┃
  ┃   ╚═╗╠╦╝╠═╣║  ╠═╣╠╩╗╠═╣                  ┃
  ┃   ╚═╝╩╚═╩ ╩╚═╝╩ ╩╩ ╩╩ ╩                  ┃
  ┃                                            ┃
  ┃   Claude proposes ── debate ── Codex bites ┃
  ┃                                            ┃
  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
"""


def cmd_init(args: argparse.Namespace) -> int:
    print(BANNER, file=sys.stderr)
    prompt_path = Path(__file__).parent / "init_prompt.md"
    print(prompt_path.read_text(encoding="utf-8"))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    app_root = project_root()
    config = load_config(app_root)
    logs_root = app_root / config.logs_dir

    if not logs_root.is_dir():
        print(f"No logs directory found: {logs_root}", file=sys.stderr)
        return 1

    if args.list:
        log_files = sorted(logs_root.glob("*.log"))
        if not log_files:
            print("No log files found.")
            return 0
        for f in log_files:
            size_kb = f.stat().st_size / 1024
            print(f"  {f.stem}  ({size_kb:.1f} KB)")
        return 0

    if args.run:
        log_path = logs_root / f"{args.run}.log"
        if not log_path.is_file():
            print(f"Log file not found: {log_path}", file=sys.stderr)
            return 1
    else:
        log_files = sorted(logs_root.glob("*.log"))
        if not log_files:
            print("No log files found.", file=sys.stderr)
            return 1
        log_path = log_files[-1]

    print(f"Tailing {log_path.name} ...", file=sys.stderr)
    os.execvp("tail", ["tail", "-f", str(log_path)])
    return 0  # unreachable after execvp


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
    p_show.add_argument("--task-file", help="Path to a markdown task file (source of truth)")
    p_show.set_defaults(func=cmd_show_step)

    p_next = sub.add_parser("next-step", help="Advance to next step")
    p_next.add_argument("--task-file", help="Path to a markdown task file (source of truth)")
    p_next.set_defaults(func=cmd_next_step)

    p_review = sub.add_parser("review-diff", help="Ask Codex to review current diff")
    p_review.add_argument("--task-file", help="Path to a markdown task file (source of truth)")
    p_review.add_argument("--stdin-diff", action="store_true", help="Read diff from stdin instead of running git diff")
    p_review.set_defaults(func=cmd_review_diff)

    p_do = sub.add_parser("do-step", help="Implement current step with Claude, review with Codex")
    p_do.add_argument("--task-file", help="Path to a markdown task file (source of truth)")
    p_do.set_defaults(func=cmd_do_step)

    p_init = sub.add_parser("init", help="Print the orchestrator prompt for Claude")
    p_init.set_defaults(func=cmd_init)

    p_logs = sub.add_parser("logs", help="View debate log files")
    p_logs.add_argument("--list", action="store_true", help="List all log files")
    p_logs.add_argument("--run", help="Show log for a specific run ID")
    p_logs.set_defaults(func=cmd_logs)

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
