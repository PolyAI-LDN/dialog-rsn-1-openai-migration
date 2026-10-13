# Moving an OpenAI Realtime agent to Dialog-RSN-1

Companion code for [Migrating from OpenAI Realtime](https://dialog-rsn-1-eap-docs.pages.dev/dialog-rsn-1/guides/openai-realtime-migration/).

One voice agent, twice. `before.py` is a front-desk agent for the fictional Grand Meridian Hotel,
written against the OpenAI Realtime API with the official `openai` SDK. `after.py` is the same
file moved to Dialog-RSN-1. The agent, its tools and its bookings live in `hotel.py` and don't
change.

```bash
diff before.py after.py
```

That diff is the whole migration. Every changed line in `after.py` has a `MIGRATION:` comment.

## What changes

| | `before.py` (OpenAI) | `after.py` (Dialog-RSN-1) |
|---|---|---|
| Base URL | `https://api.openai.com/v1` | `https://api.studio.poly.ai/v1` |
| Key | OpenAI API key | Dialog-RSN-1 workspace API key |
| Replies | `output_modalities: ["audio"]`, a voice, an audio output format | `output_modalities: ["text"]`, no `audio.output` |
| Transcription | `gpt-4o-mini-transcribe` | none to configure: the model transcribes as part of its turn |
| Turn detection | `server_vad` with tuned `threshold`, padding and silence | `server_vad` with `create_response` only |
| Reply events | `response.output_audio.delta` and its transcript | `response.output_text.delta` |
| Speaker, echo muting, barge-in clearing | yes | removed: there's no assistant audio |

Everything else stays: the SDK, `client.realtime.connect()`, the session shape, tool
definitions, function calling, `input_audio_buffer.append` and the transcription events.

The SDK still sends the key as `Authorization: Bearer`, and Dialog-RSN-1 accepts that. The
model name in `connect()` is only a label here. The service runs Dialog-RSN-1 whatever you pass.

## What happens if you only change the URL and key

Point `before.py` at Dialog-RSN-1 unchanged and it connects, then prints this and nothing else:

```text
[error] 'audio.output' is not supported by this service. This service has no audio output, so bring your own TTS.
```

A rejected `session.update` applies none of its fields, so the instructions and tools go with it.
The model still answers, but in text events that `before.py` never listens for. The same goes
for the tuned turn-detection fields: `threshold`, `prefix_padding_ms`, `silence_duration_ms`,
`interrupt_response` and `semantic_vad` are each rejected with `unsupported_parameter`.

## Run it

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env    # add DIALOGUE_API_KEY, and OPENAI_API_KEY to run before.py
uv sync

uv run after.py --say "Can you look up booking GM40912?"   # one text turn
uv run after.py                                            # talk through the microphone
```

`before.py` takes the same flags and speaks its replies through your speakers.

To try the audio path without a microphone, make a clip and stream it with `--file`:

```bash
say -o call.aiff "Could you look up my booking? The code is G M four one zero five five."
afconvert -f WAVE -d LEI16@24000 -c 1 call.aiff call.wav
uv run after.py --file call.wav
```

List microphones with `uv run python -m sounddevice` and pick one with `--device`.

## Try saying

- "Hi, could you look up my booking? The code is G M four zero nine one two."
- "Can I get a late checkout at three on Thursday?"
- "I need to cancel my reservation. The last name is Reid."

Demo bookings: `GM40912` (Okafor), `GM41055` (Reid), `GM41182` (Reid, a suite),
`GM39877` (Bergmann, already checked out). Dates are relative to today, and nothing is saved.

## Where the voice goes

Dialog-RSN-1 replies in text. To speak the replies, stream `response.output_text.delta` into a
text-to-speech provider. The [streaming to text-to-speech guide](https://dialog-rsn-1-eap-docs.pages.dev/dialog-rsn-1/guides/streaming-text-to-speech/)
covers it, including how to report playback so interruptions work across the whole reply.

## License

Apache 2.0. See [LICENSE](LICENSE).
