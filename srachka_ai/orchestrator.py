from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .models import DiffReview, PlanDraft, PlanReview, RunState
from .prompts import diff_review_prompt, implementation_brief, plan_prompt, review_prompt
from .providers import ClaudeProvider, CodexProvider, ProviderMeta, ProviderResult
from .shell import CommandError
from .state import REVIEW_HISTORY_FILE_NAME, point_latest, save_run_state
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
        self.claude = ClaudeProvider(config, work_root)
        self.codex = CodexProvider(config, work_root, schema_dir)

    def create_run_dir(self) -> Path:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
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
