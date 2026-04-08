"""
transcript_server.py — WebSocket server for streaming translation transcripts.

Broadcasts real-time transcript events to connected clients (terminal UI, Flutter app, etc).
Runs alongside the LiveKit agent on a separate port.

Protocol (server → client, JSON):
  {"type": "partial_input",     "text": "こんにちは...",    "is_final": false}
  {"type": "final_input",       "text": "こんにちは",      "is_final": true}
  {"type": "partial_output",    "text": "Xin chào...",     "is_final": false}
  {"type": "final_output",      "text": "Xin chào",       "is_final": true}
  {"type": "state",             "agent": "listening|thinking|speaking", "user": "speaking|listening"}
  {"type": "turn_complete"}

Connect: ws://localhost:8765
"""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("transcript_server")

# Connected WebSocket clients
_clients: set[asyncio.Queue] = set()
_broadcast_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()


# ── Public API (called from agent.py) ────────────────────────────────────────

def broadcast(event: dict[str, Any]) -> None:
    """Queue a transcript event for broadcast to all connected clients.

    Safe to call from any context (sync or async).
    """
    try:
        _broadcast_queue.put_nowait(event)
    except asyncio.QueueFull:
        pass  # drop if overwhelmed


# ── Terminal display ─────────────────────────────────────────────────────────

# ANSI colors for terminal output
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_ERASE_LINE = "\033[2K"  # erase entire current line

import sys

_last_phase = ""  # track current display phase to avoid conflicts


def _write(text: str, newline: bool = False) -> None:
    """Write to stderr to avoid conflict with logger output on stdout."""
    sys.stderr.write(f"{_ERASE_LINE}\r{text}")
    if newline:
        sys.stderr.write("\n")
    sys.stderr.flush()


def print_transcript(event: dict[str, Any]) -> None:
    """Print transcript event to terminal with colors.

    Uses \\033[2K (erase line) + \\r to cleanly overwrite partial updates.
    Writes to stderr so logger output on stdout doesn't interleave.
    """
    global _last_phase

    etype = event.get("type", "")
    text = event.get("text", "")

    if etype == "partial_input":
        _last_phase = "input"
        _write(f"{_DIM}{_CYAN}[听] {text}{_RESET}")

    elif etype == "final_input":
        _last_phase = "input_done"
        _write(f"{_CYAN}{_BOLD}[源] {text}{_RESET}", newline=True)

    elif etype == "partial_output":
        _last_phase = "output"
        _write(f"{_DIM}{_GREEN}[译] {text}{_RESET}")

    elif etype == "final_output":
        _last_phase = "output_done"
        _write(f"{_GREEN}{_BOLD}[翻] {text}{_RESET}", newline=True)

    elif etype == "state":
        agent_state = event.get("agent", "")
        if agent_state == "thinking" and _last_phase in ("input_done", "input"):
            _write(f"{_YELLOW}  ⋯ translating...{_RESET}")

    elif etype == "turn_complete":
        _last_phase = ""
        _write(f"{_DIM}{'─' * 50}{_RESET}", newline=True)


# ── WebSocket server ─────────────────────────────────────────────────────────

async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Not used — we use websockets library instead."""
    pass


async def _client_handler(websocket):
    """Handle a single WebSocket client connection."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _clients.add(queue)
    logger.info("Transcript client connected (%d total)", len(_clients))
    try:
        while True:
            event = await queue.get()
            await websocket.send(json.dumps(event, ensure_ascii=False))
    except Exception:
        pass
    finally:
        _clients.discard(queue)
        logger.info("Transcript client disconnected (%d remaining)", len(_clients))


async def _broadcaster():
    """Fan out events from the broadcast queue to all connected clients."""
    while True:
        event = await _broadcast_queue.get()

        # Always print to terminal
        print_transcript(event)

        # Send to all WebSocket clients
        for q in list(_clients):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # drop for slow clients


async def start_server(port: int = 8765) -> None:
    """Start the WebSocket transcript server.

    Call this as a background task from the agent entrypoint.
    """
    import websockets

    # Start the broadcaster task
    asyncio.create_task(_broadcaster())

    async with websockets.serve(_client_handler, "0.0.0.0", port):
        logger.info("Transcript server listening on ws://0.0.0.0:%d", port)
        await asyncio.Future()  # run forever
