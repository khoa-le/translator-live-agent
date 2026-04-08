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

Streaming transcripts:
  Partial source + translation text streams to terminal in real-time.
  WebSocket on ws://localhost:8765 for Flutter/web clients.

Meeting setup:
  1. brew install blackhole-2ch
  2. Set Zoom/Teams speaker → BlackHole 2ch, mic → BlackHole 2ch
  3. python agent.py console --input-device "BlackHole" --output-device "BlackHole"
  See setup_audio.py for full guide.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from livekit.agents import AgentServer, AgentSession, Agent, JobContext, cli, RoomInputOptions
from livekit.plugins import silero, google, openai
from google.genai import types

from prompt import build_realtime_instructions
from transcript_server import broadcast, start_server as start_transcript_server

load_dotenv()
logger = logging.getLogger("translator")
logging.basicConfig(level=logging.INFO, stream=__import__("sys").stderr)

# ── Configuration ────────────────────────────────────────────────────────────

SOURCE = os.getenv("SOURCE_LANGUAGE", "Japanese")
TARGET = os.getenv("TARGET_LANGUAGE", "Vietnamese")
MODE = os.getenv("TRANSLATION_MODE", "realtime_gemini")
DOMAIN = os.getenv("TRANSLATION_DOMAIN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TRANSCRIPT_PORT = int(os.getenv("TRANSCRIPT_PORT", "8765"))

# Performance profile: "default" or "meeting"
PROFILE = os.getenv("PERFORMANCE_PROFILE", "meeting")


# ── VAD factory ──────────────────────────────────────────────────────────────

def create_vad():
    """Create Silero VAD with profile-based tuning."""
    if PROFILE == "meeting":
        return silero.VAD.load(
            min_speech_duration=0.03,
            min_silence_duration=0.40,
            activation_threshold=0.55,
            prefix_padding_duration=0.3,
            sample_rate=16000,
            force_cpu=True,
        )
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
    """Gemini Live API — audio-in → audio-out in one pass."""
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
    """OpenAI Realtime API — audio-in → audio-out."""
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


# ── Transcript event hooks ───────────────────────────────────────────────────

def attach_transcript_hooks(session: AgentSession) -> None:
    """Wire up AgentSession events to stream transcripts in real-time.

    Source text:  user_input_transcribed → partial/final as speaker talks
    Translation:  Hook into realtime model's generation text_stream for
                  word-by-word output — does NOT wait for turn to finish.
    """

    # ── Source language: partial + final as speaker talks ─────────────
    @session.on("user_input_transcribed")
    def on_user_transcript(event):
        text = event.transcript
        is_final = event.is_final
        if text:
            broadcast({
                "type": "final_input" if is_final else "partial_input",
                "text": text,
                "is_final": is_final,
            })

    # ── Agent state changes ──────────────────────────────────────────
    @session.on("agent_state_changed")
    def on_agent_state(event):
        broadcast({
            "type": "state",
            "agent": event.new_state,
        })

    # ── Translation output: stream word-by-word from generation ──────
    # Hook into the realtime session's generation_created event to read
    # output text as it streams — this fires for each text chunk from
    # the model, not waiting for the full sentence.

    async def _stream_generation_text(gen_event):
        """Read text_stream from each generation and broadcast chunks."""
        async for msg_gen in gen_event.message_stream:
            accumulated = ""
            async for chunk in msg_gen.text_stream:
                if chunk:
                    accumulated += chunk
                    broadcast({
                        "type": "partial_output",
                        "text": accumulated,
                        "is_final": False,
                    })
            # Generation done — send final
            if accumulated:
                broadcast({
                    "type": "final_output",
                    "text": accumulated,
                    "is_final": True,
                })
                broadcast({"type": "turn_complete"})

    def _on_generation_created(gen_event):
        asyncio.create_task(_stream_generation_text(gen_event))

    # We attach this after session.start() when the realtime session exists
    session._generation_created_handler = _on_generation_created


def attach_realtime_hooks(session: AgentSession) -> None:
    """Attach hooks to the internal realtime session after it's created.

    Must be called after session.start() so _activity._rt_session exists.
    """
    handler = getattr(session, "_generation_created_handler", None)
    if not handler:
        return

    activity = getattr(session, "_activity", None)
    if activity is None:
        return

    rt_session = getattr(activity, "_rt_session", None)
    if rt_session is None:
        logger.warning("No realtime session found — output streaming unavailable")
        return

    rt_session.on("generation_created", handler)
    logger.info("Realtime output text streaming attached")


# ── Entry point ──────────────────────────────────────────────────────────────

server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    logger.info(
        "Starting translation: %s → %s (mode=%s, profile=%s)",
        SOURCE, TARGET, MODE, PROFILE,
    )

    # Start transcript WebSocket server in background
    asyncio.create_task(start_transcript_server(port=TRANSCRIPT_PORT))

    await ctx.connect()

    factory = SESSION_FACTORIES.get(MODE)
    if not factory:
        raise ValueError(
            f"Unknown TRANSLATION_MODE={MODE!r}. "
            f"Choose from: {', '.join(SESSION_FACTORIES)}"
        )

    session, agent = factory()

    # Attach transcript hooks (session-level events)
    attach_transcript_hooks(session)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(),
    )

    # After start, attach to the realtime model's text stream
    # Small delay to let the activity initialize
    await asyncio.sleep(0.5)
    attach_realtime_hooks(session)


if __name__ == "__main__":
    cli.run_app(server)
