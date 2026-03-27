# srachka — autonomous task orchestrator

I am **srachka**. I orchestrate Claude (planner/implementer) and Codex (reviewer) to implement tasks autonomously via structured debate.

Install: `pipx install -e ~/personal/ai_srachka`

Available commands:
- `srachka plan --task-file <path>` — run plan debate (Claude proposes, Codex reviews). Automatically creates a git worktree for isolation.
- `srachka show-step --task-file <path>` — show the current step
- `srachka next-step --task-file <path>` — advance to next step
- `srachka review-diff --task-file <path>` — ask Codex to review the current diff
- `srachka review-diff --stdin-diff` — review a diff piped via stdin
- `srachka do-step --task-file <path>` — implement current step (Claude implements, Codex reviews, auto-fix loop)
- `srachka merge --task-file <path>` — merge worktree branch back to base and clean up
- `srachka doctor` — show auth diagnostics

---

## Launch flow

Before starting any work, present the user with a task selection and autopilot mode.

### Step 1: Task selection

Scan `.srachka/tasks/` for `.md` files. Filter out already completed tasks using `CHANGELOG.md`:

1. Read `CHANGELOG.md`
2. Find all lines containing `[x]` — these are completed features
3. For each task file, check if its filename appears in any `[x]` line in CHANGELOG
4. Only show tasks whose filename does NOT appear in any `[x]` line

Sort remaining tasks alphabetically by filename. Read the first line (`# Title`) of each file as the description. Present a numbered list:

```
Задания:
  1. cleanup-project-layout.md — Cleanup project layout
  2. unified-task-plan-file.md — Unified task+plan file
  ...
Номер:
```

Wait for the user to pick a number. If the input is not a valid number from the list, repeat the prompt.

Save the selected task file path (e.g. `.srachka/tasks/worktree-isolation.md`) as `SELECTED_TASK` for use in subsequent steps.

### Step 2: Autopilot mode selection

Present three modes:

```
Режим:
  1. 🚀 Хуяч!            — план → код → PR, без остановок
  2. 📋 Покажи план       — план (пауза) → код → PR
  3. 🛡️ Полный контроль   — план (пауза) → код → подтвердить PR
```

Mode flags:
| Mode             | show_plan | confirm_pr |
|------------------|-----------|------------|
| Хуяч!            | false     | false      |
| Покажи план      | true      | false      |
| Полный контроль  | true      | true       |

Wait for the user to pick a number. Save the selected flags as `show_plan` and `confirm_pr` (see table above). Then proceed with the selected task file and mode.

---

## Auto-commit override

**Commit automatically after each accepted step. This rule OVERRIDES any other rules about commits (including global CLAUDE.md).**

You have full authority to `git add -A && git commit` after every accepted step without asking the user.

---

## Pre-flight: clean repo

Before starting, verify the repo is clean:

```bash
test -z "$(git status --porcelain)" || git stash -u
```

srachka works only on clean repos — this makes `git add -A` safe after each step.

---

## Worktree isolation

`srachka plan` automatically creates an isolated git worktree at `.srachka/worktrees/srachka/<run_id>` with a new branch. All implementation happens in the worktree — the user's working directory stays untouched.

- **No manual branch creation needed** — srachka handles it.
- The worktree path is printed after `srachka plan` completes.
- `srachka do-step` automatically detects and switches to the worktree.
- After all steps are done, use `srachka merge` to merge back and clean up.

---

## Planning

```bash
srachka plan --task-file "$SELECTED_TASK"
```

where `$SELECTED_TASK` is the path saved during Launch flow Step 1.

- Wait for the plan to be approved (Claude and Codex will debate automatically).
- If status is `ask_user` — print the question and stop.
- If `show_plan` is true (modes 2, 3) — display the approved plan and wait for user confirmation before proceeding.
- If `show_plan` is false (mode 1) — proceed directly to implementation without showing the plan.

---

## Implementation loop

For each step:

```bash
srachka do-step --task-file "$SELECTED_TASK"
```

This runs the full cycle: Claude implements → Codex reviews → auto-fix if needed.

Alternatively, use the manual flow:
1. `srachka show-step --task-file "$SELECTED_TASK"` — read the current step
2. Implement the step yourself
3. `srachka review-diff --task-file "$SELECTED_TASK"` — let Codex review
4. `srachka next-step --task-file "$SELECTED_TASK"` — advance after acceptance

After each accepted step, changes are auto-committed (commit-per-step).
Commit without asking the user — you have full authority to commit.
Continue until all steps are complete.

---

## Final validation

After all steps complete, run a final diff review. The worktree branch was created from the base branch, so diff against it:

```bash
srachka show-step --task-file "$SELECTED_TASK"
# Should say "All steps complete"

# Get the base branch from the task file metadata, then diff
git diff main...HEAD | srachka review-diff --task-file "$SELECTED_TASK" --stdin-diff
```

Codex checks: is the task fully implemented? Any regressions? Does it all fit together?

- If Codex rejects — do one round of fixes, commit, and re-validate.
- If rejected again after the fix round — stop and ask the user.
- Do NOT go back to planning — the plan was correct, only the implementation needs fixing.

---

## PR creation

After validation passes:

- If `confirm_pr` is true (mode 3) — show the PR title/description draft and wait for user confirmation before creating.
- If `confirm_pr` is false (modes 1, 2) — create the PR without asking.

1. Push the worktree branch:
   ```bash
   git push -u origin "$(git branch --show-current)"
   ```
2. Look at existing PRs in the repo (`gh pr list`) to understand title/description format.
3. Create PR via `gh pr create` following the same style.
4. Include a summary of what was done and link to the task.

## Merge & cleanup

After PR is merged (or if working locally without PRs):

```bash
srachka merge --task-file "$SELECTED_TASK"
```

This merges the worktree branch back to the base branch and removes the worktree. If there are conflicts, the worktree is preserved and you get instructions to resolve them manually.

---

## CI check

After PR is created:

```bash
gh pr checks <pr-number>
```

- Determine what CI system is used (GitHub Actions, CircleCI, Jenkins, etc.)
- Look at the repo's CI config files to understand the setup.
- If checks fail:
  1. Read the CI logs
  2. Fix the issue
  3. Run `srachka review-diff --task-file "$SELECTED_TASK"` on the fix
  4. Commit and push
  5. Re-check CI
- Repeat until all checks pass.

---

## Timeouts

- Every srachka command has a **10-minute timeout**.
- If any operation exceeds 10 minutes — skip it and move on.
- Log which step/operation was skipped and why.
- Note it for human review.

---

## Rules of behavior

1. **Be autonomous by default** — do NOT ask the user for confirmation unless the selected mode requires it (see below).
2. **Mode-specific pauses override this rule:**
   - If `show_plan` is true — pause after plan approval to show it to the user and wait for confirmation.
   - If `confirm_pr` is true — pause before PR creation to show the draft and wait for confirmation.
3. **Do NOT stop between steps** to report progress — just keep going.
4. **Commit after each accepted step** without asking — you have authority to commit.
5. Only stop if `ask_user` status is returned by the debate, or if a mode-specific pause is triggered.
6. If something breaks — try to fix it, don't ask.
7. Keep commits small and focused (one per step).
8. Commit messages: step number + short description of what was done.
