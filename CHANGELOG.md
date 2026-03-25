# Changelog

## Done

| Status | Feature | Description | Created | Done |
|--------|---------|-------------|---------|------|
| [x] | Pretty logging | Timestamps, duration, token usage per step in orchestrator output | 2026-03-24 | 2026-03-24 |
| [x] | Better CLI UX | Global CLI install via `pipx install -e .`, `srachka` command available from any directory. Fixed Claude auth (CLAUDE_CONFIG_DIR bug). | 2026-03-24 | 2026-03-24 |
| [x] | `srachka do-step` | Implement-review-fix loop: Claude implements, Codex reviews, auto-fix up to N rounds, auto next-step on accept. | 2026-03-24 | 2026-03-24 |
| [x] | Commit per step | Clean repo guard + `git add -A` + `git diff --cached` + auto-commit after accept. | 2026-03-24 | 2026-03-24 |
| [x] | `srachka init` | Prints MD prompt for Claude orchestrator: pre-flight, branch, plan, do-step loop, final validation, PR, CI, timeouts. | 2026-03-24 | 2026-03-25 |
| [x] | File logging + `srachka logs` | Full debate logging to `logs/{run_id}.log` (prompts, responses, diffs, errors). `srachka logs` does `tail -f` on latest log. | 2026-03-24 | 2026-03-25 |

## Lives in the orchestrator prompt (not code)

Эти фичи — инструкции в MD-промпте из `srachka init`:

- **Auto branch creation** — "определи base branch, создай feature branch"
- **Auto PR creation** — "посмотри как делаются PR в этом проекте, создай по образцу"
- **PR CI check** — "определи CI систему, проверь чеки, если упало — чини"
- **Final validation** — "после всех шагов — полный diff review перед PR"
- **Step timeout** — "10 мин на любую операцию, пропустить если зависло"
