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
| [x] | Provider timeout | Threading-based timeout for `run_command_streaming` — reader threads + `process.wait(timeout=)`. `CommandTimeout` exception, synthetic reject on timeout in `do_step`. | 2026-03-25 | 2026-03-25 |
| [x] | Split config | Separate `claude_command` (planning) and `claude_implement_command` (implementation with `--effort max`). | 2026-03-25 | 2026-03-25 |
| [x] | Clean project layout | Runtime files moved to `.srachka/` (config, runs, logs, schemas, tasks). Task files gitignored — no more dirty repo from creating tasks. | 2026-03-25 | 2026-03-25 |
| [x] | Unified task+plan file | Таск и план живут в одном .md файле — план дописывается после разделителя, прогресс через чекбоксы. `--task-file` во всех CLI командах. | 2026-03-25 | 2026-03-26 |

## Backlog

| Status | Feature | Description | Task | Created |
|--------|---------|-------------|------|---------|
| [ ] | Worktree isolation | srachka автоматически создаёт git worktree при запуске — вся работа в изоляции, юзер может продолжать работать | [worktree-isolation.md](.srachka/tasks/worktree-isolation.md) | 2026-03-25 |
| [x] | Unified task+plan file | Таск и план живут в одном .md файле — план дописывается после разделителя, прогресс через чекбоксы | [unified-task-plan-file.md](.srachka/tasks/unified-task-plan-file.md) | 2026-03-25 |
| [x] | Fix commit messages | Auto-commit убирает дублирование `Step N: Step N:` — strip prefix перед форматированием. | | 2026-03-26 |
| [x] | Srachka Autopilot | Интерактивный запуск: выбор задания из `.srachka/tasks/`, 3 режима автономности (Хуяч / Покажи план / Полный контроль), авто-коммиты всегда | [srachka-autopilot.md](.srachka/tasks/srachka-autopilot.md) | 2026-03-26 |

## Lives in the orchestrator prompt (not code)

Эти фичи — инструкции в MD-промпте из `srachka init`:

- **Auto branch creation** — "определи base branch, создай feature branch"
- **Auto PR creation** — "посмотри как делаются PR в этом проекте, создай по образцу"
- **PR CI check** — "определи CI систему, проверь чеки, если упало — чини"
- **Final validation** — "после всех шагов — полный diff review перед PR"
- **Step timeout** — "10 мин на любую операцию, пропустить если зависло"
