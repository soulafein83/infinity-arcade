import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Add the src directory to the path for module imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infinity_arcade.llm_service import (
    NO_THINKING_KWARGS,
    TITLE_MAX_TOKENS_NO_THINKING,
    TITLE_MAX_TOKENS_THINKING,
    ExtractedCode,
    LLMError,
    LLM_RESPONSE_DIR,
    LLM_RESPONSE_KEEP,
    _extract_python_code,
    _save_llm_response,
    generate_game_code_with_llm,
    generate_game_title,
)


class _FakeHttpxClient:
    """Stands in for httpx.AsyncClient; captures the JSON payload of post()."""

    def __init__(self, payload, **kwargs):
        self._payload = payload
        self.captured_payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self.captured_payload = json
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = self._payload
        return response


class _FakeStream:
    """Async iterator of chat-completion chunks."""

    def __init__(self, chunks):
        self._it = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _chunk(content=None, finish=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish, delta=SimpleNamespace(content=content)
            )
        ]
    )


class _FakeOpenAIClient:
    """Stands in for AsyncOpenAI; captures the create() kwargs."""

    def __init__(self, captured, chunks):
        self.captured = captured
        self._chunks = chunks
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.captured.update(kwargs)
        return _FakeStream(self._chunks)


def _lemonade_handle():
    return SimpleNamespace(url="http://127.0.0.1:13305")


async def _collect(generator):
    return [item async for item in generator]


class TestTitleGeneration(unittest.TestCase):
    def _run_title(self, no_thinking, payload):
        fake_client = _FakeHttpxClient(payload)
        with patch(
            "infinity_arcade.llm_service.httpx.AsyncClient",
            lambda **kwargs: fake_client,
        ):
            title = asyncio.run(
                generate_game_title(
                    _lemonade_handle(), "test-model", "pong with fast ball",
                    no_thinking=no_thinking,
                )
            )
        return title, fake_client.captured_payload

    def test_title_no_thinking_default(self):
        payload = {"choices": [{"message": {"content": "Speed Pong"}}]}
        title, sent = self._run_title(True, payload)
        self.assertEqual(title, "Speed Pong")
        self.assertEqual(sent["max_tokens"], TITLE_MAX_TOKENS_NO_THINKING)
        self.assertEqual(sent["chat_template_kwargs"], NO_THINKING_KWARGS["chat_template_kwargs"])

    def test_title_thinking_keeps_large_budget_without_kwargs(self):
        payload = {"choices": [{"message": {"content": "Velocity Pong"}}]}
        title, sent = self._run_title(False, payload)
        self.assertEqual(title, "Velocity Pong")
        self.assertEqual(sent["max_tokens"], TITLE_MAX_TOKENS_THINKING)
        self.assertNotIn("chat_template_kwargs", sent)

    def test_title_fallback_on_error(self):
        payload = {"choices": []}
        title, sent = self._run_title(True, payload)
        self.assertEqual(title, "Pong With Fast")


class TestCodeGeneration(unittest.TestCase):
    CODE_CHUNKS = [
        _chunk("```python\n"),
        _chunk("import pygame\n"),
        _chunk("\n```\n"),
    ]

    def _run_create(self, no_thinking, chunks=None):
        captured = {}
        fake_client = _FakeOpenAIClient(captured, chunks or self.CODE_CHUNKS)
        with patch(
            "infinity_arcade.llm_service.AsyncOpenAI",
            lambda **kwargs: fake_client,
        ):
            results = asyncio.run(
                _collect(
                    generate_game_code_with_llm(
                        _lemonade_handle(), "test-model", "create",
                        "a pong game", no_thinking=no_thinking,
                    )
                )
            )
        return results, captured

    def test_code_no_thinking_sends_extra_body(self):
        results, captured = self._run_create(True)
        self.assertEqual(
            captured["extra_body"], NO_THINKING_KWARGS
        )
        self.assertIn("pygame", captured["messages"][0]["content"])
        self.assertEqual(captured["messages"][1]["content"], "Create a game: a pong game")
        codes = [r for r in results if isinstance(r, ExtractedCode)]
        self.assertEqual(len(codes), 1)
        self.assertIn("pygame", codes[0].code)

    def test_code_thinking_omits_extra_body(self):
        _, captured = self._run_create(False)
        self.assertNotIn("extra_body", captured)

    def test_code_truncated_yields_llm_error(self):
        chunks = [
            _chunk("```python\nimport pygame\n"),
            _chunk("", finish="length"),
        ]
        results, _ = self._run_create(True, chunks)
        errors = [r for r in results if isinstance(r, LLMError)]
        self.assertEqual(len(errors), 1)


