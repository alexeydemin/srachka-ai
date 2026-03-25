from __future__ import annotations

from pathlib import Path

from .models import RunState
from .utils import write_json
import json


STATE_FILE_NAME = "state.json"
PLAN_FILE_NAME = "plan.json"
REVIEW_HISTORY_FILE_NAME = "review.jsonl"
STEP_REVIEWS_FILE_NAME = "step_reviews.jsonl"
IMPLEMENTATION_BRIEF_NAME = "implementation_brief.md"
LATEST_POINTER_NAME = "latest"


def save_run_state(run_dir: Path, state: RunState, implementation_text: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / STATE_FILE_NAME, state.to_dict())
    write_json(run_dir / PLAN_FILE_NAME, state.plan.to_dict())
    (run_dir / IMPLEMENTATION_BRIEF_NAME).write_text(implementation_text, encoding="utf-8")


def read_run_state(run_dir: Path) -> RunState:
    data = json.loads((run_dir / STATE_FILE_NAME).read_text(encoding="utf-8"))
    return RunState.from_dict(data)


def point_latest(runs_root: Path, run_dir: Path) -> None:
    latest_path = runs_root / LATEST_POINTER_NAME
    latest_path.write_text(run_dir.name + "\n", encoding="utf-8")


def resolve_latest_run_dir(runs_root: Path) -> Path:
    latest_path = runs_root / LATEST_POINTER_NAME
    if not latest_path.exists():
        raise FileNotFoundError("No latest run found. Run the plan command first.")
    run_name = latest_path.read_text(encoding="utf-8").strip()
    return runs_root / run_name
