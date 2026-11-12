import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add the src directory to the path for module imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infinity_arcade.game_orchestrator import GameOrchestrator
from infinity_arcade.llm_service import ExtractedCode


def _collect(generator):
    """Run an async generator to completion and return all yielded items."""
    async def run():
        return [item async for item in generator]
    return asyncio.run(run())


def _code_generator(code):
    """Build an async generator that yields one ExtractedCode, like a real LLM stream."""
    async def gen():
        yield ExtractedCode(code=code, length=len(code))
    return gen()


class OrchestratorTestCase(unittest.TestCase):
    GAME_ID = "test-game"
    GAME_CODE = "import pygame\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        games_dir = root / "games"
        games_dir.mkdir(parents=True)
        self.game_file = games_dir / f"{self.GAME_ID}.py"
        self.game_file.write_text(self.GAME_CODE, encoding="utf-8")
        self.preview_path = root / "previews" / f"{self.GAME_ID}.png"

        self.storage = MagicMock()
        self.storage.games_dir = games_dir
        self.storage.builtin_games = {}
        self.storage.game_metadata = {self.GAME_ID: {"title": "Test Game"}}

        self.launcher = MagicMock()
        self.launcher.launch_game_process.return_value = (True, "")
        self.launcher.get_preview_path.return_value = self.preview_path
        self.launcher.capture_screenshot.return_value = (True, str(self.preview_path))

        self.llm = MagicMock()
        self.llm.stream_game_code.side_effect = (
            lambda *args, **kwargs: _code_generator(self.GAME_CODE)
        )
        self.llm.generate_title = AsyncMock(return_value="Test Game")

        self.orchestrator = GameOrchestrator(
            self.storage,
            self.launcher,
            self.llm,
            screenshot_seconds=3,
            screenshots_enabled=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_capture_on_success_sets_metadata(self):
        events = _collect(
            self.orchestrator.launch_game_with_auto_fix_streaming(
                self.GAME_ID, "Test Game", capture_preview=True
            )
        )
        text = "".join(events)
        self.assertIn("Capturing preview screenshot", text)
        self.assertIn('"type": "complete"', text)
        self.launcher.capture_screenshot.assert_called_once_with(
            self.game_file, self.preview_path, 3
        )
        self.assertTrue(self.storage.game_metadata[self.GAME_ID]["has_preview"])
        self.storage.save_metadata.assert_called_once()

    def test_no_capture_when_flag_is_false(self):
        events = _collect(
            self.orchestrator.launch_game_with_auto_fix_streaming(
                self.GAME_ID, "Test Game", capture_preview=False
            )
        )
        text = "".join(events)
        self.assertNotIn("Capturing preview screenshot", text)
        self.assertIn('"type": "complete"', text)
        self.launcher.capture_screenshot.assert_not_called()
        self.assertNotIn("has_preview", self.storage.game_metadata[self.GAME_ID])
        self.storage.save_metadata.assert_not_called()

    def test_no_capture_when_screenshots_disabled(self):
        self.orchestrator.screenshots_enabled = False
        events = _collect(
            self.orchestrator.launch_game_with_auto_fix_streaming(
                self.GAME_ID, "Test Game", capture_preview=True
            )
        )
        text = "".join(events)
        self.assertNotIn("Capturing preview screenshot", text)
        self.assertIn('"type": "complete"', text)
        self.launcher.capture_screenshot.assert_not_called()
        self.assertNotIn("has_preview", self.storage.game_metadata[self.GAME_ID])

    def test_failed_capture_does_not_block_flow(self):
        self.launcher.capture_screenshot.return_value = (False, "game exited with code 1")
        events = _collect(
            self.orchestrator.launch_game_with_auto_fix_streaming(
                self.GAME_ID, "Test Game", capture_preview=True
            )
        )
        text = "".join(events)
        self.assertIn("Capturing preview screenshot", text)
        self.assertIn('"type": "complete"', text)
        self.assertNotIn("has_preview", self.storage.game_metadata[self.GAME_ID])
        self.storage.save_metadata.assert_not_called()

    def test_launch_failure_without_retries_yields_error(self):
        self.launcher.launch_game_process.return_value = (False, "boom")
        events = _collect(
            self.orchestrator.launch_game_with_auto_fix_streaming(
                self.GAME_ID, "Test Game", max_retries=0, capture_preview=True
            )
        )
        text = "".join(events)
        self.assertIn('"type": "error"', text)
        self.assertIn("Game launch failed", text)
        self.launcher.capture_screenshot.assert_not_called()

    def test_create_flow_captures_preview(self):
        events = _collect(
            self.orchestrator.create_and_launch_game_with_streaming(
                self.GAME_ID, "a pong game"
            )
        )
        text = "".join(events)
        self.assertIn('"type": "complete"', text)
        self.launcher.capture_screenshot.assert_called_once_with(
            self.game_file, self.preview_path, 3
        )
        self.assertTrue(self.storage.game_metadata[self.GAME_ID]["has_preview"])
        self.assertEqual(self.storage.game_metadata[self.GAME_ID]["title"], "Test Game")

    def test_remix_flow_captures_preview(self):
        remix_id = "remix-game"
        remix_file = self.storage.games_dir / f"{remix_id}.py"
        events = _collect(
            self.orchestrator.remix_and_launch_game_with_streaming(
                self.GAME_ID, remix_id, "make the ball faster", "Remix Test Game"
            )
        )
        text = "".join(events)
        self.assertIn('"type": "complete"', text)
        self.launcher.capture_screenshot.assert_called_once_with(
            remix_file, self.preview_path, 3
        )
        self.assertTrue(self.storage.game_metadata[remix_id]["has_preview"])
        self.assertEqual(
            self.storage.game_metadata[remix_id]["parent_game_id"], self.GAME_ID
        )


if __name__ == "__main__":
    unittest.main()
