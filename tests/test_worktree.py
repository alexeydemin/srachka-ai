"""Tests for srachka_ai/worktree.py utilities."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from srachka_ai.worktree import (
    create_worktree,
    get_current_branch,
    resolve_git_toplevel,
    verify_worktree,
)


class VerifyWorktreeTest(unittest.TestCase):
    def test_valid_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "wt"
            wt.mkdir()
            (wt / ".git").write_text("gitdir: fake")
            self.assertTrue(verify_worktree(wt))

    def test_missing_dir(self) -> None:
        self.assertFalse(verify_worktree(Path("/nonexistent/path")))

    def test_dir_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(verify_worktree(Path(tmp)))


class ResolveGitToplevelTest(unittest.TestCase):
    def test_resolves_from_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=str(root), capture_output=True, check=True)
            sub = root / "a" / "b"
            sub.mkdir(parents=True)
            result = resolve_git_toplevel(sub)
            self.assertEqual(result, root.resolve())

    def test_raises_on_non_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                resolve_git_toplevel(Path(tmp))


class GetCurrentBranchTest(unittest.TestCase):
    def test_returns_branch_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-b", "main"], cwd=str(root), capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "init"],
                cwd=str(root), capture_output=True, check=True,
            )
            branch = get_current_branch(root)
            self.assertEqual(branch, "main")


class CreateWorktreeTest(unittest.TestCase):
    def test_creates_and_raises_on_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-b", "main"], cwd=str(root), capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "init"],
                cwd=str(root), capture_output=True, check=True,
            )
            wt = create_worktree(root, "srachka/test")
            self.assertTrue(wt.is_dir())
            self.assertTrue((wt / ".git").exists())

            with self.assertRaises(RuntimeError) as ctx:
                create_worktree(root, "srachka/test")
            self.assertIn("already exists", str(ctx.exception))

            # Cleanup
            subprocess.run(
                ["git", "worktree", "remove", str(wt), "--force"],
                cwd=str(root), capture_output=True,
            )


if __name__ == "__main__":
    unittest.main()
