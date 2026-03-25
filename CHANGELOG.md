# Changelog

## Done

| Status | Feature | Description | Created | Done |
|--------|---------|-------------|---------|------|
| [x] | Pretty logging | Timestamps, duration, token usage per step in orchestrator output | 2026-03-24 | 2026-03-24 |
| [x] | Better CLI UX | Global CLI install via `pipx install -e .`, `srachka` command available from any directory. Fixed Claude auth (CLAUDE_CONFIG_DIR bug). | 2026-03-24 | 2026-03-24 |

## Backlog

| # | Feature | Польза | Труд | Что конкретно делаем |
|---|---------|--------|------|----------------------|
| 1 | `srachka do-step` | 5/5 | 3/5 | Новая CLI-команда. Внутри: читает текущий шаг из state → запускает `claude -p` с implementation brief в work repo → собирает `git diff` → вызывает `review_diff` (Codex) → если reject (high/medium) — передаёт `required_fixes` обратно Claude → повторный review → до `max_step_fix_rounds` раундов → при accept автоматически `next-step`. Новый метод `Orchestrator.do_step()` по аналогии с `debate_plan()`. |
| 2 | Commit per step | 4/5 | 2/5 | Встраивается в `do-step`: после accept — auto `git add -A && git commit` с сообщением из step description. `review-diff` переключается на `git diff HEAD~1` вместо полного unstaged diff. Коммит-сообщение генерирует Codex или берётся из step summary. |
| 3 | `srachka init` | 5/5 | 2/5 | Новая CLI-команда. Печатает MD-промпт для Claude-оркестратора. Промпт описывает: установку, workflow (branch → plan → do-step в цикле → PR → CI check), правила поведения. Блоки промпта: auto branch creation, auto PR, CI check, timeout — всё текстом, не кодом. |
| 4 | File logging | 2/5 | 1/5 | `_log()` в orchestrator.py дублирует вывод в `logs/{run_id}.log`. Файл можно `tail -f` из другого терминала. |

## Lives in the orchestrator prompt (not code)

Эти фичи — инструкции в MD-промпте из `srachka init`:

- **Auto branch creation** — "определи base branch, создай feature branch"
- **Auto PR creation** — "посмотри как делаются PR в этом проекте, создай по образцу"
- **PR CI check** — "определи CI систему, проверь чеки, если упало — чини"
- **Step timeout** — "если шаг завис >15 мин, пропусти и отметь для человека"
