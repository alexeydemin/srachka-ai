"""Tests for models — RunState serialization, backward compat, active_work_root."""
from __future__ import annotations

import unittest

from srachka_ai.models import PlanDraft, PlanReview, RunState


def _make_state(**overrides) -> RunState:
    defaults = dict(
        task="task",
        run_id="run1",
        work_repo="/repo",
        current_step_index=0,
        plan=PlanDraft(status="approved", summary="s", steps=["step"], risks=[], open_questions=[]),
        final_plan_review=PlanReview(
            status="approved", summary="ok", issues=[], requested_changes=[], question_for_user=None,
        ),
    )
    defaults.update(overrides)
    return RunState(**defaults)


class ActiveWorkRootTest(unittest.TestCase):
    def test_returns_worktree_when_present(self) -> None:
        state = _make_state(worktree_path="/wt/path")
        self.assertEqual(state.active_work_root, "/wt/path")

    def test_returns_work_repo_when_no_worktree(self) -> None:
        state = _make_state()
        self.assertEqual(state.active_work_root, "/repo")


class RunStateBackwardCompatTest(unittest.TestCase):
    def test_from_dict_without_worktree_fields(self) -> None:
        data = {
            "task": "t",
            "run_id": "r",
            "work_repo": "/w",
            "current_step_index": 0,
            "plan": {"status": "approved", "summary": "s", "steps": ["a"], "risks": [], "open_questions": []},
            "final_plan_review": {
                "status": "approved", "summary": "ok", "issues": [],
                "requested_changes": [], "question_for_user": None,
            },
        }
        state = RunState.from_dict(data)
        self.assertIsNone(state.worktree_path)
        self.assertIsNone(state.worktree_branch)
        self.assertIsNone(state.base_branch)
        self.assertEqual(state.active_work_root, "/w")

    def test_to_dict_omits_none_worktree_fields(self) -> None:
        state = _make_state()
        d = state.to_dict()
        self.assertNotIn("worktree_path", d)
        self.assertNotIn("worktree_branch", d)
        self.assertNotIn("base_branch", d)

    def test_round_trip_with_worktree_fields(self) -> None:
        state = _make_state(
            worktree_path="/wt",
            worktree_branch="srachka/run1",
            base_branch="main",
        )
        d = state.to_dict()
        restored = RunState.from_dict(d)
        self.assertEqual(restored.worktree_path, "/wt")
        self.assertEqual(restored.worktree_branch, "srachka/run1")
        self.assertEqual(restored.base_branch, "main")


if __name__ == "__main__":
    unittest.main()
