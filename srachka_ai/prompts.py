from __future__ import annotations

import json

from .models import DiffReview, PlanDraft, PlanReview, RunState


def plan_prompt(task: str, previous_review: PlanReview | None) -> str:
    review_block = ""
    if previous_review is not None:
        review_block = (
            "\nPrevious Codex review to address:\n"
            f"{json.dumps(previous_review.to_dict(), ensure_ascii=False, indent=2)}\n"
        )

    return f"""
You are Claude Planner.

Task:
{task}
{review_block}
Return JSON only.

Required schema:
{{
  "status": "draft",
  "summary": "short summary",
  "steps": ["step 1", "step 2"],
  "risks": ["risk 1"],
  "open_questions": ["question 1"]
}}

Rules:
1. No code.
2. Prefer the simplest workable plan.
3. Address every reviewer concern explicitly.
4. Break the work into concrete sequential steps.
5. Do not add polish work unless it is needed for correctness.
6. JSON only.
""".strip()


def review_prompt(task: str, plan: PlanDraft) -> str:
    return f"""
You are Codex Reviewer.

Task:
{task}

Plan proposal:
{json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)}

Return JSON only.

Required schema:
{{
  "status": "approved | revise | overengineered | ask_user",
  "summary": "short verdict",
  "issues": [{{"severity": "high | medium | low", "message": "..."}}],
  "requested_changes": ["change 1"],
  "question_for_user": null
}}

Rules:
1. Be practical, not perfectionist.
2. Approve when the plan is good enough to start.
3. Use overengineered only when a simpler approach is clearly better.
4. Use ask_user only for real product or business ambiguity.
5. Prefer small, local, low dependency solutions.
6. JSON only.
""".strip()


def diff_review_prompt(state: RunState, diff_text: str) -> str:
    current_step = state.current_step or "All steps complete. Only review whether the current diff cleanly finishes any remaining required work."
    return f"""
You are Codex Diff Reviewer.

Overall task:
{state.task}

Approved plan summary:
{state.plan.summary}

Current step index:
{state.current_step_index + 1} of {len(state.plan.steps)}

Current step goal:
{current_step}

Git diff to review:
{diff_text}

Return JSON only.

Required schema:
{{
  "status": "accept | reject | ask_user",
  "summary": "short verdict",
  "issues": [{{"severity": "high | medium | low", "message": "..."}}],
  "required_fixes": ["fix 1"],
  "done_enough": true,
  "question_for_user": null
}}

Rules:
1. Judge only whether this diff is good enough for the current step.
2. Do not request unrelated future improvements.
3. Reject only for correctness, missing required step work, obvious regressions, or clearly unnecessary complexity.
4. If the best answer is good enough, accept it.
5. Use ask_user only if there is a real product choice that the diff cannot resolve alone.
6. When status is ask_user, set question_for_user to the specific question.
7. JSON only.
""".strip()


def implementation_brief(state: RunState) -> str:
    lines = [
        "# Implementation brief for Claude Code",
        "",
        "You are implementing a task step by step.",
        "",
        "## Target repository",
        state.work_repo,
        "",
        "## Overall task",
        state.task,
        "",
        "## Approved plan summary",
        state.plan.summary,
        "",
        "## Steps",
    ]

    for idx, step in enumerate(state.plan.steps, start=1):
        prefix = "[CURRENT]" if idx - 1 == state.current_step_index else "[PENDING]"
        lines.append(f"{idx}. {prefix} {step}")

    lines.extend(
        [
            "",
            "## Rules",
            "1. Work only on the current step unless a tiny prerequisite is unavoidable.",
            "2. Keep the solution simple.",
            "3. Before stopping, ensure your changes match the current step goal.",
            "4. If the hook blocks you, treat the reason as required feedback and continue.",
            "5. If there is a true product ambiguity, ask the human.",
        ]
    )
    return "\n".join(lines) + "\n"


def fix_prompt(state: RunState, diff_review: DiffReview) -> str:
    current_step = state.current_step or "Unknown step"

    if not diff_review.issues and not diff_review.required_fixes:
        return (
            f"You were asked to implement this step:\n{current_step}\n\n"
            "No changes were made. Please implement the step."
        )

    blocking = [i for i in diff_review.issues if i.severity in ("high", "medium")]
    lines = [
        f"You implemented this step:\n{current_step}\n",
        "The reviewer found these blocking issues (high/medium only):\n",
    ]
    for issue in blocking:
        lines.append(f"- [{issue.severity}] {issue.message}")

    if diff_review.required_fixes:
        lines.append("\nRequired fixes:")
        for fix in diff_review.required_fixes:
            lines.append(f"- {fix}")

    lines.append("\nFix these specific problems and nothing else. Ignore any low-severity suggestions.")
    return "\n".join(lines)
