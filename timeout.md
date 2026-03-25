# Таймаут на вызовы провайдеров

## Проблема

Сейчас `claude -p` и `codex exec` запускаются через `subprocess` без ограничения по времени. Реальные случаи:
- Claude думал 16 минут над планом (opus + max effort)
- Codex ревьюил diff 7 минут
- Claude завис на 10+ минут при попытке написать тесты

Промпт `srachka init` говорит "10-minute timeout", но в коде таймаута нет.

## Что делаем

Добавить таймаут на уровне `shell.py` — каждый вызов `run_command` и `run_command_streaming` должен убивать процесс если он не завершился за N секунд.

## Реализация

### shell.py

- `run_command()` — добавить параметр `timeout_s: int | None = None`, передавать в `subprocess.run(timeout=timeout_s)`
- `run_command_streaming()` — сложнее, т.к. используется `Popen`. Нужен отдельный таймер:
  - Запомнить `time.monotonic()` на старте
  - В цикле чтения stdout проверять `elapsed > timeout_s`
  - Если превышен — `process.kill()`, `process.wait()`, raise `TimeoutError` (или свой `CommandTimeout`)
- Новый exception: `CommandTimeout(CommandError)` — чтобы orchestrator мог различать таймаут от обычной ошибки

### config.py

- Добавить `provider_timeout_s: int = 600` (10 минут) в `AppConfig`

### orchestrator.py

- Передавать `timeout_s=self.config.provider_timeout_s` во все вызовы провайдеров
- При `CommandTimeout` — логировать через `_flog()` и пробрасывать наверх
- В `do_step()`: если таймаут — считать как reject, переходить к следующему раунду фиксов (или стоп если раунды кончились)

### providers.py

- `ClaudeProvider.ask_json()`, `implement()` — прокинуть timeout_s
- `CodexProvider.ask_json()` — прокинуть timeout_s

## Что НЕ делаем

- Не делаем разные таймауты для разных операций (plan vs review vs implement) — один для всех
- Не делаем retry после таймаута — просто fail
- Не меняем промпт в init_prompt.md — там уже написано правильно
