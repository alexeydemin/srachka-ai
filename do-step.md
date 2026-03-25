# srachka do-step: Auto implement + review loop

## Context

Currently implementing a step requires manual work:
1. `srachka show-step` — read what to do
2. Manually run Claude Code to implement the step
3. `srachka review-diff` — ask Codex to review
4. If rejected — manually fix and re-run review-diff
5. `srachka next-step` — advance

This needs to be a single command: `srachka do-step`.

## Desired Behavior

```bash
srachka do-step
```

This command:
1. Reads current step from state (same as `show-step`)
2. Launches `claude -p` with the implementation brief in the work repo
3. Waits for Claude to finish
4. Runs `git diff` to capture changes
5. Calls Codex to review the diff (same logic as `review-diff`)
6. If Codex rejects with high/medium severity issues:
   - Passes `required_fixes` back to Claude as a new prompt
   - Claude fixes the code
   - Codex re-reviews
   - Repeat up to `max_step_fix_rounds` rounds (default: 2)
7. On accept — advances to the next step (same as `next-step`)
8. Returns exit code 0 on accept, 2 on final reject, 1 on error

## Architecture

This follows the exact same debate pattern as `debate_plan()`:

```
debate_plan:  Claude generates plan → Codex reviews → reject → Claude revises → Codex re-reviews
do_step:      Claude implements step → Codex reviews diff → reject → Claude fixes → Codex re-reviews
```

### New code needed

**orchestrator.py** — new method `Orchestrator.do_step(state) -> DiffReview`:
- Loop up to `max_step_fix_rounds`:
  - Round 1: run Claude with `implementation_brief(state)` prompt
  - Get git diff
  - Run Codex review (existing `_review_diff`)
  - If accept → break
  - If reject → build fix prompt with `required_fixes`, run Claude again
- Save review history to run dir
- Return final review

**cli.py** — new subcommand `do-step`:
- No arguments needed (reads state from latest run, work repo from state)
- Calls `orchestrator.do_step(state)`
- Prints review result
- On accept: auto-advance `current_step_index` and save state

**prompts.py** — new function `fix_prompt(state, diff_review) -> str`:
- Tells Claude: "You implemented step X. Codex found these issues: [required_fixes]. Fix them."
- Includes the current step goal for context

## What NOT to do

- Do not change `debate_plan()` or `review_diff()` — they stay as they are
- Do not add git commit logic — that's the next task (commit per step)
- Do not add branch/PR logic — that lives in the orchestrator prompt
- Do not change existing commands or their arguments
- Keep `review-diff` as a standalone command for manual use
- The fix prompt should be minimal — just the fixes needed, not the full task

## Edge cases

- If there are no changes after Claude runs (empty diff) — treat as reject, log warning
- If all steps are already complete — print message and exit 0
- If `ask_user` status from review — stop the loop, print the question, exit 2
- Only high and medium severity issues trigger a fix round. Low severity issues are ignored (logged but not sent back to Claude).
