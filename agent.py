"""
agent.py — LiveKit Agents entry point for real-time translation.

Supports two translation modes:
  realtime_gemini — Gemini Live end-to-end audio (default, lowest latency)
  realtime_openai — OpenAI Realtime end-to-end audio

Run modes:
  python agent.py console                          # local mic/speaker
  python agent.py console --input-device "BlackHole" --output-device "BlackHole"
                                                    # meeting translation via BlackHole
  python agent.py dev                               # dev mode with hot reload
  python agent.py start                             # production worker

Meeting setup:
  1. brew install blackhole-2ch
  2. Set Zoom/Teams speaker → BlackHole 2ch, mic → BlackHole 2ch
  3. python agent.py console --input-device "BlackHole" --output-device "BlackHole"
  See setup_audio.py for full guide.
"""

import logging
import os

from dotenv import load_dotenv
from livekit.agents import AgentServer, AgentSession, Agent, JobContext, cli, RoomInputOptions
from livekit.plugins import silero, google, openai
from google.genai import types

from prompt import build_realtime_instructions

load_dotenv()
logger = logging.getLogger("translator")
logging.basicConfig(level=logging.INFO)

# ── Configuration ────────────────────────────────────────────────────────────

SOURCE = os.getenv("SOURCE_LANGUAGE", "Japanese")
TARGET = os.getenv("TARGET_LANGUAGE", "Vietnamese")
MODE = os.getenv("TRANSLATION_MODE", "realtime_gemini")
DOMAIN = os.getenv("TRANSLATION_DOMAIN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Performance profile: "default" or "meeting"
# Meeting mode uses tighter VAD and faster endpointing for multi-speaker calls
PROFILE = os.getenv("PERFORMANCE_PROFILE", "meeting")


# ── VAD factory ──────────────────────────────────────────────────────────────

def create_vad():
    """Create Silero VAD with profile-based tuning."""
    if PROFILE == "meeting":
        # Meeting-optimized: faster detection, tighter silence window
        return silero.VAD.load(
            min_speech_duration=0.03,
            min_silence_duration=0.40,
            activation_threshold=0.55,
            prefix_padding_duration=0.3,
            sample_rate=16000,
            force_cpu=True,
        )
    # Default: standard settings
    return silero.VAD.load(force_cpu=True)


# ── Session factory helpers ──────────────────────────────────────────────────

def _meeting_turn_handling() -> dict:
    """Turn handling config optimized for meeting translation."""
    if PROFILE != "meeting":
        return {}
    return {
        "turn_detection": "vad",
        "endpointing": {
            "min_delay": 0.3,
            "max_delay": 2.0,
        },
        "interruption": {
            "enabled": True,
            "mode": "vad",
            "min_duration": 0.3,
        },
    }


# ── Realtime Gemini mode ────────────────────────────────────────────────────

def create_realtime_gemini_session() -> tuple[AgentSession, Agent]:
    """Create session using Gemini Live API (audio-in → audio-out).

    Single model handles STT + translation + TTS in one pass.
    Requires only GOOGLE_API_KEY.
    """
    model = google.realtime.RealtimeModel(
        model="gemini-3.1-flash-live-preview",
        voice="Aoede",
        api_key=GOOGLE_API_KEY,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    turn_handling = _meeting_turn_handling()
    session = AgentSession(
        llm=model,
        vad=create_vad(),
        preemptive_generation=True,
        aec_warmup_duration=1.0 if PROFILE == "meeting" else 3.0,
        **({"turn_handling": turn_handling} if turn_handling else {}),
    )

    instructions = build_realtime_instructions(SOURCE, TARGET, domain=DOMAIN)
    agent = Agent(instructions=instructions)

    return session, agent


# ── Realtime OpenAI mode ────────────────────────────────────────────────────

def create_realtime_openai_session() -> tuple[AgentSession, Agent]:
    """Create session using OpenAI Realtime API (audio-in → audio-out).

    Requires OPENAI_API_KEY.
    """
    model = openai.realtime.RealtimeModel(
        model="gpt-4o-realtime-preview",
        voice="alloy",
        api_key=OPENAI_API_KEY,
    )

    turn_handling = _meeting_turn_handling()
    session = AgentSession(
        llm=model,
        vad=create_vad(),
        preemptive_generation=True,
        aec_warmup_duration=1.0 if PROFILE == "meeting" else 3.0,
        **({"turn_handling": turn_handling} if turn_handling else {}),
    )

    instructions = build_realtime_instructions(SOURCE, TARGET, domain=DOMAIN)
    agent = Agent(instructions=instructions)

    return session, agent


# ── Session factory ──────────────────────────────────────────────────────────

SESSION_FACTORIES = {
    "realtime_gemini": create_realtime_gemini_session,
    "realtime_openai": create_realtime_openai_session,
}


# ── Entry point ──────────────────────────────────────────────────────────────

server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    logger.info(
        "Starting translation: %s → %s (mode=%s, profile=%s)",
        SOURCE, TARGET, MODE, PROFILE,
    )

    await ctx.connect()

    factory = SESSION_FACTORIES.get(MODE)
    if not factory:
        raise ValueError(
            f"Unknown TRANSLATION_MODE={MODE!r}. "
            f"Choose from: {', '.join(SESSION_FACTORIES)}"
        )

    session, agent = factory()

    # Log transcript events for debugging
    @session.on("conversation_item_added")
    def on_item(event):
        msg = event.item
        role = getattr(msg, "role", "unknown")
        content = msg.content if hasattr(msg, "content") else []
        text = " ".join(
            getattr(c, "text", "") or "" for c in content if hasattr(c, "text")
        )
        if text:
            logger.info("[%s] %s", role, text[:120])

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(),
    )


if __name__ == "__main__":
    cli.run_app(server)
