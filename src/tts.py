from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
import re
import security
import checkpoints
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
                seconds = duration(path)
                # A successful stream can still contain only a tiny prefix.
                # Use a deliberately generous 600 words/minute ceiling, adjusted
                # for the requested rate, to catch gross truncation without
                # rejecting naturally short passages or fast voices.
                speed = max(0.1, 1 + int(rate.rstrip("%")) / 100)
                minimum = len(text.split()) / (10 * speed)
                if math.isfinite(seconds) and seconds > 0 and seconds >= minimum:
                    return True
                raise RuntimeError("TTS returned implausibly short audio")
        except security.BudgetExceeded:
            raise
        except Exception:
            print(f"TTS retry {n + 1}")
        path.unlink(missing_ok=True)
        time.sleep(2 ** (n + 1))
    return False


def speak_pieces(text: str, tmp: Path, name: str) -> list[Path]:
    with narration_budget():
        return _speak_pieces(text, tmp, name)


def _speak_pieces(text: str, tmp: Path, name: str) -> list[Path]:
    """Voices text, splitting a chunk that keeps failing into halves rather than losing the episode."""
    path = tmp / f"{name}.mp3"
    cache = checkpoints.current()
    key = cache.key(text, os.environ.get("TTS_VOICE") or VOICE,
                    os.environ.get("TTS_RATE") or RATE) if cache else None
    saved = cache.get(key) if cache else None
    split = saved == b"split"
    reused = False
    if saved and saved.startswith(b"audio:"):
        path.write_bytes(saved[6:])
        try:
            seconds = duration(path)
            rate = os.environ.get("TTS_RATE") or RATE
            minimum = len(text.split()) / (10 * max(0.1, 1 + int(rate.rstrip("%")) / 100))
            reused = math.isfinite(seconds) and seconds > 0 and seconds >= minimum
        except (ValueError, subprocess.SubprocessError):
            pass
        if not reused:
            path.unlink(missing_ok=True)
    if reused or (not split and speak(text, path)):
        budget = _audio_budget.get()
        if budget is not None:
            if reused:
                budget.bytes += path.stat().st_size
            budget.seconds += duration(path)
            if budget.bytes > security.MAX_AUDIO_BYTES:
                raise security.BudgetExceeded("Narration exceeds the temporary audio byte limit")
            if not math.isfinite(budget.seconds) or budget.seconds > security.MAX_AUDIO_SECONDS:
                raise security.BudgetExceeded("Narration exceeds the total duration limit")
        if cache and not reused:
            cache.put(key, b"audio:" + path.read_bytes())
        return [path]
    if len(text) <= 200:
        raise RuntimeError("TTS could not voice a passage; episode will be retried")
    if cache:
        cache.put(key, b"split")
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
        return join_audio(parts, out_path, max_seconds)


def join_audio(parts, out_path, max_seconds=None):
    """Join complete clips; only summary callers request a hard duration cap."""
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "list.txt"
        # All clip paths are generated internally, not from article metadata.
        listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
        limit = ["-t", str(max(0.01, max_seconds - 0.08))] if max_seconds else []
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        *limit, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1", "-b:a", "64k",
                        str(out_path)], check=True, timeout=180)
    seconds = duration(out_path)
    if not math.isfinite(seconds) or seconds > security.MAX_AUDIO_SECONDS or out_path.stat().st_size > security.MAX_AUDIO_BYTES:
        out_path.unlink(missing_ok=True)
        raise security.BudgetExceeded("Narration exceeds its output budget")
    return seconds


def text_breaks(text):
    """Sentence/paragraph boundaries, with conservative abbreviation handling."""
    result = []
    for match in re.finditer(r"""[.!?][”’"'\)\]]*(?:\s+|$)|[。！？][”’"'\)\]]*\s*|\n+""", text):
        prefix = text[:match.start() + 1]
        if prefix.endswith(".") and re.search(
                r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e|[A-Z])\.$", prefix, re.I):
            continue
        if 0 < match.end() < len(text):
            result.append(match.end())
    return result


def divide_text(text):
    """Prefer a sentence, then a clause, then whitespace; never discard words."""
    choices = text_breaks(text)
    if not choices:
        choices = [m.end() for m in re.finditer(r"[,;:—–]\s+", text)]
    if not choices:
        choices = [m.end() for m in re.finditer(r"\s+", text)]
    choices = [n for n in choices if text[:n].strip() and text[n:].strip()]
    if not choices:
        raise RuntimeError("A spoken passage cannot fit the episode duration limit")
    cut = min(choices, key=lambda n: abs(n - len(text) / 2))
    return text[:cut].strip(), text[cut:].strip()


