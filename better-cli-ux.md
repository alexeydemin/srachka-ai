# Better CLI UX: Make srachka a proper global CLI tool

## Context

Currently `srachka` has no proper packaging. It runs via `python -m srachka_ai` or direct script execution. There's no way to install it globally and use from any repo directory.

The workflow is: Claude (the AI assistant) is the orchestrator. Claude goes into a target repo and runs `srachka` commands (`plan`, `show-step`, `next-step`, `review-diff`) step by step. `srachka` is a CLI wrapper around Claude + Codex that handles the debate logic.

## Desired Behavior

After `pip install -e .` (from the srachka repo), the `srachka` command is available globally:

```bash
cd ~/some-project-repo
srachka plan --task-file ~/tasks/feature.md
srachka show-step
srachka review-diff
srachka next-step
srachka doctor
```

Key points:
- `srachka` works from any directory — the current directory is the work repo
- `--work-repo` flag is optional override (defaults to cwd)
- All existing commands keep working as before
- The tool's own config/runs/schemas/logs live in srachka's install directory, not in the work repo

## What needs to be done

1. Create `pyproject.toml` with:
   - Package metadata (name: `srachka-ai`, version, etc.)
   - `[project.scripts]` entry point: `srachka = "srachka_ai.cli:main"`
   - Dependencies (if any beyond stdlib)
   - Python >=3.10 requirement

2. Make sure `paths.py` resolves `project_root()` correctly — it should point to the srachka package install location (where config.json, schemas/, runs/ live), NOT to the current working directory.

3. Verify all existing commands work when invoked as `srachka <command>` from an arbitrary directory.

## Current Architecture

- `cli.py` — argparse commands: `plan`, `show-step`, `next-step`, `review-diff`, `doctor`
- `orchestrator.py` — `Orchestrator` class with `debate_plan()` and `review_diff()` methods
- `providers.py` — `ClaudeProvider` and `CodexProvider` for calling Claude/Codex CLIs
- `shell.py` — `run_command()` wrapper around subprocess
- `config.py` — `AppConfig` loaded from `config.json`
- `prompts.py` — prompt templates
- `state.py` — run state persistence in `runs/`
- `paths.py` — `project_root()`, `runs_dir()`, `schema_dir()` path resolvers

## What NOT to do

- Do not add new commands (like `run`) — that's a separate improvement
- Do not change command behavior or arguments
- Do not add dependencies beyond what's already used
- Do not rename the Python package (`srachka_ai`) — only the CLI entry point is `srachka`
