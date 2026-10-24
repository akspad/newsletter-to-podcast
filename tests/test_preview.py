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
    def test_article_preview_keeps_coauthors_and_omits_footnote_controls(self):
        body = ('Careful observations<sup><a role="doc-noteref" href="#fn1">1</a></sup> help researchers '
                'compare results and test their ideas. They share their evidence so readers can understand '
                'what changed and how future experiments might help.')
        html = ('<article><header><h1>A discovery</h1><p class="byline">By '
                '<a href="/authors/alex">Alex Writer</a> and <a href="/authors/sam">Sam Author</a>'
                '</p></header><div class="entry-content"><p>' + body + '</p></div></article>')
        with patch('substack.Substack.get', return_value=html):
            text = preview.article_text('https://fictional.example/story')
        self.assertTrue(text.startswith('fictional.example. A discovery. By Alex Writer, Sam Author.\nCareful observations help'))
        self.assertNotIn('observations1', preview.excerpt(text))

    def test_preview_uses_visible_author_when_only_an_unrelated_schema_article_exists(self):
        data = {'@type': 'Article', 'url': 'https://fictional.example/other', 'headline': 'Other story',
                'author': {'name': 'Unrelated Writer'}}
        body = 'Actual article sentence with enough readable words to make an opening excerpt. ' * 3
        html = ('<title>Requested article</title><script type="application/ld+json">' + json.dumps(data) +
                '</script><main><article><h1>Requested article</h1><p class="byline">Correct Writer</p>'
                '<div class="entry-content"><p>' + body + '</p></div></article></main>')
        with patch('substack.Substack.get', return_value=html):
            self.assertEqual(preview.article_text('https://fictional.example/story'),
                             'fictional.example. Requested article. By Correct Writer.\n' + body.strip())

    def test_structured_tables_and_definitions_keep_word_boundaries_without_paragraph_tags(self):
        from article_extract import extract_structured_text
        for body, expected in (
                ('<table><tr><th>Model</th><th>Memory</th></tr><tr><td>Atlas</td><td>16 GB</td></tr></table>',
                 'Model Memory Atlas 16 GB'),
                ('<dl><dt>Processor</dt><dd>Four cores</dd></dl>', 'Processor Four cores')):
            with self.subTest(body=body):
                self.assertEqual(extract_structured_text(body), expected)

    def test_worker_json_input_limit_preserves_valid_unicode_and_escaped_text(self):
        for text in ('Café résumé naïve André. ' * 3000, '\x01' * preview.MAX_INPUT_BYTES):
            payload = preview.validate({'text': text})
            for ascii_only in (False, True):
                wire = json.dumps(payload, ensure_ascii=ascii_only).encode('utf-8')
                with self.subTest(ascii_only=ascii_only, bytes=len(wire)):
                    self.assertLessEqual(len(wire), preview.MAX_WORKER_INPUT_BYTES)
                    self.assertEqual(preview.read_payload(io.BytesIO(wire)), payload)
        with self.assertRaises(ValueError):
            preview.read_payload(io.BytesIO(b' ' * (preview.MAX_WORKER_INPUT_BYTES + 1)))
        with self.assertRaises(ValueError):
            preview.validate({'text': 'é' * (preview.MAX_INPUT_BYTES // 2 + 1)})

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg required')
    def test_real_worker_accepts_large_unicode_paste_and_only_narrates_the_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'fixture.mp3'
            subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=24000', '-t', '30', str(audio)], check=True)
            audio_data = audio.read_bytes()
            spoken = []
            class Speech:
                def __init__(self, text, voice, **kwargs):
                    spoken.append(text)
                async def stream(self):
                    yield {'type': 'audio', 'data': audio_data}
            text = 'Café résumé naïve André. ' * 3000
            payload = io.TextIOWrapper(io.BytesIO(json.dumps({'text': text}, ensure_ascii=False).encode('utf-8')))
            with patch('edge_tts.Communicate', Speech), patch('sys.stdin', payload), patch('sys.argv', ['preview.py', tmp]):
                runpy.run_path(preview.__file__, run_name='__main__')
            self.assertEqual(spoken, [preview.excerpt(text)])
            self.assertTrue((Path(tmp) / 'preview.mp3').is_file())
            self.assertLessEqual(len(spoken[0].split()), preview.MAX_WORDS)

    def test_structured_article_body_is_read_when_the_dom_has_only_a_shell(self):
        body = ('A useful article explains how chemistry helps people understand the world. Researchers compare observations, '
                'test their ideas, and share results so others can learn from the same evidence.')
        schema = {'@type': 'Article', 'headline': 'A useful article', 'articleBody': body,
                  'author': {'name': 'Alex Writer'}, 'publisher': {'name': 'Science Notes'}}
        html = ('<script type="application/ld+json">' + json.dumps(schema) + '</script>'
                '<main><h1>A useful article</h1><div id="app"></div></main>')
        with patch('substack.Substack.get', return_value=html) as fetch:
            text = preview.article_text('https://fictional.example/story')
        self.assertEqual(text, 'Science Notes. A useful article. By Alex Writer.\n' + body)
        fetch.assert_called_once()

    def test_structured_fallback_selects_the_requested_article_instead_of_a_recommendation(self):
        body = 'Actual article sentence. ' * 30
        schema = {'@graph': [
            {'@type': 'Article', 'url': 'https://fictional.example/other', 'headline': 'Other article',
             'articleBody': 'Unrelated recommendation. ' * 30, 'author': {'name': 'Other Writer'}},
            {'@type': 'Article', 'url': 'https://fictional.example/story', 'headline': 'A useful article',
             'articleBody': body, 'author': {'name': 'Correct Writer'}}]}
        for urls in (True, False):
            if not urls:
                for node in schema['@graph']:
                    node.pop('url', None)
            html = ('<title>A useful article</title><script type="application/ld+json">' + json.dumps(schema) +
                    '</script><main><h1>A useful article</h1></main>')
            with self.subTest(urls=urls), patch('substack.Substack.get', return_value=html):
                text = preview.article_text('https://fictional.example/story?utm_source=email')
            self.assertIn('By Correct Writer.', text)
            self.assertIn(body.strip(), text)
            self.assertNotIn('Unrelated recommendation', text)

    def test_unmatched_and_paid_structured_bodies_are_not_used(self):
        body = 'Restricted article sentence. ' * 30
        variants = [
            {'url': 'https://fictional.example/other', 'headline': 'Other article'},
            {'isAccessibleForFree': False}, {'isAccessibleForFree': 'false'},
            {'hasPart': {'isAccessibleForFree': False}},
            {'hasPart': {'@id': '#paid'}}, {'hasPart': '#paid'}, {'articleBody': {'text': body}}]
        for variant in variants:
            schema = {'@graph': [dict({'@type': 'Article', 'headline': 'A useful article', 'articleBody': body}, **variant),
                                 {'@id': '#paid', '@type': 'WebPageElement', 'isAccessibleForFree': False}]}
            html = '<script type="application/ld+json">' + json.dumps(schema) + '</script><main><h1>A useful article</h1></main>'
            with self.subTest(variant=variant), patch('substack.Substack.get', return_value=html), self.assertRaises(ValueError):
                preview.article_text('https://fictional.example/story')

    def test_visible_article_prose_is_preferred_over_a_stale_structured_body(self):
        schema = {'@type': 'Article', 'headline': 'A useful article', 'articleBody': 'Stale structured sentence. ' * 30}
        html = ('<script type="application/ld+json">' + json.dumps(schema) + '</script>'
                '<article><h1>A useful article</h1><p>' + 'Current article sentence. ' * 30 + '</p></article>')
        with patch('substack.Substack.get', return_value=html):
            text = preview.article_text('https://fictional.example/story')
        self.assertIn('Current article sentence.', text)
        self.assertNotIn('Stale structured', text)

    def test_structured_html_is_cleaned_and_plain_text_comparisons_are_preserved(self):
        from article_extract import extract_structured_text
        self.assertEqual(extract_structured_text('Compare a < b and c > d with C++ <vector> &amp; maps.'),
                         'Compare a < b and c > d with C++ <vector> & maps.')
        body = ('<h1>A useful article</h1><nav>Ignore navigation</nav><p><span>A</span>n original '
                '<em>sentence</em> &amp; another idea.</p><script>Ignore script</script>'
                '<span style="display:none">Ignore hidden</span>')
        self.assertEqual(extract_structured_text(body, 'A useful article'), 'An original sentence & another idea.')
        self.assertEqual(extract_structured_text('<p>Use &lt;vector&gt; and compare a &lt; b.</p>'),
                         'Use <vector> and compare a < b.')

    def test_redirect_destination_is_used_for_publication_and_article_selection(self):
        from curl_cffi.requests import Response
        from urllib.parse import urlparse
        html = ('<html><head><title>A useful article</title></head><body>'
                '<header><a href="https://publication.example/">Science Notes</a></header><main>'
                '<article><h1><a href="/stories/other">A useful article</a></h1><div class="entry-content"><p>' +
                'Unrelated recommendation. ' * 80 + '</p></div></article>'
                '<article><h1><a href="/stories/useful">A useful article</a></h1><div class="entry-content"><p>' +
                'Actual article sentence. ' * 30 + '</p></div></article></main></body></html>')
        redirect, success = Response(), Response()
        redirect.status_code = 302
        redirect.headers['Location'] = 'https://publication.example/stories/useful'
        success.status_code = 200
        responses = iter([(redirect, b''), (success, html.encode())])
        def get(url, **kwargs):
            response, data = next(responses)
            kwargs['content_callback'](data)
            return response
        with patch('curl_cffi.requests.get', side_effect=get), patch('security.public_destination',
                side_effect=lambda url: (urlparse(url).hostname, 443, '93.184.216.34')):
            text = preview.article_text('https://short.example/link')
        self.assertTrue(text.startswith('Science Notes. A useful article.\nActual article sentence.'))
        self.assertNotIn('Unrelated recommendation', text)
        self.assertNotIn('short.example', text)

    def test_worker_rejects_success_status_challenges_without_calling_speech(self):
        from curl_cffi.requests import Response
        response = Response()
        response.status_code = 200
        response.headers['X-Vercel-Mitigated'] = 'challenge'
        def get(url, **kwargs):
            kwargs['content_callback'](b'<main><h1>Security checkpoint</h1><p>' + b'PRIVATE verification text. ' * 30 + b'</p></main>')
            return response
        stderr = io.StringIO()
        payload = io.TextIOWrapper(io.BytesIO(json.dumps({'url': 'https://fictional.example/story'}).encode()))
        with tempfile.TemporaryDirectory() as tmp, patch('curl_cffi.requests.get', side_effect=get), \
                patch('security.public_destination', return_value=('fictional.example', 443, '93.184.216.34')), \
                patch('edge_tts.Communicate') as speak, patch('sys.stdin', payload), patch('sys.stderr', stderr), \
                patch('sys.argv', ['preview.py', tmp]), self.assertRaises(SystemExit) as error:
            runpy.run_path(preview.__file__, run_name='__main__')
        self.assertEqual(error.exception.code, 3)
        self.assertIn(preview.ARTICLE_BLOCKED_MESSAGE, stderr.getvalue())
        self.assertIn('http_status=200', stderr.getvalue())
        self.assertNotIn('PRIVATE', stderr.getvalue())
        speak.assert_not_called()

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

    def test_download_network_failures_suggest_paste_text_before_calling_speech(self):
        from curl_cffi.requests.exceptions import Timeout, ConnectionError
        for failure in (Timeout, ConnectionError, OSError):
            stderr = io.StringIO()
            payload = io.TextIOWrapper(io.BytesIO(json.dumps({'url': 'https://fictional.example/story'}).encode()))
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp, \
                    patch('substack.Substack.get', side_effect=failure('PRIVATE source details')), \
                    patch('edge_tts.Communicate') as speak, patch('sys.stdin', payload), \
                    patch('sys.stderr', stderr), patch('sys.argv', ['preview.py', tmp]), \
                    self.assertRaises(SystemExit) as error:
                runpy.run_path(preview.__file__, run_name='__main__')
            self.assertEqual(error.exception.code, 5)
            self.assertIn(preview.ARTICLE_UNAVAILABLE_MESSAGE, stderr.getvalue())
            self.assertNotIn('PRIVATE', stderr.getvalue())
            speak.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg required')
    def test_valid_but_truncated_mp3_is_rejected_while_short_input_is_allowed(self):
        async def short_audio(text, voice, path):
            subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=24000', '-t', '5', str(path)], check=True)
        with tempfile.TemporaryDirectory() as tmp, patch('preview.narrate', side_effect=short_audio):
            with self.assertRaises(preview.SpeechUnavailableError):
                preview.generate({'text': 'An original sentence for the requested article. ' * 30}, Path(tmp))
            result = preview.generate({'text': 'A brief sentence.'}, Path(tmp))
            self.assertGreater(tts.duration(result), 0)

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

    def test_rate_limit_retry_delay_tracks_client_and_global_windows(self):
        limiter = preview_server.RateLimit()
        with patch('preview_server.time.monotonic', return_value=1000):
            for _ in range(5):
                self.assertTrue(limiter.allow('client'))
            self.assertEqual(limiter.retry_after('client'), 600)
            self.assertEqual(limiter.retry_after('new-client'), 0)
            for i in range(55):
                self.assertTrue(limiter.allow(f'other-{i}'))
            self.assertEqual(limiter.retry_after('client'), 3600)
        with patch('preview_server.time.monotonic', return_value=1601):
            self.assertEqual(limiter.retry_after('client'), 2999)
            self.assertFalse(limiter.allow('client'))
        with patch('preview_server.time.monotonic', return_value=4599.1):
            self.assertEqual(limiter.retry_after('client'), 1)
        with patch('preview_server.time.monotonic', return_value=4600):
            self.assertEqual(limiter.retry_after('client'), 0)
            self.assertTrue(limiter.allow('client'))


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

    async def test_oversized_text_gets_a_shorter_excerpt_prompt_before_generation(self):
        for text, expected_status in (('é' * 50001, 400), ('a' * 100001, 400), ('a' * 130000, 413)):
            data = json.dumps({'text': text}, ensure_ascii=False).encode('utf-8')
            response = await self.client.post('/api/preview', data=data,
                                              headers={'Content-Type': 'application/json', 'Origin': 'https://demo.example'})
            with self.subTest(bytes=len(data)):
                self.assertEqual(response.status, expected_status)
                self.assertEqual((await response.json())['error'], preview.INPUT_TOO_LONG_MESSAGE)
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'https://demo.example')
        self.assertEqual(self.calls, [])
        for _ in range(5):
            response = await self.client.post('/api/preview', data=json.dumps({'text': 'é' * 50000}, ensure_ascii=False).encode(),
                                              headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status, 200)
        self.assertEqual(len(self.calls), 5)  # Invalid inputs spent no generation allowance.

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

    async def test_request_identifiers_correlate_concurrent_jobs_without_logging_content(self):
        identities = []
        entered = asyncio.Event()
        async def generator(payload):
            identities.append(preview_server.REQUEST_ID.get())
            if len(identities) == 2:
                entered.set()
            await asyncio.wait_for(entered.wait(), 3)
            return b'ID3-audio-fixture'
        client = TestClient(TestServer(preview_server.create_app(['https://demo.example'], generator)))
        await client.start_server()
        output = io.StringIO()
        try:
            with patch('sys.stdout', output):
                responses = await asyncio.gather(*[
                    client.post('/api/preview', json={'text': 'PRIVATE article content'},
                                headers={'Origin': 'https://demo.example', 'X-Preview-Request-ID': 'PRIVATE'})
                    for _ in range(2)])
            self.assertEqual(len(set(identities)), 2)
            self.assertEqual({response.headers['X-Preview-Request-ID'] for response in responses}, set(identities))
            for response in responses:
                identity = response.headers['X-Preview-Request-ID']
                self.assertRegex(identity, r'^[a-f0-9]{32}$')
                self.assertEqual(response.headers['X-Preview-Request-ID'], identity)
                self.assertIn('X-Preview-Request-ID', response.headers['Access-Control-Expose-Headers'])
                self.assertIn(f'request_id={identity} event=received', output.getvalue())
                self.assertIn(f'request_id={identity} event=finished http_status=200', output.getvalue())
            self.assertNotIn('PRIVATE', output.getvalue())
            self.assertEqual(preview_server.REQUEST_ID.get(), '')
        finally:
            await client.close()

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

    async def test_global_rate_limit_returns_the_actual_retry_after_delay(self):
        limiter = preview_server.RateLimit()
        with patch('preview_server.RateLimit', return_value=limiter):
            app = preview_server.create_app(generator=AsyncMock())
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            for age, expected in ((0, 3600), (601, 2999)):
                limiter.total.clear()
                limiter.total.extend([preview_server.time.monotonic() - age] * 60)
                response = await client.post('/api/preview', json={'text': 'An original passage.'})
                self.assertEqual(response.status, 429)
                self.assertLessEqual(abs(int(response.headers['Retry-After']) - expected), 1)
        finally:
            await client.close()

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
    async def test_worker_handoff_keeps_unicode_within_the_worker_wire_limit(self):
        payload = preview.validate({'text': 'Café résumé naïve André. ' * 3000})
        captured = []
        async def communicate(data):
            captured.append(data)
            self.assertEqual(preview.read_payload(io.BytesIO(data)), payload)
            return None, b''
        process = type('Process', (), {'pid': 98765, 'returncode': 0,
                       'communicate': AsyncMock(side_effect=communicate), 'wait': AsyncMock(return_value=0)})()
        async def start(*args, **kwargs):
            (Path(args[-1]) / 'preview.mp3').write_bytes(b'ID3-test-audio')
            return process
        with patch('preview_server.asyncio.create_subprocess_exec', side_effect=start), patch('preview_server.os.killpg'):
            self.assertEqual(await preview_server.generate_audio(payload), b'ID3-test-audio')
        self.assertEqual(len(captured), 1)
        self.assertLess(len(captured[0]), 100_000)

    async def test_transient_speech_failures_retry_with_fresh_audio_and_same_voice(self):
        from aiohttp import ClientConnectionError
        from edge_tts.exceptions import NoAudioReceived, WebSocketError
        for failure, failures in ((NoAudioReceived, 2), (ClientConnectionError, 1), (WebSocketError, 1)):
            attempts = []
            class Speech:
                def __init__(self, *args, **kwargs):
                    attempts.append((args, kwargs))
                    self.attempt = len(attempts)
                async def stream(self):
                    if self.attempt <= failures:
                        yield {'type': 'audio', 'data': b'PARTIAL'}
                        raise failure('PRIVATE provider details')
                    yield {'type': 'audio', 'data': b'COMPLETE'}
            stderr = io.StringIO()
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp, \
                    patch('edge_tts.Communicate', Speech), patch('preview.asyncio.sleep', AsyncMock()), \
                    patch('tts.duration', return_value=1), \
                    patch('sys.stderr', stderr):
                audio = Path(tmp) / 'speech.mp3'
                await preview.narrate('Original text', 'en-US-AndrewNeural', audio)
                self.assertEqual(audio.read_bytes(), b'COMPLETE')
            self.assertEqual(len(attempts), failures + 1)
            self.assertTrue(all(attempt == attempts[0] for attempt in attempts))
            self.assertIn('status=retry', stderr.getvalue())
            self.assertIn(f'attempt={failures + 1}', stderr.getvalue())
            self.assertNotIn('PRIVATE', stderr.getvalue())

    async def test_persistent_websocket_errors_stop_after_three_attempts(self):
        from edge_tts.exceptions import WebSocketError
        class Speech:
            async def stream(self):
                raise WebSocketError('PRIVATE provider details')
                yield
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch('edge_tts.Communicate', return_value=Speech()) as speak, \
                patch('preview.asyncio.sleep', AsyncMock()) as delay, patch('sys.stderr', errors):
            with self.assertRaises(WebSocketError):
                await preview.narrate('An original article.', 'en-US-AndrewNeural', Path(tmp) / 'speech.mp3')
        self.assertEqual(speak.call_count, 3)
        self.assertEqual([call.args[0] for call in delay.await_args_list], [1, 2])
        self.assertNotIn('PRIVATE', errors.getvalue())

    async def test_truncated_stream_retries_and_never_appends_previous_audio(self):
        class Speech:
            async def stream(self):
                yield {'type': 'audio', 'data': b'ONE-ATTEMPT'}
        for durations, succeeds in (([5, 5, 45], True), ([5, 5, 5], False),
                                    ([float('nan'), float('inf'), 45], True), ([0, -1, 45], True)):
            with self.subTest(durations=durations), tempfile.TemporaryDirectory() as tmp, \
                    patch('edge_tts.Communicate', return_value=Speech()) as speak, \
                    patch('tts.duration', side_effect=durations), patch('preview.asyncio.sleep', AsyncMock()):
                path = Path(tmp) / 'speech.mp3'
                if succeeds:
                    await preview.narrate('word ' * 126, 'en-US-AndrewNeural', path)
                else:
                    with self.assertRaises(preview.SpeechUnavailableError):
                        await preview.narrate('word ' * 126, 'en-US-AndrewNeural', path)
                self.assertEqual(speak.call_count, 3)
                self.assertEqual(path.read_bytes(), b'ONE-ATTEMPT')

    async def test_download_timeout_error_reaches_the_api_as_a_paste_text_prompt(self):
        process = type('Process', (), {'pid': 98765, 'returncode': 5,
                       'communicate': AsyncMock(return_value=(None, b'PRIVATE provider details')),
                       'wait': AsyncMock(return_value=0)})()
        client = TestClient(TestServer(preview_server.create_app()))
        await client.start_server()
        try:
            with patch('preview_server.asyncio.create_subprocess_exec', AsyncMock(return_value=process)), \
                    patch('preview_server.os.killpg'):
                response = await client.post('/api/preview', json={'url': 'https://fictional.example/story'})
            self.assertEqual(response.status, 422)
            self.assertEqual(await response.json(), {'error': preview.ARTICLE_UNAVAILABLE_MESSAGE})
        finally:
            await client.close()

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

    async def test_worker_diagnostics_include_the_active_request_identifier(self):
        diagnostic = b'preview_stage stage=speech status=failed elapsed=12.0s error_type=NoAudioReceived'
        process = type('Process', (), {'pid': 98765, 'returncode': 4,
                       'communicate': AsyncMock(return_value=(None, diagnostic + b'\nPRIVATE provider text')),
                       'wait': AsyncMock(return_value=0)})()
        output = io.StringIO()
        token = preview_server.REQUEST_ID.set('a' * 32)
        try:
            with patch('preview_server.asyncio.create_subprocess_exec', AsyncMock(return_value=process)), \
                    patch('preview_server.os.killpg'), patch('sys.stdout', output):
                with self.assertRaises(preview_server.PreviewError):
                    await preview_server.generate_audio({'text': 'PRIVATE article text'})
        finally:
            preview_server.REQUEST_ID.reset(token)
        self.assertEqual(output.getvalue(), 'request_id=' + 'a' * 32 + ' ' + diagnostic.decode() + '\n')

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
