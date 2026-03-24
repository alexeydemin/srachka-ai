from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .models import DiffReview, PlanDraft, PlanReview, RunState
from .prompts import diff_review_prompt, implementation_brief, plan_prompt, review_prompt
from .providers import ClaudeProvider, CodexProvider
from .shell import CommandError
from .state import REVIEW_HISTORY_FILE_NAME, point_latest, save_run_state
from .utils import append_jsonl


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
        try:
            return self.claude.ask_json(prompt)
        except CommandError as primary_exc:
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        try:
            return self.codex.ask_json(prompt, "plan.schema.json")
        except CommandError as fallback_exc:
            raise RuntimeError(
                "Planning failed. Claude and Codex were both unavailable for plan generation.\n\n"
                f"Claude error:\n{primary_error}\n\n"
                f"Codex error:\n{fallback_exc}"
            ) from fallback_exc

    def _review_plan(self, task: str, plan: PlanDraft) -> dict:
        prompt = review_prompt(task, plan)
        primary_error: CommandError | None = None
        try:
            return self.codex.ask_json(prompt, "plan_review.schema.json")
        except CommandError as primary_exc:
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        try:
            return self.claude.ask_json(prompt)
        except CommandError as fallback_exc:
            raise RuntimeError(
                "Plan review failed. Codex and Claude were both unavailable for review.\n\n"
                f"Codex error:\n{primary_error}\n\n"
                f"Claude error:\n{fallback_exc}"
            ) from fallback_exc

    def _review_diff(self, state: RunState, diff_text: str) -> dict:
        prompt = diff_review_prompt(state, diff_text)
        primary_error: CommandError | None = None
        try:
            return self.codex.ask_json(prompt, "diff_review.schema.json")
        except CommandError as primary_exc:
            if not _is_auth_failure(primary_exc):
                raise
            primary_error = primary_exc
        try:
            return self.claude.ask_json(prompt)
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
                break

            if review.status == "ask_user":
                break

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
        return state

    def review_diff(self, state: RunState, diff_text: str) -> DiffReview:
        raw = self._review_diff(state, diff_text)
        return DiffReview.from_dict(raw)
