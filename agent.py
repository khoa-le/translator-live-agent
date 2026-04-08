"""
agent.py — LiveKit Agents entry point for real-time translation.

Supports three modes:
  pipeline        — STT → LLM (translate) → TTS  (most flexible)
  realtime_gemini — Gemini Live end-to-end audio   (lowest latency)
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
from livekit.agents import inference
from livekit.plugins import silero

from prompt import build_translation_instructions, build_realtime_instructions

load_dotenv()
logger = logging.getLogger("translator")
logging.basicConfig(level=logging.INFO)

# ── Configuration ────────────────────────────────────────────────────────────

SOURCE = os.getenv("SOURCE_LANGUAGE", "Japanese")
TARGET = os.getenv("TARGET_LANGUAGE", "Vietnamese")
MODE = os.getenv("TRANSLATION_MODE", "pipeline")
DOMAIN = os.getenv("TRANSLATION_DOMAIN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


# ── Pipeline mode: STT → LLM → TTS ─────────────────────────────────────────

def create_pipeline_session() -> tuple[AgentSession, Agent]:
    """Create session using discrete STT + LLM + TTS pipeline.

    STT transcribes source language, LLM translates text, TTS speaks it.
    """
    stt = inference.STT(
        "google/gemini-2.0-flash",
        language=SOURCE,
        api_key=GOOGLE_API_KEY,
    )

    llm = inference.LLM(
        "google/gemini-2.0-flash",
        api_key=GOOGLE_API_KEY,
    )

    tts = inference.TTS(
        "google/gemini-2.0-flash",
        language=TARGET,
        api_key=GOOGLE_API_KEY,
    )

    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=silero.VAD.load(),
    )

    instructions = build_translation_instructions(SOURCE, TARGET, domain=DOMAIN)
    agent = Agent(instructions=instructions)

    return session, agent


# ── Realtime Gemini mode: end-to-end audio ──────────────────────────────────

def create_realtime_gemini_session() -> tuple[AgentSession, Agent]:
    """Create session using Gemini Live API (audio-in → audio-out)."""
    from livekit.plugins import google
    from google.genai import types

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
    """Create session using OpenAI Realtime API (audio-in → audio-out)."""
    from livekit.plugins import openai

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
    "pipeline": create_pipeline_session,
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
    def on_item(item):
        logger.info("[%s] %s", item.role, getattr(item, "text", "")[:120])

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(),
    )


if __name__ == "__main__":
    cli.run_app(server)
