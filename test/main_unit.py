import base64
import os
import sys
import unittest
from unittest.mock import MagicMock

# Add the src directory to the path for module imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infinity_arcade.main import (
    ArcadeApp,
    parse_max_retries,
    parse_screenshot_seconds,
    parse_screenshots_enabled,
)


class TestParseMaxRetries(unittest.TestCase):
    def test_default_when_unset(self):
        self.assertEqual(parse_max_retries(None), 1)

    def test_default_when_empty(self):
        self.assertEqual(parse_max_retries(""), 1)

    def test_valid_one(self):
        self.assertEqual(parse_max_retries("1"), 1)

    def test_valid_two(self):
        self.assertEqual(parse_max_retries("2"), 2)

    def test_whitespace_is_stripped(self):
        self.assertEqual(parse_max_retries(" 2 "), 2)

    def test_zero_clamped_to_one(self):
        self.assertEqual(parse_max_retries("0"), 1)

    def test_negative_clamped_to_one(self):
        self.assertEqual(parse_max_retries("-3"), 1)

    def test_invalid_falls_back_to_default(self):
        self.assertEqual(parse_max_retries("abc"), 1)


class TestFinishedGamesMiddleware(unittest.TestCase):
    """The finished-games cleanup now lives in a single HTTP middleware
    instead of being repeated across endpoints."""

    def setUp(self):
        from fastapi.testclient import TestClient

        self.app_instance = ArcadeApp()
        self.client = TestClient(self.app_instance.app)
        self.launcher = self.app_instance.game_launcher

    def tearDown(self):
        for key in ("__test_finished__", "__test_running__"):
            self.launcher.running_games.pop(key, None)

    def test_middleware_removes_finished_keeps_running(self):
        finished = MagicMock()
        finished.poll.return_value = 0
        running = MagicMock()
        running.poll.return_value = None
        self.launcher.running_games["__test_finished__"] = finished
        self.launcher.running_games["__test_running__"] = running

        response = self.client.get("/api/games")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("__test_finished__", self.launcher.running_games)
        self.assertIn("__test_running__", self.launcher.running_games)

    def test_middleware_registered_once(self):
        dispatches = [
            getattr(m.kwargs.get("dispatch"), "__name__", None)
            for m in self.app_instance.app.user_middleware
        ]
        self.assertEqual(dispatches.count("cleanup_finished_games"), 1)


class TestParseScreenshotSeconds(unittest.TestCase):
    def test_default_when_unset(self):
        self.assertEqual(parse_screenshot_seconds(None), 3)

    def test_default_when_empty(self):
        self.assertEqual(parse_screenshot_seconds(""), 3)

    def test_valid_value(self):
        self.assertEqual(parse_screenshot_seconds("10"), 10)

    def test_whitespace_is_stripped(self):
        self.assertEqual(parse_screenshot_seconds(" 5 "), 5)

    def test_zero_clamped_to_one(self):
        self.assertEqual(parse_screenshot_seconds("0"), 1)

    def test_negative_clamped_to_one(self):
        self.assertEqual(parse_screenshot_seconds("-3"), 1)

    def test_above_max_clamped_to_60(self):
        self.assertEqual(parse_screenshot_seconds("999"), 60)

    def test_invalid_falls_back_to_default(self):
        self.assertEqual(parse_screenshot_seconds("abc"), 3)


class TestParseScreenshotsEnabled(unittest.TestCase):
    def test_enabled_when_unset(self):
        self.assertTrue(parse_screenshots_enabled(None))

    def test_enabled_when_empty(self):
        self.assertTrue(parse_screenshots_enabled(""))

    def test_enabled_for_truthy_values(self):
        for value in ("1", "true", "yes", "on", "anything"):
            self.assertTrue(parse_screenshots_enabled(value))

    def test_disabled_for_zero(self):
        self.assertFalse(parse_screenshots_enabled("0"))

    def test_disabled_for_falsy_words(self):
        for value in ("false", "no", "off", "FALSE", " Off "):
            self.assertFalse(parse_screenshots_enabled(value))


class TestGamePreviewEndpoint(unittest.TestCase):
    """GET /api/game-preview/{game_id} serves the headless-captured PNG
    thumbnail and 404s for unknown games or games without a preview."""

    # Minimal 1x1 transparent PNG
    PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    PNG_BYTES = base64.b64decode(PNG_B64)

    def setUp(self):
        import tempfile
        from pathlib import Path
        from fastapi.testclient import TestClient

        self.tmp = tempfile.TemporaryDirectory()
        self.preview_dir = Path(self.tmp.name)
        self.app_instance = ArcadeApp()
        self.client = TestClient(self.app_instance.app)
        self.launcher = self.app_instance.game_launcher
        self.original_preview_dir = self.launcher.preview_dir
        self.launcher.preview_dir = self.preview_dir
        self._restored = False

    def tearDown(self):
        if not self._restored:
            self.launcher.preview_dir = self.original_preview_dir
            self._restored = True
        self.tmp.cleanup()

    def test_unknown_game_returns_404(self):
        response = self.client.get("/api/game-preview/__test_missing__")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Game not found")

    def test_known_game_without_preview_returns_404(self):
        self.app_instance.arcade_games.game_metadata["__test_nopreview__"] = {
            "title": "No Preview Game"
        }
        response = self.client.get("/api/game-preview/__test_nopreview__")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "No preview available")

    def test_known_game_with_preview_returns_png(self):
        self.app_instance.arcade_games.game_metadata["__test_preview__"] = {
            "title": "Preview Game"
        }
        preview_path = self.preview_dir / "__test_preview__.png"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_bytes(self.PNG_BYTES)

        response = self.client.get("/api/game-preview/__test_preview__")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, self.PNG_BYTES)


if __name__ == "__main__":
    unittest.main()
