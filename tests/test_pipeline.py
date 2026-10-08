"""Offline regression tests. All source content is fictional."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config
import feed
import main
import substack
import summarize
import storage
import tts

NOW = datetime.now(timezone.utc)
PUB = {"base": "https://newsletter.example.com", "name": "Example", "mode": "full"}
POST = {"id": 123, "title": "A fictional article", "slug": "article", "post_date": NOW.isoformat(),
        "wordcount": 2000, "audience": "everyone", "canonical_url": "https://newsletter.example.com/p/article"}


class ConfigurationTests(unittest.TestCase):
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = config.Settings.from_env()
        self.assertEqual(settings.max_seconds, 300)
        self.assertEqual(settings.mode, "summary")
        self.assertEqual(settings.state_dir, Path(".state"))

    def test_fractional_and_unlimited_duration(self):
        for value, expected in [("2.5", 150), ("0", None)]:
            with patch.dict(os.environ, {"MAX_EPISODE_MINUTES": value}, clear=True):
                self.assertEqual(config.Settings.from_env().max_seconds, expected)

    def test_invalid_configuration(self):
        invalid = [{"MAX_EPISODE_MINUTES": v} for v in ("-1", "nan", "inf", "bad", "0.001")]
        invalid += [{"EPISODE_MODE": "invalid"}, {"KEEP_EPISODES": "-1"}, {"MAX_EPISODES_PER_RUN": "0"},
                    {"STATE_DIR": "site/state"}, {"STATE_DIR": "site"},
                    {"SITE_URL": "https://user:pass@example.com"}, {"SITE_URL": "file:///tmp"}]
        for env in invalid:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                config.Settings.from_env()

    def test_env_file_does_not_execute_and_existing_env_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# comment\nEPISODE_MODE='full'\nFEED_TITLE=$(touch should-not-exist)\n")
            with patch.dict(os.environ, {"EPISODE_MODE": "summary"}, clear=True):
                config.load_env(path)
                self.assertEqual(os.environ["EPISODE_MODE"], "summary")
                self.assertEqual(os.environ["FEED_TITLE"], "$(touch should-not-exist)")

    def test_explicit_list_does_not_discover_subscriptions(self):
        with patch.dict(os.environ, {"PUBLICATIONS": "https://newsletter.example.com Example | full"}, clear=True):
            source = substack.Substack("cookie")
            with patch.object(source, "get", side_effect=AssertionError("Unexpected network request")):
                self.assertEqual(source.publications()[0]["mode"], "full")

    def test_missing_or_empty_list_has_helpful_error(self):
        with self.assertRaisesRegex(ValueError, "copy publications.example"):
            substack.Substack.publications_from_file("/nonexistent/fictional-publications.txt")
        with self.assertRaisesRegex(ValueError, "empty"):
            substack.Substack.publications_from_text("# no sources")

    def test_source_options_and_validation(self):
        pubs = substack.Substack.publications_from_text(
            "https://blog.example.com/feed Example Blog | rss | summary | only: Weekly | any length")
        self.assertTrue(pubs[0]["rss"])
        self.assertTrue(pubs[0]["any_length"])
        self.assertEqual(pubs[0]["only"], "Weekly")
        for line in ("file:///etc/passwd", "https://user:password@example.com", "https://example.com | ful",
                     "https://example.com | full | summary"):
            with self.assertRaises(ValueError):
                substack.Substack.publications_from_text(line)

    def test_full_only_check_needs_no_gemini(self):
        env = {"PUBLICATIONS": "https://example.com Example | full"}
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["main", "--check"]), \
                patch("main.shutil.which", return_value="/usr/bin/ffmpeg"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(), 0)

    def test_summary_check_requires_key(self):
        with patch.dict(os.environ, {"PUBLICATIONS": "https://example.com Example"}, clear=True), \
                patch.object(sys, "argv", ["main", "--check"]), contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main.main(), 2)
            self.assertIn("GEMINI_API_KEY", errors.getvalue())


class PrivacyAndSelectionTests(unittest.TestCase):
    def test_cookie_exact_https_host_allowlist(self):
        with patch.dict(os.environ, {"SUBSTACK_AUTH_HOSTS": "newsletter.example.com"}, clear=True):
            source = substack.Substack("substack.sid=test-cookie")
        self.assertEqual(source.auth_headers("https://newsletter.example.com/p/a")["Cookie"], "substack.sid=test-cookie")
        for url in ["https://other.example.com", "http://newsletter.example.com", "https://newsletter.example.com.evil.test",
                    "https://newsletter.example.com:444", "https://user@newsletter.example.com"]:
            self.assertEqual(source.auth_headers(url), {})

    def test_cookie_not_forwarded_after_redirect(self):
        calls = []
        responses = iter([types.SimpleNamespace(is_redirect=True, headers={"Location": "https://other.example.com"}),
                          types.SimpleNamespace(is_redirect=False, status_code=200, text="ok")])
        def get(url, **kwargs):
            calls.append(kwargs["headers"])
            return next(responses)
        fake = types.ModuleType("curl_cffi")
        fake.requests = types.SimpleNamespace(get=get)
        with patch.dict(os.environ, {"SUBSTACK_AUTH_HOSTS": "newsletter.example.com"}, clear=True), \
                patch.dict(sys.modules, {"curl_cffi": fake}):
            self.assertEqual(substack.Substack("secret").get("https://newsletter.example.com", raw=True), "ok")
        self.assertIn("Cookie", calls[0])
        self.assertNotIn("Cookie", calls[1])

    def test_source_errors_do_not_include_response_or_url(self):
        fake = types.ModuleType("curl_cffi")
        fake.requests = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(
            is_redirect=False, status_code=403, text="PERSONAL-CONTENT", headers={}))
        with patch.dict(sys.modules, {"curl_cffi": fake}), self.assertRaisesRegex(RuntimeError, "HTTP 403") as error:
            substack.Substack("").get("https://example.com/private-token")
        self.assertNotIn("PERSONAL", str(error.exception))
        self.assertNotIn("private-token", str(error.exception))

    def test_source_identity_avoids_cross_publication_collision(self):
        self.assertNotEqual(main.post_key(PUB, POST), main.post_key({**PUB, "base": "https://other.example.com"}, POST))
        self.assertNotIn("Example", main.post_key(PUB, POST))

    def test_mode_and_selection(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = config.Settings.from_env()
        since = NOW - timedelta(days=1)
        short = {**POST, "wordcount": 10, "podcast_url": "https://example.com/audio.mp3"}
        self.assertTrue(main.eligible(PUB, short, since, set(), settings))
        self.assertFalse(main.eligible({**PUB, "mode": "summary"}, short, since, set(), settings))
        self.assertTrue(main.eligible({**PUB, "mode": "summary", "only": "fictional"}, short, since, set(), settings))
        self.assertFalse(main.eligible(PUB, POST, since, {main.post_key(PUB, POST)}, settings))
        self.assertFalse(main.eligible(PUB, {**POST, "post_date": (NOW - timedelta(days=3)).isoformat()}, since, set(), settings))

    def test_summary_budget_and_sentence_clipping(self):
        self.assertEqual(summarize.word_budget(120, 700), 260)
        self.assertEqual(summarize.word_budget(600, 700), 700)
        self.assertEqual(summarize.word_budget(None, 700), 700)
        self.assertEqual(summarize.limit_words("One complete sentence. More words that overflow.", 5), "One complete sentence.")

    def test_failed_passage_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp, patch("tts.speak", return_value=False), self.assertRaises(RuntimeError):
            tts.speak_pieces("A complete short passage.", Path(tmp), "part")

    def test_empty_script_rejected(self):
        with self.assertRaises(ValueError):
            tts.synthesize(" ", Path("unused.mp3"))

    def test_tts_chunks_preserve_text_without_empty_chunks(self):
        for script in ["x" * 3000, "x" * 9000, "An introduction.\n" + "x" * 9000 + "\nA conclusion.",
                       "A paragraph.\nAnother paragraph."]:
            pieces = tts.chunks(script)
            self.assertTrue(all(piece.strip() for piece in pieces))
            self.assertTrue(all(len(piece) <= tts.CHUNK_CHARS for piece in pieces))
            self.assertEqual("".join(script.split()), "".join("".join(pieces).split()))

    def test_voice_settings_loaded_after_import_are_used(self):
        calls = []
        class Communicate:
            def __init__(self, text, voice, rate):
                calls.append((voice, rate))
            async def save(self, path):
                Path(path).write_bytes(b"audio")
        fake = types.ModuleType("edge_tts")
        fake.Communicate = Communicate
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"edge_tts": fake}), \
                patch.dict(os.environ, {"TTS_VOICE": "example-voice", "TTS_RATE": "+10%"}, clear=True):
            self.assertTrue(tts.speak("Fictional text.", Path(tmp) / "voice.mp3"))
        self.assertEqual(calls, [("example-voice", "+10%")])

    def test_summary_provider_receives_budget_and_returns_bounded_script(self):
        calls = []
        google = types.ModuleType("google")
        genai = types.ModuleType("google.genai")
        class APIError(Exception):
            pass
        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        def generate_content(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(text="One complete sentence. More words that should be clipped.")
        genai.Client = lambda: types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate_content))
        genai.errors = types.SimpleNamespace(APIError=APIError)
        genai.types = types.SimpleNamespace(GenerateContentConfig=GenerateContentConfig)
        google.genai = genai
        with patch.dict(sys.modules, {"google": google, "google.genai": genai}), patch.dict(os.environ, {}, clear=True):
            script = summarize.write_script("Example", "Author", "Title", "Article text", max_seconds=120, max_words=5)
        self.assertEqual(script, "One complete sentence.")
        self.assertIn("Hard limit: 5 words", calls[0]["config"].system_instruction)
        self.assertIn("untrusted data", calls[0]["config"].system_instruction)


class FeedAndPipelineTests(unittest.TestCase):
    def settings(self, tmp, **overrides):
        with patch.dict(os.environ, {"SITE_DIR": str(Path(tmp) / "site"), "STATE_DIR": str(Path(tmp) / "state"),
                                     "EPISODE_MODE": "full", **overrides}, clear=True):
            return config.Settings.from_env()

    def source(self, post=POST):
        return types.SimpleNamespace(recent_posts=lambda pub: [post], post_text=lambda pub, p: (p, "Fictional article body."))

    def render(self, script, path, maximum):
        path.write_bytes(b"synthetic-audio")
        return 20

    def test_feed_escapes_xml_and_preserves_notes_on_reload(self):
        episode = {"guid": "post-id", "source_key": "post-id", "title": "A & B <test>", "description": "Plain <text> & notes",
                   "link": "https://example.com/?a=1&b=2", "published": NOW.isoformat(), "file": "audio.mp3", "bytes": 12, "duration": 61}
        xml = feed.build('https://example.com/a"b', [episode], "A & B")
        root = ET.fromstring(xml)
        self.assertEqual(root.findtext("channel/item/title"), episode["title"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.xml"
            path.write_text(xml)
            recovered = feed.read(path)
        rebuilt = ET.fromstring(feed.build("https://example.com", recovered))
        self.assertEqual(root.findtext("channel/item/description"), rebuilt.findtext("channel/item/description"))

    def test_run_keeps_state_outside_site_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            with patch.dict(os.environ, {}, clear=True), patch("tts.synthesize", side_effect=self.render), \
                    patch("tts.duration", return_value=20), patch("tts.split_episode", side_effect=lambda path, cap: [path]), \
                    patch("summarize.write_script", side_effect=AssertionError("Full mode called summary")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                main.run(settings, [PUB], self.source())
                main.run(settings, [PUB], self.source())
            state = json.loads((settings.state_dir / "state.json").read_text())
            self.assertEqual(len(state["episodes"]), 1)
            self.assertFalse((settings.site / "state.json").exists())
            self.assertNotIn("fictional article", output.getvalue())
            self.assertIn("Fictional article body", (settings.site / "feed.xml").read_text())
            self.assertNotIn("Fictional article body", output.getvalue())

    def test_retry_does_not_mark_failed_article_seen_or_leak_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            def fail(script, path, cap):
                path.write_bytes(b"partial")
                raise RuntimeError("SECRET article body https://personal.example.com")
            with patch.dict(os.environ, {}, clear=True), patch("tts.synthesize", side_effect=fail), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as output:
                main.run(settings, [PUB], self.source())
            state = json.loads((settings.state_dir / "state.json").read_text())
            self.assertEqual(state["seen"], [])
            self.assertEqual(len(state["retry"]), 1)
            self.assertFalse(list((settings.site / "episodes").glob("*.mp3")))
            self.assertNotIn("SECRET", output.getvalue())

    def test_removed_source_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            state = {"episodes": [], "seen": [], "retry": [{"pub": {**PUB, "base": "https://removed.example.com"}, "post": POST}]}
            main.save_state(settings, state)
            with patch.dict(os.environ, {}, clear=True), patch("tts.synthesize", side_effect=AssertionError("Unexpected retry")), \
                    contextlib.redirect_stdout(io.StringIO()):
                main.run(settings, [PUB], types.SimpleNamespace(recent_posts=lambda p: []))
            self.assertEqual(json.loads((settings.state_dir / "state.json").read_text())["retry"], [])

    def test_summary_uses_configured_audio_and_word_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp, MAX_EPISODE_MINUTES="2.5", MAX_SCRIPT_WORDS="250")
            (settings.site / "episodes").mkdir(parents=True)
            with patch.dict(os.environ, {}, clear=True), patch("summarize.write_script", return_value="A summary.") as writer, \
                    patch("tts.synthesize", side_effect=self.render) as render, patch("tts.duration", return_value=20), \
                    contextlib.redirect_stdout(io.StringIO()):
                state = {"episodes": []}
                main.make_episode(self.source(), {**PUB, "mode": "summary"}, POST, NOW, state, settings)
            self.assertEqual(writer.call_args.args[4:6], (150, 250))
            self.assertEqual(render.call_args.args[2], 150)

    def test_full_part_group_is_retained_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp, KEEP_EPISODES="1")
            settings.site.joinpath("episodes").mkdir(parents=True)
            old = {"guid": "old", "source_key": "old", "published": (NOW - timedelta(days=1)).isoformat(), "file": "old.mp3"}
            (settings.site / "episodes" / "old.mp3").write_bytes(b"old")
            main.save_state(settings, {"episodes": [old], "seen": [], "retry": []})
            def split(path, cap):
                parts = [path.with_name(path.stem + f"-part-{i:03d}.mp3") for i in (1, 2, 3)]
                for part in parts:
                    part.write_bytes(b"part")
                path.unlink()
                return parts
            with patch.dict(os.environ, {}, clear=True), patch("tts.synthesize", side_effect=self.render), \
                    patch("tts.split_episode", side_effect=split), patch("tts.duration", return_value=20), \
                    contextlib.redirect_stdout(io.StringIO()):
                main.run(settings, [PUB], self.source())
            state = json.loads((settings.state_dir / "state.json").read_text())
            self.assertEqual(len(state["episodes"]), 3)
            self.assertFalse((settings.site / "episodes" / "old.mp3").exists())
            self.assertEqual(len({e["source_key"] for e in state["episodes"]}), 1)


class MigrationTests(unittest.TestCase):
    def test_legacy_seen_ids_prevent_regeneration_including_retired_episodes(self):
        state = storage.migrate({"episodes": [], "seen": ["123", "456"], "retry": []}, Path("/nonexistent/fictional-feed.xml"))
        with patch.dict(os.environ, {}, clear=True):
            settings = config.Settings.from_env()
        self.assertFalse(main.eligible(PUB, POST, NOW - timedelta(days=1), set(state["seen"]), settings))
        self.assertIn(storage.legacy_key("456"), state["seen"])
        self.assertNotIn("123", state["seen"])

    def test_legacy_feed_retains_exact_guids_links_notes_and_dates(self):
        old = {"guid": "substack-123", "title": "Example old episode", "description": "Original notes.",
               "link": POST["canonical_url"], "published": NOW.isoformat(), "file": "old-audio.mp3", "bytes": 99, "duration": 60}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.xml"
            original = feed.build("https://original.example.com/podcast", [old], "Original feed title")
            path.write_text(original)
            state = storage.migrate({"episodes": [old], "seen": ["123"], "retry": []}, path)
            # Even a different configured base cannot change an existing enclosure or GUID.
            rebuilt = feed.build("https://different.example.com", state["episodes"], state["feed_title"])
        before, after = ET.fromstring(original), ET.fromstring(rebuilt)
        for tag in ("guid", "description", "pubDate", "title", "link"):
            self.assertEqual(before.findtext(f"channel/item/{tag}"), after.findtext(f"channel/item/{tag}"))
        self.assertEqual(before.find("channel/item/enclosure").attrib, after.find("channel/item/enclosure").attrib)
        self.assertEqual(before.findtext("channel/title"), after.findtext("channel/title"))

    def test_unlimited_retention_keeps_existing_audio_when_a_new_article_arrives(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = FeedAndPipelineTests()
            settings = helper.settings(tmp)
            self.assertEqual(settings.keep_episodes, 0)
            (settings.site / "episodes").mkdir(parents=True)
            old = {"guid": "substack-456", "title": "Old episode", "description": "Old notes.", "link": "https://example.com/old",
                   "published": (NOW - timedelta(days=1)).isoformat(), "file": "old.mp3", "bytes": 3, "duration": 20}
            (settings.site / "episodes" / "old.mp3").write_bytes(b"old")
            (settings.site / "feed.xml").write_text(feed.build("https://original.example.com", [old]))
            settings.state_dir.mkdir()
            (settings.state_dir / "legacy-state.json").write_text(json.dumps({"episodes": [old], "seen": ["456"], "retry": []}))
            with patch.dict(os.environ, {}, clear=True), patch("tts.synthesize", side_effect=helper.render), \
                    patch("tts.duration", return_value=20), patch("tts.split_episode", side_effect=lambda p, cap: [p]), \
                    contextlib.redirect_stdout(io.StringIO()):
                main.run(settings, [PUB], helper.source())
            state = json.loads((settings.state_dir / "state.json").read_text())
            self.assertEqual(len(state["episodes"]), 2)
            self.assertEqual((settings.site / "episodes" / "old.mp3").read_bytes(), b"old")
            self.assertEqual(state["episodes"][0]["guid"], "substack-456")
            self.assertIn(storage.legacy_key("456"), state["seen"])
            self.assertIn(main.post_key(PUB, POST), state["seen"])

    def test_key_validation_is_safe_and_does_not_echo_key(self):
        for key in ("", "short-secret", "not-base64!", "é"):
            with patch.dict(os.environ, {"STATE_ENCRYPTION_KEY": key}, clear=True), self.assertRaises(ValueError) as error:
                storage.validate_key()
            if key:
                self.assertNotIn(key, str(error.exception))
        valid = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        with patch.dict(os.environ, {"STATE_ENCRYPTION_KEY": valid}, clear=True):
            self.assertEqual(storage.validate_key(), valid)


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography required (installed in CI)")
class EncryptionTests(unittest.TestCase):
    def test_private_retry_configuration_survives_encrypted_publication(self):
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory() as tmp:
            settings = FeedAndPipelineTests().settings(tmp)
            settings.site.mkdir()
            state = {"episodes": [], "seen": ["post-abc"], "retry": [{"pub": {**PUB, "only": "PRIVATE_FILTER"}, "post": POST}]}
            key = Fernet.generate_key().decode()
            with patch.dict(os.environ, {"STATE_ENCRYPTION_KEY": key, "PUBLISH_TO_PAGES": "true"}, clear=True):
                storage.publish(settings, state)
                encrypted = (settings.site / storage.PUBLIC_STATE).read_bytes()
                recovered = storage.load(settings)
            self.assertNotIn(b"PRIVATE_FILTER", encrypted)
            self.assertNotIn(PUB["base"].encode(), encrypted)
            self.assertEqual(recovered["retry"], state["retry"])
            self.assertFalse((settings.site / "state.json").exists())

    def test_tampering_or_wrong_key_fails_without_resetting_history(self):
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory() as tmp:
            settings = FeedAndPipelineTests().settings(tmp)
            settings.site.mkdir()
            key = Fernet.generate_key().decode()
            with patch.dict(os.environ, {"STATE_ENCRYPTION_KEY": key, "PUBLISH_TO_PAGES": "true"}, clear=True):
                storage.publish(settings, {"episodes": [], "seen": ["post-abc"], "retry": []})
                path = settings.site / storage.PUBLIC_STATE
                original = path.read_bytes()
                path.write_bytes(original[:-1] + b"!")
                with self.assertRaisesRegex(ValueError, "Cannot decrypt"):
                    storage.load(settings)
                path.write_bytes(original)
                os.environ["STATE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
                with self.assertRaisesRegex(ValueError, "Cannot decrypt"):
                    storage.load(settings)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
class RealAudioTests(unittest.TestCase):
    def tone(self, path, seconds=4.2):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                        "-ar", "44100", "-ac", "1", "-b:a", "64k", str(path)], check=True)

    def test_full_audio_split_preserves_duration_and_caps_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "article.mp3"
            self.tone(path)
            original = tts.duration(path)
            parts = tts.split_episode(path, 2)
            lengths = [tts.duration(part) for part in parts]
            self.assertEqual(len(parts), 3)
            self.assertTrue(all(length <= 2 for length in lengths), lengths)
            self.assertGreaterEqual(sum(lengths), original - 0.1)
            self.assertFalse(path.exists())

    def test_summary_audio_has_real_configured_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.mp3"
            def speak(text, tmpdir, name):
                piece = tmpdir / f"{name}.mp3"
                self.tone(piece)
                return [piece]
            with patch("tts.speak_pieces", side_effect=speak):
                seconds = tts.synthesize("Fictional summary.", path, 2)
            self.assertLessEqual(seconds, 2)
            self.assertGreater(seconds, 1.8)

    def test_unlimited_full_audio_is_not_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "article.mp3"
            self.tone(path)
            before = tts.duration(path)
            self.assertEqual(tts.split_episode(path, None), [path])
            self.assertEqual(tts.duration(path), before)


@unittest.skipUnless(importlib.util.find_spec("bs4"), "beautifulsoup4 required (installed in CI)")
class AdapterTests(unittest.TestCase):
    def test_rss_and_atom_read_available_text(self):
        source = substack.Substack("")
        rss = '<rss><channel><item><title>Example</title><guid>rss-1</guid><link>https://example.com/p/a</link><pubDate>Sun, 04 Oct 2026 12:00:00 GMT</pubDate><description>&lt;p&gt;A fictional body.&lt;/p&gt;</description></item></channel></rss>'
        atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>atom-1</id><title>Example</title><updated>2026-10-04T12:00:00Z</updated><link href="/p/a"/><content type="html">&lt;p&gt;A fictional body.&lt;/p&gt;</content></entry></feed>'
        for xml in (rss, atom):
            with patch.object(source, "get", return_value=xml):
                posts = source.rss_posts({**PUB, "rss": True}, 50)
            self.assertEqual(posts[0]["wordcount"], 3)
            self.assertEqual(source.post_text({**PUB, "rss": True}, posts[0])[1], "A fictional body.")

    def test_html_removes_scripts_and_widgets(self):
        text = substack.html_to_text('<p>Hello <a href="/">world</a>.</p><script>secret</script><div class="subscription-widget-wrap"><p>Subscribe</p></div>')
        self.assertEqual(text, "Hello world.")


if __name__ == "__main__":
    unittest.main()

