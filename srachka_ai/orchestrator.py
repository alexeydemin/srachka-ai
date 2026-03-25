from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .models import DiffReview, Issue, PlanDraft, PlanReview, RunState
from .prompts import diff_review_prompt, fix_prompt, implementation_brief, plan_prompt, review_prompt
from .providers import ClaudeProvider, CodexProvider, ProviderMeta, ProviderResult
from .shell import CommandError
from .state import REVIEW_HISTORY_FILE_NAME, STEP_REVIEWS_FILE_NAME, point_latest, save_run_state
from .utils import append_jsonl


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(message: str) -> None:
    print(f"  [{_ts()}] {message}", file=sys.stderr, flush=True)


def _meta_str(meta: ProviderMeta) -> str:
    parts = [f"{meta.duration_s:.0f}s"]
    if meta.input_tokens or meta.output_tokens:
        total = meta.input_tokens + meta.output_tokens
        if total >= 1000:
            parts.append(f"{total / 1000:.1f}k tok")
        else:
            parts.append(f"{total} tok")
    if meta.cost_usd:
        parts.append(f"${meta.cost_usd:.4f}")
    return ", ".join(parts)


def _log_header(round_index: int, max_rounds: int) -> None:
    header = f" Round {round_index}/{max_rounds} "
    line = header.center(50, "\u2500")
    print(f"\n{line}", file=sys.stderr, flush=True)


AUTH_ERROR_MARKERS = (
    "failed to authenticate",
    "authentication_error",
    "oauth token has expired",
    "not logged in",
    "please run /login",
    "please run 'codex login'",
    "please sign in again",
    "missing authentication",
    "access token could not be refreshed",
)


def _is_auth_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in AUTH_ERROR_MARKERS)


