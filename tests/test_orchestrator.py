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


class TaskFileIntegrationTests(unittest.TestCase):
    """Tests for orchestrator writing plan / marking steps in task files."""

    def _make_orchestrator(self, tmp_path: Path) -> Orchestrator:
        runs_root = tmp_path / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        orch = Orchestrator(tmp_path, tmp_path, DEFAULT_CONFIG, tmp_path, runs_root)
        return orch

    def _plan_result(self, steps: list[str]) -> ProviderResult:
        return ProviderResult(
            data={
                "status": "draft",
                "summary": "plan",
                "steps": steps,
                "risks": [],
                "open_questions": [],
            },
            meta=ProviderMeta(provider="Claude"),
        )

    def _review_approved(self) -> ProviderResult:
        return ProviderResult(
            data={
                "status": "approved",
                "summary": "looks good",
                "issues": [],
                "requested_changes": [],
                "question_for_user": None,
            },
            meta=ProviderMeta(provider="Codex"),
        )

    def _mock_worktree(self, tmp_path: Path):
        """Context manager that mocks worktree functions to work in temp dirs."""
        wt_dir = tmp_path / ".srachka" / "worktrees" / "test-branch"
        wt_dir.mkdir(parents=True, exist_ok=True)
        (wt_dir / ".git").write_text("gitdir: fake")
        return (
            mock.patch("srachka_ai.orchestrator.resolve_git_toplevel", return_value=tmp_path),
            mock.patch("srachka_ai.orchestrator.get_current_branch", return_value="main"),
            mock.patch("srachka_ai.orchestrator.create_worktree", return_value=wt_dir),
        )

    def test_debate_plan_writes_to_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            tf = tmp_path / "task.md"
            tf.write_text("# My Task\n\nDo something.\n")

            orch = self._make_orchestrator(tmp_path)
            wt_mocks = self._mock_worktree(tmp_path)

            with mock.patch.object(orch, "_ensure_clean_repo"), \
                 mock.patch.object(orch, "_switch_work_root"), \
                 wt_mocks[0], wt_mocks[1], wt_mocks[2], \
                 mock.patch.object(orch.claude, "ask_json", return_value=self._plan_result(["step A", "step B"])), \
                 mock.patch.object(orch.codex, "ask_json", return_value=self._review_approved()):
                state = orch.debate_plan("# My Task\n\nDo something.\n", task_file_path=tf)

            content = tf.read_text()
            from srachka_ai.task_file import SEPARATOR, read_task_plan, read_task_metadata
            self.assertIn(SEPARATOR, content)
            steps = read_task_plan(tf)
            self.assertEqual(len(steps), 2)
            self.assertEqual(steps[0].text, "step A")
            self.assertFalse(steps[0].done)
            meta = read_task_metadata(tf)
            self.assertEqual(meta.run_id, state.run_id)
            self.assertEqual(meta.status, "approved")

    def test_debate_plan_without_task_file_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            orch = self._make_orchestrator(tmp_path)
            wt_mocks = self._mock_worktree(tmp_path)

            with mock.patch.object(orch, "_ensure_clean_repo"), \
                 mock.patch.object(orch, "_switch_work_root"), \
                 wt_mocks[0], wt_mocks[1], wt_mocks[2], \
                 mock.patch.object(orch.claude, "ask_json", return_value=self._plan_result(["s1"])), \
                 mock.patch.object(orch.codex, "ask_json", return_value=self._review_approved()):
                state = orch.debate_plan("task text", task_file_path=None)

            self.assertEqual(state.plan.steps, ["s1"])

    def test_do_step_marks_task_file_on_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_dir = tmp_path / "runs" / "run_tf"
            run_dir.mkdir(parents=True)

            tf = tmp_path / "task.md"
            tf.write_text("# Task\n\nBody\n")
            from srachka_ai.task_file import write_plan_to_task, read_task_plan
            write_plan_to_task(tf, ["step 1", "step 2"], "run_tf", str(tmp_path))

            orch = self._make_orchestrator(tmp_path)
            orch._log_file = tmp_path / "test.log"
            orch._log_file.touch()

            state = RunState(
                task="task",
                run_id="run_tf",
                work_repo=str(tmp_path),
                current_step_index=0,
                plan=PlanDraft(status="approved", summary="s", steps=["step 1", "step 2"], risks=[], open_questions=[]),
                final_plan_review=PlanReview(
                    status="approved", summary="ok", issues=[], requested_changes=[], question_for_user=None,
                ),
            )

            accept_review = ProviderResult(
                data={
                    "status": "accept",
                    "summary": "done",
                    "issues": [],
                    "required_fixes": [],
                    "done_enough": True,
                },
                meta=ProviderMeta(provider="Codex"),
            )

            with mock.patch.object(orch, "_ensure_clean_repo"):
                with mock.patch.object(orch.claude, "implement", return_value=(ProviderMeta(provider="Claude"), "ok")):
                    with mock.patch.object(orch, "_raw_git_diff", return_value="diff --git a/file"):
                        with mock.patch.object(orch.codex, "ask_json", return_value=accept_review):
                            with mock.patch.object(orch, "_auto_commit"):
                                review = orch.do_step(state, run_dir, task_file_path=tf)

            self.assertEqual(review.status, "accept")
            steps = read_task_plan(tf)
            self.assertTrue(steps[0].done)
            self.assertFalse(steps[1].done)

    def test_do_step_does_not_mark_on_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_dir = tmp_path / "runs" / "run_rej"
            run_dir.mkdir(parents=True)

            tf = tmp_path / "task.md"
            tf.write_text("# Task\n\nBody\n")
            from srachka_ai.task_file import write_plan_to_task, read_task_plan
            write_plan_to_task(tf, ["step 1"], "run_rej", str(tmp_path))

            orch = self._make_orchestrator(tmp_path)
            orch._log_file = tmp_path / "test.log"
            orch._log_file.touch()

            state = RunState(
                task="task",
                run_id="run_rej",
                work_repo=str(tmp_path),
                current_step_index=0,
                plan=PlanDraft(status="approved", summary="s", steps=["step 1"], risks=[], open_questions=[]),
                final_plan_review=PlanReview(
                    status="approved", summary="ok", issues=[], requested_changes=[], question_for_user=None,
                ),
            )

            reject_review = ProviderResult(
                data={
                    "status": "reject",
                    "summary": "bad",
                    "issues": [{"severity": "high", "message": "broken"}],
                    "required_fixes": ["fix it"],
                    "done_enough": False,
                },
                meta=ProviderMeta(provider="Codex"),
            )

            with mock.patch.object(orch, "_ensure_clean_repo"):
                with mock.patch.object(orch.claude, "implement", return_value=(ProviderMeta(provider="Claude"), "ok")):
                    with mock.patch.object(orch, "_raw_git_diff", return_value="diff --git a/file"):
                        with mock.patch.object(orch.codex, "ask_json", return_value=reject_review):
                            review = orch.do_step(state, run_dir, task_file_path=tf)

            self.assertEqual(review.status, "reject")
            steps = read_task_plan(tf)
            self.assertFalse(steps[0].done)


if __name__ == "__main__":
    unittest.main()
