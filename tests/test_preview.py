"""Interactive demo boundaries, provider failures and actual audio duration."""
import asyncio
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import preview
import preview_server
import website
import tts


class PreviewTests(unittest.TestCase):
    def test_input_and_excerpt_budgets(self):
        for payload in ([], {}, {"url": "https://example.com", "text": "both"}, {"text": 4},
                        {"text": "sample", "voice": []}, {"text": "sample", "voice": "unknown"},
                        {"url": "file:///etc/passwd"}, {"url": "https://user:secret@example.com"},
                        {"url": "https://example.com:8080"}, {"text": "a" * 100001}):
            with self.subTest(payload=str(payload)[:100]), self.assertRaises(ValueError):
                preview.validate(payload)
        self.assertEqual(preview.validate({"text": "  hello  "})["text"], "hello")
        self.assertLessEqual(len(preview.excerpt("word " * 1000).split()), 390)
        self.assertLessEqual(len(preview.excerpt("文" * 10000)), 3000)
        self.assertEqual(preview.excerpt("win\u200bner"), "winner")

    def test_extraction_excludes_navigation_and_requires_article_content(self):
        html = '<nav>DO NOT READ</nav><article><h1>An original story</h1><p>' + 'Original sentence. ' * 40 + '</p><script>DO NOT READ</script></article>'
        with patch("substack.Substack.get", return_value=html):
            text = preview.article_text("https://fictional.example/article")
            self.assertIn("An original story", text)
            self.assertNotIn("DO NOT READ", text)
        with patch("substack.Substack.get", return_value="<body>Sign in</body>"), self.assertRaises(ValueError):
            preview.article_text("https://fictional.example/article")

    def test_private_destination_is_rejected_before_fetch(self):
        with patch("security.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
            with self.assertRaisesRegex(ValueError, "Private or reserved"):
                preview.article_text("http://fictional.example/article")

    def test_page_keeps_preview_primary_and_does_not_invent_a_backend(self):
        page = website.render(sample=True)
        self.assertLess(page.index('id="preview-form"'), page.index('class="sample"'))
        self.assertIn('id="generate-preview" type="submit" disabled', page)
        self.assertIn("Live previews aren’t connected", page)
        page = website.render(sample=True, preview_api_url="https://preview.example/api/preview")
        self.assertIn('data-endpoint="https://preview.example/api/preview"', page)
        self.assertNotIn('type="submit" disabled', page)
        for endpoint in ('javascript:alert(1)', 'https://user:secret@example.com/api', 'http://example.com/api', 'https://example.com/api#x'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                website.render(preview_api_url=endpoint)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
    def test_real_audio_is_capped_at_three_minutes(self):
        async def fake_narrate(text, voice, path):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=24000:cl=mono", "-t", "190", str(path)], check=True)
        with tempfile.TemporaryDirectory() as tmp, patch("preview.narrate", side_effect=fake_narrate):
            result = preview.generate({"text": "An original short article."}, Path(tmp))
            self.assertTrue(result.is_file())
            self.assertGreater(tts.duration(result), 179)
            self.assertLessEqual(tts.duration(result), 180)

    def test_rate_limits_and_expiry(self):
        limiter = preview_server.RateLimit()
        with patch("preview_server.time.monotonic", return_value=1000):
            self.assertTrue(all(limiter.allow("client") for _ in range(5)))
            self.assertFalse(limiter.allow("client"))
            for i in range(55):
                self.assertTrue(limiter.allow(str(i)))
            self.assertFalse(limiter.allow("new-client"))
        with patch("preview_server.time.monotonic", return_value=4601):
            self.assertTrue(limiter.allow("client"))
            self.assertEqual(len(limiter.clients), 1)


class PreviewApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        async def generator(payload):
            self.calls.append(payload)
            return b"ID3-audio-fixture"
        self.client = TestClient(TestServer(preview_server.create_app(["https://demo.example"], generator)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_form_to_mp3_response_and_cors(self):
        page = await self.client.get("/")
        self.assertIn('data-endpoint="/api/preview"', await page.text())
        response = await self.client.post("/api/preview", json={"text": "An original article."},
                                          headers={"Origin": "https://demo.example"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "audio/mpeg")
        self.assertEqual(await response.read(), b"ID3-audio-fixture")
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://demo.example")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.calls[0]["voice"], "en-US-AndrewNeural")
        self.assertEqual((await self.client.get("/health")).status, 200)
        self.assertEqual((await self.client.get("/.state/state.json")).status, 404)

    async def test_rejected_origin_and_invalid_inputs_never_generate(self):
        denied = await self.client.post("/api/preview", json={"text": "article"}, headers={"Origin": "https://untrusted.example"})
        self.assertEqual(denied.status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", denied.headers)
        preflight = await self.client.options("/api/preview", headers={"Origin": "https://demo.example"})
        self.assertEqual(preflight.status, 204)
        self.assertEqual(preflight.headers["Access-Control-Allow-Headers"], "Content-Type")
        for payload in ({}, {"url": "file:///etc/passwd"}, {"text": "text", "url": "https://example.com"}):
            response = await self.client.post("/api/preview", json=payload)
            self.assertEqual(response.status, 400)
        self.assertEqual((await self.client.post("/api/preview", data="bad json", headers={"Content-Type": "application/json"})).status, 400)
        self.assertEqual((await self.client.post("/api/preview", data="text")).status, 415)
        self.assertEqual((await self.client.post("/api/preview", json={"text": "a" * 130000})).status, 413)
        self.assertEqual(self.calls, [])

    async def test_rate_limit_is_enforced(self):
        for _ in range(5):
            self.assertEqual((await self.client.post("/api/preview", json={"text": "article"})).status, 200)
        limited = await self.client.post("/api/preview", json={"text": "article"})
        self.assertEqual(limited.status, 429)
        self.assertIn("Retry-After", limited.headers)
        self.assertEqual(len(self.calls), 5)

    async def test_busy_service_and_provider_failures_are_actionable(self):
        entered, release = asyncio.Event(), asyncio.Event()
        count = 0
        async def blocked(payload):
            nonlocal count
            count += 1
            if count == 2:
                entered.set()
            await release.wait()
            raise preview_server.PreviewError("Try pasting the article text.", 422)
        client = TestClient(TestServer(preview_server.create_app(generator=blocked)))
        await client.start_server()
        try:
            jobs = [asyncio.create_task(client.post("/api/preview", json={"text": "article"})) for _ in range(2)]
            await asyncio.wait_for(entered.wait(), 3)
            busy = await client.post("/api/preview", json={"text": "article"})
            self.assertEqual(busy.status, 503)
            release.set()
            for response in await asyncio.gather(*jobs):
                self.assertEqual(response.status, 422)
                self.assertEqual((await response.json())["error"], "Try pasting the article text.")
        finally:
            release.set()
            await client.close()

    async def test_small_instance_runs_one_job_and_health_remains_responsive(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked(payload):
            entered.set()
            await release.wait()
            return b"ID3-audio-fixture"
        client = TestClient(TestServer(preview_server.create_app(generator=blocked, max_concurrent=1)))
        await client.start_server()
        try:
            job = asyncio.create_task(client.post("/api/preview", json={"text": "article"}))
            await asyncio.wait_for(entered.wait(), 3)
            self.assertEqual((await client.get("/health")).status, 200)
            for _ in range(7):
                busy = await client.post("/api/preview", json={"text": "article"})
                self.assertEqual(busy.status, 503)
                self.assertEqual((await busy.json())["code"], "preview_busy")
                self.assertEqual(busy.headers["Retry-After"], "5")
            release.set()
            self.assertEqual((await job).status, 200)
            # Seven busy rejections did not consume the five-job allowance.
            for _ in range(4):
                self.assertEqual((await client.post("/api/preview", json={"text": "article"})).status, 200)
            self.assertEqual((await client.post("/api/preview", json={"text": "article"})).status, 429)
        finally:
            release.set()
            await client.close()

    async def test_render_https_page_is_allowed_behind_http_proxy(self):
        async def generator(payload):
            return b"ID3-audio-fixture"
        with patch.dict("os.environ", {"RENDER_EXTERNAL_URL": "https://preview.onrender.com/"}):
            app = preview_server.create_app(generator=generator)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post("/api/preview", json={"text": "article"},
                                         headers={"Origin": "https://preview.onrender.com"})
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://preview.onrender.com")
        finally:
            await client.close()


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_excludes_secrets_and_removes_temporary_audio(self):
        paths, environments = [], []
        process = type("Process", (), {"pid": 98765, "returncode": 0,
                                       "communicate": AsyncMock(return_value=(None, b"")),
                                       "wait": AsyncMock(return_value=0)})()
        async def start(*args, **kwargs):
            directory = Path(args[-1])
            paths.append(directory)
            environments.append(kwargs["env"])
            (directory / "preview.mp3").write_bytes(b"ID3-test-audio")
            return process
        with patch.dict("os.environ", {"GEMINI_API_KEY": "PRIVATE", "SUBSTACK_SID": "PRIVATE"}), \
                patch("preview_server.asyncio.create_subprocess_exec", side_effect=start), \
                patch("preview_server.os.killpg") as terminate:
            audio = await preview_server.generate_audio({"text": "Original article"})
        self.assertEqual(audio, b"ID3-test-audio")
        self.assertNotIn("GEMINI_API_KEY", environments[0])
        self.assertNotIn("SUBSTACK_SID", environments[0])
        self.assertFalse(paths[0].exists())
        terminate.assert_called_once()

    async def test_timeout_terminates_worker_and_removes_files(self):
        paths = []
        process = type("Process", (), {"pid": 98765, "returncode": None,
                                       "communicate": AsyncMock(side_effect=asyncio.TimeoutError),
                                       "wait": AsyncMock(return_value=0)})()
        async def start(*args, **kwargs):
            paths.append(Path(args[-1]))
            return process
        with patch("preview_server.asyncio.create_subprocess_exec", side_effect=start), \
                patch("preview_server.os.killpg") as terminate:
            with self.assertRaises(preview_server.PreviewError) as error:
                await preview_server.generate_audio({"text": "Original article"})
        self.assertEqual(error.exception.status, 504)
        terminate.assert_called_once()
        process.wait.assert_awaited_once()
        self.assertFalse(paths[0].exists())


if __name__ == "__main__":
    unittest.main()
