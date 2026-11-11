import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional, Union

import httpx
from openai import AsyncOpenAI

from lemonade_client import LemonadeClient


logger = logging.getLogger("infinity_arcade.main")

# Fork: full LLM responses are saved for debugging in a dedicated folder
# next to the game cache (not in /tmp), keeping only the newest
# LLM_RESPONSE_KEEP files so the history doesn't grow forever.
LLM_RESPONSE_DIR = Path.home() / ".infinity-arcade" / "llm-responses"
LLM_RESPONSE_KEEP = 20


# Request kwargs that disable "thinking" (reasoning) tokens for models that
# support them (e.g. Qwen3.x). Verified on Qwen3.5-9B-GGUF: with thinking on,
# the model spends the entire max_tokens budget on reasoning_content before
# producing any output (even a 4-token title got truncated at 800). Sending
# the kwarg is harmless on models without this option (llama.cpp ignores it).
NO_THINKING_KWARGS = {"chat_template_kwargs": {"enable_thinking": False}}

# Title budget per mode: a 2-3 word title needs very little once the model is
# not reasoning; thinking models need a much larger budget because
# reasoning tokens are deducted from max_tokens first.
TITLE_MAX_TOKENS_NO_THINKING = 100
TITLE_MAX_TOKENS_THINKING = 800


@dataclass
class ExtractedCode:
    """Represents successfully extracted Python code from an LLM response."""

    code: str
    length: int

    def __post_init__(self):
        if not self.code or not isinstance(self.code, str):
            raise ValueError("Code must be a non-empty string")
        if self.length != len(self.code):
            raise ValueError("Length must match the actual code length")

    def __str__(self) -> str:
        return self.code


@dataclass
class LLMError:
    """A clear LLM-side failure (e.g. truncated response) with a user-facing message."""

    message: str

    def __str__(self) -> str:
        return self.message


async def generate_game_title(
    lemonade_handle: LemonadeClient, model: str, prompt: str, no_thinking: bool = True
) -> str:
    logger.debug(f"Generating title for prompt: {prompt[:50]}...")

    try:
        # pylint: disable=line-too-long
        title_prompt = f"""Generate a short game title (2-3 words maximum) for this game concept: "{prompt}"

Requirements:
- EXACTLY 2-3 words only
- Should be catchy and describe the game
- No punctuation except spaces
- Examples: "Snake Game", "Space Shooter", "Puzzle Master", "Racing Fun"

Return ONLY the title, nothing else."""

        messages = [
            {
                "role": "system",
                "content": "You are a game title generator. Return only the title, nothing else.",
            },
            {"role": "user", "content": title_prompt},
        ]

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            # Small budget is enough without reasoning tokens; thinking models
            # spend max_tokens on reasoning first, so they keep the larger one
            "max_tokens": (
                TITLE_MAX_TOKENS_NO_THINKING if no_thinking else TITLE_MAX_TOKENS_THINKING
            ),
            "temperature": 0.3,
        }
        if no_thinking:
            payload.update(NO_THINKING_KWARGS)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{lemonade_handle.url}/api/v1/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code == 200:
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    title = (data["choices"][0]["message"]["content"] or "").strip()
                    title = title.strip("\"'").split("\n")[0].strip()
                    words = title.split()[:3]
                    final_title = " ".join(words)
                    if final_title:
                        logger.debug(f"Generated title: {final_title}")
                        return final_title
                    logger.warning("Model returned an empty title, using fallback")
    except Exception as e:
        logger.warning(f"Failed to generate title: {e}")

    fallback_title = " ".join(prompt.split()[:3]).title()
    logger.debug(f"Using fallback title: {fallback_title}")
    return fallback_title


def _extract_python_code(llm_response: str) -> Optional[ExtractedCode]:
    logger.debug(f"Extracting Python code from response of length {len(llm_response)}")

    logger.debug(f"Response start: {repr(llm_response[:500])}")
    logger.debug(f"Response end: {repr(llm_response[-500:])}")

    patterns = [
        r"```python\s*\n(.*?)\n```",
        r"```py\s*\n(.*?)\n```",
        r"```\s*\n(.*?)\n```",
    ]

    valid_code_blocks = []
    for i, pattern in enumerate(patterns):
        logger.debug(f"Trying pattern {i+1}: {pattern}")
        matches = re.findall(pattern, llm_response, re.DOTALL)
        for match in matches:
            code = match.strip()
            logger.debug(f"Found code block with pattern {i+1}, length: {len(code)}")
            logger.debug(f"Extracted code start: {repr(code[:200])}")
            if "pygame" in code.lower():
                logger.debug("Code contains pygame, validation passed")
                valid_code_blocks.append(code)
            else:
                logger.warning("Code block found but doesn't contain pygame")
                logger.debug(f"Code content (first 300 chars): {repr(code[:300])}")

    if valid_code_blocks:
        longest_code = max(valid_code_blocks, key=len)
        logger.debug(f"Selected longest pygame code block, length: {len(longest_code)}")
        return ExtractedCode(code=longest_code, length=len(longest_code))

    logger.error("No valid Python code block found in response")
    all_code_blocks = re.findall(r"```.*?\n(.*?)\n```", llm_response, re.DOTALL)
    logger.debug(f"Total code blocks found: {len(all_code_blocks)}")
    for i, block in enumerate(all_code_blocks):
        logger.debug(
            f"Block {i+1} length: {len(block)}, starts with: {repr(block[:100])}"
        )
    return None


