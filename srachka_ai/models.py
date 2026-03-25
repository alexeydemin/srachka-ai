from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Issue:
    severity: str
    message: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Issue":
        return cls(
            severity=str(data.get("severity", "medium")),
            message=str(data.get("message", "")),
        )


@dataclass
class PlanDraft:
    status: str
    summary: str
    steps: list[str]
    risks: list[str]
    open_questions: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanDraft":
        return cls(
            status=str(data["status"]),
            summary=str(data["summary"]),
            steps=[str(x) for x in data["steps"]],
            risks=[str(x) for x in data["risks"]],
            open_questions=[str(x) for x in data["open_questions"]],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanReview:
    status: str
    summary: str
    issues: list[Issue]
    requested_changes: list[str]
    question_for_user: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanReview":
        return cls(
            status=str(data["status"]),
            summary=str(data["summary"]),
            issues=[Issue.from_dict(x) for x in data.get("issues", [])],
            requested_changes=[str(x) for x in data.get("requested_changes", [])],
            question_for_user=(None if data.get("question_for_user") is None else str(data.get("question_for_user"))),
        )

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["issues"] = [asdict(x) for x in self.issues]
        return out


@dataclass
class DiffReview:
    status: str
    summary: str
    issues: list[Issue]
    required_fixes: list[str]
    done_enough: bool
    question_for_user: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiffReview":
        return cls(
            status=str(data["status"]),
            summary=str(data["summary"]),
            issues=[Issue.from_dict(x) for x in data.get("issues", [])],
            required_fixes=[str(x) for x in data.get("required_fixes", [])],
            done_enough=bool(data.get("done_enough", False)),
            question_for_user=(None if data.get("question_for_user") is None else str(data["question_for_user"])),
        )

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["issues"] = [asdict(x) for x in self.issues]
        return out


@dataclass
class RunState:
    task: str
    run_id: str
    work_repo: str
    current_step_index: int
    plan: PlanDraft
    final_plan_review: PlanReview
    review_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "run_id": self.run_id,
            "work_repo": self.work_repo,
            "current_step_index": self.current_step_index,
            "plan": self.plan.to_dict(),
            "final_plan_review": self.final_plan_review.to_dict(),
            "review_history": self.review_history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        return cls(
            task=str(data["task"]),
            run_id=str(data["run_id"]),
            work_repo=str(data.get("work_repo", ".")),
            current_step_index=int(data.get("current_step_index", 0)),
            plan=PlanDraft.from_dict(data["plan"]),
            final_plan_review=PlanReview.from_dict(data["final_plan_review"]),
            review_history=list(data.get("review_history", [])),
        )

    @property
    def current_step(self) -> str | None:
        if self.current_step_index < 0:
            return None
        if self.current_step_index >= len(self.plan.steps):
            return None
        return self.plan.steps[self.current_step_index]
