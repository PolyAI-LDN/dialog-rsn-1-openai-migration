"""Grand Meridian front desk, migrated to Dialog-RSN-1.

    uv run after.py                          # talk through the microphone
    uv run after.py --file call.wav          # a 24 kHz mono PCM16 WAV instead of the mic
    uv run after.py --say "Look up GM40912"  # one text turn, no audio

`diff before.py after.py` shows everything the migration changed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time
import wave

import sounddevice as sd
from dotenv import load_dotenv
from openai import AsyncOpenAI

from hotel import INSTRUCTIONS, TOOLS, run_tool

# MIGRATION: a new base URL and key. The SDK still appends /realtime and sends the key as
# Authorization: Bearer, both of which Dialog-RSN-1 accepts.
BASE_URL = os.environ.get("DIALOGUE_BASE_URL", "https://api.studio.poly.ai/v1")
API_KEY_VAR = "DIALOGUE_API_KEY"
MODEL = "dialog-rsn-1"

SAMPLE_RATE = 24_000
CHUNK_FRAMES = SAMPLE_RATE // 10  # 100 ms

SESSION = {
    "type": "realtime",
    "instructions": INSTRUCTIONS,
    "tools": TOOLS,
    # MIGRATION: replies are text only. Asking for audio, or sending audio.output, is an error.
    "output_modalities": ["text"],
    "audio": {
        "input": {
            "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
            # MIGRATION: no transcription model. The model transcribes the guest as part of its
            # turn, and the transcript still arrives as input_audio_transcription events.
            # MIGRATION: create_response is the only turn_detection field the service reads. The
            # model decides when the guest has finished, so the timing fields are rejected.
            "turn_detection": {"type": "server_vad", "create_response": True},
        },
    },
}


async def microphone(device):
    """Yield 100 ms chunks of PCM16 from the microphone."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def on_audio(indata, frames, time_info, status):
        loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

    if device and device.isdigit():
        device = int(device)
    with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                           blocksize=CHUNK_FRAMES, device=device, callback=on_audio):
        while True:
            yield await queue.get()


async def wav_file(path):
    """Yield a WAV file in 100 ms chunks at real time, then a second of silence."""
    with wave.open(path, "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
            sys.exit(f"{path} must be mono, 16-bit, {SAMPLE_RATE} Hz.")
        started, sent = time.monotonic(), 0
        while chunk := wav.readframes(CHUNK_FRAMES):
            yield chunk
            sent += len(chunk) // 2
            await asyncio.sleep(max(0.0, started + sent / SAMPLE_RATE - time.monotonic()))
    for _ in range(10):
        yield bytes(CHUNK_FRAMES * 2)
        await asyncio.sleep(0.1)


async def send_audio(conn, chunks):
    # MIGRATION: no echo avoidance. There's no assistant audio for the mic to pick up.
    async for chunk in chunks:
        await conn.input_audio_buffer.append(audio=base64.b64encode(chunk).decode())


async def handle_events(conn, one_turn: bool):
    """Print the conversation and answer tool calls. With one_turn, return after one reply."""
    reply = ""
    tool_called = False
    async for event in conn:
        kind = event.type
        if kind == "conversation.item.input_audio_transcription.completed":
            print(f"Guest:  {event.transcript.strip()}")
        # MIGRATION: the reply arrives as text events instead of audio and its transcript.
        elif kind == "response.output_text.delta":
            reply += event.delta
        elif kind == "response.output_text.done":
            print(f"Hotel:  {reply}\n")
            reply = ""
        elif kind == "response.output_item.done" and event.item.type == "function_call":
            item = event.item
            result = run_tool(item.name, item.arguments)
            print(f"  -> {item.name}({' '.join(item.arguments.split())}) = {result}")
            await conn.conversation.item.create(
                item={"type": "function_call_output", "call_id": item.call_id, "output": result})
            await conn.response.create()
            tool_called = True
        elif kind == "response.done":
            if one_turn and not tool_called:
                return
            tool_called = False
        elif kind == "error":
            print(f"[error] {event.error.message}", file=sys.stderr)


async def main(args):
    load_dotenv()
    key = os.environ.get(API_KEY_VAR)
    if not key:
        sys.exit(f"{API_KEY_VAR} is not set. Copy .env.example to .env and fill it in.")

    client = AsyncOpenAI(api_key=key, base_url=BASE_URL)
    async with client.realtime.connect(model=MODEL) as conn:
        await conn.session.update(session=SESSION)
        print(f"[connected to {MODEL} at {BASE_URL}]\n")

        if args.say:
            await conn.conversation.item.create(item={
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": args.say}]})
            await conn.response.create()
            await handle_events(conn, one_turn=True)
            return

        chunks = wav_file(args.file) if args.file else microphone(args.device)
        events = asyncio.create_task(handle_events(conn, one_turn=False))
        audio = asyncio.create_task(send_audio(conn, chunks))
        done, _ = await asyncio.wait({events, audio}, return_when=asyncio.FIRST_COMPLETED)
        if audio in done and args.file:
            await asyncio.wait({events}, timeout=15)  # let the last replies arrive
        for task in (events, audio):
            task.cancel()
        for task in done:
            if not task.cancelled() and task.exception():
                raise task.exception()


def parse_args():
    parser = argparse.ArgumentParser(description="Grand Meridian front desk voice agent.")
    parser.add_argument("--say", help="send one text turn instead of audio")
    parser.add_argument("--file", help="stream a 24 kHz mono PCM16 WAV instead of the mic")
    parser.add_argument("--device", help="microphone index or name, see `python -m sounddevice`")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        print("\nbye")
