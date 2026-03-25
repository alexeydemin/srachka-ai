from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from srachka_ai.config import DEFAULT_CONFIG
from srachka_ai.models import PlanDraft, PlanReview, RunState
from srachka_ai.orchestrator import Orchestrator, _is_auth_failure
from srachka_ai.providers import ProviderMeta, ProviderResult
from srachka_ai.shell import CommandError, CommandTimeout
from srachka_ai.state import STEP_REVIEWS_FILE_NAME


class OrchestratorFallbackTests(unittest.TestCase):
    def test_auth_failure_detection_matches_expected_errors(self) -> None:
        self.assertTrue(_is_auth_failure(CommandError("Failed to authenticate. API Error: 401")))
        self.assertTrue(_is_auth_failure(CommandError("Not logged in · Please run /login")))
        self.assertFalse(_is_auth_failure(CommandError("Command failed: rg")))

    def test_plan_generation_falls_back_to_codex_when_claude_auth_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            orchestrator = Orchestrator(
                tmp_path,
                tmp_path,
                DEFAULT_CONFIG,
                tmp_path,
                tmp_path / "runs",
            )

            with mock.patch.object(
                orchestrator.claude,
                "ask_json",
                side_effect=CommandError("Not logged in · Please run /login"),
            ):
                with mock.patch.object(
                    orchestrator.codex,
                    "ask_json",
                    return_value=ProviderResult(
                        data={
                            "status": "draft",
                            "summary": "fallback plan",
                            "steps": ["step 1"],
                            "risks": [],
                            "open_questions": [],
                        },
                        meta=ProviderMeta(provider="Codex"),
                    ),
                ) as codex_mock:
                    result = orchestrator._ask_plan("task", None)

        self.assertEqual(result["summary"], "fallback plan")
        self.assertEqual(codex_mock.call_args.args[1], "plan.schema.json")

    def test_plan_review_falls_back_to_claude_when_codex_auth_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            orchestrator = Orchestrator(
                tmp_path,
                tmp_path,
                DEFAULT_CONFIG,
                tmp_path,
                tmp_path / "runs",
            )
            plan = PlanDraft(status="draft", summary="s", steps=["a"], risks=[], open_questions=[])

            with mock.patch.object(
                orchestrator.codex,
                "ask_json",
                side_effect=CommandError("OAuth token has expired"),
            ):
                with mock.patch.object(
                    orchestrator.claude,
                    "ask_json",
                    return_value=ProviderResult(
                        data={
                            "status": "approved",
                            "summary": "fallback review",
                            "issues": [],
                            "requested_changes": [],
                            "question_for_user": None,
                        },
                        meta=ProviderMeta(provider="Claude"),
                    ),
                ):
                    result = orchestrator._review_plan("task", plan)

        self.assertEqual(result["summary"], "fallback review")

    def test_diff_review_falls_back_to_claude_when_codex_auth_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            orchestrator = Orchestrator(
                tmp_path,
                tmp_path,
                DEFAULT_CONFIG,
                tmp_path,
                tmp_path / "runs",
            )
            state = RunState(
                task="task",
                run_id="run",
                work_repo=str(tmp_path),
                current_step_index=0,
                plan=PlanDraft(status="draft", summary="sum", steps=["step"], risks=[], open_questions=[]),
                final_plan_review=PlanReview(
                    status="approved",
                    summary="ok",
                    issues=[],
                    requested_changes=[],
                    question_for_user=None,
                ),
            )

            with mock.patch.object(
                orchestrator.codex,
                "ask_json",
                side_effect=CommandError("Failed to authenticate"),
            ):
                with mock.patch.object(
                    orchestrator.claude,
                    "ask_json",
                    return_value=ProviderResult(
                        data={
                            "status": "accept",
                            "summary": "fallback diff review",
                            "issues": [],
                            "required_fixes": [],
                            "done_enough": True,
                        },
                        meta=ProviderMeta(provider="Claude"),
                    ),
                ):
                    result = orchestrator._review_diff(state, "diff")

        self.assertEqual(result["summary"], "fallback diff review")


class TimeoutTests(unittest.TestCase):
    def test_is_auth_failure_returns_false_for_timeout(self) -> None:
        exc = CommandTimeout(["claude", "-p", "hello"], timeout_s=600, elapsed_s=600.0)
        self.assertFalse(_is_auth_failure(exc))

    def test_do_step_creates_synthetic_reject_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_dir = tmp_path / "runs" / "run1"
            run_dir.mkdir(parents=True)

            orchestrator = Orchestrator(
                tmp_path, tmp_path, DEFAULT_CONFIG, tmp_path, tmp_path / "runs",
            )
            orchestrator._log_file = tmp_path / "test.log"
            orchestrator._log_file.touch()

            state = RunState(
                task="task",
                run_id="run1",
                work_repo=str(tmp_path),
                current_step_index=0,
                plan=PlanDraft(status="draft", summary="s", steps=["step 1"], risks=[], open_questions=[]),
                final_plan_review=PlanReview(
                    status="approved", summary="ok", issues=[],
                    requested_changes=[], question_for_user=None,
                ),
            )

            timeout_exc = CommandTimeout(["claude", "-p", "x"], timeout_s=600, elapsed_s=600.0)

            with mock.patch.object(orchestrator, "_ensure_clean_repo"):
                with mock.patch.object(
                    orchestrator.claude, "implement", side_effect=timeout_exc,
                ):
                    review = orchestrator.do_step(state, run_dir)

            self.assertIsNotNone(review)
            self.assertEqual(review.status, "reject")
            self.assertIn("timed out", review.summary.lower())
            self.assertTrue(any(i.severity == "high" for i in review.issues))

            step_reviews_path = run_dir / STEP_REVIEWS_FILE_NAME
            self.assertTrue(step_reviews_path.exists())
            import json
            lines = step_reviews_path.read_text().strip().split("\n")
            self.assertGreaterEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["review"]["status"], "reject")


if __name__ == "__main__":
    unittest.main()
