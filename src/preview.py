"""Short, stateless article previews, isolated from the personal podcast pipeline."""
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from substack import SourceDownloadError

MAX_SECONDS = 60
MAX_WORDS = 130
MAX_EXCERPT_CHARS = 1000
MAX_INPUT_BYTES = 100_000
MAX_AUDIO_BYTES = 2 * 1024 * 1024
ARTICLE_BLOCKED_MESSAGE = ("This site blocked access to the article. Choose “Paste text” "
                           "and paste the article text you can access.")
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


def article_metadata(soup, url):
    """Read attribution from the downloaded page, without extra requests."""
    from urllib.parse import urlparse
    from tts import speech_text

    def clean(value, limit):
        if not isinstance(value, str):
            return ""
        return " ".join(speech_text(value).split())[:limit].strip()

    def meta(*keys):
        for key in keys:
            node = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
            if node and node.get("content", "").strip():
                return node["content"]
        return ""

    def names(value):
        values = value[:5] if isinstance(value, list) else [value]
        return ", ".join(filter(None, (clean(item.get("name", "") if isinstance(item, dict) else item, 100)
                                      for item in values)))

    article = {}
    for script in soup.select('script[type="application/ld+json"]')[:20]:
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, RecursionError):
            continue
        pending = data[:] if isinstance(data, list) else [data]
        for _ in range(100):
            if not pending:
                break
            node = pending.pop(0)
            if not isinstance(node, dict):
                continue
            kinds = node.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if isinstance(kinds, list) and any(isinstance(kind, str) and
                    (kind.rsplit("/", 1)[-1].endswith("Article") or kind.rsplit("/", 1)[-1] == "BlogPosting") for kind in kinds):
                article = node
                break
            graph = node.get("@graph", [])
            if isinstance(graph, list):
                pending.extend(graph[:100])
        if article:
            break

    heading = soup.select_one("article h1, main h1")
    byline = soup.select_one('[rel~="author"], [itemprop="author"]')
    publication = clean(meta("og:site_name") or names(article.get("publisher")) or
                        names(article.get("isPartOf")) or meta("application-name"), 80)
    publication = publication or clean((urlparse(url).hostname or "").removeprefix("www."), 80)
    title = clean(article.get("headline"), 160) or clean(heading.get_text(" ", strip=True) if heading else "", 160)
    title = title or clean(meta("og:title", "twitter:title") or (soup.title.get_text(" ", strip=True) if soup.title else ""), 160)
    author = clean(names(article.get("author")) or meta("author", "parsely-author") or
                   (byline.get_text(" ", strip=True) if byline else "") or meta("article:author"), 100)
    # Some sites put a profile URL in article:author; don't announce it as a name.
    if author.startswith(("http://", "https://")):
        author = ""
    author = re.sub(r"^by\s+", "", author, flags=re.IGNORECASE)
    return publication, title, author


def article_text(url):
    from bs4 import BeautifulSoup
    from substack import Substack

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
        raise
    print(f"article_download status=completed elapsed={time.monotonic() - started:.1f}s", file=sys.stderr)
    soup = BeautifulSoup(html, "html.parser")
    publication, title, author = article_metadata(soup, url)
    for node in soup.select("script, style, noscript, nav, header, footer, aside, form, [hidden]"):
        node.decompose()
    body = (soup.select_one('[itemprop~="articleBody"], .entry-content, .post-content, .post__content')
            or soup.select_one("article") or soup.select_one("main"))
    if body is None:
        raise ValueError("We couldn't find an article on that page. Try a direct article link or paste its text.")
    # The title and a recognized byline are already spoken in the introduction.
    for node in body.select('h1, [rel~="author"], [itemprop="author"]'):
        value = " ".join(node.get_text(" ", strip=True).split())
        if (title and value[:160].strip() == title) or (author and
                re.sub(r"^by\s+", "", value, flags=re.IGNORECASE)[:100].strip() == author):
            node.decompose()
    text = body.get_text(" ", strip=True)
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
    # Edge already returns MP3. Copy its audio frames while trimming instead of
    # decoding, loudness-filtering and encoding again on the small free CPU.
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(raw),
                    "-map", "0:a:0", "-t", str(MAX_SECONDS - 0.1), "-c:a", "copy", str(output)],
                   check=True, timeout=40, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from tts import duration
    seconds = duration(output)
    if not 0 < seconds <= MAX_SECONDS or output.stat().st_size > MAX_AUDIO_BYTES:
        raise RuntimeError("Invalid preview audio")
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
    except ValueError:
        print("We couldn't read that article. Try a direct public article link or paste its text.", file=sys.stderr)
        sys.exit(2)
    except Exception:
        print("Audio generation is unavailable. Please try again shortly.", file=sys.stderr)
        sys.exit(1)
