from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def schema_dir(root: Path) -> Path:
    return root / ".srachka" / "schemas"


def runs_dir(root: Path, relative_name: str) -> Path:
    return root / relative_name


def logs_dir(root: Path, relative_name: str) -> Path:
    return root / relative_name
