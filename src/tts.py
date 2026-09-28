import os
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI

MODEL = os.environ.get("TTS_MODEL", "gpt-4o-mini-tts")
VOICE = os.environ.get("TTS_VOICE", "alloy")
MAX_SECONDS = 20 * 60
CHUNK_CHARS = 3000  # stays under the per-request input limit


def chunks(text):
    out, cur = [], ""
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        while len(para) > CHUNK_CHARS:  # split an overlong paragraph at a sentence end
            cut = para.rfind(". ", 0, CHUNK_CHARS) + 1 or CHUNK_CHARS
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if len(cur) + len(para) + 1 > CHUNK_CHARS:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{para}".strip()
    if cur:
        out.append(cur)
    return out


def duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def synthesize(script: str, out_path: Path) -> float:
    """Renders script to a mono MP3 no longer than 20 minutes; returns its duration in seconds."""
    client = OpenAI()
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, chunk in enumerate(chunks(script)):
            p = Path(tmp) / f"{i:03d}.mp3"
            with client.audio.speech.with_streaming_response.create(
                model=MODEL, voice=VOICE, input=chunk, response_format="mp3",
                instructions="Calm, clear podcast narrator reading an analytical summary.",
            ) as resp:
                resp.stream_to_file(p)
            parts.append(p)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        # -t enforces the 20-minute cap even if the script ran long.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-t", str(MAX_SECONDS), "-ac", "1", "-b:a", "64k", str(out_path)], check=True)
    return duration(out_path)
