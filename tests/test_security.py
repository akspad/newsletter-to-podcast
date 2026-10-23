"""Security boundary regressions; fictional payloads and mocked external services."""
import asyncio
import contextlib
import io
import gzip
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config
import feed
import main
import security
import storage
import substack
import summarize
import tts


class DestinationTests(unittest.TestCase):
    def test_all_nonpublic_address_classes_and_credentials_are_rejected(self):
        addresses = ["127.0.0.1", "::1", "10.0.0.1", "192.168.1.1", "172.16.0.1", "169.254.169.254",
                     "fc00::1", "fe80::1", "::ffff:127.0.0.1", "0.0.0.0", "224.0.0.1", "ff02::1"]
        for address in addresses:
            with self.subTest(address=address), patch("security.socket.getaddrinfo", return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 443))]), self.assertRaises(ValueError):
                security.public_destination("https://fictional.example")
        for url in ["file:///tmp/a", "https://user@fictional.example", "https://@fictional.example",
                    "https://fictional.example:444", "http://fictional.example:443", "https://[fe80::1%25en0]",
                    "https://fictional.example\n"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                security.public_destination(url)

    def test_mixed_public_private_dns_answers_fail_closed(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 443))
                   for ip in ["93.184.216.34", "127.0.0.1"]]
        with patch("security.socket.getaddrinfo", return_value=answers), self.assertRaises(ValueError):
            security.public_destination("https://fictional.example")

    def fake_transport(self, responses, calls):
        fake = types.ModuleType("curl_cffi")
        fake.CurlOpt = types.SimpleNamespace(RESOLVE=1, PROXY=2, MAXFILESIZE_LARGE=3)
        responses = iter(responses)
        def get(url, **kwargs):
            calls.append((url, kwargs))
            response, data = next(responses)
            for block in data:
                if kwargs["content_callback"](block) == 0xFFFFFFFF:
                    raise RuntimeError("transport aborted")
            return response
        fake.requests = types.SimpleNamespace(get=get)
        return fake

    def test_redirect_to_private_address_never_reaches_transport(self):
        calls = []
        response = types.SimpleNamespace(is_redirect=True, headers={"Location": "http://127.0.0.1/secret"})
        fake = self.fake_transport([(response, [])], calls)
        def dns(host, port, **kwargs):
            ip = "127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, port))]
        with patch.dict(sys.modules, {"curl_cffi": fake}), patch("security.socket.getaddrinfo", side_effect=dns), self.assertRaises(ValueError):
            substack.Substack("").get("http://fictional.example")
        self.assertEqual(len(calls), 1)

    def test_checked_ip_is_pinned_and_proxies_disabled(self):
        calls = []
        response = types.SimpleNamespace(is_redirect=False, status_code=200)
        fake = self.fake_transport([(response, [b'{"ok":true}'])], calls)
        with patch.dict(sys.modules, {"curl_cffi": fake}), patch("security.socket.getaddrinfo", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))]) as dns:
            self.assertEqual(substack.Substack("").get("https://fictional.example"), {"ok": True})
        self.assertEqual(dns.call_count, 1)
        self.assertEqual(calls[0][1]["curl_options"][1], [b"fictional.example:443:93.184.216.34"])
        self.assertEqual(calls[0][1]["curl_options"][2], b"")

    def test_preview_timeout_override_keeps_the_download_limits(self):
        for timeout in (30, 60):
            calls = []
            fake = self.fake_transport([(types.SimpleNamespace(is_redirect=False, status_code=200),
                                         [b'{"ok":true}'])], calls)
            with patch.dict(sys.modules, {"curl_cffi": fake}), patch("security.public_destination", return_value=(
                    "fictional.example", 443, "93.184.216.34")):
                source = substack.Substack("") if timeout == 30 else substack.Substack("", request_timeout=60)
                self.assertEqual(source.get("https://fictional.example"), {"ok": True})
            self.assertEqual(calls[0][1]["timeout"], timeout)
            self.assertEqual(calls[0][1]["curl_options"][1], [b"fictional.example:443:93.184.216.34"])
            self.assertEqual(calls[0][1]["curl_options"][3], security.MAX_RESPONSE_BYTES)

    def test_http_status_is_preserved_when_source_rejects_or_exhausts_retries(self):
        for status in (403, 429):
            calls = []
            response = types.SimpleNamespace(is_redirect=False, status_code=status)
            fake = self.fake_transport([(response, [])] * 5, calls)
            with patch.dict(sys.modules, {"curl_cffi": fake}), patch("security.public_destination", return_value=(
                    "fictional.example", 443, "93.184.216.34")), patch("substack.time.sleep"), \
                    self.assertRaises(substack.SourceDownloadError) as error:
                substack.Substack("").get("https://fictional.example")
            self.assertEqual(error.exception.status_code, status)
            self.assertEqual(len(calls), 5 if status == 429 else 1)

    def test_browser_challenges_are_not_retried(self):
        for headers, body in [({"x-vercel-mitigated": "challenge"}, b"Vercel Security Checkpoint"),
                              ({"cf-mitigated": "challenge"}, b"Check your browser")]:
            calls = []
            response = types.SimpleNamespace(is_redirect=False, status_code=429, headers=headers)
            fake = self.fake_transport([(response, [body])], calls)
            with patch.dict(sys.modules, {"curl_cffi": fake}), patch("security.public_destination", return_value=(
                    "fictional.example", 443, "93.184.216.34")), patch("substack.time.sleep") as pause, \
                    self.assertRaises(substack.SourceDownloadError):
                substack.Substack("").get("https://fictional.example")
            self.assertEqual(len(calls), 1)
            pause.assert_not_called()

    def test_success_status_browser_challenges_are_rejected_before_article_parsing(self):
        cases = [({'X-Vercel-Mitigated': 'challenge'}, b'Verification required', 'vercel_challenge'),
                 ({'Cf-Mitigated': 'challenge'}, b'Verification required', 'cloudflare_challenge'),
                 ({'Content-Type': 'text/html'}, b'<title>Vercel Security Checkpoint</title>', 'vercel_challenge'),
                 ({'Content-Type': 'text/html'}, b'<title>Just a moment...</title>'
                  b'<script src="/cdn-cgi/challenge-platform/example.js"></script>', 'cloudflare_challenge')]
        for headers, body, protection in cases:
            calls = []
            response = types.SimpleNamespace(is_redirect=False, status_code=200, headers=headers)
            fake = self.fake_transport([(response, [body])], calls)
            with self.subTest(protection=protection, headers=headers), patch.dict(sys.modules, {'curl_cffi': fake}), \
                    patch('security.public_destination', return_value=('fictional.example', 443, '93.184.216.34')), \
                    patch('substack.time.sleep') as pause, self.assertRaises(substack.SourceDownloadError) as error:
                substack.Substack('').get('https://fictional.example/story', raw=True)
            self.assertEqual(error.exception.status_code, 200)
            self.assertEqual(error.exception.protection, protection)
            self.assertEqual(len(calls), 1)
            pause.assert_not_called()

    def test_ordinary_articles_and_json_quoting_checkpoint_text_are_not_blocked(self):
        html = '<html><title>Understanding browser checks</title><article>We discuss Vercel Security Checkpoint.</article></html>'
        data = {'body_html': '<title>Vercel Security Checkpoint</title>'}
        for content, mime, raw, expected in ((html, 'text/html', True, html),
                                           (json.dumps(data), 'application/json', False, data)):
            calls = []
            response = types.SimpleNamespace(is_redirect=False, status_code=200, headers={'Content-Type': mime})
            fake = self.fake_transport([(response, [content.encode()])], calls)
            with self.subTest(mime=mime), patch.dict(sys.modules, {'curl_cffi': fake}), \
                    patch('security.public_destination', return_value=('fictional.example', 443, '93.184.216.34')):
                self.assertEqual(substack.Substack('').get('https://fictional.example/story', raw=raw), expected)

    def test_page_charset_declarations_preserve_accents_and_punctuation(self):
        body = 'Café owners discuss a résumé. “Useful ideas,” said André, “deserve clear explanations.”'
        for declaration in ('<meta charset="windows-1252">',
                            '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'):
            html = '<html><head>' + declaration + '</head><body><p>' + body + '</p></body></html>'
            calls = []
            response = types.SimpleNamespace(is_redirect=False, status_code=200, encoding='utf-8',
                                             headers={'Content-Type': 'text/html'})
            fake = self.fake_transport([(response, [html.encode('cp1252')])], calls)
            with self.subTest(declaration=declaration), patch.dict(sys.modules, {'curl_cffi': fake}), \
                    patch('security.public_destination', return_value=('fictional.example', 443, '93.184.216.34')):
                self.assertEqual(substack.Substack('').get('https://fictional.example/story', raw=True), html)

    def test_http_charset_bom_and_xml_encoding_are_respected(self):
        text = '<html><p>Café — a useful résumé.</p></html>'
        cases = [(text.encode('cp1252'), {'Content-Type': 'text/html; charset="windows-1252"'}, text),
                 (text.encode('utf-8-sig'), {'Content-Type': 'text/html; charset=windows-1252'}, text),
                 (text.encode('utf-16'), {'Content-Type': 'text/html'}, text),
                 ('<?xml version="1.0" encoding="iso-8859-1"?><rss><title>Café</title></rss>'.encode('latin1'),
                  {'Content-Type': 'application/rss+xml'},
                  '<?xml version="1.0" encoding="iso-8859-1"?><rss><title>Café</title></rss>')]
        for data, headers, expected in cases:
            with self.subTest(headers=headers):
                self.assertEqual(substack.decode_source(data, headers), expected)
        declared = '<meta charset="windows-1252"><p>Café</p>'
        self.assertEqual(substack.decode_source(declared.encode('cp1252'),
                         {'Content-Type': 'text/html; charset=not-a-codec'}), declared)

    def test_final_redirect_destination_is_retained_only_after_success(self):
        calls = []
        redirects = [(types.SimpleNamespace(is_redirect=True, headers={'Location': 'https://publication.example/stories/one'}), []),
                     (types.SimpleNamespace(is_redirect=False, status_code=200), [b'{"ok":true}'])]
        fake = self.fake_transport(redirects, calls)
        source = substack.Substack('')
        with patch.dict(sys.modules, {'curl_cffi': fake}), \
                patch('security.public_destination', side_effect=lambda url: (url.split('/')[2], 443, '93.184.216.34')):
            self.assertEqual(source.get('https://short.example/link'), {'ok': True})
        self.assertEqual(source.last_url, 'https://publication.example/stories/one')
        self.assertEqual([call[0] for call in calls], ['https://short.example/link', source.last_url])
        with patch('security.public_destination', side_effect=ValueError('Private or reserved')), self.assertRaises(ValueError):
            source.get('https://private.example/')
        self.assertIsNone(source.last_url)

    def test_challenge_diagnostics_exclude_response_content_and_tokens(self):
        cases = [({"Server": "Vercel", "X-Vercel-Mitigated": "challenge", "Set-Cookie": "SECRET"},
                  b"SECRET", "server=vercel protection=vercel_challenge retry_after=none"),
                 ({}, b"<title>Vercel Security Checkpoint</title>SECRET",
                  "server=unknown protection=vercel_challenge retry_after=none"),
                 ({"Server": "cloudflare", "Cf-Mitigated": "challenge", "Retry-After": "60"},
                  b"SECRET", "server=cloudflare protection=cloudflare_challenge retry_after=60"),
                 ({"Server": "SECRET", "Retry-After": "SECRET"}, b"SECRET",
                  "server=other protection=none retry_after=present")]
        for headers, body, expected in cases:
            with self.subTest(expected=expected):
                error = substack.SourceDownloadError("Source error", 429, headers=headers, body=body)
                self.assertEqual(error.diagnostics, expected)
                self.assertNotIn("SECRET", str(error.__dict__))

    def test_chunked_response_and_aggregate_downloads_abort_before_parsing(self):
        for response_limit, run_limit in [(5, 100), (100, 5)]:
            calls = []
            fake = self.fake_transport([(types.SimpleNamespace(is_redirect=False, status_code=200),
                                         [b"123", b"456", b"should never be read"])], calls)
            with patch.dict(sys.modules, {"curl_cffi": fake}), patch("security.public_destination", return_value=(
                    "fictional.example", 443, "93.184.216.34")), patch("security.MAX_RESPONSE_BYTES", response_limit), \
                    patch("security.MAX_DOWNLOAD_BYTES", run_limit), self.assertRaises(security.BudgetExceeded):
                substack.Substack("").get("https://fictional.example")


