"""Short, stateless article previews, isolated from the personal podcast pipeline."""
import asyncio
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from substack import SourceDownloadError
from article_metadata import article_metadata

MAX_SECONDS = 60
MAX_WORDS = 130
MAX_EXCERPT_CHARS = 1000
MAX_INPUT_BYTES = 100_000
MAX_AUDIO_BYTES = 2 * 1024 * 1024
ARTICLE_BLOCKED_MESSAGE = ("This site blocked access to the article. Choose “Paste text” "
                           "and paste the article text you can access.")
ARTICLE_UNAVAILABLE_MESSAGE = ("We couldn't download that article. The site may be slow or unreachable. "
                               "Choose “Paste text” and paste the article text you can access.")
SPEECH_UNAVAILABLE_MESSAGE = ("The speech service couldn't generate audio. "
                              "Please try again or choose another narrator.")
VOICES = {
    "en-US-AndrewNeural": "Andrew · English (US)",
    "en-US-AriaNeural": "Aria · English (US)",
    "en-GB-SoniaNeural": "Sonia · English (UK)",
}


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("Send an article URL or pasted text.")
    url, text = payload.get("url", ""), payload.get("text", "")
    voice = payload.get("voice", "en-US-AndrewNeural")
    if not isinstance(url, str) or not isinstance(text, str) or not isinstance(voice, str):
        raise ValueError("URL, text and voice must be strings.")
    url, text = url.strip(), text.strip()
    if bool(url) == bool(text):
        raise ValueError("Provide either one public article URL or pasted text.")
    if len(url) > 8192 or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("That input is too long. Paste a shorter article excerpt.")
    if voice not in VOICES:
        raise ValueError("Choose one of the available voices.")
    if url:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 80 if parsed.scheme == "http" else 443)):
            raise ValueError("Use a public HTTP(S) article link without login details or custom ports.")
    return {"url": url, "text": text, "voice": voice}


class SpeechUnavailableError(RuntimeError):
    """The upstream speech request failed, rather than article access."""


class IncompleteSpeechError(SpeechUnavailableError):
    """A successful stream contained implausibly little audio for the excerpt."""


class ArticleUnavailableError(RuntimeError):
    """The source could not be downloaded, before any speech was requested."""


def minimum_audio_seconds(text):
    # Match the personal pipeline's generous 600 words/minute ceiling. This is
    # a gross-truncation check, not a promise of exact spoken completeness.
    return min(len(text.split()) / 10, MAX_SECONDS - 0.1)


def stage_log(stage, status, started, error=None, attempt=None):
    details = f" error_type={type(error).__name__}" if error is not None else ""
    details += f" attempt={attempt}" if attempt is not None else ""
    print(f"preview_stage stage={stage} status={status} elapsed={time.monotonic() - started:.1f}s"
          + details, file=sys.stderr)


def article_text(url):
    from bs4 import BeautifulSoup
    from substack import Substack
    from curl_cffi.requests.exceptions import RequestException

    # Reuse the bounded downloader: public destinations only, DNS pinned, and
    # every redirect revalidated. No subscription cookies or private config.
    started = time.monotonic()
    try:
        html = Substack("", request_timeout=60).get(url, raw=True)
    except Exception as error:
        status = getattr(error, "status_code", None)
        status_log = f" http_status={status}" if type(status) is int and 100 <= status <= 599 else ""
        details = f" {error.diagnostics}" if isinstance(error, SourceDownloadError) else ""
        print(f"article_download status=failed elapsed={time.monotonic() - started:.1f}s "
              f"error_type={type(error).__name__}{status_log}{details}", file=sys.stderr)
        if isinstance(error, (RequestException, OSError)):
            raise ArticleUnavailableError from error
        raise
    print(f"article_download status=completed elapsed={time.monotonic() - started:.1f}s", file=sys.stderr)
    soup = BeautifulSoup(html, "html.parser")
    publication, title, author = article_metadata(soup, url)
    from article_extract import extract_text
    text = extract_text(soup, title, author, url)
    if not text:
        raise ValueError("We couldn't find an article on that page. Try a direct article link or paste its text.")
    if len(text.split()) < 20:
        raise ValueError("That page has too little readable text. Try pasting the article text instead.")
    parts = [publication, title, f"By {author}" if author else ""]
    intro = " ".join(part if part.endswith((".", "!", "?")) else part + "." for part in parts if part)
    return f"{intro}\n{text}"


def excerpt(text):
    from tts import speech_text
    words = speech_text(text).split()
    if not words:
        raise ValueError("Add some readable article text.")
    # Bound both word count and characters, including languages without spaces.
    selected = " ".join(words[:MAX_WORDS])[:MAX_EXCERPT_CHARS]
    if len(words) > MAX_WORDS or len(" ".join(words[:MAX_WORDS])) > MAX_EXCERPT_CHARS:
        ends = list(re.finditer(r"[.!?。！？](?:\s|$)", selected))
        if ends and ends[-1].end() > len(selected) // 2:
            selected = selected[:ends[-1].end()].strip()
    return selected


