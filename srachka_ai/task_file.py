"""Read/write plan section in task markdown files.

Task file format:
    # Title
    Description...

    <!-- ===== SRACHKA PLAN ===== -->
    <!-- status: approved | run_id: 20260325_130455 | work_repo: /path/to/repo -->

    - [x] Step 1: done step
    - [ ] Step 2: current step  <-- first unchecked = current
    - [ ] Step 3: future step
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SEPARATOR = "<!-- ===== SRACHKA PLAN ===== -->"
_META_RE = re.compile(r"^<!--\s*(.+?)\s*-->$")
_STEP_RE = re.compile(r"^- \[([ xX])\] (.+)$")


@dataclass
class TaskPlanStep:
    text: str
    done: bool


@dataclass
class TaskMetadata:
    status: str | None = None
    run_id: str | None = None
    work_repo: str | None = None


def read_task_text(path: Path) -> str:
    """Return everything before the SRACHKA PLAN separator (the task body)."""
    content = path.read_text(encoding="utf-8")
    idx = content.find(SEPARATOR)
    if idx == -1:
        return content
    return content[:idx].rstrip("\n") + "\n"


def read_task_metadata(path: Path) -> TaskMetadata:
    """Parse the HTML comment metadata line after the separator."""
    content = path.read_text(encoding="utf-8")
    idx = content.find(SEPARATOR)
    if idx == -1:
        return TaskMetadata()
    after = content[idx + len(SEPARATOR) :]
    for line in after.split("\n"):
        line = line.strip()
        m = _META_RE.match(line)
        if m:
            pairs = {}
            for pair in m.group(1).split("|"):
                pair = pair.strip()
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    pairs[k.strip()] = v.strip()
            return TaskMetadata(
                status=pairs.get("status"),
                run_id=pairs.get("run_id"),
                work_repo=pairs.get("work_repo"),
            )
    return TaskMetadata()


def read_task_plan(path: Path) -> list[TaskPlanStep]:
    """Parse the checklist steps after the separator."""
    content = path.read_text(encoding="utf-8")
    idx = content.find(SEPARATOR)
    if idx == -1:
        return []
    after = content[idx + len(SEPARATOR) :]
    steps: list[TaskPlanStep] = []
    for line in after.split("\n"):
        m = _STEP_RE.match(line.strip())
        if m:
            done = m.group(1).lower() == "x"
            steps.append(TaskPlanStep(text=m.group(2), done=done))
    return steps


def get_current_step_index(steps: list[TaskPlanStep]) -> int | None:
    """Return index of first unchecked step, or None if all done."""
    for i, step in enumerate(steps):
        if not step.done:
            return i
    return None


def write_plan_to_task(
    path: Path,
    steps: list[str],
    run_id: str,
    work_repo: str,
    status: str = "approved",
) -> None:
    """Write or replace the plan section in the task file."""
    content = path.read_text(encoding="utf-8")
    idx = content.find(SEPARATOR)
    if idx == -1:
        body = content.rstrip("\n")
    else:
        body = content[:idx].rstrip("\n")

    meta_line = f"<!-- status: {status} | run_id: {run_id} | work_repo: {work_repo} -->"
    checklist = "\n".join(f"- [ ] {step}" for step in steps)
    plan_section = f"\n\n{SEPARATOR}\n{meta_line}\n\n{checklist}\n"
    path.write_text(body + plan_section, encoding="utf-8")


def mark_step_done(path: Path, step_index: int) -> None:
    """Change the Nth unchecked step from [ ] to [x]."""
    content = path.read_text(encoding="utf-8")
    idx = content.find(SEPARATOR)
    if idx == -1:
        return
    before = content[:idx]
    after = content[idx:]

    lines = after.split("\n")
    step_count = 0
    for i, line in enumerate(lines):
        m = _STEP_RE.match(line.strip())
        if m:
            if step_count == step_index:
                lines[i] = line.replace("- [ ]", "- [x]", 1)
                break
            step_count += 1

    path.write_text(before + "\n".join(lines), encoding="utf-8")
