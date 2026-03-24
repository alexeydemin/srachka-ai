from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from srachka_ai.config import DEFAULT_CONFIG
from srachka_ai.models import PlanDraft, PlanReview, RunState
from srachka_ai.orchestrator import Orchestrator, _is_auth_failure
from srachka_ai.shell import CommandError


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
                    return_value={
                        "status": "draft",
                        "summary": "fallback plan",
                        "steps": ["step 1"],
                        "risks": [],
                        "open_questions": [],
                    },
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
                    return_value={
                        "status": "approved",
                        "summary": "fallback review",
                        "issues": [],
                        "requested_changes": [],
                        "question_for_user": None,
                    },
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
                    return_value={
                        "status": "accept",
                        "summary": "fallback diff review",
                        "issues": [],
                        "required_fixes": [],
                        "done_enough": True,
                    },
                ):
                    result = orchestrator._review_diff(state, "diff")

        self.assertEqual(result["summary"], "fallback diff review")


if __name__ == "__main__":
    unittest.main()
