import asyncio
import os
import subprocess
import tempfile
import time
from pathlib import Path

# Microsoft Edge's free neural voices; list others with `edge-tts --list-voices`.
VOICE = os.environ.get("TTS_VOICE", "en-US-AndrewNeural")
RATE = os.environ.get("TTS_RATE", "+0%")
MAX_SECONDS = 5 * 60  # default only; callers pass the configured limit
CHUNK_CHARS = 3000  # small requests are less likely to be dropped by the free endpoint


def chunks(text):
    out, cur = [], ""
    for para in text.split("\n"):
        para = para.strip()
        while para:
            if len(para) > CHUNK_CHARS:
                cut = para.rfind(". ", 0, CHUNK_CHARS) + 1
                cut = cut or para.rfind(" ", 0, CHUNK_CHARS)
                cut = cut if cut > 0 else CHUNK_CHARS
                piece, para = para[:cut].strip(), para[cut:].strip()
            else:
                piece, para = para, ""
            if cur and len(cur) + len(piece) + 1 > CHUNK_CHARS:
                out.append(cur)
                cur = ""
            cur = f"{cur}\n{piece}".strip()
    if cur:
        out.append(cur)
    return out


def duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def speak(text: str, path: Path, attempts=3) -> bool:
    import edge_tts

    # The Edge endpoint is unofficial and sometimes returns no audio for a request, so retry with backoff.
    for n in range(attempts):
        try:
            # --env-file is loaded after imports, so read voice options at call time.
            voice = os.environ.get("TTS_VOICE") or VOICE
            rate = os.environ.get("TTS_RATE") or RATE
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(path)))
            if path.stat().st_size > 0:
                return True
        except Exception:
            print(f"TTS retry {n + 1}")
        time.sleep(2 ** (n + 1))
    return False


def speak_pieces(text: str, tmp: Path, name: str) -> list[Path]:
    """Voices text, splitting a chunk that keeps failing into halves rather than losing the episode."""
    path = tmp / f"{name}.mp3"
    if speak(text, path):
        return [path]
    if len(text) <= 200:
        raise RuntimeError("TTS could not voice a passage; episode will be retried")
    mid = text.rfind(". ", 0, len(text) // 2) + 1 or len(text) // 2
    return speak_pieces(text[:mid].strip(), tmp, name + "a") + speak_pieces(text[mid:].strip(), tmp, name + "b")


def synthesize(script: str, out_path: Path, max_seconds: float | None = MAX_SECONDS) -> float:
    """Renders script to a mono MP3, cut at max_seconds if given; returns its duration in seconds."""
    if not script.strip():
        raise ValueError("Cannot narrate empty text")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, chunk in enumerate(chunks(script)):
            parts += speak_pieces(chunk, Path(tmp), f"{i:03d}")
        if not parts:
            raise RuntimeError("Edge TTS returned no audio")
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        # -t enforces the summary length cap even if the script ran long. loudnorm brings the
        # quiet Edge voice up to the -16 LUFS loudness most podcast apps expect.
        # Reserve room for MP3 encoder padding so the measured file stays under the cap.
        limit = ["-t", str(max(0.01, max_seconds - 0.08))] if max_seconds else []
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        *limit, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1", "-b:a", "64k",
                        str(out_path)], check=True)
    return duration(out_path)


def split_episode(path: Path, max_seconds: float | None) -> list[Path]:
    """Split a complete narration into bounded parts, preserving all its audio."""
    total = duration(path)
    if not max_seconds or total <= max_seconds:
        return [path]
    span = max_seconds - 0.08  # reserve encoder padding without dropping source audio
    parts = []
    offset = 0.0
    try:
        while offset < total:
            part = path.with_name(f"{path.stem}-part-{len(parts) + 1:03d}.mp3")
            parts.append(part)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                            "-ss", str(offset), "-t", str(min(span, total - offset)),
                            "-ar", "44100", "-ac", "1", "-b:a", "64k", str(part)], check=True)
            if duration(part) > max_seconds:
                raise RuntimeError("Encoded audio exceeds MAX_EPISODE_MINUTES")
            offset += span
    except Exception:
        for part in parts:
            part.unlink(missing_ok=True)
        raise
    path.unlink()
    return parts
