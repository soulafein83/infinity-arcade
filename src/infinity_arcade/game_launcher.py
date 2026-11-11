import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, TextIO, Tuple


logger = logging.getLogger("infinity_arcade.main")

# Lines containing any of these are treated as errors (used for the
# "last error" surfaced in the UI and for filtering stderr on quick exits)
ERROR_INDICATORS = [
    "Error",
    "Exception",
    "Traceback",
    'File "',
    "line ",
    "NameError",
    "ImportError",
    "SyntaxError",
    "AttributeError",
    "TypeError",
    "ValueError",
]

# Lines matching any of these are noise, never treated as errors
NOISE_PHRASES = [
    "UserWarning",
    "pkg_resources is deprecated",
    "from pkg_resources import",
    "pygame community",
    "https://www.pygame.org",
]


def filter_error_lines(stderr: str) -> list:
    """Return the lines from `stderr` that look like actual errors."""
    lines = stderr.strip().split("\n") if stderr else []
    actual_errors = []
    for line in lines:
        if any(skip_phrase in line for skip_phrase in NOISE_PHRASES):
            continue
        if line.strip() and any(indicator in line for indicator in ERROR_INDICATORS):
            actual_errors.append(line)
    return actual_errors


class GameLauncher:
    """Handles game process execution and lifecycle management."""

    def __init__(self) -> None:
        self.running_games: Dict[str, subprocess.Popen] = {}
        self.log_dir = Path.home() / ".infinity-arcade" / "logs"
        self.log_files: Dict[str, TextIO] = {}

    def get_log_path(self, game_id: str) -> Path:
        """Path of the per-game log file (stdout + stderr are appended here)."""
        return self.log_dir / f"{game_id}.log"

    @staticmethod
    def _write_to_log(log_fh: TextIO, header: str, text: str) -> None:
        if text:
            log_fh.write(f"{header}\n{text}\n")
            log_fh.flush()

    def _pump_stream(self, stream, game_id: str, log_fh: TextIO) -> None:
        """Copy one stream to the game log line by line until EOF."""
        try:
            for line in stream:
                log_fh.write(line)
                log_fh.flush()
        except Exception as e:
            logger.debug(f"Log pump for game {game_id} stopped: {e}")
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _start_log_pump(self, game_id: str, process: subprocess.Popen, log_fh: TextIO) -> None:
        """Pump stdout and stderr of a running game to its log file."""
        threads = []
        for stream in (process.stdout, process.stderr):
            t = threading.Thread(
                target=self._pump_stream, args=(stream, game_id, log_fh), daemon=True
            )
            t.start()
            threads.append(t)

        def _finalize() -> None:
            for t in threads:
                t.join()
            fh = self.log_files.get(game_id)
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass
                self.log_files.pop(game_id, None)

        threading.Thread(target=_finalize, daemon=True).start()

    def launch_game_process(self, game_file: Path, game_id: str) -> Tuple[bool, str]:
        """Launch a game process and return (success, error_message).

        This mirrors the previous behavior used in ArcadeGames: if the process
        exits within ~2 seconds, treat that as a failure for pygame-based games
        and capture stderr to present a useful error message. All output is
        also appended to the per-game log file in ~/.infinity-arcade/logs/.
        """
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, str(game_file)]
                logger.debug(f"PyInstaller mode - Launching: {' '.join(cmd)}")
            else:
                cmd = [sys.executable, str(game_file)]
                logger.debug(f"Development mode - Launching: {' '.join(cmd)}")

            # Per-game log: append so repeated launches of the same game
            # accumulate their history in one file
            self.log_dir.mkdir(parents=True, exist_ok=True)
            # pylint: disable=consider-using-with
            log_fh = open(self.get_log_path(game_id), "a", encoding="utf-8")
            self.log_files[game_id] = log_fh

            # pylint: disable=consider-using-with
            # start_new_session=True gives the game its own process group so
            # stop_game can kill it together with any grandchild processes
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )

            start_time = time.time()
            logger.debug(f"Game {game_id} subprocess started with PID {process.pid}")

            try:
                # wait() (instead of communicate()) works with PIPEs when the
                # game is expected to keep running; communicate() is used only
                # to drain the output of a process that already exited
                process.wait(timeout=2)
                end_time = time.time()
                duration = end_time - start_time
                logger.debug(
                    f"Game {game_id} subprocess (PID {process.pid}) EXITED after {duration:.3f} "
                    f"seconds with return code {process.returncode}"
                )
                stdout, stderr = process.communicate()
                self._write_to_log(log_fh, "STDOUT:", stdout)
                self._write_to_log(log_fh, "STDERR:", stderr)

                # Filter out noisy warnings from stderr to get actual errors
                actual_errors = filter_error_lines(stderr)
                filtered_stderr = "\n".join(actual_errors).strip()

                if process.returncode != 0:
                    error_msg = (
                        filtered_stderr
                        if filtered_stderr
                        else f"Game exited with code {process.returncode} but no error message was captured"
                    )
                    logger.error(
                        f"Game {game_id} failed with return code {process.returncode}: {error_msg}"
                    )
                    if stdout:
                        print("STDOUT:")
                        print(stdout)
                    if stderr:
                        print("STDERR:")
                        print(stderr)
                    if not stdout and not stderr:
                        print("No output captured")
                    print("=" * 60)
                    return False, error_msg

                # Success path for quick-and-clean exit (no time-based failure)
                logger.debug(
                    f"Game {game_id} exited quickly with return code 0; treating as successful completion"
                )
                if stdout:
                    print("STDOUT:")
                    print(stdout)
                if stderr:
                    print("STDERR:")
                    print(stderr)
                if not stdout and not stderr:
                    print("No output captured")
                print("=" * 60)
                return True, "Game exited successfully"
            except subprocess.TimeoutExpired:
                # Timeout is good - means the game is still running; pump its
                # output to the log file in background threads
                end_time = time.time()
                duration = end_time - start_time
                self.running_games[game_id] = process
                self._start_log_pump(game_id, process, log_fh)
                logger.debug(
                    f"Game {game_id} subprocess (PID {process.pid}) STILL RUNNING after {duration:.3f} seconds timeout"
                )
                return True, "Game launched successfully"
        except Exception as e:
            logger.error(f"Error launching game {game_id}: {e}")
            return False, str(e)

    def stop_game(self, game_id: str) -> None:
        if game_id in self.running_games:
            process = self.running_games[game_id]
            pid = process.pid
            try:
                logger.debug(
                    f"MANUALLY STOPPING game {game_id} process group (PID {pid})"
                )
                # Kill the whole process group (game + its children)
                os.killpg(pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                    logger.debug(
                        f"Game {game_id} process group (PID {pid}) terminated gracefully"
                    )
                except subprocess.TimeoutExpired:
                    logger.debug(
                        f"Game {game_id} process group (PID {pid}) did not terminate gracefully, killing..."
                    )
                    os.killpg(pid, signal.SIGKILL)
                    logger.debug(
                        f"Game {game_id} process group (PID {pid}) killed"
                    )
            except (ProcessLookupError, PermissionError):
                logger.debug(
                    f"Game {game_id} process group (PID {pid}) no longer exists"
                )
            except Exception as e:
                print(f"Error stopping game {game_id}: {e}")
            finally:
                del self.running_games[game_id]

    def cleanup_finished_games(self) -> None:
        finished: list[str] = []
        for game_id, process in self.running_games.items():
            if process.poll() is not None:
                return_code = process.returncode
                logger.debug(
                    f"Game {game_id} subprocess (PID {process.pid}) FINISHED with return code {return_code} - cleaning up"
                )
                finished.append(game_id)
        for game_id in finished:
            del self.running_games[game_id]