async def narrate(text, voice, path):
    import edge_tts
    from aiohttp import ClientConnectionError, ClientResponseError
    from tts import duration
    # edge-tts pins a certifi SSLContext. Add an explicitly configured CA bundle
    # for managed networks while retaining certificate and hostname validation.
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if cafile:
        edge_tts.communicate._SSL_CTX.load_verify_locations(cafile=cafile)
    # Edge sometimes closes a successful connection without returning speech.
    # Retry up to twice within generate's 70-second total speech deadline.
    # Start a fresh communicator and file so partial audio cannot be duplicated.
    for attempt in (1, 2, 3):
        started = time.monotonic()
        try:
            count = 0
            communication = edge_tts.Communicate(text, voice, proxy=os.environ.get("HTTPS_PROXY"))
            with path.open("wb") as output:
                async for item in communication.stream():
                    if item["type"] == "audio":
                        count += len(item["data"])
                        if count > MAX_AUDIO_BYTES:
                            raise ValueError("Preview audio exceeded its size limit.")
                        output.write(item["data"])
            if not count:
                raise edge_tts.exceptions.NoAudioReceived("No speech returned")
            seconds = duration(path)
            if not math.isfinite(seconds) or seconds <= 0 or seconds < minimum_audio_seconds(text):
                raise IncompleteSpeechError
            stage_log('speech', 'completed', started, attempt=attempt)
            return
        except (edge_tts.exceptions.NoAudioReceived, ClientConnectionError, ClientResponseError,
                IncompleteSpeechError) as error:
            transient = not isinstance(error, ClientResponseError) or error.status == 429 or error.status >= 500
            if attempt == 3 or not transient:
                raise
            stage_log('speech', 'retry', started, error, attempt)
            await asyncio.sleep(attempt)


def generate(payload, directory):
    payload = validate(payload)
    started = time.monotonic()
    try:
        text = excerpt(payload["text"] or article_text(payload["url"]))
    except Exception as error:
        stage_log('extract', 'failed', started, error)
        raise
    stage_log('extract', 'completed', started)
    raw, output = directory / "speech.mp3", directory / "preview.mp3"
    started = time.monotonic()
    try:
        asyncio.run(asyncio.wait_for(narrate(text, payload["voice"], raw), timeout=70))
    except Exception as error:
        stage_log('speech', 'failed', started, error)
        raise SpeechUnavailableError from error
    # Edge already returns MP3. Copy its audio frames while trimming instead of
    # decoding, loudness-filtering and encoding again on the small free CPU.
    started = time.monotonic()
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(raw),
                        "-map", "0:a:0", "-t", str(MAX_SECONDS - 0.1), "-c:a", "copy", str(output)],
                       check=True, timeout=40, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as error:
        stage_log('trim', 'failed', started, error)
        raise
    stage_log('trim', 'completed', started)
    started = time.monotonic()
    try:
        from tts import duration
        seconds = duration(output)
        if not math.isfinite(seconds) or seconds < minimum_audio_seconds(text):
            raise IncompleteSpeechError
        if not 0 < seconds <= MAX_SECONDS or output.stat().st_size > MAX_AUDIO_BYTES:
            raise RuntimeError("Invalid preview audio")
    except Exception as error:
        stage_log('validate', 'failed', started, error)
        raise
    stage_log('validate', 'completed', started)
    return output


if __name__ == "__main__":
    # Worker errors intentionally exclude URLs, pasted text and provider details.
    try:
        generate(json.loads(sys.stdin.buffer.read(MAX_INPUT_BYTES + 20_000)), Path(sys.argv[1]))
    except SourceDownloadError as error:
        if error.protection != "none" or error.status_code in (401, 403, 429):
            print(ARTICLE_BLOCKED_MESSAGE, file=sys.stderr)
            sys.exit(3)
        print("We couldn't read that article. Try a direct public article link or paste its text.", file=sys.stderr)
        sys.exit(2)
    except ArticleUnavailableError:
        print(ARTICLE_UNAVAILABLE_MESSAGE, file=sys.stderr)
        sys.exit(5)
    except SpeechUnavailableError:
        print(SPEECH_UNAVAILABLE_MESSAGE, file=sys.stderr)
        sys.exit(4)
    except ValueError:
        print("We couldn't read that article. Try a direct public article link or paste its text.", file=sys.stderr)
        sys.exit(2)
    except Exception:
        print("Audio generation is unavailable. Please try again shortly.", file=sys.stderr)
        sys.exit(1)
