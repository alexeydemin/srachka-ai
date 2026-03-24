from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from srachka_ai.config import DEFAULT_CONFIG
from srachka_ai.providers import (
    CLAUDE_AUTH_ENV_VARS,
    CODEX_AUTH_ENV_VARS,
    ClaudeProvider,
    CodexProvider,
    claude_env_overrides,
    codex_env_overrides,
)
from srachka_ai.shell import CommandResult, run_command


class ShellEnvTests(unittest.TestCase):
    def test_run_command_can_remove_inherited_auth_variables(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "stale-key",
                "OPENAI_ACCESS_TOKEN": "expired-token",
                "PATH": "/bin:/usr/bin",
            },
            clear=True,
        ):
            result = run_command(
                [
                    "python3",
                    "-c",
                    "import json, os; print(json.dumps({"
                    "'OPENAI_API_KEY': os.environ.get('OPENAI_API_KEY'), "
                    "'OPENAI_ACCESS_TOKEN': os.environ.get('OPENAI_ACCESS_TOKEN'), "
                    "'PATH': os.environ.get('PATH')"
                    "}))",
                ],
                cwd=Path.cwd(),
                env_remove=CODEX_AUTH_ENV_VARS,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn('"OPENAI_API_KEY": null', result.stdout)
        self.assertIn('"OPENAI_ACCESS_TOKEN": null', result.stdout)
        self.assertIn('"/bin:/usr/bin"', result.stdout)


class ClaudeProviderTests(unittest.TestCase):
    def test_ask_json_uses_explicit_claude_config_env(self) -> None:
        provider = ClaudeProvider(DEFAULT_CONFIG, Path("/tmp/work"))

        with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": "/tmp/claude-payjoy"}, clear=False):
            with mock.patch(
                "srachka_ai.providers.run_command",
                return_value=CommandResult(returncode=0, stdout='{"status":"draft"}', stderr=""),
            ) as run_mock:
                response = provider.ask_json("Return JSON")

        self.assertEqual(response, {"status": "draft"})
        self.assertEqual(run_mock.call_args.kwargs["env_remove"], CLAUDE_AUTH_ENV_VARS)
        self.assertEqual(run_mock.call_args.kwargs["env_overrides"]["CLAUDE_CONFIG_DIR"], "/tmp/claude-payjoy")


class CodexProviderTests(unittest.TestCase):
    def test_ask_json_strips_ambient_auth_variables(self) -> None:
        provider = CodexProvider(DEFAULT_CONFIG, Path("/tmp/work"), Path("/tmp/schemas"))

        with mock.patch(
            "srachka_ai.providers.run_command",
            return_value=CommandResult(returncode=0, stdout='{"status":"ok"}', stderr=""),
        ) as run_mock:
            response = provider.ask_json("Return JSON", "plan_review.schema.json")

        self.assertEqual(response, {"status": "ok"})
        self.assertEqual(run_mock.call_args.kwargs["env_remove"], CODEX_AUTH_ENV_VARS)
        self.assertEqual(run_mock.call_args.kwargs["env_overrides"], codex_env_overrides())

    def test_env_override_helpers_respect_existing_switcher_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "CLAUDE_CONFIG_DIR": "/Users/test/.claude-payjoy",
                "CODEX_HOME": "/Users/test/.codex-work",
                "HOME": "/Users/test",
            },
            clear=False,
        ):
            self.assertEqual(claude_env_overrides()["CLAUDE_CONFIG_DIR"], "/Users/test/.claude-payjoy")
            self.assertEqual(codex_env_overrides()["CODEX_HOME"], "/Users/test/.codex-work")


if __name__ == "__main__":
    unittest.main()
