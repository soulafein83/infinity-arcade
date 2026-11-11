import os
import sys
import unittest
from unittest.mock import MagicMock

# Add the src directory to the path for module imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infinity_arcade.main import ArcadeApp, parse_max_retries


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


if __name__ == "__main__":
    unittest.main()
