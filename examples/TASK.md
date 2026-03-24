Build a small orchestration loop for Claude Code and Codex.

Requirements:

1. Claude should draft a minimal implementation plan.
2. Codex should review that plan and call out missing risks or over engineering.
3. Claude should revise until the plan is approved or a human decision is needed.
4. During implementation, Codex should review the current diff before Claude stops.
5. The system should be simple, local first, and easy to understand.
6. Avoid unnecessary dependencies.
