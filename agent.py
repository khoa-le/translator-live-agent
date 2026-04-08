"""
agent.py — LiveKit Agents entry point for real-time translation.

Supports two modes:
  realtime_gemini — Gemini Live end-to-end audio (default, lowest latency)
  realtime_openai — OpenAI Realtime end-to-end audio

Run:
  python agent.py console   # local mic/speaker, no LiveKit server needed
  python agent.py dev       # dev mode with hot reload
  python agent.py start     # production worker
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


# ── Realtime Gemini mode: end-to-end audio ──────────────────────────────────

def create_realtime_gemini_session() -> tuple[AgentSession, Agent]:
    """Create session using Gemini Live API (audio-in → audio-out).

    Single model handles STT + translation + TTS in one pass.
    Requires only GOOGLE_API_KEY (no service account needed).
    """
    model = google.realtime.RealtimeModel(
        model="gemini-2.0-flash-live-001",
        voice="Aoede",
        api_key=GOOGLE_API_KEY,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    session = AgentSession(
        llm=model,
        vad=silero.VAD.load(),
    )

    instructions = build_realtime_instructions(SOURCE, TARGET, domain=DOMAIN)
    agent = Agent(instructions=instructions)

    return session, agent


# ── Realtime OpenAI mode: end-to-end audio ──────────────────────────────────

def create_realtime_openai_session() -> tuple[AgentSession, Agent]:
    """Create session using OpenAI Realtime API (audio-in → audio-out).

    Requires OPENAI_API_KEY.
    """
    model = openai.realtime.RealtimeModel(
        model="gpt-4o-realtime-preview",
        voice="alloy",
        api_key=OPENAI_API_KEY,
    )

    session = AgentSession(
        llm=model,
        vad=silero.VAD.load(),
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
    logger.info("Starting translation agent: %s → %s (mode=%s)", SOURCE, TARGET, MODE)

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
