# Changelog

| Status | Feature | Description | Created | Done |
|--------|---------|-------------|---------|------|
| [x] | Pretty logging | Timestamps, duration, token usage per step in orchestrator output | 2026-03-24 | 2026-03-24 |
| [ ] | File logging | Auto-write logs to file so you can `tail -f logs/run.log` from another terminal | 2026-03-24 | |
| [ ] | Auto code review loop | After implementation, Claude and Codex should debate the diff automatically (like they do for the plan). Codex reviews -> if reject (high/medium only, ignore low) -> Claude fixes -> Codex re-reviews, up to N rounds. No manual intervention needed. | 2026-03-24 | |
| [ ] | Commit per step | Auto-commit after each Claude step. review-diff compares last commit only (git diff HEAD~1) instead of full unstaged diff. Smaller diffs = faster/better Codex reviews. | 2026-03-24 | |
| [ ] | Auto branch creation | At plan start: git fetch, checkout fresh base branch (develop/master/main — detect which exists), pull latest, then create feature branch (e.g. AI-567/feature/speak-first). Never work on an existing branch. | 2026-03-24 | |
| [ ] | Auto PR creation | After final commit+push, auto-create PR via gh CLI. Look at existing PRs in the repo for title/description format and follow the same convention. Also create release notes matching the project's existing notes style. | 2026-03-24 | |
| [ ] | PR CI check | After PR is created, poll `gh pr checks` until all CI checks complete. If tests fail — Claude reads logs and fixes, Codex reviews the fix, then commit+push and re-check. Same debate loop as plan/review-diff. | 2026-03-24 | |
| [ ] | Better CLI UX | Single command to run full pipeline: `srachka run --task AI-567.md --repo ~/api-core`. No need to cd between dirs or run multiple commands manually. | 2026-03-24 | |
| [ ] | Orchestrator memory | Create a reusable prompt/readme for Claude-as-orchestrator: run plan, implement steps, review-diff, fix, commit, push, PR, CI check — all automatically without asking user. | 2026-03-24 | |
| [ ] | Step timeout 15min | Each implementation step gets max 15 min. If exceeded — kill process and retry once. If still stuck — skip and note for human. | 2026-03-24 | |