def _save_llm_response(
    full_response: str, mode: str, directory: Path | None = None
) -> Optional[Path]:
    """Save a full LLM response to the debug folder for later inspection.

    Files are named with a sortable timestamp (newest last) and the
    generation mode; only the newest LLM_RESPONSE_KEEP files are kept.
    Returns the saved file's path, or None on failure (debugging must
    never break generation).
    """
    directory = directory if directory is not None else LLM_RESPONSE_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now():%Y%m%dT%H%M%S_%f}_{mode}.txt"
        response_path = directory / filename
        response_path.write_text(full_response, encoding="utf-8")
        # Prune the history: drop the oldest files beyond the limit
        existing = sorted(directory.glob("*.txt"), key=lambda p: p.name)
        for old_path in existing[:-LLM_RESPONSE_KEEP]:
            old_path.unlink(missing_ok=True)
        logger.info(f"DEBUG: Complete LLM response for {mode} mode saved to: {response_path}")
        logger.debug(f"Full response length: {len(full_response)} characters")
        return response_path
    except Exception as e:
        logger.error(f"Failed to save LLM response for debugging: {e}")
        return None


async def generate_game_code_with_llm(
    lemonade_handle: LemonadeClient,
    model: str,
    mode: str,
    content: str,
    mode_data: str | None = None,
    no_thinking: bool = True,
) -> Union[str, ExtractedCode, LLMError, None]:
    if mode == "create":
        # pylint: disable=line-too-long
        system_prompt = """You are an expert Python game developer. Generate a complete, working Python game using pygame based on the user's description.

Rules:
1. Use ONLY the pygame library - no external images, sounds, or files
2. Create everything (graphics, colors, shapes) using pygame's built-in drawing functions
3. Make the game fully playable and fun
4. Include proper game mechanics (win/lose conditions, scoring if appropriate)
5. Use proper pygame event handling and game loop
6. Add comments explaining key parts of the code
7. Make sure the game window closes properly when the user clicks the X button
8. Use reasonable colors and make the game visually appealing with pygame primitives

Geometry rules (get these right - they are the most common failure):
- Use a fixed window size (e.g. 800x600) and define all coordinates relative to screen width/height
- Be consistent with the axes: X increases to the RIGHT, Y increases DOWNWARD (y=0 is the top of the screen)
- Implement exactly the movement/rotation direction the concept requires - do not swap the X and Y axes or mirror directions
- Distinguish walls (continuous barriers) from single points or edge collisions - implement what the concept describes, not a simpler approximation

Size rule: keep the game compact (roughly 300 lines of code or less). A complete, correct, compact game is better than a long, truncated one.

Generate ONLY the Python code wrapped in a markdown code block using triple backticks (```python). Do not include any explanations outside the code block."""

        user_prompt = f"Create a game: {content}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    elif mode == "debug":

        system_prompt = """You are a Python expert debugging a pygame script that has an error.

Rules:
1. Fix ONLY the bug described by the error - keep every other part of the code exactly as in the input (no restructuring, renaming, reformatting, or unrelated "improvements")
2. Use ONLY the pygame library - no external images, sounds, or files
3. Make sure the game window closes properly when the user clicks the X button
4. If the error indicates a missing asset or an import problem, replace it with a pygame-primitive equivalent instead of adding external files

Generate ONLY the complete fixed Python code wrapped in a markdown code block using triple backticks (```python). Do not include any explanations outside the code block."""

        user_prompt = f"""## Error details (from the game's stderr)
```
{mode_data}
```

## Script with error
```python
{content}
```

Please fix the bug described in the error details and provide the complete corrected code.
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    elif mode == "remix":
        system_prompt = """You are an expert Python game developer. You will be given an existing pygame game and a modification request. Your task is to modify the existing game according to the user's request while keeping it fully functional.

