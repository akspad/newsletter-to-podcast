"""Interactive demo boundaries, provider failures and actual audio duration."""
import asyncio
import json
import io
import runpy
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
        self.assertLessEqual(len(preview.excerpt("word " * 1000).split()), 130)
        self.assertLessEqual(len(preview.excerpt("文" * 10000)), 1000)
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

    def test_article_intro_uses_page_metadata_without_repeating_title_or_byline(self):
        html = ('<meta property="og:site_name" content="Curiosity Weekly">'
                '<meta name="author" content="Alex Writer">'
                '<article><h1>A little room for curiosity</h1><a rel="author">Alex Writer</a>'
                '<p>' + 'An original sentence. ' * 40 + '</p></article>')
        with patch("substack.Substack.get", return_value=html) as fetch:
            text = preview.article_text("https://fictional.example/story")
        self.assertTrue(text.startswith("Curiosity Weekly. A little room for curiosity. By Alex Writer.\n"))
        self.assertEqual(text.count("A little room for curiosity"), 1)
        self.assertEqual(text.count("Alex Writer"), 1)
        fetch.assert_called_once_with("https://fictional.example/story", raw=True)

    def test_article_intro_supports_json_ld_graph_and_multiple_authors(self):
        data = {"@graph": [{"@type": "WebSite", "name": "Unrelated"},
                           {"@type": ["Article", "BlogPosting"], "headline": "An original story",
                            "publisher": {"name": "The Thoughtful Blog"},
                            "author": [{"@type": "Person", "name": "Alex"}, {"name": "Sam"}]}]}
        html = ('<script type="application/ld+json">' + json.dumps(data) + '</script>'
                '<article><p>' + 'Original sentence. ' * 40 + '</p></article>')
        with patch("substack.Substack.get", return_value=html):
            text = preview.article_text("https://fictional.example/story")
        self.assertTrue(text.startswith("The Thoughtful Blog. An original story. By Alex, Sam.\n"))

    def test_missing_or_malformed_metadata_never_invents_an_author(self):
        html = ('<script type="application/ld+json">{broken</script>'
                '<meta property="article:author" content="https://fictional.example/profile">'
                '<title>A quiet afternoon</title><main><p>' + 'Original sentence. ' * 40 + '</p></main>')
        with patch("substack.Substack.get", return_value=html):
            text = preview.article_text("https://www.fictional.example/story")
        self.assertTrue(text.startswith("fictional.example. A quiet afternoon.\n"))
        self.assertNotIn("By ", text)
        self.assertNotIn("/profile", text)

    def test_site_header_does_not_override_article_title(self):
        html = ('<header><h1>Site branding</h1></header><meta property="og:title" content="Actual article title">'
                '<main><p>' + 'Original sentence. ' * 40 + '</p></main>')
        with patch("substack.Substack.get", return_value=html):
            text = preview.article_text("https://fictional.example/story")
        self.assertTrue(text.startswith("fictional.example. Actual article title.\n"))
        self.assertNotIn("Site branding", text)

    def test_explicit_article_body_is_preferred_over_an_author_bio(self):
        html = ('<meta property="og:site_name" content="Example Blog"><meta name="author" content="Alex">'
                '<main><h1>A useful story</h1><article class="author-bio">' + 'Author biography. ' * 40 +
                '</article><section class="post__content"><p>' + 'Actual article sentence. ' * 40 + '</p></section></main>')
        with patch("substack.Substack.get", return_value=html):
            text = preview.article_text("https://fictional.example/story")
        self.assertTrue(text.startswith("Example Blog. A useful story. By Alex.\nActual article sentence."))
        self.assertNotIn("Author biography", text)

    def test_lesswrong_post_container_excludes_comments_and_preserves_attribution(self):
        body = 'An original sentence for the article. ' * 40
        for wrapper in ('div', 'main'):
            html = ('<title>An original story — LessWrong</title>'
                    '<nav>DO NOT READ navigation</nav><' + wrapper + '><h1>635</h1>'
                    '<h1 class="PostsPageTitle-root">An original story</h1>'
                    '<span class="PostsAuthors-root">by Alex Writer</span>'
                    '<div hidden id="S:4"><div class="PostsPage-postContent instapaper_body"><p>' + body + '</p>'
                    '<script>DO NOT READ scripts</script><span hidden>DO NOT READ hidden text</span></div></div>'
                    '<div class="Comment-body">DO NOT READ comments</div></' + wrapper + '>')
            with self.subTest(wrapper=wrapper), patch("substack.Substack.get", return_value=html):
                text = preview.article_text("https://www.lesswrong.com/posts/fictional/story")
            self.assertEqual(text, "lesswrong.com. An original story. By Alex Writer.\n" + body.strip())

    def test_title_omits_only_a_matching_publication_suffix(self):
        for raw, expected in [("A useful story - Science Notes", "A useful story"),
                              ("A useful story - Another subject", "A useful story - Another subject")]:
            html = ('<meta property="og:site_name" content="Science Notes">'
                    '<meta property="og:title" content="' + raw + '">'
                    '<article><p>' + 'Original sentence. ' * 40 + '</p></article>')
            with self.subTest(title=raw), patch("substack.Substack.get", return_value=html):
                text = preview.article_text("https://fictional.example/story")
            self.assertTrue(text.startswith("Science Notes. " + expected + ".\n"))

    def test_long_metadata_leaves_room_for_the_article(self):
        html = ('<meta property="og:site_name" content="' + 'Blog ' * 100 + '">'
                '<meta name="author" content="' + 'Writer ' * 100 + '">'
                '<article><h1>' + 'Title ' * 100 + '</h1><p>' + 'Body sentence. ' * 100 + '</p></article>')
        with patch("substack.Substack.get", return_value=html):
            text = preview.excerpt(preview.article_text("https://fictional.example/story"))
        self.assertIn("Body sentence.", text)
        self.assertLessEqual(len(text.split()), 130)
        self.assertLessEqual(len(text), 1000)

    def test_page_section_order_and_optional_backend(self):
        page = website.render(sample=True)
        self.assertLess(page.index('class="sample"'), page.index('class="grid"'))
        self.assertLess(page.index('class="grid"'), page.index('id="preview-form"'))
        self.assertIn('id="generate-preview" type="submit" disabled', page)
        self.assertIn("Live previews aren’t connected", page)
        page = website.render(sample=True, preview_api_url="https://preview.example/api/preview")
        self.assertIn('data-endpoint="https://preview.example/api/preview"', page)
        self.assertNotIn('type="submit" disabled', page)
        for endpoint in ('javascript:alert(1)', 'https://user:secret@example.com/api', 'http://example.com/api', 'https://example.com/api#x'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                website.render(preview_api_url=endpoint)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
    def test_real_audio_is_capped_at_one_minute(self):
        spoken = []
        async def fake_narrate(text, voice, path):
            spoken.append(text)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=24000:cl=mono", "-t", "70", str(path)], check=True)
        html = ('<meta property="og:site_name" content="Original Blog"><meta name="author" content="Alex">'
                '<article><h1>A short story</h1><p>' + 'Original sentence. ' * 200 + '</p></article>')
        with tempfile.TemporaryDirectory() as tmp, patch("preview.narrate", side_effect=fake_narrate), \
                patch("substack.Substack.get", return_value=html):
            result = preview.generate({"url": "https://fictional.example/story"}, Path(tmp))
            self.assertTrue(spoken[0].startswith("Original Blog. A short story. By Alex."))
            self.assertLessEqual(len(spoken[0].split()), 130)
            self.assertTrue(result.is_file())
            self.assertGreater(tts.duration(result), 59)
            self.assertLessEqual(tts.duration(result), 60)

    def test_worker_classifies_source_errors_without_exposing_provider_details(self):
        from substack import SourceDownloadError
        for status, exit_code in [(401, 3), (403, 3), (429, 3), (404, 2), (500, 2)]:
            stderr = io.StringIO()
            payload = io.TextIOWrapper(io.BytesIO(json.dumps({"url": "https://fictional.example/story"}).encode()))
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp, \
                    patch("substack.Substack.get", side_effect=SourceDownloadError("PRIVATE provider response", status)), \
                    patch("sys.stdin", payload), patch("sys.stderr", stderr), patch("sys.argv", ["preview.py", tmp]), \
                    self.assertRaises(SystemExit) as error:
                runpy.run_path(str(Path(preview.__file__)), run_name="__main__")
            self.assertEqual(error.exception.code, exit_code)
            self.assertNotIn("PRIVATE", stderr.getvalue())
            if exit_code == 3:
                self.assertIn(preview.ARTICLE_BLOCKED_MESSAGE, stderr.getvalue())

    def test_worker_distinguishes_speech_failure_from_article_access(self):
        from edge_tts.exceptions import NoAudioReceived
        class EmptySpeech:
            async def stream(self):
                raise NoAudioReceived('PRIVATE provider details')
                yield  # Make this an asynchronous iterator.
        stderr = io.StringIO()
        payload = io.TextIOWrapper(io.BytesIO(json.dumps({'text': 'An original article.'}).encode()))
        with tempfile.TemporaryDirectory() as tmp, patch('edge_tts.Communicate', return_value=EmptySpeech()), \
                patch('asyncio.sleep', AsyncMock()), patch('sys.stdin', payload), patch('sys.stderr', stderr), \
                patch('sys.argv', ['preview.py', tmp]), self.assertRaises(SystemExit) as error:
            runpy.run_path(str(Path(preview.__file__)), run_name='__main__')
        self.assertEqual(error.exception.code, 4)
        self.assertIn(preview.SPEECH_UNAVAILABLE_MESSAGE, stderr.getvalue())
        self.assertIn('stage=speech status=failed', stderr.getvalue())
        self.assertNotIn('PRIVATE', stderr.getvalue())

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
    async def test_transient_speech_failure_retries_once_with_fresh_audio_and_same_voice(self):
        from aiohttp import ClientConnectionError
        from edge_tts.exceptions import NoAudioReceived
        for failure in (NoAudioReceived, ClientConnectionError):
            attempts = []
            class Speech:
                def __init__(self, *args, **kwargs):
                    attempts.append((args, kwargs))
                    self.attempt = len(attempts)
                async def stream(self):
                    if self.attempt == 1:
                        yield {'type': 'audio', 'data': b'PARTIAL'}
                        raise failure('PRIVATE provider details')
                    yield {'type': 'audio', 'data': b'COMPLETE'}
            stderr = io.StringIO()
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp, \
                    patch('edge_tts.Communicate', Speech), patch('preview.asyncio.sleep', AsyncMock()), \
                    patch('sys.stderr', stderr):
                audio = Path(tmp) / 'speech.mp3'
                await preview.narrate('Original text', 'en-US-AndrewNeural', audio)
                self.assertEqual(audio.read_bytes(), b'COMPLETE')
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0], attempts[1])
            self.assertIn('status=retry', stderr.getvalue())
            self.assertIn('attempt=2', stderr.getvalue())
            self.assertNotIn('PRIVATE', stderr.getvalue())

    async def test_speech_retry_does_not_repeat_nontransient_failures(self):
        class OversizedSpeech:
            async def stream(self):
                yield {'type': 'audio', 'data': b'a' * (preview.MAX_AUDIO_BYTES + 1)}
        with tempfile.TemporaryDirectory() as tmp, patch('edge_tts.Communicate', return_value=OversizedSpeech()) as speak:
            with self.assertRaises(ValueError):
                await preview.narrate('Original text', 'en-US-AndrewNeural', Path(tmp) / 'speech.mp3')
        self.assertEqual(speak.call_count, 1)

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

    async def test_download_diagnostics_exclude_raw_provider_messages(self):
        diagnostic = (b"article_download status=failed elapsed=26.6s error_type=SourceDownloadError http_status=429 "
                      b"server=vercel protection=vercel_challenge retry_after=none")
        process = type("Process", (), {"pid": 98765, "returncode": 1,
                                       "communicate": AsyncMock(return_value=(None, diagnostic +
                                           b"\nhttps://private.example/token SECRET article text\n")),
                                       "wait": AsyncMock(return_value=0)})()
        output = io.StringIO()
        with patch("preview_server.asyncio.create_subprocess_exec", AsyncMock(return_value=process)), \
                patch("preview_server.os.killpg"), patch("sys.stdout", output):
            with self.assertRaises(preview_server.PreviewError):
                await preview_server.generate_audio({"url": "https://fictional.example/story"})
        self.assertEqual(output.getvalue(), diagnostic.decode() + "\n")

    async def test_speech_diagnostics_and_actionable_error_reach_server_without_private_output(self):
        diagnostic = b'preview_stage stage=speech status=failed elapsed=12.0s error_type=NoAudioReceived'
        process = type('Process', (), {'pid': 98765, 'returncode': 4,
                       'communicate': AsyncMock(return_value=(None, diagnostic +
                           b'\npreview_stage stage=PRIVATE status=failed elapsed=1.0s\nSECRET text and provider URL\n')),
                       'wait': AsyncMock(return_value=0)})()
        output = io.StringIO()
        with patch('preview_server.asyncio.create_subprocess_exec', AsyncMock(return_value=process)), \
                patch('preview_server.os.killpg'), patch('sys.stdout', output):
            with self.assertRaises(preview_server.PreviewError) as error:
                await preview_server.generate_audio({'text': 'Original article'})
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(error.exception.message, preview.SPEECH_UNAVAILABLE_MESSAGE)
        self.assertEqual(output.getvalue(), diagnostic.decode() + '\n')

    async def test_blocked_article_error_reaches_api_as_a_paste_text_prompt(self):
        process = type("Process", (), {"pid": 98765, "returncode": 3,
                                       "communicate": AsyncMock(return_value=(None, b"PRIVATE provider output")),
                                       "wait": AsyncMock(return_value=0)})()
        client = TestClient(TestServer(preview_server.create_app()))
        await client.start_server()
        try:
            with patch("preview_server.asyncio.create_subprocess_exec", AsyncMock(return_value=process)), \
                    patch("preview_server.os.killpg"):
                response = await client.post("/api/preview", json={"url": "https://fictional.example/story"})
            self.assertEqual(response.status, 422)
            self.assertEqual(await response.json(), {"error": preview.ARTICLE_BLOCKED_MESSAGE})
        finally:
            await client.close()

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
