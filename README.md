
<pre align="center">
██╗███╗   ██╗███████╗██╗███╗   ██╗██╗████████╗██╗   ██╗
██║████╗  ██║██╔════╝██║███╗   ██║██║╚██╔══╝██║██║ ██╔╝
██║██╔██╗ ██║█████╗  ██║██╔══╗ ██║██║ ╚═█║ ███████║
██║██║╚██╗██║██╔══╝  ██║██╔══╝██║██║ ██╔╝ ╚════██║
██║██║ ╚████║███████╗████║████╗  ██║██║██╔╝ ███████╔╝
╚═╝╚═╝  ╚═══╝╚══════╝╚═══╝╚═══╝  ╚═╝╚═╝╚═╝   ╚══════╝
</pre>

<p align="center">
  <a href="https://discord.gg/5xXzkMu8Zk">
    <img src="https://img.shields.io/badge/Discord-7289DA?logo=discord&logoColor=white" alt="Discord" /></a>
  <a href="https://lemonade-server.ai/#linux" title="Ubuntu 24.04 & 25.04 Supported">
    <img src="https://img.shields.io/badge/Ubuntu-24.04%20%7C%2025.04-E95420?logo=ubuntu&logoColor=white" alt="Ubuntu 24.04 | 25.04" /></a>
  <a href="https://lemonade-server.ai/">
    <img src="https://img.shields.io/badge/Python-3.10--3.13-blue?logo=python&logoColor=white" alt="Made with Python" /></a>
  <a href="https://github.com/soulafein83/infinity-arcade">
    <img src="https://img.shields.io/badge/fork-soulafein83-infinity--arcade-lightgrey" alt="Fork badge" /></a>
  <a href="https://github.com/soulafein83/infinity-arcade/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

Create playable retro-style games with LLMs in minutes! Enter your prompt and your game pops open, it's that simple.

