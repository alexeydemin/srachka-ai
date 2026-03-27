from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from srachka_ai.task_file import (
    SEPARATOR,
    TaskPlanStep,
    get_current_step_index,
    mark_step_done,
    read_task_metadata,
    read_task_plan,
    read_task_text,
    write_plan_to_task,
)


class ReadTaskTextTest(unittest.TestCase):
    def test_no_separator(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# My Task\n\nSome description.\n")
            f.flush()
            result = read_task_text(Path(f.name))
        self.assertIn("# My Task", result)
        self.assertIn("Some description.", result)

    def test_with_separator(self) -> None:
        content = f"# Task\n\nBody\n\n{SEPARATOR}\n<!-- status: approved | run_id: abc -->\n\n- [ ] Step 1\n"
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            result = read_task_text(Path(f.name))
        self.assertIn("# Task", result)
        self.assertIn("Body", result)
        self.assertNotIn("Step 1", result)
        self.assertNotIn("SRACHKA PLAN", result)


class ReadTaskMetadataTest(unittest.TestCase):
    def test_parses_metadata(self) -> None:
        content = f"# Task\n\n{SEPARATOR}\n<!-- status: approved | run_id: 123 | work_repo: /foo -->\n\n- [ ] Step 1\n"
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            meta = read_task_metadata(Path(f.name))
        self.assertEqual(meta.status, "approved")
        self.assertEqual(meta.run_id, "123")
        self.assertEqual(meta.work_repo, "/foo")

    def test_no_separator(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# No plan\n")
            f.flush()
            meta = read_task_metadata(Path(f.name))
        self.assertIsNone(meta.run_id)


class ReadTaskPlanTest(unittest.TestCase):
    def test_parses_steps(self) -> None:
        content = (
            f"# Task\n\n{SEPARATOR}\n<!-- status: approved | run_id: r1 -->\n\n"
            "- [x] Step 1: done\n- [ ] Step 2: todo\n- [ ] Step 3: future\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            steps = read_task_plan(Path(f.name))
        self.assertEqual(len(steps), 3)
        self.assertTrue(steps[0].done)
        self.assertEqual(steps[0].text, "Step 1: done")
        self.assertFalse(steps[1].done)
        self.assertFalse(steps[2].done)

    def test_no_separator(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# No plan\n")
            f.flush()
            steps = read_task_plan(Path(f.name))
        self.assertEqual(steps, [])


class GetCurrentStepIndexTest(unittest.TestCase):
    def test_first_unchecked(self) -> None:
        steps = [
            TaskPlanStep("a", done=True),
            TaskPlanStep("b", done=False),
            TaskPlanStep("c", done=False),
        ]
        self.assertEqual(get_current_step_index(steps), 1)

    def test_all_done(self) -> None:
        steps = [TaskPlanStep("a", done=True), TaskPlanStep("b", done=True)]
        self.assertIsNone(get_current_step_index(steps))


class WritePlanToTaskTest(unittest.TestCase):
    def test_write_new_plan(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Task\n\nDescription.\n")
            f.flush()
            path = Path(f.name)
        write_plan_to_task(path, ["Step 1: a", "Step 2: b"], "run1", "/repo")
        content = path.read_text()
        self.assertIn(SEPARATOR, content)
        self.assertIn("- [ ] Step 1: a", content)
        self.assertIn("- [ ] Step 2: b", content)
        self.assertIn("run_id: run1", content)
        self.assertIn("work_repo: /repo", content)

    def test_overwrite_existing_plan(self) -> None:
        initial = f"# Task\n\nBody\n\n{SEPARATOR}\n<!-- status: approved | run_id: old -->\n\n- [x] Old step\n"
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(initial)
            f.flush()
            path = Path(f.name)
        write_plan_to_task(path, ["New step 1"], "new_run", "/new_repo")
        content = path.read_text()
        self.assertIn("- [ ] New step 1", content)
        self.assertNotIn("Old step", content)
        self.assertIn("run_id: new_run", content)
        self.assertIn("# Task", content)
        self.assertIn("Body", content)


class MarkStepDoneTest(unittest.TestCase):
    def test_marks_correct_step(self) -> None:
        content = (
            f"# Task\n\n{SEPARATOR}\n<!-- status: approved | run_id: r1 -->\n\n"
            "- [x] Step 1: done\n- [ ] Step 2: current\n- [ ] Step 3: future\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        mark_step_done(path, 1)
        updated = path.read_text()
        self.assertIn("- [x] Step 2: current", updated)
        self.assertIn("- [ ] Step 3: future", updated)

    def test_no_separator_is_noop(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# No plan\n")
            f.flush()
            path = Path(f.name)
        mark_step_done(path, 0)
        self.assertEqual(path.read_text(), "# No plan\n")


class WorktreeMetadataTest(unittest.TestCase):
    def test_write_and_read_worktree_fields(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Task\n\nBody\n")
            f.flush()
            path = Path(f.name)
        write_plan_to_task(
            path, ["step 1"], "run_wt", "/repo",
            worktree_path="/repo/.srachka/worktrees/srachka/run_wt",
            worktree_branch="srachka/run_wt",
            base_branch="main",
        )
        meta = read_task_metadata(path)
        self.assertEqual(meta.worktree_path, "/repo/.srachka/worktrees/srachka/run_wt")
        self.assertEqual(meta.worktree_branch, "srachka/run_wt")
        self.assertEqual(meta.base_branch, "main")

    def test_no_worktree_fields_returns_none(self) -> None:
        content = f"# Task\n\n{SEPARATOR}\n<!-- status: approved | run_id: old -->\n\n- [ ] Step 1\n"
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            meta = read_task_metadata(Path(f.name))
        self.assertIsNone(meta.worktree_path)
        self.assertIsNone(meta.worktree_branch)
        self.assertIsNone(meta.base_branch)


class RoundTripTest(unittest.TestCase):
    def test_write_then_read(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# My Task\n\nRequirements here.\n")
            f.flush()
            path = Path(f.name)

        steps = ["Step 1: create module", "Step 2: add tests"]
        write_plan_to_task(path, steps, "run_42", "/work", status="approved")

        body = read_task_text(path)
        self.assertIn("# My Task", body)
        self.assertNotIn("Step 1", body)

        meta = read_task_metadata(path)
        self.assertEqual(meta.run_id, "run_42")
        self.assertEqual(meta.work_repo, "/work")
        self.assertEqual(meta.status, "approved")

        plan = read_task_plan(path)
        self.assertEqual(len(plan), 2)
        self.assertFalse(plan[0].done)

        mark_step_done(path, 0)
        plan2 = read_task_plan(path)
        self.assertTrue(plan2[0].done)
        self.assertFalse(plan2[1].done)
        self.assertEqual(get_current_step_index(plan2), 1)


if __name__ == "__main__":
    unittest.main()
