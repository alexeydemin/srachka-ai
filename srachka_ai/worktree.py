"""Git worktree utilities for srachka isolation."""
from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_git_toplevel(cwd: Path) -> Path:
    """Get the git repo root (handles --work-repo subdirectories)."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Not a git repo: {cwd}\n{result.stderr.strip()}")
    return Path(result.stdout.strip())


def get_current_branch(cwd: Path) -> str:
    """Get current branch name. Raises if detached HEAD."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git rev-parse failed:\n{result.stderr.strip()}")
    branch = result.stdout.strip()
    if branch == "HEAD":
        raise RuntimeError("Cannot run srachka from detached HEAD — checkout a branch first.")
    return branch


def create_worktree(git_root: Path, branch_name: str) -> Path:
    """Create a git worktree at .srachka/worktrees/<branch_name>.

    Returns the absolute path to the new worktree.
    """
    worktree_dir = git_root / ".srachka" / "worktrees" / branch_name
    if worktree_dir.exists():
        raise RuntimeError(
            f"Worktree already exists at {worktree_dir}.\n"
            "Run 'srachka merge' to finalize, or remove it manually:\n"
            f"  git worktree remove {worktree_dir}"
        )
    result = subprocess.run(
        ["git", "worktree", "add", str(worktree_dir), "-b", branch_name],
        cwd=str(git_root),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add failed:\n{result.stderr.strip()}")
    return worktree_dir.resolve()


def remove_worktree(git_root: Path, worktree_path: Path) -> None:
    """Remove a git worktree and prune."""
    result = subprocess.run(
        ["git", "worktree", "remove", str(worktree_path), "--force"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git worktree remove failed:\n{result.stderr.strip()}")


def verify_worktree(path: Path) -> bool:
    """Check if a worktree path exists and is a valid git checkout."""
    return path.is_dir() and (path / ".git").exists()
