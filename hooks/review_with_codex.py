#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))

from srachka_ai.config import load_config
from srachka_ai.orchestrator import Orchestrator
from srachka_ai.paths import runs_dir, schema_dir
from srachka_ai.state import read_run_state, resolve_latest_run_dir


def git_diff(cwd: Path) -> str:
    completed = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--unified=1"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git diff failed: {completed.stderr.strip()}")
    return completed.stdout.strip() or "No diff detected."


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
        work_repo = Path(hook_input.get("cwd") or hook_input.get("workspace") or ".").resolve()
        config = load_config(APP_ROOT)
        runs_root = runs_dir(APP_ROOT, config.runs_dir)
        run_dir = resolve_latest_run_dir(runs_root)
        state = read_run_state(run_dir)
        planned_repo = Path(state.work_repo).resolve()
        if planned_repo != work_repo:
            raise RuntimeError(
                f"latest run targets {planned_repo}, but hook is running in {work_repo}"
            )
        orchestrator = Orchestrator(APP_ROOT, work_repo, config, schema_dir(APP_ROOT), runs_root)
        review = orchestrator.review_diff(state, git_diff(work_repo))

        if review.status == "accept":
            return 0

        payload = {
            "decision": "block",
            "reason": f"Codex review blocked stop: {review.summary}. Required fixes: {'; '.join(review.required_fixes) if review.required_fixes else 'See issues.'}"
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"srachka_ai hook failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
