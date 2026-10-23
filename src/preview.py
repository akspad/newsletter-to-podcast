"""Short, stateless article previews, isolated from the personal podcast pipeline."""
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys

MAX_SECONDS = 180
MAX_WORDS = 390
MAX_INPUT_BYTES = 100_000
MAX_AUDIO_BYTES = 2 * 1024 * 1024
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


def article_text(url):
    from bs4 import BeautifulSoup
    from substack import Substack

    # Reuse the bounded downloader: public destinations only, DNS pinned, and
    # every redirect revalidated. No subscription cookies or private config.
    soup = BeautifulSoup(Substack("").get(url, raw=True), "html.parser")
    for node in soup.select("script, style, noscript, nav, header, footer, aside, form, [hidden]"):
        node.decompose()
    body = soup.select_one("article") or soup.select_one("main")
    if body is None:
        raise ValueError("We couldn't find an article on that page. Try a direct article link or paste its text.")
    text = body.get_text(" ", strip=True)
    if len(text.split()) < 20:
        raise ValueError("That page has too little readable text. Try pasting the article text instead.")
    return text


def excerpt(text):
    from tts import speech_text
    words = speech_text(text).split()
    if not words:
        raise ValueError("Add some readable article text.")
    # Bound both word count and characters, including languages without spaces.
    selected = " ".join(words[:MAX_WORDS])[:3000]
    if len(words) > MAX_WORDS or len(" ".join(words[:MAX_WORDS])) > 3000:
        ends = list(re.finditer(r"[.!?。！？](?:\s|$)", selected))
        if ends and ends[-1].end() > len(selected) // 2:
            selected = selected[:ends[-1].end()].strip()
    return selected


async def narrate(text, voice, path):
    import edge_tts
    # edge-tts pins a certifi SSLContext. Add an explicitly configured CA bundle
    # for managed networks while retaining certificate and hostname validation.
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if cafile:
        edge_tts.communicate._SSL_CTX.load_verify_locations(cafile=cafile)
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
        raise RuntimeError("No speech returned")


def generate(payload, directory):
    payload = validate(payload)
    text = excerpt(payload["text"] or article_text(payload["url"]))
    raw, output = directory / "speech.mp3", directory / "preview.mp3"
    asyncio.run(asyncio.wait_for(narrate(text, payload["voice"], raw), timeout=70))
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(raw),
                    "-t", "179.9", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-ar", "44100", "-ac", "1", "-b:a", "64k", str(output)],
                   check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from tts import duration
    seconds = duration(output)
    if not 0 < seconds <= MAX_SECONDS or output.stat().st_size > MAX_AUDIO_BYTES:
        raise RuntimeError("Invalid preview audio")
    return output


if __name__ == "__main__":
    # Worker errors intentionally exclude URLs, pasted text and provider details.
    try:
        generate(json.loads(sys.stdin.buffer.read(MAX_INPUT_BYTES + 20_000)), Path(sys.argv[1]))
    except ValueError:
        print("We couldn't read that article. Try a direct public article link or paste its text.", file=sys.stderr)
        sys.exit(2)
    except Exception:
        print("Audio generation is unavailable. Please try again shortly.", file=sys.stderr)
        sys.exit(1)