class TestExtractPythonCode(unittest.TestCase):
    def test_no_code_block(self):
        self.assertIsNone(_extract_python_code("No code here, just text."))

    def test_truncated_block_missing_closing_fence(self):
        response = (
            "Here is the game:\n```python\nimport pygame\n\n"
            "pygame.init()\n# response cut off here"
        )
        self.assertIsNone(_extract_python_code(response))

    def test_block_without_pygame(self):
        response = "```python\nimport sys\nprint(sys.argv)\n```"
        self.assertIsNone(_extract_python_code(response))

    def test_python_fenced_block(self):
        response = (
            "Sure!\n```python\nimport pygame\n\nclass Game:\n    pass\n```\nDone."
        )
        extracted = _extract_python_code(response)
        self.assertIsInstance(extracted, ExtractedCode)
        self.assertIn("import pygame", extracted.code)
        self.assertEqual(extracted.length, len(extracted.code))

    def test_py_fenced_block(self):
        response = "```py\nimport pygame\npygame.init()\n```"
        extracted = _extract_python_code(response)
        self.assertIsInstance(extracted, ExtractedCode)
        self.assertIn("pygame", extracted.code)

    def test_bare_fenced_block(self):
        response = "```\nimport pygame\npygame.quit()\n```"
        extracted = _extract_python_code(response)
        self.assertIsInstance(extracted, ExtractedCode)
        self.assertIn("pygame", extracted.code)

    def test_multiple_blocks_picks_longest_pygame(self):
        long_code = "import pygame\n\n" + "\n".join(
            f"# line {i} for logic" for i in range(20)
        )
        response = (
            "Short one:\n```python\nimport pygame\n```\n\n"
            f"Longer one:\n```python\n{long_code}\n```\n\n"
            "Ignored one:\n```python\nimport sys\nprint('no pygame')\n```\n"
        )
        extracted = _extract_python_code(response)
        self.assertIsInstance(extracted, ExtractedCode)
        self.assertIn("# line 19", extracted.code)
        self.assertEqual(extracted.length, len(long_code.strip()))

    def test_case_insensitive_pygame_match(self):
        response = "```python\nimport PyGame\n```"
        extracted = _extract_python_code(response)
        self.assertIsInstance(extracted, ExtractedCode)


class TestSaveLlmResponse(unittest.TestCase):
    def test_saves_response_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _save_llm_response("import pygame\n", "create", Path(tmp))
            self.assertIsNotNone(path)
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "import pygame\n")
            self.assertTrue(path.name.endswith("_create.txt"))

    def test_creates_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "llm-responses"
            path = _save_llm_response("import pygame", "remix", target)
            self.assertIsNotNone(path)
            self.assertTrue(path.parent.is_dir())

    def test_prunes_oldest_files_beyond_limit(self):
        extra = 5
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(LLM_RESPONSE_KEEP + extra):
                path = _save_llm_response(f"response {i}", "debug", Path(tmp))
                self.assertIsNotNone(path)
            files = sorted(Path(tmp).glob("*.txt"), key=lambda p: p.name)
            self.assertEqual(len(files), LLM_RESPONSE_KEEP)
            # The newest saved response must survive the pruning
            newest = files[-1].read_text(encoding="utf-8")
            self.assertEqual(newest, f"response {LLM_RESPONSE_KEEP + extra - 1}")

    def test_default_directory_points_to_home_cache(self):
        self.assertEqual(
            LLM_RESPONSE_DIR, Path.home() / ".infinity-arcade" / "llm-responses"
        )


if __name__ == "__main__":
    unittest.main()
