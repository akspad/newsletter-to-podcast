"""Run the article-to-audio demo: python src/preview_server.py."""
import asyncio
from collections import defaultdict, deque
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import time
from urllib.parse import urlparse

from aiohttp import web

import preview
import website

ROOT = Path(__file__).resolve().parents[1]
REQUEST_BYTES = 120_000


class PreviewError(Exception):
    def __init__(self, message, status=503):
        self.message, self.status = message, status


class RateLimit:
    """Single-instance budgets; don't trust user-provided forwarded IP headers."""
    def __init__(self):
        self.clients = defaultdict(deque)
        self.total = deque()

    def allow(self, client):
        now = time.monotonic()
        for key in list(self.clients):
            while self.clients[key] and self.clients[key][0] <= now - 600:
                self.clients[key].popleft()
            if not self.clients[key]:
                del self.clients[key]
        while self.total and self.total[0] <= now - 3600:
            self.total.popleft()
        if len(self.clients.get(client, ())) >= 5 or len(self.total) >= 60:
            return False
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
            await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), timeout=120)
            if process.returncode:
                if process.returncode == 2:
                    raise PreviewError("We couldn't read that article. Try a direct public article link or paste its text.", 422)
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


def create_app(allowed_origins=(), generator=generate_audio):
    limiter = RateLimit()
    slots = asyncio.Semaphore(2)
    origins = frozenset(allowed_origins)
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("PREVIEW_ALLOWED_ORIGINS must contain exact HTTP(S) origins without paths")

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
            response = web.json_response({"error": "Request too large." if error.status == 413 else "Request unavailable."}, status=error.status)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer"})
        if origin and permitted:
            response.headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                                     "Access-Control-Allow-Methods": "POST, OPTIONS",
                                     "Access-Control-Allow-Headers": "Content-Type"})
        return response

    async def index(request):
        return web.Response(text=website.render(sample=True, preview_api_url="/api/preview"), content_type="text/html")

    async def audio_preview(request):
        if request.content_type != "application/json":
            return web.json_response({"error": "Send JSON containing an article URL or text."}, status=415)
        try:
            payload = preview.validate(await request.json())
        except (ValueError, TypeError):
            return web.json_response({"error": "Provide one public HTTP(S) article URL or pasted text and an available voice."}, status=400)
        if not limiter.allow(request.remote or "unknown"):
            return web.json_response({"error": "Preview limit reached. Please try again later."}, status=429,
                                     headers={"Retry-After": "600"})
        if slots.locked():
            return web.json_response({"error": "Both preview slots are busy. Please try again shortly."}, status=503,
                                     headers={"Retry-After": "15"})
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

    app = web.Application(middlewares=[boundaries], client_max_size=REQUEST_BYTES)
    app.router.add_get("/", index)
    app.router.add_get("/favicon.svg", favicon)
    app.router.add_get("/preview.js", script)
    app.router.add_get("/demo/sample.mp3", sample)
    app.router.add_get("/health", health)
    app.router.add_post("/api/preview", audio_preview)
    app.router.add_options("/api/preview", preflight)
    return app


if __name__ == "__main__":
    if os.name != "posix" or not all(shutil.which(name) for name in ("ffmpeg", "ffprobe")):
        sys.exit("The preview server needs macOS/Linux and ffmpeg (including ffprobe).")
    configured = [value.strip() for value in os.environ.get("PREVIEW_ALLOWED_ORIGINS", "").split(",") if value.strip()]
    web.run_app(create_app(configured), host=os.environ.get("PREVIEW_HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")), access_log=None)
