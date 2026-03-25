# File logging + srachka logs

## Что делаем

Полное логирование всего что происходит в дебатах — промпты, ответы, дифы, ревью — в файл. Плюс команда для удобного просмотра.

## Лог-файл

- Путь: `logs/{run_id}.log` (run_id уже содержит дату: `20260324_214159_914920`)
- Пишем ВСЁ:
  - Промпты которые отправляются Claude и Codex (план, ревью, имплементация, фиксы)
  - Полные ответы от Claude и Codex (JSON, текст)
  - Git diff целиком
  - Статусы раундов (approved, reject, ask_user)
  - Мета-информация (duration, tokens, cost)
  - Ошибки и fallback-и (auth failures, retries)
- Формат: plain text с таймстемпами, читаемый человеком
- Размер не волнует — пусть будет большой

## Как пишем

- В `orchestrator.py`: добавить `self._log_file: Path | None` — открывается при создании run_dir
- Новый метод `_flog(message)` — пишет в файл с таймстемпом (в дополнение к `_log()` в stderr)
- Провайдеры (`ClaudeProvider`, `CodexProvider`) возвращают prompt и response — логируем оба
- `_raw_git_diff()` — логируем полный diff

## CLI команда: `srachka logs`

- `srachka logs` — находит последний лог-файл в `logs/`, запускает `tail -f` на нём
- `srachka logs --run <run_id>` — конкретный run
- `srachka logs --list` — показать все лог-файлы
- Под капотом: `tail -f logs/{run_id}.log` через `os.execvp` (заменяет процесс, ctrl+c работает нативно)

## Что НЕ делаем

- Не structured logging (JSON lines) — plain text для человека
- Не ротация логов
- Не уровни логирования (debug/info/warn) — пишем всё
