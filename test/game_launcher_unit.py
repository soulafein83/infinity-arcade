import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Add the src directory to the path for module imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infinity_arcade.game_launcher import GameLauncher


class TestGetPreviewPath(unittest.TestCase):
    def test_path_inside_preview_dir(self):
        launcher = GameLauncher()
        self.assertEqual(launcher.get_preview_path("abc123"), launcher.preview_dir / "abc123.png")


class TestCaptureScreenshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.launcher = GameLauncher()
        self.game_file = Path(self.tmp.name) / "game.py"
        self.game_file.write_text("import pygame\n", encoding="utf-8")
        self.dest = Path(self.tmp.name) / "previews" / "abc123.png"

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_run(self, returncode=0, stderr="", save_file=True):
        def fake_run(cmd, **kwargs):
            if save_file:
                self.dest.write_bytes(b"\x89PNG fake image bytes")
            return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)
        return fake_run

    def test_success_returns_dest_path(self):
        with patch(
            "infinity_arcade.game_launcher.subprocess.run", self._fake_run()
        ):
            ok, message = self.launcher.capture_screenshot(self.game_file, self.dest, 3)
        self.assertTrue(ok)
        self.assertEqual(message, str(self.dest))
        self.assertTrue(self.dest.exists())

    def test_success_passes_screenshot_args_and_dummy_drivers(self):
        run_mock = MagicMock(side_effect=self._fake_run())
        with patch("infinity_arcade.game_launcher.subprocess.run", run_mock):
            self.launcher.capture_screenshot(self.game_file, self.dest, 3)
        args, kwargs = run_mock.call_args
        self.assertEqual(
            args[0],
            [
                sys.executable,
                str(self.game_file),
                "--screenshot",
                "3",
                "--screenshot-file",
                str(self.dest),
            ],
        )
        self.assertEqual(kwargs["env"]["SDL_VIDEODRIVER"], "dummy")
        self.assertEqual(kwargs["env"]["SDL_AUDIODRIVER"], "dummy")
        # Generous wall-clock margin: max(seconds, 1) + 60
        self.assertEqual(kwargs["timeout"], 63)

    def test_success_creates_missing_parent_directory(self):
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.dest.parent)
        with patch(
            "infinity_arcade.game_launcher.subprocess.run", self._fake_run()
        ):
            ok, _ = self.launcher.capture_screenshot(self.game_file, self.dest, 3)
        self.assertTrue(ok)
        self.assertTrue(self.dest.exists())

    def test_zero_seconds_clamped_to_one_in_timeout(self):
        run_mock = MagicMock(side_effect=self._fake_run())
        with patch("infinity_arcade.game_launcher.subprocess.run", run_mock):
            self.launcher.capture_screenshot(self.game_file, self.dest, 0)
        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][3], "0")
        self.assertEqual(kwargs["timeout"], 61)

    def test_timeout_returns_failure(self):
        run_mock = MagicMock(
            side_effect=subprocess.TimeoutExpired(["python", "game.py"], 63)
        )
        with patch("infinity_arcade.game_launcher.subprocess.run", run_mock):
            ok, message = self.launcher.capture_screenshot(self.game_file, self.dest, 3)
        self.assertFalse(ok)
        self.assertIn("timed out", message)

    def test_nonzero_exit_returns_stderr_tail(self):
        stderr = "line one\nline two\nValueError: boom"
        with patch(
            "infinity_arcade.game_launcher.subprocess.run",
            self._fake_run(returncode=1, stderr=stderr),
        ):
            ok, message = self.launcher.capture_screenshot(self.game_file, self.dest, 3)
        self.assertFalse(ok)
        self.assertIn("ValueError: boom", message)

    def test_nonzero_exit_without_stderr(self):
        with patch(
            "infinity_arcade.game_launcher.subprocess.run",
            self._fake_run(returncode=1, stderr=""),
        ):
            ok, message = self.launcher.capture_screenshot(self.game_file, self.dest, 3)
        self.assertFalse(ok)
        self.assertIn("exited with code 1", message)
        self.assertIn("no stderr", message)

    def test_missing_image_returns_failure(self):
        with patch(
            "infinity_arcade.game_launcher.subprocess.run",
            self._fake_run(save_file=False),
        ):
            ok, message = self.launcher.capture_screenshot(self.game_file, self.dest, 3)
        self.assertFalse(ok)
        self.assertIn("did not save the screenshot", message)


if __name__ == "__main__":
    unittest.main()