class ResourceTests(unittest.TestCase):
    def test_article_rejected_before_summary_or_narration(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = config.Settings.from_env()
            source = types.SimpleNamespace(post_text=lambda *args: ({}, "x" * (security.MAX_ARTICLE_BYTES + 1)))
            with patch("tts.synthesize_full") as audio, patch("summarize.write_script") as model, self.assertRaises(security.BudgetExceeded):
                main.make_episode(source, {"base": "https://fictional.example", "mode": "full"}, {}, None,
                                  {"episodes": []}, settings)
            audio.assert_not_called()
            model.assert_not_called()
        with self.assertRaises(security.BudgetExceeded):
            summarize.write_script("Pub", "Author", "Title", "x" * (security.MAX_MODEL_INPUT_BYTES + 1))

    def test_retry_count_and_byte_budget_preserve_bounded_article_bodies(self):
        payloads = [{"pub": {"base": "https://fictional.example/feed", "rss": True},
                     "post": {"id": i, "title": "Article", "body_html": "Keep this article."}} for i in range(10)]
        with patch("security.MAX_RETRY_COUNT", 3), contextlib.redirect_stderr(io.StringIO()):
            kept = main.bounded_retries(payloads)
        self.assertEqual(len(kept), 3)
        self.assertEqual(kept[0]["post"]["body_html"], "Keep this article.")
        with patch("security.MAX_RETRY_BYTES", 400), contextlib.redirect_stderr(io.StringIO()):
            kept = main.bounded_retries(payloads)
        self.assertLessEqual(len(json.dumps(kept).encode()), 400)

    def test_oversized_provider_extras_are_not_saved_in_retry_queue(self):
        post = main.bounded_post({"id": 1, "title": "Normal", "provider_extra": "x" * 300_000})
        self.assertNotIn("provider_extra", post)
        with self.assertRaises(security.BudgetExceeded):
            main.bounded_post({"id": 1, "body_html": "x" * 300_000})

    def test_rss_and_atom_entry_ceiling_is_client_side(self):
        xml = "<rss><channel>" + "".join(f"<item><guid>{i}</guid><pubDate>Mon, 12 Oct 2026 12:00:00 GMT</pubDate>"
              "<description>Body</description></item>" for i in range(10)) + "</channel></rss>"
        atom = '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(f"<entry><id>{i}</id>"
               "<updated>2026-10-12T12:00:00Z</updated><content>Body</content></entry>" for i in range(10)) + "</feed>"
        source = substack.Substack("")
        for document in [xml, atom]:
            with patch.object(source, "get", return_value=document), patch("substack.html_to_text", side_effect=lambda x: x), \
                    patch("security.MAX_SOURCE_ENTRIES", 3):
                self.assertEqual(len(source.recent_posts({"base": "https://fictional.example/feed", "rss": True})), 3)

    def test_tts_chunks_and_audio_parts_fail_before_provider_or_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp, patch("security.MAX_TTS_CHUNKS", 1), patch("tts.speak") as speak:
            with self.assertRaises(security.BudgetExceeded):
                tts.synthesize("x" * 6000, Path(tmp) / "out.mp3", None)
            speak.assert_not_called()
        with patch("tts.subprocess.run") as run:
            with self.assertRaises(security.BudgetExceeded):
                tts.pack_clips([("text", Path("unused.mp3"), 1)] * 201, 1)
            run.assert_not_called()

    def test_streaming_audio_byte_limit(self):
        class Voice:
            async def stream(self):
                yield {"type": "audio", "data": b"123"}
                yield {"type": "audio", "data": b"456"}
        with tempfile.TemporaryDirectory() as tmp, patch("security.MAX_AUDIO_BYTES", 5), tts.narration_budget():
            path = Path(tmp) / "part.mp3"
            with self.assertRaises(security.BudgetExceeded):
                asyncio.run(tts.save_audio(Voice(), path))
            self.assertLessEqual(path.stat().st_size, 5)

    def test_run_budget_resets_between_runs(self):
        with security.run_budget(), self.assertRaises(security.RunBudgetExceeded):
            security.charge("tts_calls", 601)
        with security.run_budget():
            security.charge("tts_calls", 1)


