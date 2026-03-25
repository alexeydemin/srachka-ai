# srachka

AI debate orchestrator — Claude vs Codex.

Claude proposes, Codex critiques. They argue until the plan is good enough, then Claude implements step by step while Codex reviews every diff.

## Install

```bash
pipx install -e ~/personal/ai_srachka
```

This makes `srachka` available globally. Works from any directory.

## Quick start

```bash
# Go to the repo you want to work on
cd ~/projects/my-app

# Create a plan (Claude proposes, Codex reviews, they debate)
srachka plan --task-file ~/tasks/feature.md

# See current step
srachka show-step

# After implementing a step, ask Codex to review the diff
srachka review-diff

# Move to next step
srachka next-step

# Check auth status for both CLIs
srachka doctor
```

## How it works

1. You write a task in a markdown file
2. `srachka plan` — Claude generates a plan, Codex reviews it. They go back and forth (up to 4 rounds) until approved
3. For each step: Claude implements, Codex reviews the diff
4. `srachka review-diff` — Codex checks if the current step is done correctly
5. `srachka next-step` — advance to the next step

The current directory is your work repo. `srachka` config, schemas, runs, and logs live in the srachka install directory, not in your project.

## Intended workflow

The user (or Claude as orchestrator) runs srachka commands step by step:

```
srachka plan --task-file task.md    # debate the plan
srachka show-step                    # see what to do
# ... implement the step ...
srachka review-diff                  # Codex reviews
srachka next-step                    # move on
# ... repeat ...
```

## Claude Code hook

You can also automate diff reviews via a Claude Code Stop hook. Add to the target repo's `.claude/settings.local.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/ai_srachka/hooks/review_with_codex.py"
          }
        ]
      }
    ]
  }
}
```

When Claude tries to stop, the hook asks Codex to review the diff and blocks if the step isn't done.

## Config

`config.json` in the srachka install directory:

```json
{
  "claude_command": ["claude", "--model", "claude-opus-4-6", "--effort", "max", "-p"],
  "codex_command": ["codex", "--ask-for-approval", "never", "exec"],
  "max_plan_rounds": 4,
  "max_step_fix_rounds": 2,
  "runs_dir": "runs",
  "logs_dir": "logs"
}
```

## Prerequisites

```bash
claude --version   # Claude Code CLI
codex --version    # OpenAI Codex CLI
```

## Design

- Claude owns planning and implementation
- Codex owns critique and review
- The human decides product ambiguities
- Over-engineering is a first-class rejection reason