Rules:
1. Use ONLY the pygame library - no external images, sounds, or files
2. Keep the core game mechanics intact unless specifically asked to change them
3. Make the requested modifications while ensuring the game remains playable
4. Maintain proper pygame event handling and game loop
5. Add comments explaining the changes you made
6. Make sure the game window closes properly when the user clicks the X button
7. Use reasonable colors and make the game visually appealing with pygame primitives

Preservation rules (avoid regressions - this is the most common failure):
- Keep every part of the code that the modification request does NOT touch completely unchanged, exactly as in the input
- Do not restructure, reformat, or move code around
- Do not rename variables, functions, or classes unless the modification requires it
- Do not "fix", simplify, or improve existing behavior (including already-fixed quirks) unless explicitly asked
- Output the COMPLETE file: unchanged sections must appear exactly as in the input code

Generate ONLY the complete modified Python code wrapped in a markdown code block using triple backticks (```python)."""

        user_prompt = f"""Here is the existing game code:

```python
{content}
```

Please modify this game according to this request: {mode_data}

Provide the complete modified game code."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    else:
        logger.error(f"Invalid mode: {mode}")
        yield None
        return

    logger.debug(f"=== OpenAI Messages Debug for {mode} mode ===")
    logger.debug(f"Number of messages: {len(messages)}")
    for i, message in enumerate(messages):
        role = message["role"]
        content_text = message["content"]
        content_length = len(content_text)
        logger.debug(
            f"Message {i+1} - Role: {role}, Content length: {content_length} chars"
        )
        if content_length <= 300:
            logger.debug(f"Message {i+1} - Full content: {repr(content_text)}")
        else:
            logger.debug(f"Message {i+1} - Content start: {repr(content_text[:200])}")
            logger.debug(f"Message {i+1} - Content end: {repr(content_text[-100:])}")
    logger.debug("=== End OpenAI Messages Debug ===")

    try:
        openai_client = AsyncOpenAI(
            base_url=f"{lemonade_handle.url}/api/v1",
            api_key="dummy",
            timeout=600.0,
        )

        create_kwargs = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": 16000,
            "temperature": 0.3,
            "top_p": 0.9,
        }
        # Without reasoning tokens, the whole max_tokens budget goes to the
        # actual code (verified on Qwen3.5-9B-GGUF)
        if no_thinking:
            create_kwargs["extra_body"] = dict(NO_THINKING_KWARGS)

        response = await openai_client.chat.completions.create(**create_kwargs)

        full_response = ""
        finish_reason: Optional[str] = None
        async for chunk in response:
            if chunk.choices and len(chunk.choices) > 0:
                choice = chunk.choices[0]
                if choice.finish_reason is not None:
                    finish_reason = choice.finish_reason
                delta = choice.delta
                if delta.content is not None:
                    content_chunk = delta.content
                    full_response += content_chunk
                    yield content_chunk

        # Save the complete LLM response for debugging (fork: kept under
        # ~/.infinity-arcade/llm-responses/ with a limited history instead
        # of a throwaway file in /tmp)
        _save_llm_response(full_response, mode)

        # If the response hit the token limit, the code block is almost
        # certainly incomplete — report it explicitly instead of letting
        # an auto-fix silently fight against truncated code
        if finish_reason == "length":
            logger.warning(
                f"LLM response for {mode} mode was truncated (finish_reason='length'); "
                f"code is likely incomplete"
            )
            yield LLMError(
                message=(
                    "LLM response was cut off at the token limit — the generated "
                    "code is incomplete and cannot be used. Try a simpler game "
                    "prompt or increase the model's max_tokens."
                )
            )
            return

        extracted_code = _extract_python_code(full_response)
        if extracted_code:
            logger.debug(f"Successfully extracted code for {mode} mode")
            yield extracted_code
        else:
            logger.error(f"Could not extract code from LLM response in {mode} mode")
            yield None
    except Exception as e:
        logger.error(f"Error calling LLM for {mode}: {e}")
        yield None


class LLMService:
    """Centralized service for all LLM-related operations used by the arcade."""

    def __init__(self, lemonade_handle: LemonadeClient, model: str, no_thinking: bool = True):
        self._lemonade_handle = lemonade_handle
        self._model = model
        self._no_thinking = no_thinking

    async def stream_game_code(
        self, mode: str, content: str, mode_data: str | None = None
    ) -> AsyncGenerator[Union[str, ExtractedCode, LLMError, None], None]:
        async for chunk in generate_game_code_with_llm(
            self._lemonade_handle,
            self._model,
            mode,
            content,
            mode_data,
            no_thinking=self._no_thinking,
        ):
            yield chunk

    async def generate_title(self, prompt: str) -> str:
        return await generate_game_title(
            self._lemonade_handle, self._model, prompt, no_thinking=self._no_thinking
        )
