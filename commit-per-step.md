# Commit per step

## Context

After `srachka do-step` accepts a step, the changes remain uncommitted. This means:
- `review-diff` sees the full accumulated diff of all steps, not just the current one
- If something breaks later, there's no clean rollback point per step
- The diff grows larger with each step, making Codex reviews slower and less accurate

## Key design decision: clean repo requirement

`git add -A` is safe because srachka requires a clean repo before starting:
- `srachka plan` and `srachka do-step` should check `git status --porcelain` is empty
- If dirty — refuse to run and tell user to `git stash -u` first
- `git stash -u` stashes both tracked changes AND untracked files (but not gitignored)
- With a clean start, the only changes after each step are Claude's — so `git add -A` is safe
- `.gitignore` is the last safety net for `.env`, `node_modules`, etc.

## Desired Behavior

After `do-step` accepts a step, automatically:
1. `git add -A` (stage all changes including new files Claude created)
2. `git commit -m "Step N: <step description>"` with a concise message

Before `do-step` and `plan` start:
1. Check `git status --porcelain` — if not empty, raise error with message to stash/commit first

Also, `_raw_git_diff()` in orchestrator and `_git_diff()` in cli should use `git diff HEAD` instead of `git diff`, so new untracked files staged by `git add -A` are also captured in reviews.

## What to change

### orchestrator.py — `do_step()`
- Before starting the loop: check repo is clean, raise if not
- After the review loop accepts: `git add -A && git commit` in work_root
- Commit message: `"Step {N}: {first ~70 chars of step description}"`
- If commit fails (nothing to commit), log warning but don't error

### orchestrator.py — `_raw_git_diff()`
- Before getting diff: run `git add -A` to stage new files
- Change from `git diff` to `git diff --cached` (shows staged changes)
- This ensures Claude's newly created files appear in the diff

### cli.py — `_git_diff()`
- Same approach: `git add -A` then `git diff --cached`
- Or simpler: keep `git diff HEAD` which shows all changes vs last commit (both staged and unstaged)

### orchestrator.py — `debate_plan()`
- Add clean-repo check at the start

## What NOT to do

- Do not push — just local commits
- Do not create branches — that's in the orchestrator prompt
- Do not change the commit message format to be fancy — keep it simple
- Do not add a `--no-commit` flag — keep it simple for now
