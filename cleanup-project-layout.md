# Cleanup: перенести runtime-файлы в .srachka/

## Проблема

Корень проекта захламлён runtime-файлами и директориями, которые не относятся к исходному коду:

```
config.json        — пользовательский конфиг
runs/              — данные прогонов (plan.json, step_reviews.jsonl, etc.)
logs/              — логи прогонов
schemas/           — JSON-схемы для Codex
```

Плюс завершённые task-файлы (.md) которые больше не нужны.

## Что делаем

### 1. Директория `.srachka/`

Все runtime-данные переезжают в `.srachka/`:

```
.srachka/
  config.json       — конфиг (был config.json)
  runs/             — данные прогонов (был runs/)
  logs/             — логи (был logs/)
  schemas/          — JSON-схемы (был schemas/)
```

### 2. Изменения в коде

- **config.py**: `load_config()` ищет `.srachka/config.json` вместо `config.json`
- **config.py**: `DEFAULT_CONFIG` — `runs_dir=".srachka/runs"`, `logs_dir=".srachka/logs"`
- **orchestrator.py**: `schema_dir` = `project_root / ".srachka" / "schemas"` вместо `project_root / "schemas"`
- **cli.py**: все пути к runs/logs/schemas через `.srachka/`
- **.gitignore**: заменить `runs/`, `logs/`, `config.json` на `.srachka/`

### 3. config.example.json

Переезжает в `.srachka/config.example.json` или удаляется (дефолты и так в коде).

### 4. Завершённые task-файлы

Удалить из корня завершённые task .md файлы (они в git history):
- better-cli-ux.md
- commit-per-step.md
- do-step.md
- file-logging.md
- srachka-init.md
- timeout.md

Оставить только:
- README.md
- CHANGELOG.md
- cleanup-project-layout.md (этот файл, удалить после выполнения)

### 5. Миграция

При первом запуске новой версии, если `config.json` существует в корне а `.srachka/config.json` нет — НЕ мигрировать автоматически. Просто кинуть понятную ошибку: "Move config.json to .srachka/config.json".

## Что НЕ делаем

- Не трогаем структуру `srachka_ai/` (исходный код)
- Не трогаем `tests/`
- Не трогаем `pyproject.toml`, `uv.lock`
- Не делаем автомиграцию старых данных
