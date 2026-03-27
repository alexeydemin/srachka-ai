"""Tests for CLI --task-file integration and related helpers."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from srachka_ai import cli
from srachka_ai.models import PlanDraft, PlanReview, RunState
from srachka_ai.state import save_run_state
from srachka_ai.task_file import SEPARATOR, write_plan_to_task


class FormatStepProgressTest(unittest.TestCase):
    def test_normal_step(self) -> None:
        self.assertEqual(cli._format_step_progress(0, 3), "1/3")
        self.assertEqual(cli._format_step_progress(2, 5), "3/5")

    def test_all_done(self) -> None:
        self.assertEqual(cli._format_step_progress(3, 3), "3/3")

    def test_zero_total(self) -> None:
        self.assertEqual(cli._format_step_progress(0, 0), "0/0")

    def test_overflow_clamped(self) -> None:
        self.assertEqual(cli._format_step_progress(10, 3), "3/3")


class TaskFileSuggestionsTest(unittest.TestCase):
    def test_returns_close_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "TASK_GOLD.md").write_text("# gold\n")
            (work / "TASK_SILVER.md").write_text("# silver\n")
            (work / "README.md").write_text("# readme\n")

            suggestions = cli._task_file_suggestions(Path("TASK_GOLD.md"), work)
            names = [s.name for s in suggestions]
            self.assertIn("TASK_GOLD.md", names)

    def test_returns_top_files_when_no_close_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "alpha.md").write_text("a\n")
            (work / "beta.md").write_text("b\n")

            suggestions = cli._task_file_suggestions(Path("zzzzzzz.md"), work)
            self.assertGreater(len(suggestions), 0)

    def test_ignores_hidden_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            hidden = work / ".git" / "notes.md"
            hidden.parent.mkdir()
            hidden.write_text("hidden\n")
            (work / "visible.md").write_text("ok\n")

            suggestions = cli._task_file_suggestions(Path("notes.md"), work)
            paths_str = [str(s) for s in suggestions]
            self.assertTrue(all(".git" not in p for p in paths_str))


class ResolveTaskFileTest(unittest.TestCase):
    def test_absolute_path(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Task\n")
            f.flush()
            resolved = cli._resolve_task_file(f.name, Path("/dummy"))
        self.assertEqual(resolved, Path(f.name).resolve())

    def test_relative_path_cwd_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd_file = Path(tmp) / "TASK.md"
            cwd_file.write_text("# cwd\n")

            prev = Path.cwd()
            os.chdir(tmp)
            try:
                resolved = cli._resolve_task_file("TASK.md", Path("/nonexistent"))
            finally:
                os.chdir(prev)
            self.assertEqual(resolved, cwd_file.resolve())

    def test_raises_cli_error_with_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "SIMILAR.md").write_text("# sim\n")

            with self.assertRaises(cli.CliError) as ctx:
                cli._resolve_task_file("SIMLAR.md", work)
            self.assertIn("Task file not found", str(ctx.exception))


class ResolveStateFromTaskFileTest(unittest.TestCase):
    def _make_task_file(self, tmp: Path, steps: list[str], run_id: str = "run_1") -> Path:
        tf = tmp / "task.md"
        tf.write_text("# Task\n\nBody\n")
        write_plan_to_task(tf, steps, run_id, str(tmp / "work"))
        return tf

    def test_rebuilds_state_from_task_file_without_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_root = tmp_path / "runs"
            runs_root.mkdir()
            tf = self._make_task_file(tmp_path, ["step A", "step B"], "run_1")

            run_dir, state = cli._resolve_state_from_task_file(tf, runs_root)

            self.assertEqual(state.run_id, "run_1")
            self.assertEqual(state.plan.steps, ["step A", "step B"])
            self.assertEqual(state.current_step_index, 0)
            self.assertIn("# Task", state.task)
            self.assertTrue((runs_root / "run_1" / "state.json").exists())

    def test_refreshes_existing_state_from_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_root = tmp_path / "runs"
            run_dir = runs_root / "run_2"
            run_dir.mkdir(parents=True)

            old_state = RunState(
                task="old task",
                run_id="run_2",
                work_repo="/old",
                current_step_index=0,
                plan=PlanDraft(status="draft", summary="old", steps=["old step"], risks=[], open_questions=[]),
                final_plan_review=PlanReview(
                    status="draft", summary="old", issues=[], requested_changes=[], question_for_user=None,
                ),
            )
            save_run_state(run_dir, old_state, "old brief")

            tf = tmp_path / "task.md"
            tf.write_text("# New Task\n\nNew body\n")
            write_plan_to_task(tf, ["new step 1", "new step 2"], "run_2", str(tmp_path))

            _, state = cli._resolve_state_from_task_file(tf, runs_root)

            self.assertEqual(state.plan.steps, ["new step 1", "new step 2"])
            self.assertIn("# New Task", state.task)
            self.assertEqual(state.current_step_index, 0)

    def test_raises_on_missing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = Path(tmp) / "task.md"
            tf.write_text("# No plan\n")

            with self.assertRaises(cli.CliError) as ctx:
                cli._resolve_state_from_task_file(tf, Path(tmp) / "runs")
            self.assertIn("no plan yet", str(ctx.exception).lower())


class CmdShowStepTaskFileTest(unittest.TestCase):
    def test_show_step_from_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = Path(tmp) / "task.md"
            tf.write_text("# Task\n\nBody\n")
            write_plan_to_task(tf, ["alpha", "beta", "gamma"], "run_show", str(tmp))

            args = mock.Mock()
            args.task_file = str(tf)

            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                code = cli.cmd_show_step(args)

            self.assertEqual(code, 0)
            out = stdout.getvalue()
            self.assertIn("run_show", out)
            self.assertIn("1/3", out)
            self.assertIn("alpha", out)

    def test_show_step_all_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = Path(tmp) / "task.md"
            content = (
                f"# Task\n\n{SEPARATOR}\n"
                f"<!-- status: approved | run_id: run_done | work_repo: {tmp} -->\n\n"
                "- [x] step one\n- [x] step two\n"
            )
            tf.write_text(content)

            args = mock.Mock()
            args.task_file = str(tf)

            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                code = cli.cmd_show_step(args)

            self.assertEqual(code, 0)
            self.assertIn("2/2", stdout.getvalue())
            self.assertIn("All steps complete", stdout.getvalue())


class ResolveStateWorktreeFieldsTest(unittest.TestCase):
    def test_recovery_includes_worktree_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_root = tmp_path / "runs"
            runs_root.mkdir()

            tf = tmp_path / "task.md"
            tf.write_text("# Task\n\nBody\n")
            write_plan_to_task(
                tf, ["step 1"], "run_wt", str(tmp_path),
                worktree_path=str(tmp_path / "wt"),
                worktree_branch="srachka/run_wt",
                base_branch="main",
            )

            _, state = cli._resolve_state_from_task_file(tf, runs_root)

            self.assertEqual(state.worktree_path, str(tmp_path / "wt"))
            self.assertEqual(state.worktree_branch, "srachka/run_wt")
            self.assertEqual(state.base_branch, "main")
            self.assertEqual(state.active_work_root, str(tmp_path / "wt"))

    def test_recovery_without_worktree_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_root = tmp_path / "runs"
            runs_root.mkdir()

            tf = tmp_path / "task.md"
            tf.write_text("# Task\n\nBody\n")
            write_plan_to_task(tf, ["step 1"], "run_no_wt", str(tmp_path))

            _, state = cli._resolve_state_from_task_file(tf, runs_root)

            self.assertIsNone(state.worktree_path)
            self.assertIsNone(state.worktree_branch)
            self.assertIsNone(state.base_branch)
            self.assertEqual(state.active_work_root, str(tmp_path))


class CmdMergeTest(unittest.TestCase):
    def test_merge_errors_without_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_root = tmp_path / "runs"
            runs_root.mkdir()

            tf = tmp_path / "task.md"
            tf.write_text("# Task\n\nBody\n")
            write_plan_to_task(tf, ["step 1"], "run_merge_no_wt", str(tmp_path))

            args = mock.Mock()
            args.task_file = str(tf)

            with mock.patch.object(cli, "_build_orchestrator") as mock_build:
                mock_build.return_value = (tmp_path, mock.Mock(), runs_root)
                with self.assertRaises(cli.CliError) as ctx:
                    cli.cmd_merge(args)
            self.assertIn("no worktree", str(ctx.exception).lower())

    def test_merge_errors_on_missing_worktree_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_root = tmp_path / "runs"
            runs_root.mkdir()

            tf = tmp_path / "task.md"
            tf.write_text("# Task\n\nBody\n")
            write_plan_to_task(
                tf, ["step 1"], "run_merge_missing", str(tmp_path),
                worktree_path=str(tmp_path / "nonexistent_wt"),
                worktree_branch="srachka/test",
                base_branch="main",
            )

            args = mock.Mock()
            args.task_file = str(tf)

            with mock.patch.object(cli, "_build_orchestrator") as mock_build:
                mock_build.return_value = (tmp_path, mock.Mock(), runs_root)
                with self.assertRaises(cli.CliError) as ctx:
                    cli.cmd_merge(args)
            self.assertIn("not found", str(ctx.exception).lower())


class CmdNextStepTaskFileTest(unittest.TestCase):
    def test_next_step_marks_done_and_advances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_root = tmp_path / "runs"
            runs_root.mkdir()

            tf = tmp_path / "task.md"
            tf.write_text("# Task\n\nBody\n")
            write_plan_to_task(tf, ["step 1", "step 2", "step 3"], "run_next", str(tmp_path))

            args = mock.Mock()
            args.task_file = str(tf)

            with mock.patch.object(cli, "_build_orchestrator") as mock_build:
                mock_build.return_value = (tmp_path, mock.Mock(), runs_root)
                stdout = io.StringIO()
                with mock.patch("sys.stdout", stdout):
                    code = cli.cmd_next_step(args)

            self.assertEqual(code, 0)
            self.assertIn("2/3", stdout.getvalue())

            updated = tf.read_text()
            self.assertIn("- [x] step 1", updated)
            self.assertIn("- [ ] step 2", updated)


if __name__ == "__main__":
    unittest.main()
