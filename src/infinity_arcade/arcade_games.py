import logging
import json
import os
from pathlib import Path
from typing import Dict

logger = logging.getLogger("infinity_arcade.main")


class ArcadeGames:
    """
    Game storage and metadata manager.

    This class is intentionally free of LLM logic and process execution logic.
    It only knows where games live on disk, how to persist metadata, and which
    games are built-in.
    """

    def __init__(self):

        # Global state
        self.games_dir = Path.home() / ".infinity-arcade" / "games"
        self.game_metadata: Dict[str, Dict] = {}

        # Per-game artifacts keyed by game_id (created on demand, not here)
        self.backup_dir = self.games_dir.parent / "backups"
        self.log_dir = self.games_dir.parent / "logs"
        # Fork: preview screenshots (headless --screenshot captures)
        self.preview_dir = self.games_dir.parent / "previews"

        # Ensure games directory exists
        self.games_dir.mkdir(parents=True, exist_ok=True)

        # Load existing game metadata
        self.metadata_file = self.games_dir / "metadata.json"
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as metadata_file:
                    self.game_metadata = json.load(metadata_file)
            except Exception:
                self.game_metadata = {}

        # Built-in games configuration
        self.builtin_games = {
            "builtin_snake": {
                "title": "Dynamic Snake",
                "created": 0,  # Special marker for built-in games
                "prompt": "Snake but the food moves around",
                "builtin": True,
                "file": "snake_moving_food.py",
            },
            "builtin_invaders": {
                "title": "Rainbow Space Invaders",
                "created": 0,  # Special marker for built-in games
                "prompt": "Space invaders with rainbow colors",
                "builtin": True,
                "file": "rainbow_space_invaders.py",
            },
        }

        # Add built-in games to metadata if not already present
        for game_id, game_data in self.builtin_games.items():
            if game_id not in self.game_metadata:
                self.game_metadata[game_id] = game_data.copy()

    def save_metadata(self):
        """Save game metadata to disk atomically (tmp file + os.replace),
        so a crash mid-write never leaves a truncated metadata.json behind."""
        try:
            tmp_file = self.metadata_file.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.game_metadata, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.metadata_file)
        except Exception as e:
            print(f"Error saving metadata: {e}")

    def delete_game(self, game_id: str) -> None:
        """Remove a game: its .py file, its auto-fix backups, its log file,
        its preview screenshot, and its metadata entry."""
        game_file = self.games_dir / f"{game_id}.py"
        if game_file.exists():
            game_file.unlink()
        # Backups ({game_id}.v{n}.py + .meta.json), the per-game log
        # ({game_id}.log) and the preview screenshot ({game_id}.png) are
        # all keyed by game_id
        for extra_dir in (self.backup_dir, self.log_dir, self.preview_dir):
            if extra_dir.is_dir():
                for path in extra_dir.glob(f"{game_id}.*"):
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
        del self.game_metadata[game_id]
        self.save_metadata()

    # Storage helpers
    def save_game_file(self, game_id: str, code: str) -> Path:
        game_file = self.games_dir / f"{game_id}.py"
        with open(game_file, "w", encoding="utf-8") as f:
            f.write(code)
        return game_file

    def read_game_file(self, game_id: str) -> str:
        game_file = self.games_dir / f"{game_id}.py"
        with open(game_file, "r", encoding="utf-8") as f:
            return f.read()
