# srachka init — orchestrator prompt task

## What it does

`srachka init` prints an MD prompt that teaches a Claude session how to use srachka end-to-end. The user opens a project repo, tells Claude "use srachka", and Claude runs `srachka init` to get instructions.

## What the prompt must contain

### 1. Introduction
- "I am srachka. I orchestrate Claude (planner/implementer) and Codex (reviewer)."
- Install: `pipx install -e ~/personal/ai_srachka`
- Available commands: `plan`, `show-step`, `next-step`, `review-diff`, `do-step`, `doctor`

### 2. Pre-flight: clean repo requirement
- Before starting, verify repo is clean: `git status --porcelain` must be empty
- If dirty — run `git stash -u` first (stashes both tracked changes AND untracked files)
- srachka works only on clean repos — this makes `git add -A` safe after each step

### 3. Branch creation
- Determine base branch: check which of `main`, `master`, `develop` exists
- `git fetch origin && git checkout <base> && git pull`
- Create feature branch: `git checkout -b <task-id>/<short-description>`
- Never work directly on the base branch

### 4. Planning
- `srachka plan --task-file <path-to-task.md>`
- Wait for plan to be approved (Claude and Codex will debate)
- If status is `ask_user` — print the question and stop
- Do NOT ask the user for confirmation — just proceed to implementation

### 5. Implementation loop
- For each step:
  - `srachka do-step` — Claude implements, Codex reviews, auto-fix loop
  - OR manual: `srachka show-step` → implement → `srachka review-diff` → `srachka next-step`
- After each accepted step, changes are auto-committed (commit-per-step feature)
- Commit without asking the user for confirmation — you have full authority to commit
- Continue until all steps complete

### 6. Final validation
- After all steps complete, run a final sanity check before creating a PR
- Get the full diff vs base branch: `git diff main...HEAD`
- Run `srachka review-diff --stdin-diff` with this diff piped in, so Codex reviews the complete result against the original task
- Codex checks: is the task fully implemented? Any regressions? Does it all fit together?
- If Codex rejects — do one round of fixes, commit, and re-validate
- If rejected again after the fix round — stop and ask the user
- Do NOT go back to planning — the plan was correct, only the implementation needs fixing

### 7. PR creation
- After validation passes, push the branch: `git push -u origin <branch>`
- Look at existing PRs in the repo to understand title/description format
- Use your memory of the project to match the convention
- Create PR via `gh pr create` following the same style
- Include a summary of what was done and link to the task

### 8. CI check
- After PR is created, check CI status: `gh pr checks <pr-number>`
- Determine what CI system is used (GitHub Actions, CircleCI, Jenkins, etc.)
- Look at the repo's CI config files to understand the setup
- If checks fail:
  - Read the CI logs
  - Fix the issue
  - Run `srachka review-diff` on the fix
  - Commit and push
  - Re-check CI
- Repeat until all checks pass

### 9. Timeouts
- Every srachka command has a 10-minute timeout
- If any operation exceeds 10 minutes — skip it and move on
- Log which step/operation was skipped and why
- Note it for human review

### 10. Rules of behavior
- Be fully autonomous — do NOT ask the user for confirmation at any step
- Do NOT stop between steps to report progress — just keep going
- Commit after each accepted step without asking — you have authority to commit
- Only stop if `ask_user` status is returned by the debate
- If something breaks — try to fix it, don't ask
- Keep commits small and focused (one per step)
- Commit messages: step number + short description of what was done

## Design decisions we made

- High-level workflow (branch, PR, CI, timeout) lives in the PROMPT, not in code
- Low-level debate logic (plan debate, code review loop) lives in CODE (srachka CLI)
- Claude is the orchestrator runtime, MD prompt is the "program"
- srachka CLI provides atomic, reliable commands ("syscalls")
- The prompt can be edited to change workflow without touching code

## Relationship to other tasks

- Depends on: `do-step` (done), `commit-per-step` (done)
- Ready to implement as a CLI command that prints this prompt as markdown