def article_chunks(text):
    """Bound initial requests without cutting a sentence that fits a request."""
    pending, result = [text.strip()], []
    while pending:
        piece = pending.pop()
        if len(piece) <= CHUNK_CHARS:
            result.append(piece)
        else:
            left, right = divide_text(piece)
            pending.extend((right, left))
        if len(pending) + len(result) > security.MAX_TTS_CHUNKS:
            raise security.BudgetExceeded("Narration exceeds the chunk limit")
    return result


def pack_clips(clips, capacity):
    groups, current, seconds = [], [], 0.0
    for clip in clips:
        if clip[2] > capacity:
            raise RuntimeError("A spoken passage exceeds the available part duration")
        if current and seconds + clip[2] > capacity:
            groups.append(current)
            current, seconds = [], 0.0
        current.append(clip)
        seconds += clip[2]
    if current:
        groups.append(current)
    if len(groups) > security.MAX_AUDIO_PARTS:
        raise security.BudgetExceeded("Article produces too many audio parts")
    return groups


def synthesize_full(script: str, out_path: Path, max_seconds: float | None, intro: str) -> list[Path]:
    """Assemble measured text passages with a spoken introduction and accurate part count."""
    security.check_text(f"{intro}\n{script}", security.MAX_ARTICLE_BYTES + 8192)
    if not script.strip() or not intro.strip():
        raise ValueError("Full narration needs an introduction and nonempty text")
    if max_seconds is not None and (not math.isfinite(max_seconds) or max_seconds < 1):
        raise ValueError("Audio part duration must be at least one second")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    outputs = [out_path]
    try:
        with narration_budget(), tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            serial = 0

            def render(text):
                nonlocal serial
                serial += 1
                path = tmp / f"clip-{serial:04d}.mp3"
                seconds = synthesize(text, path, None)
                return text, path, seconds

            clips = [render(piece) for piece in article_chunks(script)]
            heading = render(intro)
            total = join_audio([heading[1], *(c[1] for c in clips)], out_path)
            if max_seconds is None or total <= max_seconds:
                return [out_path]

            # Reserve measured space for numbering, then verify the actual
            # headings once the number of parts is known. Cache all speech.
            probe = render(f"{intro} Part 1 of 2.")
            reserve = probe[2] + 0.15  # MP3 encoder padding margin
            headings = {}
            for _ in range(8):
                capacity = max_seconds - reserve
                if capacity <= 0:
                    raise RuntimeError("Episode duration limit cannot fit the spoken introduction and part number")
                pending, fitted = list(reversed(clips)), []
                while pending:
                    clip = pending.pop()
                    if clip[2] <= capacity:
                        fitted.append(clip)
                    else:
                        left, right = divide_text(clip[0])
                        pending.extend(reversed([render(left), render(right)]))
                    if len(fitted) + len(pending) > security.MAX_AUDIO_PARTS:
                        raise security.BudgetExceeded("Article produces too many audio passages")
                clips = fitted
                groups = pack_clips(clips, capacity)
                count = len(groups)
                for index in range(1, count + 1):
                    key = index, count
                    if key not in headings:
                        headings[key] = render(f"{intro} Part {index} of {count}.")
                actual_reserve = max(headings[i, count][2] for i in range(1, count + 1)) + 0.15
                if actual_reserve > reserve:
                    reserve = actual_reserve
                    continue
                break
            else:
                raise RuntimeError("Could not fit numbered narration within the episode duration limit")

            total_seconds = total_bytes = 0
            for index, group in enumerate(groups, 1):
                part = out_path.with_name(f"{out_path.stem}-part-{index:03d}.mp3")
                outputs.append(part)
                seconds = join_audio([headings[index, count][1], *(c[1] for c in group)], part)
                if seconds > max_seconds:
                    raise RuntimeError("Encoded audio exceeds MAX_EPISODE_MINUTES")
                total_seconds += seconds
                total_bytes += part.stat().st_size
                if total_seconds > security.MAX_AUDIO_SECONDS or total_bytes > security.MAX_AUDIO_BYTES:
                    raise security.BudgetExceeded("Narration exceeds its output budget")
            out_path.unlink()
            return outputs[1:]
    except Exception:
        for path in outputs:
            path.unlink(missing_ok=True)
        raise