> **Fork of [lemonade-sdk/infinity-arcade](https://github.com/lemonade-sdk/infinity-arcade), developed independently.**
> Key differences from upstream: the app **never starts the Lemonade Server** and **never downloads models** —
> it connects to your own Lemonade Server and uses the models you manage there. Everything is configurable
> via environment variables (see [Configuration](#configuration)).

Push your imagination to the limit, it's 100% free and local.

![Infinity Arcade GIF](https://github.com/lemonade-sdk/assets/blob/main/arcade/infinity-arcade-demo.gif?raw=true)

## Hardware Requirement

Infinity Arcade will detect the hardware you have available and suggest a model; in this fork you can override
any model via environment variables (see [Configuration](#configuration)).

| Configuration | GPU/APU | Memory | Disk Space | Suggested LLM |
|---------------|---------|---------|------------|---------------|
| **Minimum (CPU)** | Ryzen AI 7000-series chip or newer | 32 GB RAM | 5 GB | [Playable1-GGUF](https://huggingface.co/playable/Playable1-GGUF) |
| **Suggested (iGPU)** | Ryzen AI 300-series chip or newer | 32 GB RAM | 5 GB | [Playable1-GGUF](https://huggingface.co/playable/Playable1-GGUF) |
| **Suggested (dGPU)** | Radeon 7800XT or newer | 16 GB VRAM | 20 GB | Qwen3-Coder-30B |
| **Suggested (APU)** | Strix Halo (Ryzen AI MAX 395) | 64 GB unified memory | 20 GB | Qwen3-Coder-30B |

## Quick Start

### Linux (and Windows Devs)

1. Clone this repository:
   ```bash
   git clone https://github.com/soulafein83/infinity-arcade
   cd infinity-arcade
   ```

2. Install the package:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

3. Make sure **your own Lemonade Server** is running and has at least one model installed
   (default: `http://127.0.0.1:13305`, model management at `http://127.0.0.1:13305/#model-management`).
   The app does **not** install or start the server — it only reports its status.

4. Run it:
   ```bash
   infinity-arcade
   ```

   The web UI opens at `http://127.0.0.1:8081`.

> Windows quick start (upstream binary): see the
> [original repository's releases](https://github.com/lemonade-sdk/infinity-arcade/releases).

## Features

- **Your own Lemonade Server**: connects to the Lemonade Server you already run; models are managed by you
  in the server's model manager (nothing is downloaded or started by this app).
- **AI Game Generation**: Describe a game concept and watch as an LLM creates a playable Python game.
- **Game Library**: All generated games are saved and can be replayed anytime.
- **Game control from the UI**: `● RUNNING` badge, **Stop** button, and the game's **last error** on each game card.
- **Per-game logs**: every game's stdout/stderr is written to `~/.infinity-arcade/logs/{game_id}.log` and is
  viewable via `GET /api/game-log/{game_id}` (last N lines + last error line).
- **Source code viewer**: view any game's code in the browser (modal with copy button) without leaving the UI.
- **Remix lineage**: games track their parents (`parent_game_id`, `version`) in `metadata.json`; the UI shows a
  clickable chain of versions (oldest → newest), and remixes always build on the newest version in the chain.
- **Safe auto-fix**: before an auto-fix overwrites a game, the previous version is backed up to
  `~/.infinity-arcade/backups/{game_id}.v{n}.py`; deleting a game removes its backups and log too.
- **Reliable generation**: truncated LLM responses (cut-off code blocks) are detected and reported as a clear
  error instead of silently triggering a failing auto-fix.
- **Game previews**: newly created and remixed games are run headless for a few seconds
  (`--screenshot` mode, dummy SDL/audio drivers) and a preview thumbnail is saved to
  `~/.infinity-arcade/previews/{game_id}.png`. Each game card shows the thumbnail (click for a
  full-size viewer); games without a preview (e.g. older games) fall back to a placeholder.
  Never blocks generation — a failed capture just means no thumbnail.

## Configuration

| Setting | How | Default |
|---|---|---|
| Lemonade Server URL | `LEMONADE_URL` | `http://127.0.0.1:13305` |
| Model (override any tier) | `LEMONADE_MODEL_HIGH_END`, `LEMONADE_MODEL_NPU`, `LEMONADE_MODEL_DEFAULT` | hardware-based selection |
| Force one specific model | `INFINITY_ARCADE_MODEL` | hardware-based selection |
| Thinking/reasoning mode | `INFINITY_ARCADE_THINKING=1` to enable | **off** (saves the token budget for the generated code) |
| Auto-fix attempts on launch failure | `INFINITY_ARCADE_MAX_RETRIES` | `1` |
| Preview screenshot length (headless run) | `INFINITY_ARCADE_SCREENSHOT_SECONDS` | `3` (clamped to 1–60) |
| Preview screenshots on/off | `INFINITY_ARCADE_SCREENSHOTS=0` to disable | **on** |
| Web server port | `--port` CLI flag or `INFINITY_ARCADE_PORT` | `8081` |
| Don't open the browser | `--no-browser` | browser opens at startup |
| Log level | `--log-level {debug,info,warning,error}` | `info` |

Example:

```bash
LEMONADE_URL=http://127.0.0.1:13305 \
INFINITY_ARCADE_MODEL=Qwen3.5-9B-MTP-GGUF-UD-Q4_K_XL \
infinity-arcade --port 8081 --no-browser
```

> Thinking mode is off by default because, on models with reasoning tokens (e.g. Qwen3.5-9B),
> reasoning is deducted from `max_tokens` *before* the code is produced and can truncate the output.

## Architecture

### Game Generation

Games are generated with the following constraints:
- Pure Python using the pygame library only.
- No external images, sounds, or asset files.
- Complete and playable with proper game mechanics.
- Proper event handling and game loops.
- Visual appeal using pygame's built-in drawing functions.

The generation prompts (create / remix / debug) are tuned in this fork: explicit geometry rules to prevent
swapped axes, strict "keep everything else unchanged" instructions for remixes, and the game's recent stderr
lines included in debug requests so the model gets full context. Newly created and remixed games are also
required to support an optional `--screenshot <seconds>` CLI mode (headless timed run saving a PNG) — this is
how the app captures preview thumbnails without injecting any code into the game files.

### Game Lifecycle

- Games run as child processes in their own session; stopping a game kills the whole process group
  (`os.killpg`), and the app registers a SIGTERM handler so `kill <pid>` cleans up running games
  exactly like Ctrl+C.
- `POST /api/stop-game/{game_id}` stops a running game; the Stop button on the game card calls it.
- Finished game processes are removed automatically before every API request
  (a single HTTP middleware), so the "RUNNING" state always reflects reality.

### Game Cache

Games and their artifacts are cached under the `.infinity-arcade` folder in your home directory.

```
~/.infinity-arcade/
├── games/
│   ├── metadata.json    # Titles, descriptions, parent_game_id, version
│   ├── abc12345.py      # Generated game files
│   └── xyz67890.py
├── logs/
│   ├── abc12345.log     # Per-game stdout/stderr
│   └── xyz67890.log
├── backups/
│   ├── abc12345.v1.py   # Pre-auto-fix backup of abc12345.py
│   └── abc12345.v2.py
├── previews/
│   ├── abc12345.png     # Preview screenshot (headless `--screenshot` run)
└── llm-responses/
    └── 20250101T120000_create.txt   # Full LLM responses (debug, latest 20 kept)
```

`metadata.json` is written atomically (tmp file + `os.replace`), so a crash mid-write never corrupts it.

## Testing

Unit tests live in `test/` and can be run with pytest (installed with the package):

```bash
pytest test/ --ignore=test/lemonade_client_integration.py
```

The integration tests require a live Lemonade Server and are excluded from CI.

## Troubleshooting

### "Server Offline" Status
- The app never starts the server — make sure **you** have your Lemonade Server running on
  `http://127.0.0.1:13305` (or set `LEMONADE_URL` to point elsewhere).
- Check that you have models installed by opening the model manager: `http://127.0.0.1:13305/#model-management`.
- Visit [lemonade-server.ai](https://lemonade-server.ai) for setup instructions.

### "Code truncated" Error
- The model ran out of tokens before closing its code block. The app now reports this explicitly
  instead of silently auto-fixing broken code.
- Try a simpler game concept, or enable `INFINITY_ARCADE_THINKING` is *not* the fix — keep thinking mode
  off (default) so the full token budget goes to the code.

### Game Won't Launch
- Check the game's log: `~/.infinity-arcade/logs/{game_id}.log` (also shown as "last error" on the game card).
- Try regenerating the game with a more specific prompt.

### Generation Failures
- Try a simpler game concept.
- Make sure your selected model supports code generation.
- Check the `infinity-arcade` and Lemonade Server logs for errors.

## Examples

Here are some example prompts that work well:

- **Classic Games**: "pong", "tetris", "pacman maze game", "asteroids"
- **Variations**: "snake but food teleports", "breakout with power-ups", "flappy bird in space"
- **Original Ideas**: "catching falling stars", "color matching puzzle", "maze with moving walls"

## Contributing

Contributions are welcome:
- Fork the repository and send a pull request to `main`.
- Share interesting game prompts and results by opening an issue!
- Report bugs and feature requests in the issues tracker.

## License and Attribution

This project is licensed under the [MIT license](./LICENSE) and derives from
[lemonade-sdk/infinity-arcade](https://github.com/lemonade-sdk/infinity-arcade).
It is built with Python with ❤️ for the gaming and LLM communities and stands on the shoulders of
many other open source tools, including llama.cpp, Hugging Face Hub, and the OpenAI API.

## Maintainer

- Original project maintained by [@jeremyfowers](https://github.com/jeremyfowers).
- This fork maintained by [@soulafein83](https://github.com/soulafein83).
