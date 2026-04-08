# Translator Live Agent

Real-time speech translation agent built on [LiveKit Agents](https://github.com/livekit/agents). Speak in one language, hear the translation in another — powered by Gemini Live or OpenAI Realtime API.

Default language pair: **Japanese → Vietnamese** (configurable).

## How It Works

```
Mic → Silero VAD → Gemini Live / OpenAI Realtime → Translated Audio → Speaker
```

The agent uses end-to-end realtime models where a single API call handles speech recognition, translation, and speech synthesis in one pass. Silero VAD (voice activity detection) runs locally to detect when you start and stop speaking.

### Translation Modes

| Mode | Provider | Latency | API Key Required |
|------|----------|---------|------------------|
| `realtime_gemini` | Gemini 3.1 Flash Live | Lowest | `GOOGLE_API_KEY` |
| `realtime_openai` | GPT-4o Realtime | Low | `OPENAI_API_KEY` |

## Prerequisites

- Python 3.10+ (tested with 3.12)
- A microphone and speaker
- At least one API key (Google AI Studio or OpenAI)

## Quick Start

### 1. Clone and install

```bash
cd ~/workspace/translator-live-agent

# Create virtualenv with Python 3.10+
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e "."
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and add your API key:

```env
GOOGLE_API_KEY=your-key-from-aistudio.google.com

SOURCE_LANGUAGE=Japanese
TARGET_LANGUAGE=Vietnamese
TRANSLATION_MODE=realtime_gemini
```

### 3. Run

#### Console mode (local mic/speaker, no server needed)

```bash
python agent.py console
```

This opens your microphone and speaker directly. Speak in the source language and hear the translation through your speaker.

Options:

```bash
# List available audio devices
python agent.py console --list-devices

# Specify input/output devices
python agent.py console --input-device 1 --output-device 3

# Text mode (type instead of speak, for testing)
python agent.py console --text
```

#### Dev mode (with LiveKit server)

```bash
python agent.py dev
```

Requires a running LiveKit server. Set `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` in `.env`. Supports hot reload on code changes.

#### Production mode

```bash
python agent.py start
```

Connects to a LiveKit server as a production worker.

## Configuration

All settings are in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | — | Google AI Studio API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `SOURCE_LANGUAGE` | `Japanese` | Language to translate from |
| `TARGET_LANGUAGE` | `Vietnamese` | Language to translate to |
| `TRANSLATION_MODE` | `realtime_gemini` | `realtime_gemini` or `realtime_openai` |
| `TRANSLATION_DOMAIN` | — | Optional: `medical`, `technical`, `legal`, `business`, `casual` |
| `LIVEKIT_URL` | `ws://localhost:7880` | LiveKit server URL (dev/start modes) |
| `LIVEKIT_API_KEY` | `devkey` | LiveKit API key (dev/start modes) |
| `LIVEKIT_API_SECRET` | `secret` | LiveKit API secret (dev/start modes) |
| `PERFORMANCE_PROFILE` | `meeting` | `meeting` (fast) or `default` (standard) |

### Domain context

Set `TRANSLATION_DOMAIN` to get domain-specific translation style:

```env
TRANSLATION_DOMAIN=medical    # precise medical terminology
TRANSLATION_DOMAIN=business   # professional business language
TRANSLATION_DOMAIN=casual     # natural conversational style
```

### Language pairs

Any language supported by the underlying model. Examples:

```env
SOURCE_LANGUAGE=English
TARGET_LANGUAGE=Japanese

SOURCE_LANGUAGE=Chinese
TARGET_LANGUAGE=English

SOURCE_LANGUAGE=Korean
TARGET_LANGUAGE=Vietnamese
```

## Meeting Translation (Zoom/Teams/Discord)

Translate any meeting in real-time by routing audio through BlackHole virtual audio.

### Audio flow

```
Meeting speaker → BlackHole → Agent (translate) → BlackHole → Meeting mic
                                    ↘ Your speakers (via Multi-Output Device)
```

### Setup

#### 1. Install BlackHole

```bash
brew install blackhole-2ch
```

Or download from https://existential.audio/blackhole/

#### 2. Create a Multi-Output Device (so you hear both original + translation)

- Open `/Applications/Utilities/Audio MIDI Setup.app`
- Click `+` at bottom-left → "Create Multi-Output Device"
- Check: `BlackHole 2ch` + your speakers (e.g. "Mac mini Speakers")
- Right-click → rename to "Translation Output"

#### 3. Configure your meeting app

| Setting | Value |
|---------|-------|
| Speaker / Audio Output | BlackHole 2ch |
| Microphone / Audio Input | BlackHole 2ch |

This sends meeting audio to the agent and receives translated audio back.

#### 4. Set macOS system output

System Settings → Sound → Output → **Translation Output**

This lets you hear both the original meeting audio and the translated audio.

#### 5. Run the agent

```bash
python agent.py console --input-device "BlackHole" --output-device "BlackHole"
```

Or run the guided setup first:

```bash
python setup_audio.py
```

### Meeting performance profile

The `meeting` profile (default) optimizes for multi-speaker calls:

| Setting | Default | Meeting |
|---------|---------|---------|
| VAD silence detection | 0.55s | 0.40s |
| VAD speech threshold | 0.50 | 0.55 |
| Endpointing min delay | 0.5s | 0.3s |
| Endpointing max delay | 3.0s | 2.0s |
| AEC warmup | 3.0s | 1.0s |
| Preemptive generation | on | on |

Set in `.env`:

```env
PERFORMANCE_PROFILE=meeting   # optimized for calls (default)
PERFORMANCE_PROFILE=default   # standard settings
```

## Project Structure

```
translator-live-agent/
├── agent.py           # Entry point — session factory + LiveKit agent server
├── prompt.py          # Translation prompt builder (domain, glossary, language notes)
├── setup_audio.py     # BlackHole audio setup checker and guide
├── pyproject.toml     # Dependencies
├── .env               # Configuration (gitignored)
└── .env.example       # Configuration template
```

## Architecture

Built on the [LiveKit Agents](https://github.com/livekit/agents) framework:

- **AgentServer** — manages worker lifecycle and job dispatch
- **AgentSession** — owns the voice pipeline (VAD → model → audio output)
- **Agent** — holds the translation instructions
- **Silero VAD** — local neural voice activity detection (~1MB LSTM, CPU-only)
- **Google/OpenAI Realtime** — end-to-end audio models via WebSocket

The agent connects to a LiveKit room (or runs locally in console mode), receives audio from participants, translates it, and publishes the translated audio back.

## Troubleshooting

**"No audio devices found"** — Make sure your microphone is connected. Use `--list-devices` to check.

**Console exits immediately** — Check your API key in `.env`. Look at the log output for auth errors.

**High latency** — Gemini mode (`realtime_gemini`) is typically faster than OpenAI. Ensure you're on a stable network.

**Wrong language detected** — Make sure `SOURCE_LANGUAGE` matches what you're speaking. The model auto-detects but a hint helps accuracy.