class Orchestrator:
    def __init__(
        self,
        app_root: Path,
        work_root: Path,
        config: AppConfig,
        schema_dir: Path,
        runs_root: Path,
    ) -> None:
        self.app_root = app_root
        self.work_root = work_root
        self.config = config
        self.schema_dir = schema_dir
        self.runs_root = runs_root
        self.logs_root = app_root / config.logs_dir
        self._log_file: Path | None = None
        self.claude = ClaudeProvider(config, work_root)
        self.codex = CodexProvider(config, work_root, schema_dir)

    def _ensure_clean_repo(self) -> None:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(self.work_root),
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git status failed (is {self.work_root} a git repo?):\n{result.stderr.strip()}"
            )
        if result.stdout.strip():
            raise RuntimeError(
                "Work repo has uncommitted changes. "
                "Run 'git stash -u' or commit first before using srachka."
            )

    def create_run_dir(self) -> Path:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self._log_file = self.logs_root / f"{run_id}.log"
        self._log_file.touch()
        return run_dir

    def _ask_plan(self, task: str, previous_review: PlanReview | None) -> dict:
        prompt = plan_prompt(task, previous_review)
        primary_error: CommandError | None = None
        _log("Claude  generating plan...")
        try:
            pr = self.claude.ask_json(prompt)
            _log(f"Claude  done ({_meta_str(pr.meta)})")
            return pr.data
        except CommandError as primary_exc:
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        _log("Claude  auth failed, falling back to Codex...")
        try:
            pr = self.codex.ask_json(prompt, "plan.schema.json")
            _log(f"Codex   done ({_meta_str(pr.meta)})")
            return pr.data
        except CommandError as fallback_exc:
            raise RuntimeError(
                "Planning failed. Claude and Codex were both unavailable for plan generation.\n\n"
                f"Claude error:\n{primary_error}\n\n"
                f"Codex error:\n{fallback_exc}"
            ) from fallback_exc

    def _review_plan(self, task: str, plan: PlanDraft) -> dict:
        prompt = review_prompt(task, plan)
        primary_error: CommandError | None = None
        _log("Codex   reviewing plan...")
        try:
            pr = self.codex.ask_json(prompt, "plan_review.schema.json")
            _log(f"Codex   done ({_meta_str(pr.meta)})")
            return pr.data
        except CommandError as primary_exc:
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        _log("Codex   auth failed, falling back to Claude...")
        try:
            pr = self.claude.ask_json(prompt)
            _log(f"Claude  done ({_meta_str(pr.meta)})")
            return pr.data
        except CommandError as fallback_exc:
            raise RuntimeError(
                "Plan review failed. Codex and Claude were both unavailable for review.\n\n"
                f"Codex error:\n{primary_error}\n\n"
                f"Claude error:\n{fallback_exc}"
            ) from fallback_exc

    def _review_diff(self, state: RunState, diff_text: str) -> dict:
        prompt = diff_review_prompt(state, diff_text)
        primary_error: CommandError | None = None
        _log("Codex   reviewing diff...")
        try:
            pr = self.codex.ask_json(prompt, "diff_review.schema.json")
            _log(f"Codex   done ({_meta_str(pr.meta)})")
            return pr.data
        except CommandError as primary_exc:
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        _log("Codex   auth failed, falling back to Claude...")
        try:
            pr = self.claude.ask_json(prompt)
            _log(f"Claude  done ({_meta_str(pr.meta)})")
            return pr.data
        except CommandError as fallback_exc:
            raise RuntimeError(
                "Diff review failed. Codex and Claude were both unavailable for review.\n\n"
                f"Codex error:\n{primary_error}\n\n"
                f"Claude error:\n{fallback_exc}"
            ) from fallback_exc

    def debate_plan(self, task: str) -> RunState:
        self._ensure_clean_repo()
        run_dir = self.create_run_dir()
        review_path = run_dir / REVIEW_HISTORY_FILE_NAME
        previous_review: PlanReview | None = None
        final_plan: PlanDraft | None = None
        final_review: PlanReview | None = None
        review_history: list[dict] = []

        for round_index in range(1, self.config.max_plan_rounds + 1):
            _log_header(round_index, self.config.max_plan_rounds)
            plan = PlanDraft.from_dict(self._ask_plan(task, previous_review))
            review = PlanReview.from_dict(self._review_plan(task, plan))

            round_record = {
                "round": round_index,
                "plan": plan.to_dict(),
                "review": review.to_dict(),
            }
            append_jsonl(review_path, round_record)
            review_history.append(round_record)

            final_plan = plan
            final_review = review

            if review.status == "approved":
                _log(f"Status: approved")
                break

            if review.status == "ask_user":
                _log(f"Status: ask_user -- human input needed")
                break

            _log(f"Status: {review.status} -- next round")
            previous_review = review

        if final_plan is None or final_review is None:
            raise RuntimeError("Planning loop finished without a plan or review")

        state = RunState(
            task=task,
            run_id=run_dir.name,
            work_repo=str(self.work_root),
            current_step_index=0,
            plan=final_plan,
            final_plan_review=final_review,
            review_history=review_history,
        )
        implementation_text = implementation_brief(state)
        save_run_state(run_dir, state, implementation_text)
        point_latest(self.runs_root, run_dir)
        _log(f"Run saved: {run_dir.name}")
        return state

    def review_diff(self, state: RunState, diff_text: str) -> DiffReview:
        raw = self._review_diff(state, diff_text)
        return DiffReview.from_dict(raw)

    def _raw_git_diff(self) -> str:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(self.work_root),
            check=True,
            capture_output=True,
        )
        completed = subprocess.run(
            ["git", "diff", "--cached", "--no-ext-diff", "--unified=1"],
            cwd=str(self.work_root),
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git diff failed:\n{completed.stderr}")
        return completed.stdout.strip()

    @staticmethod
    def _has_blocking_issues(review: DiffReview) -> bool:
        return any(i.severity in ("high", "medium") for i in review.issues)

    @staticmethod
    def _synthetic_empty_reject() -> DiffReview:
        return DiffReview(
            status="reject",
            summary="No changes detected.",
            issues=[Issue(severity="high", message="No changes were produced.")],
            required_fixes=["Implement the step — no file changes were made."],
            done_enough=False,
        )

    def do_step(self, state: RunState, run_dir: Path) -> DiffReview | None:
        if state.current_step is None:
            return None
        self._ensure_clean_repo()

        step_reviews_path = run_dir / STEP_REVIEWS_FILE_NAME
        step_index = state.current_step_index

        # 1 initial implementation + up to max_step_fix_rounds fix rounds
        max_attempts = 1 + self.config.max_step_fix_rounds
        final_review: DiffReview | None = None

        for round_index in range(1, max_attempts + 1):
            _log_header(round_index, max_attempts)

            # Run Claude
            if round_index == 1:
                prompt = implementation_brief(state)
            else:
                prompt = fix_prompt(state, final_review)
            _log("Claude  implementing...")
            meta = self.claude.implement(prompt)
            _log(f"Claude  done ({_meta_str(meta)})")

            # Get diff
            diff_text = self._raw_git_diff()

            if not diff_text:
                _log("Warning: empty diff — no changes produced")
                final_review = self._synthetic_empty_reject()
                append_jsonl(step_reviews_path, {
                    "type": "step_review", "step_index": step_index,
                    "round": round_index, "review": final_review.to_dict(),
                })
                continue

            # Codex reviews
            review = DiffReview.from_dict(self._review_diff(state, diff_text))
            final_review = review

            append_jsonl(step_reviews_path, {
                "type": "step_review", "step_index": step_index,
                "round": round_index, "review": review.to_dict(),
            })

            if review.status == "ask_user":
                _log("Status: ask_user — stopping")
                break

            if review.status == "accept" or not self._has_blocking_issues(review):
                _log("Status: accepted")
                review.status = "accept"
                break

            _log(f"Status: reject — {len([i for i in review.issues if i.severity in ('high', 'medium')])} blocking issues")

        if final_review is not None and final_review.status == "accept":
            self._auto_commit(state)

        return final_review

    def _auto_commit(self, state: RunState) -> None:
        step_num = state.current_step_index + 1
        description = (state.current_step or "unknown step")[:70].replace("\n", " ")
        message = f"Step {step_num}: {description}"
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(self.work_root),
            check=True,
            capture_output=True,
        )
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(self.work_root),
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            combined = f"{result.stdout}\n{result.stderr}".lower()
            if "nothing to commit" in combined:
                _log("Warning: nothing to commit after accept")
            else:
                raise RuntimeError(
                    f"git commit failed after accepted step:\n{result.stderr.strip()}"
                )
        else:
            _log(f"Committed: {message}")