@unittest.skipUnless(importlib.util.find_spec("curl_cffi"), "curl_cffi installed in CI")
class RealTransportTests(unittest.TestCase):
    def test_pinned_transport_and_decoded_byte_limit_with_compressed_response(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                data = gzip.compress(b"x" * 100_000) if self.path == "/large" else b'{"ok":true}'
                self.send_response(200)
                if self.path == "/large":
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        port = server.server_port
        try:
            # Only the resolver is replaced: exercise the real libcurl pin and callback.
            with patch("security.public_destination", return_value=("fictional.test", port, "127.0.0.1")):
                source = substack.Substack("")
                self.assertEqual(source.get(f"http://fictional.test:{port}/small"), {"ok": True})
                with patch("security.MAX_RESPONSE_BYTES", 1000), self.assertRaises(security.BudgetExceeded):
                    source.get(f"http://fictional.test:{port}/large", raw=True)
                # Also verify the callback abort independently of libcurl's own size check.
                from curl_cffi import CurlOpt, requests
                original_get = requests.get
                def callback_only(url, **kwargs):
                    kwargs["curl_options"][CurlOpt.MAXFILESIZE_LARGE] = 0
                    return original_get(url, **kwargs)
                with patch("security.MAX_RESPONSE_BYTES", 1000), patch.object(requests, "get", side_effect=callback_only), \
                        self.assertRaises(security.BudgetExceeded):
                    source.get(f"http://fictional.test:{port}/large", raw=True)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


class FeedSafetyTests(unittest.TestCase):
    def test_xml_forbidden_chars_sanitized_in_every_feed_string(self):
        poison = "Safe & <text>\x00\x01\ud800\ufffe"
        episode = {"guid": poison, "rss_guid": poison, "enclosure_url": poison, "title": poison,
                   "description": poison, "link": poison, "published": "2026-10-12T12:00:00+00:00",
                   "file": "audio.mp3", "bytes": 1, "duration": 1}
        document = feed.build(poison, [episode], poison)
        root = ET.fromstring(document)
        self.assertEqual(root.findtext("channel/item/title"), "Safe & <text>")
        for control in ("\x00", "\x01", "\ud800", "\ufffe"):
            self.assertNotIn(control, document)

    def test_invalid_or_oversized_candidate_preserves_previous_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.xml"
            original = feed.build("https://fictional.example", [])
            path.write_text(original)
            with self.assertRaises(ET.ParseError):
                feed.write(path, "<invalid>")
            with patch("security.MAX_FEED_BYTES", 1), self.assertRaises(security.BudgetExceeded):
                feed.write(path, original)
            self.assertEqual(path.read_text(), original)
            feed.write(path, original)
            ET.parse(path)
            self.assertEqual(list(Path(tmp).glob(".feed-*")), [])


@unittest.skipUnless(os.name == "posix", "POSIX permission enforcement")
class PrivateStateTests(unittest.TestCase):
    def settings(self, root):
        with patch.dict(os.environ, {"STATE_DIR": str(root / "private"), "SITE_DIR": str(root / "site")}, clear=True):
            return config.Settings.from_env()

    def test_umask_permissions_and_atomic_updates(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            settings = self.settings(Path(tmp))
            previous = os.umask(0o022)
            try:
                storage.save(settings, {"retry": []})
                storage.save(settings, {"retry": [], "seen": ["new"]})
            finally:
                os.umask(previous)
            self.assertEqual(settings.state_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual((settings.state_dir / "state.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((settings.state_dir / "state.json").read_text())["seen"], ["new"])

    def test_state_and_directory_symlinks_are_rejected_without_changing_target(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            settings = self.settings(root)
            victim = root / "victim.json"
            victim.write_text("unchanged")
            settings.state_dir.mkdir()
            (settings.state_dir / "state.json").symlink_to(victim)
            with self.assertRaises(OSError):
                storage.save(settings, {"retry": []})
            self.assertEqual(victim.read_text(), "unchanged")
            (settings.state_dir / "state.json").unlink()
            settings.state_dir.rmdir()
            settings.state_dir.symlink_to(root, target_is_directory=True)
            with self.assertRaises(OSError):
                storage.save(settings, {"retry": []})

    def test_existing_owned_files_are_hardened_but_unowned_files_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            settings = self.settings(Path(tmp))
            settings.state_dir.mkdir(mode=0o755)
            path = settings.state_dir / "state.json"
            path.write_text('{"episodes": [], "seen": [], "retry": []}')
            os.chmod(path, 0o644)
            storage.load(settings)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch("storage.os.getuid", return_value=os.getuid() + 1), self.assertRaises(ValueError):
                storage.save(settings, {"retry": []})


if __name__ == "__main__":
    unittest.main()
