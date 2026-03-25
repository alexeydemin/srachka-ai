from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from srachka_ai.shell import CommandTimeout, run_command, run_command_streaming


class RunCommandTimeoutTests(unittest.TestCase):
    def test_run_command_raises_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t0 = time.monotonic()
            with self.assertRaises(CommandTimeout) as ctx:
                run_command(["sleep", "10"], Path(tmp), timeout_s=1)
            elapsed = time.monotonic() - t0

            self.assertLessEqual(elapsed, 5)
            self.assertEqual(ctx.exception.timeout_s, 1)
            self.assertIn("timed out", str(ctx.exception))


class RunCommandStreamingTimeoutTests(unittest.TestCase):
    def test_streaming_raises_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t0 = time.monotonic()
            with self.assertRaises(CommandTimeout) as ctx:
                run_command_streaming(["sleep", "10"], Path(tmp), timeout_s=1)
            elapsed = time.monotonic() - t0

            self.assertLessEqual(elapsed, 5)
            self.assertEqual(ctx.exception.timeout_s, 1)
            self.assertIn("timed out", str(ctx.exception))

    def test_streaming_works_without_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_command_streaming(
                ["echo", "hello world"], Path(tmp),
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("hello world", result.stdout)


if __name__ == "__main__":
    unittest.main()
