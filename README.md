# srachka_ai

`srachka_ai` is a tiny local orchestrator for a two model workflow:

1. Claude proposes a practical implementation plan.
2. Codex critiques the plan.
3. Claude revises until the plan is approved, simplified, or escalated to the human.
4. During implementation, a Claude Code `Stop` hook can ask Codex to review the current diff and block completion when the step is not ready.

This repo is intentionally small. It uses only the Python standard library and shells out to your existing `claude` and `codex` CLIs.

## Why this shape

This project leans on two current capabilities:

`codex exec` supports machine readable automation, including JSONL output and `--output-schema` for structured final responses. Claude Code supports non interactive runs with `claude -p`, and `Stop` hooks can block stopping with `decision: "block"` or with exit code `2`.

## Folder layout

```text
srachka_ai/
  README.md
  config.example.json
  .gitignore
  .claude/
    settings.local.json.example
  examples/
    TASK.md
  hooks/
    review_with_codex.py
  schemas/
    plan.schema.json
    plan_review.schema.json
    diff_review.schema.json
  srachka_ai/
    __init__.py
    cli.py
    config.py
    models.py
    orchestrator.py
    paths.py
    prompts.py
    providers.py
    shell.py
    state.py
    utils.py
```

## Prerequisites

Install and authenticate both CLIs.

```bash
claude --version
codex --version
```

## Quick start

Copy config and adjust commands only if your local setup is unusual.

```bash
cd ~/projects/srachka_ai
cp config.example.json config.json
python3 -m srachka_ai.cli plan --task-file examples/TASK.md --work-repo ~/code/my_app
```

That creates a run directory under `runs/` and writes:

- `state.json`, orchestrator state for the latest run
- `plan.json`, approved or last proposed plan
- `review.jsonl`, all reviewer rounds
- `implementation_brief.md`, text you can paste into Claude Code

See the current step:

```bash
python3 -m srachka_ai.cli show-step
```

Advance after you accept a step:

```bash
python3 -m srachka_ai.cli next-step
```

Manually ask Codex to review the current diff from the active work repo:

```bash
python3 -m srachka_ai.cli review-diff
```

Or let Claude Code do it automatically through the hook.

## Claude Code hook

Create a hook entry in the target repository. The command should point to the absolute path of this project's hook script:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/Users/you/projects/srachka_ai/hooks/review_with_codex.py"
          }
        ]
      }
    ]
  }
}
```

Put that into the target repo's `.claude/settings.local.json`.

Then start Claude Code in the target repo and tell it to follow the generated `runs/<run_id>/implementation_brief.md` step by step.

When Claude tries to stop, the Stop hook will:

- read the active `state.json`
- inspect `git diff`
- ask Codex whether the current step is done well enough
- allow stop or block it with a reason

## Suggested workflow

1. Write the task into `examples/TASK.md`, or any markdown file.
2. Run plan.
3. Open Claude Code in the target repo.
4. Paste the generated implementation brief.
5. Let Claude work on step 1.
6. If the hook blocks, Claude keeps going.
7. Once you are happy, run `next-step`.

## Config

`config.json` supports these fields:

```json
{
  "claude_command": ["claude", "-p"],
  "codex_command": ["codex", "--ask-for-approval", "never", "exec"],
  "max_plan_rounds": 4,
  "max_step_fix_rounds": 2,
  "runs_dir": "runs",
  "logs_dir": "logs"
}
```

## Notes

This is a practical first version, not a framework. It is intentionally opinionated:

- Claude owns planning and implementation.
- Codex owns critique and merge readiness.
- The human decides product ambiguities.
- Over engineering is treated as a first class rejection reason.

## Nice next upgrades

- auto advance step when diff review is accepted
- richer state per step, including expected files and test commands
- Slack or terminal notifications when human input is needed
- Agents SDK or MCP based multi turn orchestration later, after this loop proves useful
