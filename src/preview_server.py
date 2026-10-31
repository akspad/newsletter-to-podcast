"""Run the article-to-audio demo: python src/preview_server.py."""
import asyncio
from collections import defaultdict, deque
from contextvars import ContextVar
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import tempfile
import time
import uuid
from urllib.parse import urlparse

from aiohttp import web

import preview
import website

ROOT = Path(__file__).resolve().parents[1]
REQUEST_BYTES = 120_000
REQUEST_ID = ContextVar('preview_request_id', default='')


class PreviewError(Exception):
    def __init__(self, message, status=503):
        self.message, self.status = message, status


class RateLimit:
    """Single-instance budgets; don't trust user-provided forwarded IP headers."""
    def __init__(self):
        self.clients = defaultdict(deque)
        self.total = deque()

    def retry_after(self, client):
        now = time.monotonic()
        for key in list(self.clients):
            while self.clients[key] and self.clients[key][0] <= now - 600:
                self.clients[key].popleft()
            if not self.clients[key]:
                del self.clients[key]
        while self.total and self.total[0] <= now - 3600:
            self.total.popleft()
        deadlines = [now]
        if len(events := self.clients.get(client, ())) >= 5:
            deadlines.append(events[len(events) - 5] + 600)
        if len(self.total) >= 60:
            deadlines.append(self.total[len(self.total) - 60] + 3600)
        return math.ceil(max(deadlines) - now)

    def allow(self, client):
        if self.retry_after(client):
            return False
        now = time.monotonic()
        self.clients[client].append(now)
        self.total.append(now)
        return True


