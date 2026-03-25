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
- Continue until all steps complete

### 6. PR creation
- After all steps done and committed, push the branch: `git push -u origin <branch>`
- Look at existing PRs in the repo to understand title/description format
- Use your memory of the project to match the convention
- Create PR via `gh pr create` following the same style
- Include a summary of what was done and link to the task

### 7. CI check
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

### 8. Step timeout
- If a step takes more than 15 minutes — skip it
- Log which step was skipped and why
- Note it for human review

### 9. Rules of behavior
- Do NOT ask the user for confirmation at any step — be fully autonomous
- Do NOT stop between steps to report progress — just keep going
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

- Depends on: `do-step` (done), `commit-per-step` (next task)
- `commit-per-step` adds auto-commit after accept — the prompt references this
- After both are done, `srachka init` can be implemented as a CLI command that prints this prompt
