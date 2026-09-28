import asyncio
import os
import subprocess
import tempfile
import time
from pathlib import Path

import edge_tts

# Microsoft Edge's free neural voices; list others with `edge-tts --list-voices`.
VOICE = os.environ.get("TTS_VOICE", "en-US-AndrewNeural")
RATE = os.environ.get("TTS_RATE", "+0%")
MAX_SECONDS = 20 * 60
CHUNK_CHARS = 3000  # small requests are less likely to be dropped by the free endpoint


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


def speak(text: str, path: Path, attempts=4):
    # The Edge endpoint is unofficial and occasionally drops a connection, so retry with backoff.
    for n in range(attempts):
        try:
            asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE).save(str(path)))
            if path.stat().st_size > 0:
                return
        except Exception as e:
            if n == attempts - 1:
                raise
            print(f"TTS retry {n + 1}: {e}")
        time.sleep(2 ** (n + 1))
    raise RuntimeError("Edge TTS returned no audio")


def synthesize(script: str, out_path: Path) -> float:
    """Renders script to a mono MP3 no longer than 20 minutes; returns its duration in seconds."""
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, chunk in enumerate(chunks(script)):
            p = Path(tmp) / f"{i:03d}.mp3"
            speak(chunk, p)
            parts.append(p)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        # -t enforces the 20-minute cap even if the script ran long.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-t", str(MAX_SECONDS), "-ac", "1", "-b:a", "64k", str(out_path)], check=True)
    return duration(out_path)
