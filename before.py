"""Grand Meridian front desk on the OpenAI Realtime API, before the migration.

    uv run before.py                          # talk through the microphone
    uv run before.py --file call.wav          # a 24 kHz mono PCM16 WAV instead of the mic
    uv run before.py --say "Look up GM40912"  # one text turn, spoken reply

`diff before.py after.py` shows everything the migration changed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import threading
import time
import wave

import sounddevice as sd
from dotenv import load_dotenv
from openai import AsyncOpenAI

from hotel import INSTRUCTIONS, TOOLS, run_tool

load_dotenv()  # before the settings below are read, so .env can set them

BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
API_KEY_VAR = "OPENAI_API_KEY"
MODEL = "gpt-realtime"

SAMPLE_RATE = 24_000
CHUNK_FRAMES = SAMPLE_RATE // 10  # 100 ms

SESSION = {
    "type": "realtime",
    "instructions": INSTRUCTIONS,
    "tools": TOOLS,
    "output_modalities": ["audio"],
    "audio": {
        "input": {
            "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
            "transcription": {"model": "gpt-4o-mini-transcribe"},
            "turn_detection": {"type": "server_vad", "threshold": 0.6, "prefix_padding_ms": 300,
                               "silence_duration_ms": 700, "create_response": True,
                               "interrupt_response": True},
        },
        "output": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}, "voice": "marin"},
    },
}


class Speaker:
    """Plays the assistant's audio as it streams in."""

    def __init__(self):
        self.buffer = bytearray()
        self.lock = threading.Lock()
        self.stream = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                         callback=self._fill)
        self.stream.start()

    def _fill(self, outdata, frames, time_info, status):
        with self.lock:
            n = min(len(outdata), len(self.buffer))
            outdata[:n] = self.buffer[:n]
            del self.buffer[:n]
        outdata[n:] = bytes(len(outdata) - n)

    def play(self, pcm: bytes):
        with self.lock:
            self.buffer.extend(pcm)

    def clear(self):
        with self.lock:
            self.buffer.clear()

    @property
    def playing(self) -> bool:
        return bool(self.buffer)


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


async def send_audio(conn, chunks, speaker):
    async for chunk in chunks:
        if speaker.playing:
            continue  # echo avoidance: don't let the assistant hear its own voice
        await conn.input_audio_buffer.append(audio=base64.b64encode(chunk).decode())


async def handle_events(conn, one_turn: bool, speaker):
    """Print the conversation and answer tool calls. With one_turn, return after one reply."""
    reply = ""
    tool_called = False
    async for event in conn:
        kind = event.type
        if kind == "conversation.item.input_audio_transcription.completed":
            print(f"Guest:  {event.transcript.strip()}")
        elif kind == "input_audio_buffer.speech_started":
            speaker.clear()  # barge-in: stop talking over the guest
        elif kind == "response.output_audio.delta":
            speaker.play(base64.b64decode(event.delta))
        elif kind == "response.output_audio_transcript.delta":
            reply += event.delta
        elif kind == "response.output_audio_transcript.done":
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
    key = os.environ.get(API_KEY_VAR)
    if not key:
        sys.exit(f"{API_KEY_VAR} is not set. Copy .env.example to .env and fill it in.")

    client = AsyncOpenAI(api_key=key, base_url=BASE_URL)
    speaker = Speaker()
    async with client.realtime.connect(model=MODEL) as conn:
        await conn.session.update(session=SESSION)
        print(f"[connected to {MODEL} at {BASE_URL}]\n")

        if args.say:
            await conn.conversation.item.create(item={
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": args.say}]})
            await conn.response.create()
            await handle_events(conn, one_turn=True, speaker=speaker)
            while speaker.playing:  # let the spoken reply finish
                await asyncio.sleep(0.1)
            return

        chunks = wav_file(args.file) if args.file else microphone(args.device)
        events = asyncio.create_task(handle_events(conn, one_turn=False, speaker=speaker))
        audio = asyncio.create_task(send_audio(conn, chunks, speaker))
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