async def generate_audio(payload):
    # A separate process keeps blocking extraction and ffmpeg off the event loop,
    # and lets us terminate the whole job (including ffmpeg) at the time limit.
    allowed = {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
               "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    with tempfile.TemporaryDirectory(prefix="article-preview-") as tmp:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "src" / "preview.py"), tmp,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            env=environment, start_new_session=True)
        try:
            data = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            _, diagnostics = await asyncio.wait_for(process.communicate(data), timeout=120)
            # Forward only structured diagnostics, never source content,
            # URLs, raw headers, exception messages, or other provider output.
            for line in diagnostics.decode("utf-8", errors="replace").splitlines():
                if (re.fullmatch(r"article_download status=(completed|failed) elapsed=\d+\.\ds"
                                r"(?: error_type=[A-Za-z][A-Za-z0-9_]{0,80})?(?: http_status=[1-5]\d{2})?"
                                r"(?: server=(?:vercel|cloudflare|cloudfront|fastly|nginx|other|unknown)"
                                r" protection=(?:none|vercel_challenge|cloudflare_challenge)"
                                r" retry_after=(?:[0-9]{1,6}|present|none))?", line) or
                        re.fullmatch(r"preview_stage stage=(extract|speech|trim|validate)"
                                     r" status=(completed|failed|retry) elapsed=\d+\.\ds"
                                     r"(?: error_type=[A-Za-z][A-Za-z0-9_]{0,80})?(?: attempt=[123])?", line)):
                    identity = REQUEST_ID.get()
                    print((f"request_id={identity} " if identity else '') + line, flush=True)
            if process.returncode:
                if process.returncode == 3:
                    raise PreviewError(preview.ARTICLE_BLOCKED_MESSAGE, 422)
                if process.returncode == 2:
                    raise PreviewError("We couldn't read that article. Try a direct public article link or paste its text.", 422)
                if process.returncode == 4:
                    raise PreviewError(preview.SPEECH_UNAVAILABLE_MESSAGE)
                if process.returncode == 5:
                    raise PreviewError(preview.ARTICLE_UNAVAILABLE_MESSAGE, 422)
                raise PreviewError("Audio generation is unavailable. Please try again shortly.")
            path = Path(tmp) / "preview.mp3"
            if not path.is_file() or not 0 < path.stat().st_size <= preview.MAX_AUDIO_BYTES:
                raise PreviewError("Audio generation returned an invalid preview. Please try again.")
            return path.read_bytes()
        except asyncio.TimeoutError:
            raise PreviewError("That preview took too long. Try a shorter excerpt or try again later.", 504) from None
        finally:
            # Kill descendants even when the direct worker has already exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


def create_app(allowed_origins=(), generator=generate_audio, max_concurrent=2):
    if max_concurrent not in (1, 2):
        raise ValueError("Preview concurrency must be 1 or 2")
    limiter = RateLimit()
    slots = asyncio.Semaphore(max_concurrent)
    origins = set(allowed_origins)
    # Render terminates HTTPS before forwarding HTTP to the container. Its
    # trusted canonical URL lets the backend's own demo work behind that proxy.
    if public_url := os.environ.get("RENDER_EXTERNAL_URL"):
        origins.add(public_url.rstrip("/"))
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("PREVIEW_ALLOWED_ORIGINS must contain exact HTTP(S) origins without paths")

    @web.middleware
    async def trace_request(request, handler):
        if request.path != '/api/preview' or request.method != 'POST':
            return await handler(request)
        identity = uuid.uuid4().hex  # Never trust a client-supplied identifier.
        token = REQUEST_ID.set(identity)
        started = time.monotonic()
        print(f"preview_request request_id={identity} event=received", flush=True)
        try:
            response = await handler(request)
            response.headers['X-Preview-Request-ID'] = identity
            # This records the handler's result, not proof of delivery through
            # a hosting gateway or of playback in the browser.
            print(f"preview_request request_id={identity} event=finished http_status={response.status} "
                  f"elapsed={time.monotonic() - started:.1f}s", flush=True)
            return response
        except (Exception, asyncio.CancelledError) as error:
            print(f"preview_request request_id={identity} event=failed error_type={type(error).__name__} "
                  f"elapsed={time.monotonic() - started:.1f}s", flush=True)
            raise
        finally:
            REQUEST_ID.reset(token)

    @web.middleware
    async def boundaries(request, handler):
        origin = request.headers.get("Origin")
        own_origin = f"{request.scheme}://{request.host}"
        permitted = origin in origins or origin == own_origin
        if request.path == "/api/preview" and origin and not permitted:
            return web.json_response({"error": "This website isn't allowed to request previews."}, status=403)
        try:
            response = await handler(request)
        except web.HTTPException as error:
            response = web.json_response({"error": preview.INPUT_TOO_LONG_MESSAGE if error.status == 413 else "Request unavailable."}, status=error.status)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer"})
        if origin and permitted:
            response.headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                                     "Access-Control-Allow-Methods": "POST, OPTIONS",
                                     "Access-Control-Expose-Headers": "Retry-After, X-Preview-Request-ID",
                                     "Access-Control-Allow-Headers": "Content-Type"})
        return response

    async def index(request):
        return web.Response(text=website.render(sample=True, preview_api_url="/api/preview"), content_type="text/html")

    async def audio_preview(request):
        if request.content_type != "application/json":
            return web.json_response({"error": "Send JSON containing an article URL or text."}, status=415)
        try:
            payload = preview.validate(await request.json())
        except preview.InputTooLongError:
            return web.json_response({"error": preview.INPUT_TOO_LONG_MESSAGE}, status=400)
        except (ValueError, TypeError):
            return web.json_response({"error": "Provide one public HTTP(S) article URL or pasted text and an available voice."}, status=400)
        if slots.locked():
            return web.json_response({"error": "The preview service is busy. Please try again shortly.",
                                      "code": "preview_busy"}, status=503, headers={"Retry-After": "5"})
        # Busy requests never start work, so waiting for capacity must not spend
        # the client's generation allowance. Admission below has no await gap.
        client = request.remote or "unknown"
        if not limiter.allow(client):
            return web.json_response({"error": "Preview limit reached. Please try again later."}, status=429,
                                     headers={"Retry-After": str(max(1, limiter.retry_after(client)))})
        async with slots:
            try:
                audio = await generator(payload)
            except PreviewError as error:
                return web.json_response({"error": error.message}, status=error.status)
            except Exception:
                return web.json_response({"error": "Audio generation is unavailable. Please try again shortly."}, status=503)
        return web.Response(body=audio, content_type="audio/mpeg",
                            headers={"Content-Disposition": 'inline; filename="article-preview.mp3"'})

    async def preflight(request):
        return web.Response(status=204)

    async def favicon(request):
        return web.FileResponse(ROOT / "src" / "favicon.svg")

    async def script(request):
        return web.FileResponse(ROOT / "src" / "preview.js")

    async def sample(request):
        return web.FileResponse(ROOT / "samples" / "demo.mp3")

    async def health(request):
        return web.json_response({"status": "ok"})

    app = web.Application(middlewares=[trace_request, boundaries], client_max_size=REQUEST_BYTES)
    app.router.add_get("/", index)
    app.router.add_get("/favicon.svg", favicon)
    app.router.add_get("/preview.js", script)
    app.router.add_get("/demo/sample.mp3", sample)
    app.router.add_get("/health", health)
    app.router.add_post("/api/preview", audio_preview)
    app.router.add_options("/api/preview", preflight)
    return app


def main():
    if os.name != "posix" or not all(shutil.which(name) for name in ("ffmpeg", "ffprobe")):
        sys.exit("The preview server needs macOS/Linux and ffmpeg (including ffprobe).")
    configured = [value.strip() for value in os.environ.get("PREVIEW_ALLOWED_ORIGINS", "").split(",") if value.strip()]
    web.run_app(create_app(configured, max_concurrent=int(os.environ.get("PREVIEW_CONCURRENCY", "2"))), host=os.environ.get("PREVIEW_HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")), access_log=None, handler_cancellation=True)


if __name__ == "__main__":
    main()
