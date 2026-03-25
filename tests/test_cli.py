from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from srachka_ai import cli


class CliTests(unittest.TestCase):
    def test_resolve_task_file_uses_work_repo_for_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            work_repo = tmp_path / "work_repo"
            task_file = work_repo / "docs" / "TASK.md"
            task_file.parent.mkdir(parents=True)
            task_file.write_text("# Task\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                resolved = cli._resolve_task_file("docs/TASK.md", work_repo)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(resolved, task_file.resolve())

    def test_main_returns_friendly_error_for_missing_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            work_repo = tmp_path / "work_repo"
            suggestion = work_repo / "archive" / "TEST_PLAN.md"
            suggestion.parent.mkdir(parents=True)
            suggestion.write_text("# Test plan\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            stderr = io.StringIO()
            os.chdir(tmp_path)
            try:
                with mock.patch.object(
                    sys,
                    "argv",
                    [
                        "srachka_ai",
                        "plan",
                        "--task-file",
                        "GOLD_OUT_OF_DLT.md",
                        "--work-repo",
                        str(work_repo),
                    ],
                ):
                    with redirect_stderr(stderr):
                        exit_code = cli.main()
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(exit_code, 2)
            self.assertIn("Task file not found: GOLD_OUT_OF_DLT.md", stderr.getvalue())
            self.assertIn(str(suggestion), stderr.getvalue())


    def test_init_prints_complete_prompt(self) -> None:
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["srachka_ai", "init"]):
            with unittest.mock.patch("sys.stdout", stdout):
                exit_code = cli.main()
        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        prompt_path = Path(cli.__file__).parent / "init_prompt.md"
        expected = prompt_path.read_text(encoding="utf-8")
        self.assertEqual(output.strip(), expected.strip())


if __name__ == "__main__":
    unittest.main()
