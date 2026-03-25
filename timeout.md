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

### shell.py — CommandTimeout

Новый exception: `CommandTimeout(CommandError)` — наследник CommandError, чтобы существующие `except CommandError` перехватывали его. Поля: `timeout_s`, `elapsed_s`.

### shell.py — run_command()

Добавить параметр `timeout_s: int | None = None`, передавать в `subprocess.run(timeout=timeout_s)`. При `subprocess.TimeoutExpired` — поднять `CommandTimeout`.

### shell.py — run_command_streaming() — ОБЯЗАТЕЛЬНО ЧЕРЕЗ THREADING

**КРИТИЧНО**: НЕ использовать проверку таймаута внутри readline-loop (`for line in process.stdout`). Readline блокируется до получения `\n` — если процесс молчит, проверка таймаута никогда не выполнится.

Правильная реализация через reader-thread:
1. Запустить `threading.Thread(daemon=True)` который читает `process.stdout` построчно и выводит prefix + line в stderr (как сейчас)
2. В основном потоке вызвать `process.wait(timeout=timeout_s)`
3. Если `process.wait()` бросил `subprocess.TimeoutExpired` — `process.kill()`, `process.wait()`, join reader thread с маленьким timeout (1 сек), raise `CommandTimeout`
4. Если `process.wait()` вернулся нормально — join reader thread, вернуть результат
5. Reader thread должен иметь `try/except` на чтение — после `process.kill()` stdout закроется и thread получит ошибку, это нормально

Также надо собрать stdout из reader thread (через list или io.StringIO) чтобы вернуть `CompletedProcess` с правильным stdout.

### config.py

- Добавить `provider_timeout_s: int = 600` (10 минут) в `AppConfig` и `DEFAULT_CONFIG`
- Добавить в `_merge()`: `provider_timeout_s=int(overrides.get('provider_timeout_s', defaults.provider_timeout_s))`

### providers.py

- `ClaudeProvider.ask_json()` — добавить `timeout_s` параметр, прокинуть в `run_command_streaming()`
- `ClaudeProvider.implement()` — добавить `timeout_s` параметр, прокинуть в `run_command_streaming()`
- `CodexProvider.ask_json()` — добавить `timeout_s` параметр, прокинуть в `run_command_streaming()`

### orchestrator.py

- Во всех вызовах провайдеров передавать `timeout_s=self.config.provider_timeout_s`
- `CommandTimeout` наследует `CommandError`, поэтому существующие `except CommandError` в fallback-логике (_ask_plan, _review_plan, _review_diff) перехватят его автоматически. Менять fallback-логику НЕ нужно.
- НО: `_is_auth_failure()` НЕ должна считать таймаут auth failure. Добавить ранний `return False` если `isinstance(exc, CommandTimeout)`.
- В `do_step()`: обернуть ВСЁ тело цикла (implement + review_diff) в `try/except CommandTimeout`. При таймауте — `_flog()`, создать synthetic `DiffReview(status='reject', summary='Provider timed out', issues=[Issue(severity='high', message='...')], required_fixes=['...'], done_enough=False)`, записать в step_reviews.jsonl, `continue` к следующему раунду. High severity гарантирует что `_has_blocking_issues()` вернёт True и ветка accept не сработает.

## Что НЕ делаем

- Не делаем разные таймауты для разных операций (plan vs review vs implement) — один для всех
- Не делаем retry после таймаута — просто fail/reject
- Не меняем промпт в init_prompt.md — там уже написано правильно
- Не убиваем process group (os.killpg) — для MVP достаточно process.kill()
