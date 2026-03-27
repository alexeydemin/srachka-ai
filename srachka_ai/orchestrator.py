from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .models import DiffReview, Issue, PlanDraft, PlanReview, RunState
from .prompts import diff_review_prompt, fix_prompt, implementation_brief, plan_prompt, review_prompt
from .providers import ClaudeProvider, CodexProvider, ProviderMeta, ProviderResult
from .shell import CommandError, CommandTimeout
from .state import REVIEW_HISTORY_FILE_NAME, STEP_REVIEWS_FILE_NAME, point_latest, save_run_state
from .task_file import mark_step_done, write_plan_to_task
from .utils import append_jsonl
from .worktree import create_worktree, get_current_branch, resolve_git_toplevel, verify_worktree


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
    if isinstance(exc, CommandTimeout):
        return False
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

    def _flog(self, message: str) -> None:
        if self._log_file is None:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with self._log_file.open("a") as f:
            f.write(f"[{ts}] {message}\n")
            f.flush()

    def _switch_work_root(self, new_path: Path) -> None:
        """Switch all providers and self to a new work directory."""
        self.work_root = new_path
        self.claude = ClaudeProvider(self.config, new_path)
        self.codex = CodexProvider(self.config, new_path, self.schema_dir)

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

    def attach_log(self, run_id: str) -> None:
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self._log_file = self.logs_root / f"{run_id}.log"
        if not self._log_file.exists():
            self._log_file.touch()

    def create_run_dir(self) -> Path:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        self.attach_log(run_id)
        return run_dir

    def _ask_plan(self, task: str, previous_review: PlanReview | None) -> dict:
        prompt = plan_prompt(task, previous_review)
        self._flog(f"=== ASK PLAN (prompt) ===\n{prompt}")
        primary_error: CommandError | None = None
        _log("Claude  generating plan...")
        try:
            pr = self.claude.ask_json(prompt, timeout_s=self.config.provider_timeout_s)
            _log(f"Claude  done ({_meta_str(pr.meta)})")
            self._flog(f"=== PLAN RESPONSE (Claude, {_meta_str(pr.meta)}) ===\n{pr.raw_response}")
            return pr.data
        except CommandError as primary_exc:
            self._flog(f"Claude error in _ask_plan: {primary_exc}")
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        except Exception as exc:
            self._flog(f"Claude unexpected error in _ask_plan: {exc}")
            raise
        _log("Claude  auth failed, falling back to Codex...")
        self._flog("Claude auth failed, falling back to Codex for plan")
        self._flog(f"=== ASK PLAN fallback (prompt) ===\n{prompt}")
        try:
            pr = self.codex.ask_json(prompt, "plan.schema.json", timeout_s=self.config.provider_timeout_s)
            _log(f"Codex   done ({_meta_str(pr.meta)})")
            self._flog(f"=== PLAN RESPONSE (Codex fallback, {_meta_str(pr.meta)}) ===\n{pr.raw_response}")
            return pr.data
        except (CommandError, Exception) as fallback_exc:
            self._flog(f"Plan generation failed completely.\nClaude: {primary_error}\nCodex: {fallback_exc}")
            raise RuntimeError(
                "Planning failed. Claude and Codex were both unavailable for plan generation.\n\n"
                f"Claude error:\n{primary_error}\n\n"
                f"Codex error:\n{fallback_exc}"
            ) from fallback_exc

    def _review_plan(self, task: str, plan: PlanDraft) -> dict:
        prompt = review_prompt(task, plan)
        self._flog(f"=== REVIEW PLAN (prompt) ===\n{prompt}")
        primary_error: CommandError | None = None
        _log("Codex   reviewing plan...")
        try:
            pr = self.codex.ask_json(prompt, "plan_review.schema.json", timeout_s=self.config.provider_timeout_s)
            _log(f"Codex   done ({_meta_str(pr.meta)})")
            self._flog(f"=== PLAN REVIEW RESPONSE (Codex, {_meta_str(pr.meta)}) ===\n{pr.raw_response}")
            return pr.data
        except CommandError as primary_exc:
            self._flog(f"Codex error in _review_plan: {primary_exc}")
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        except Exception as exc:
            self._flog(f"Codex unexpected error in _review_plan: {exc}")
            raise
        _log("Codex   auth failed, falling back to Claude...")
        self._flog("Codex auth failed, falling back to Claude for plan review")
        self._flog(f"=== REVIEW PLAN fallback (prompt) ===\n{prompt}")
        try:
            pr = self.claude.ask_json(prompt, timeout_s=self.config.provider_timeout_s)
            _log(f"Claude  done ({_meta_str(pr.meta)})")
            self._flog(f"=== PLAN REVIEW RESPONSE (Claude fallback, {_meta_str(pr.meta)}) ===\n{pr.raw_response}")
            return pr.data
        except (CommandError, Exception) as fallback_exc:
            self._flog(f"Plan review failed completely.\nCodex: {primary_error}\nClaude: {fallback_exc}")
            raise RuntimeError(
                "Plan review failed. Codex and Claude were both unavailable for review.\n\n"
                f"Codex error:\n{primary_error}\n\n"
                f"Claude error:\n{fallback_exc}"
            ) from fallback_exc

    def _review_diff(self, state: RunState, diff_text: str) -> dict:
        prompt = diff_review_prompt(state, diff_text)
        self._flog(f"=== REVIEW DIFF (prompt) ===\n{prompt}")
        primary_error: CommandError | None = None
        _log("Codex   reviewing diff...")
        try:
            pr = self.codex.ask_json(prompt, "diff_review.schema.json", timeout_s=self.config.provider_timeout_s)
            _log(f"Codex   done ({_meta_str(pr.meta)})")
            self._flog(f"=== DIFF REVIEW RESPONSE (Codex, {_meta_str(pr.meta)}) ===\n{pr.raw_response}")
            return pr.data
        except CommandError as primary_exc:
            self._flog(f"Codex error in _review_diff: {primary_exc}")
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        except Exception as exc:
            self._flog(f"Codex unexpected error in _review_diff: {exc}")
            raise
        _log("Codex   auth failed, falling back to Claude...")
        self._flog("Codex auth failed, falling back to Claude for diff review")
        self._flog(f"=== REVIEW DIFF fallback (prompt) ===\n{prompt}")
        try:
            pr = self.claude.ask_json(prompt, timeout_s=self.config.provider_timeout_s)
            _log(f"Claude  done ({_meta_str(pr.meta)})")
            self._flog(f"=== DIFF REVIEW RESPONSE (Claude fallback, {_meta_str(pr.meta)}) ===\n{pr.raw_response}")
            return pr.data
        except (CommandError, Exception) as fallback_exc:
            self._flog(f"Diff review failed completely.\nCodex: {primary_error}\nClaude: {fallback_exc}")
            if isinstance(fallback_exc, CommandTimeout):
                raise
            raise RuntimeError(
                "Diff review failed. Codex and Claude were both unavailable for review.\n\n"
                f"Codex error:\n{primary_error}\n\n"
                f"Claude error:\n{fallback_exc}"
            ) from fallback_exc

    def debate_plan(self, task: str, task_file_path: Path | None = None) -> RunState:
        self._ensure_clean_repo()

        # Capture base branch and create worktree
        git_root = resolve_git_toplevel(self.work_root)
        base_branch = get_current_branch(self.work_root)
        original_work_repo = str(git_root)

        run_dir = self.create_run_dir()
        worktree_branch = f"srachka/{run_dir.name}"
        worktree_path = create_worktree(git_root, worktree_branch)
        self._switch_work_root(worktree_path)
        _log(f"Worktree: {worktree_path}")

        self._flog(f"=== DEBATE PLAN START ===\nrun_id: {run_dir.name}\ntask: {task}\nworktree: {worktree_path}")
        review_path = run_dir / REVIEW_HISTORY_FILE_NAME
        previous_review: PlanReview | None = None
        final_plan: PlanDraft | None = None
        final_review: PlanReview | None = None
        review_history: list[dict] = []

        for round_index in range(1, self.config.max_plan_rounds + 1):
            _log_header(round_index, self.config.max_plan_rounds)
            self._flog(f"--- Plan round {round_index}/{self.config.max_plan_rounds} ---")
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
                self._flog(f"Plan round {round_index} status: approved")
                break

            if review.status == "ask_user":
                _log(f"Status: ask_user -- human input needed")
                self._flog(f"Plan round {round_index} status: ask_user")
                break

            _log(f"Status: {review.status} -- next round")
            self._flog(f"Plan round {round_index} status: {review.status} — next round")
            previous_review = review

        if final_plan is None or final_review is None:
            self._flog("Planning loop finished without a plan or review")
            raise RuntimeError("Planning loop finished without a plan or review")

        state = RunState(
            task=task,
            run_id=run_dir.name,
            work_repo=original_work_repo,
            current_step_index=0,
            plan=final_plan,
            final_plan_review=final_review,
            review_history=review_history,
            worktree_path=str(worktree_path),
            worktree_branch=worktree_branch,
            base_branch=base_branch,
        )
        implementation_text = implementation_brief(state)
        save_run_state(run_dir, state, implementation_text)
        point_latest(self.runs_root, run_dir)

        if task_file_path is not None:
            write_plan_to_task(
                task_file_path,
                final_plan.steps,
                run_id=run_dir.name,
                work_repo=original_work_repo,
                status=final_review.status,
                worktree_path=str(worktree_path),
                worktree_branch=worktree_branch,
                base_branch=base_branch,
            )

        _log(f"Run saved: {run_dir.name}")
        self._flog(f"=== DEBATE PLAN END ===\nrun saved: {run_dir.name}\nfinal status: {final_review.status}\nsteps: {len(final_plan.steps)}")
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
            self._flog(f"git diff failed:\n{completed.stderr}")
            raise RuntimeError(f"git diff failed:\n{completed.stderr}")
        diff = completed.stdout.strip()
        self._flog(f"=== GIT DIFF ({len(diff)} chars) ===\n{diff}")
        return diff

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

    def do_step(self, state: RunState, run_dir: Path, task_file_path: Path | None = None) -> DiffReview | None:
        if state.current_step is None:
            return None

        # Switch to worktree if present
        if state.worktree_path:
            wt = Path(state.worktree_path)
            if not verify_worktree(wt):
                raise RuntimeError(
                    f"Worktree not found at {wt}.\n"
                    "It may have been manually removed. Re-run 'srachka plan' to create a new one."
                )
            self._switch_work_root(wt)

        self._ensure_clean_repo()

        step_reviews_path = run_dir / STEP_REVIEWS_FILE_NAME
        step_index = state.current_step_index
        self._flog(f"=== DO STEP {step_index + 1} ===\n{state.current_step}")

        # 1 initial implementation + up to max_step_fix_rounds fix rounds
        max_attempts = 1 + self.config.max_step_fix_rounds
        final_review: DiffReview | None = None

        for round_index in range(1, max_attempts + 1):
            _log_header(round_index, max_attempts)
            self._flog(f"--- Step {step_index + 1}, attempt {round_index}/{max_attempts} ---")

            # Run Claude
            if round_index == 1:
                prompt = implementation_brief(state)
            else:
                prompt = fix_prompt(state, final_review)
            self._flog(f"=== IMPLEMENTATION PROMPT ===\n{prompt}")
            _log("Claude  implementing...")

            try:
                try:
                    meta, response_text = self.claude.implement(prompt, timeout_s=self.config.provider_timeout_s)
                except CommandError as exc:
                    self._flog(f"Claude implement error:\n{exc}")
                    raise
                _log(f"Claude  done ({_meta_str(meta)})")
                self._flog(f"=== IMPLEMENTATION RESPONSE (Claude, {_meta_str(meta)}) ===\n{response_text}")

                # Get diff
                diff_text = self._raw_git_diff()

                if not diff_text:
                    _log("Warning: empty diff — no changes produced")
                    self._flog("Warning: empty diff — no changes produced")
                    final_review = self._synthetic_empty_reject()
                    append_jsonl(step_reviews_path, {
                        "type": "step_review", "step_index": step_index,
                        "round": round_index, "review": final_review.to_dict(),
                    })
                    continue

                # Codex reviews
                review = DiffReview.from_dict(self._review_diff(state, diff_text))
                final_review = review

            except CommandTimeout as exc:
                _log(f"Timeout: provider timed out after {exc.elapsed_s:.0f}s")
                self._flog(f"Step {step_index + 1} attempt {round_index}: CommandTimeout after {exc.elapsed_s:.0f}s")
                final_review = DiffReview(
                    status="reject",
                    summary=f"Provider timed out after {exc.elapsed_s:.0f}s (limit {exc.timeout_s}s)",
                    issues=[Issue(severity="high", message=f"Provider timed out after {exc.elapsed_s:.0f}s")],
                    required_fixes=["Retry — the provider did not respond in time."],
                    done_enough=False,
                )
                append_jsonl(step_reviews_path, {
                    "type": "step_review", "step_index": step_index,
                    "round": round_index, "review": final_review.to_dict(),
                })
                continue

            append_jsonl(step_reviews_path, {
                "type": "step_review", "step_index": step_index,
                "round": round_index, "review": review.to_dict(),
            })

            if review.status == "ask_user":
                _log("Status: ask_user — stopping")
                self._flog(f"Step {step_index + 1} attempt {round_index} status: ask_user")
                break

            if review.status == "accept" or not self._has_blocking_issues(review):
                _log("Status: accepted")
                review.status = "accept"
                self._flog(f"Step {step_index + 1} attempt {round_index} status: accepted")
                break

            blocking = len([i for i in review.issues if i.severity in ("high", "medium")])
            _log(f"Status: reject — {blocking} blocking issues")
            self._flog(f"Step {step_index + 1} attempt {round_index} status: reject — {blocking} blocking issues")

        if final_review is not None and final_review.status == "accept":
            self._auto_commit(state)
            if task_file_path is not None:
                mark_step_done(task_file_path, step_index)

        self._flog(f"=== DO STEP {step_index + 1} END === status: {final_review.status if final_review else 'None'}")
        return final_review

    def _auto_commit(self, state: RunState) -> None:
        raw = state.current_step or "unknown step"
        # Strip "Step N: " prefix if present to avoid duplication
        description = re.sub(r"^Step\s+\d+:\s*", "", raw)[:70].replace("\n", " ")
        step_num = state.current_step_index + 1
        message = f"Step {step_num}: {description}"
        self._flog(f"Auto-committing: {message}")
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
                self._flog("Warning: nothing to commit after accept")
            else:
                self._flog(f"git commit failed:\n{result.stderr.strip()}")
                raise RuntimeError(
                    f"git commit failed after accepted step:\n{result.stderr.strip()}"
                )
        else:
            _log(f"Committed: {message}")
            self._flog(f"Committed: {message}")
