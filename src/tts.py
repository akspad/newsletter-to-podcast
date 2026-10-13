from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
import security
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


@dataclass
class AudioBudget:
    calls: int = 0
    bytes: int = 0
    seconds: float = 0


_audio_budget = ContextVar("article_audio_budget", default=None)


@contextmanager
def narration_budget():
    if _audio_budget.get() is not None:
        yield
        return
    token = _audio_budget.set(AudioBudget())
    try:
        yield
    finally:
        _audio_budget.reset(token)


async def save_audio(communication, path):
    budget = _audio_budget.get()
    count = 0
    with path.open("wb") as output:
        async for item in communication.stream():
            if item["type"] != "audio":
                continue
            data = item["data"]
            count += len(data)
            if budget is not None:
                budget.bytes += len(data)
            if count > security.MAX_AUDIO_BYTES or (budget and budget.bytes > security.MAX_AUDIO_BYTES):
                raise security.BudgetExceeded("Narration exceeds the temporary audio byte limit")
            output.write(data)


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
    for n in range(min(attempts, 3)):
        security.charge("tts_calls", 1)
        budget = _audio_budget.get()
        if budget is not None:
            budget.calls += 1
            if budget.calls > 240:
                raise security.BudgetExceeded("Narration exceeds the TTS call limit")
        try:
            # --env-file is loaded after imports, so read voice options at call time.
            voice = os.environ.get("TTS_VOICE") or VOICE
            rate = os.environ.get("TTS_RATE") or RATE
            asyncio.run(asyncio.wait_for(save_audio(edge_tts.Communicate(text, voice, rate=rate), path), timeout=60))
            if path.stat().st_size > 0:
                return True
        except security.BudgetExceeded:
            raise
        except Exception:
            print(f"TTS retry {n + 1}")
        time.sleep(2 ** (n + 1))
    return False


def speak_pieces(text: str, tmp: Path, name: str) -> list[Path]:
    with narration_budget():
        return _speak_pieces(text, tmp, name)


def _speak_pieces(text: str, tmp: Path, name: str) -> list[Path]:
    """Voices text, splitting a chunk that keeps failing into halves rather than losing the episode."""
    path = tmp / f"{name}.mp3"
    if speak(text, path):
        budget = _audio_budget.get()
        if budget is not None:
            budget.seconds += duration(path)
            if not math.isfinite(budget.seconds) or budget.seconds > security.MAX_AUDIO_SECONDS:
                raise security.BudgetExceeded("Narration exceeds the total duration limit")
        return [path]
    if len(text) <= 200:
        raise RuntimeError("TTS could not voice a passage; episode will be retried")
    mid = text.rfind(". ", 0, len(text) // 2) + 1 or len(text) // 2
    return speak_pieces(text[:mid].strip(), tmp, name + "a") + speak_pieces(text[mid:].strip(), tmp, name + "b")


def synthesize(script: str, out_path: Path, max_seconds: float | None = MAX_SECONDS) -> float:
    with narration_budget():
        return _synthesize(script, out_path, max_seconds)


def _synthesize(script: str, out_path: Path, max_seconds: float | None) -> float:
    """Renders script to a mono MP3, cut at max_seconds if given; returns its duration in seconds."""
    security.check_text(script, security.MAX_ARTICLE_BYTES + 8192)
    pieces = chunks(script)
    if len(pieces) > security.MAX_TTS_CHUNKS:
        raise security.BudgetExceeded("Narration exceeds the chunk limit")
    if not script.strip():
        raise ValueError("Cannot narrate empty text")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, chunk in enumerate(pieces):
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
                        str(out_path)], check=True, timeout=180)
    seconds = duration(out_path)
    if not math.isfinite(seconds) or seconds > security.MAX_AUDIO_SECONDS or out_path.stat().st_size > security.MAX_AUDIO_BYTES:
        out_path.unlink(missing_ok=True)
        raise security.BudgetExceeded("Narration exceeds its output budget")
    return seconds


def split_episode(path: Path, max_seconds: float | None) -> list[Path]:
    """Split a complete narration into bounded parts, preserving all its audio."""
    total = duration(path)
    if not math.isfinite(total) or total > security.MAX_AUDIO_SECONDS or path.stat().st_size > security.MAX_AUDIO_BYTES:
        raise security.BudgetExceeded("Narration exceeds its output budget")
    if max_seconds and (not math.isfinite(max_seconds) or max_seconds < 1):
        raise ValueError("Audio part duration must be at least one second")
    if not max_seconds or total <= max_seconds:
        return [path]
    span = max_seconds - 0.08  # reserve encoder padding without dropping source audio
    if math.ceil(total / span) > security.MAX_AUDIO_PARTS:
        raise security.BudgetExceeded("Narration exceeds the part-count limit")
    parts = []
    offset = 0.0
    try:
        while offset < total:
            part = path.with_name(f"{path.stem}-part-{len(parts) + 1:03d}.mp3")
            parts.append(part)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                            "-ss", str(offset), "-t", str(min(span, total - offset)),
                            "-ar", "44100", "-ac", "1", "-b:a", "64k", str(part)], check=True, timeout=180)
            if duration(part) > max_seconds:
                raise RuntimeError("Encoded audio exceeds MAX_EPISODE_MINUTES")
            offset += span
    except Exception:
        for part in parts:
            part.unlink(missing_ok=True)
        raise
    path.unlink()
    return parts
