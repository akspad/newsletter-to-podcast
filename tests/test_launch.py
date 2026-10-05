"""Regression coverage for first use, public rendering and source outages."""
import contextlib
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config
import demo
import main
import website
import feed

ROOT = Path(__file__).resolve().parents[1]
PUB = {"base": "https://fictional.example/feed", "name": "Fictional", "mode": "full", "rss": True}


class SourceFailureTests(unittest.TestCase):
    def settings(self, root):
        with patch.dict(os.environ, {"SITE_DIR": str(root / "site"), "STATE_DIR": str(root / "state")}, clear=True):
            return config.Settings.from_env()

    def test_total_outage_preserves_every_existing_file_and_retry_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            settings.site.mkdir()
            settings.state_dir.mkdir()
            (settings.site / "episodes").mkdir()
            state = {"episodes": [], "seen": ["post-old"], "retry": [{"pub": PUB, "post": {"id": 1, "title": "Queued"}}],
                     "last_run": "2026-10-01T12:00:00+00:00", "last_scheduled_run": "2026-10-01T12:00:00+00:00"}
            (settings.state_dir / "state.json").write_text(json.dumps(state))
            for path in (settings.site / "feed.xml", settings.site / "index.html",
                         settings.site / "podcast-state.enc", settings.site / "episodes" / "old.mp3"):
                path.write_bytes(b"existing output")
            # A deliberately unreadable feed lets us prove failure returns before parsing or rewriting it.
            with patch("main.load_state", return_value=state), patch.dict(os.environ, {}, clear=True), \
                    patch("main.make_episode", side_effect=AssertionError("Outage must not consume queued work")), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                source = types.SimpleNamespace(recent_posts=lambda pub: (_ for _ in ()).throw(RuntimeError("PRIVATE_URL")))
                self.assertEqual(main.run(settings, [PUB], source), 1)
                after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertNotIn("PRIVATE_URL", errors.getvalue())
            self.assertIn("All sources unavailable", errors.getvalue())
            self.assertEqual(state["last_run"], "2026-10-01T12:00:00+00:00")
            self.assertEqual(state["last_scheduled_run"], "2026-10-01T12:00:00+00:00")
            self.assertEqual(len(state["retry"]), 1)

    def test_total_outage_on_first_run_does_not_create_empty_feed_or_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            source = types.SimpleNamespace(recent_posts=lambda pub: (_ for _ in ()).throw(RuntimeError("offline")))
            with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main.run(settings, [PUB], source), 1)
            self.assertFalse(settings.site.exists())
            self.assertFalse(settings.state_dir.exists())

    def test_successful_empty_source_returns_zero_and_creates_valid_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.run(settings, [PUB], types.SimpleNamespace(recent_posts=lambda pub: [])), 0)
            self.assertEqual(ET.parse(settings.site / "feed.xml").getroot().findall("channel/item"), [])
            self.assertTrue((settings.site / "index.html").exists())

    def test_partial_failure_keeps_catch_up_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            previous = "2026-10-01T12:00:00+00:00"
            state = {"episodes": [], "seen": [], "retry": [], "last_run": previous}
            def recent(pub):
                if pub["base"] == PUB["base"]:
                    raise RuntimeError("unavailable")
                return []
            with patch.dict(os.environ, {}, clear=True), patch("main.load_state", return_value=state), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main.run(settings, [PUB, {**PUB, "base": "https://other.example/feed"}],
                                          types.SimpleNamespace(recent_posts=recent)), 0)
            self.assertEqual(state["last_run"], previous)

    def test_cli_propagates_run_failure_to_exit_status(self):
        with patch.dict(os.environ, {"PUBLICATIONS": "https://fictional.example/feed | rss | full"}, clear=True), \
                patch.object(sys, "argv", ["main"]), patch("main.shutil.which", return_value="ffmpeg"), \
                patch("main.importlib.util.find_spec", return_value=object()), patch("main.run", return_value=1):
            self.assertEqual(main.main(), 1)


class ListeningPageTests(unittest.TestCase):
    def test_already_completed_scheduled_run_still_adds_listening_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = SourceFailureTests().settings(Path(tmp))
            settings.site.mkdir()
            original = feed.build(settings.site_url, [], "Existing podcast")
            (settings.site / "feed.xml").write_text(original)
            now = datetime(2026, 10, 5, 17, tzinfo=timezone.utc)
            state = {"episodes": [], "seen": [], "retry": [], "last_scheduled_run": now.isoformat()}
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True), \
                    patch("main.load_state", return_value=state), patch("main.datetime", wraps=datetime) as clock, \
                    contextlib.redirect_stdout(io.StringIO()):
                clock.now.return_value = now
                source = types.SimpleNamespace(recent_posts=lambda pub: self.fail("Skipped run requested source"))
                self.assertEqual(main.run(settings, [PUB], source), 0)
            self.assertTrue((settings.site / "index.html").exists())
            self.assertTrue((settings.site / "demo" / "sample.mp3").exists())
            self.assertEqual((settings.site / "feed.xml").read_text(), original)

    def test_public_page_neither_reads_nor_changes_personal_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            original = 'PRIVATE_FEED_TITLE PRIVATE_EPISODE https://personal.example/feed.xml'
            (site / "feed.xml").write_text(original)
            website.write(site)
            page = (site / "index.html").read_text()
            self.assertEqual((site / "feed.xml").read_text(), original)
            for value in ("PRIVATE_FEED_TITLE", "PRIVATE_EPISODE", "personal.example", "feed.xml", "application/rss+xml", 'class="episode"'):
                self.assertNotIn(value, page)
            self.assertIn("A little room for curiosity", page)
            self.assertIn('src="demo/sample.mp3"', page)
            HTMLParser().feed(page)

    def test_personal_metadata_remains_in_feed_but_not_generated_homepage(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            settings = SourceFailureTests().settings(site)
            settings.site.mkdir()
            episode = {"guid": "private-episode-id", "title": "PRIVATE_EPISODE_TITLE", "source_key": "private-episode-id",
                       "description": "Private preference", "link": "https://personal.example/article",
                       "published": "2026-01-01T12:00:00+00:00", "file": "private-audio.mp3", "bytes": 3, "duration": 61}
            state = {"episodes": [episode], "seen": [], "retry": [], "feed_title": "PRIVATE_FEED_TITLE"}
            with patch.dict(os.environ, {}, clear=True), patch("main.load_state", return_value=state), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.run(settings, [PUB], types.SimpleNamespace(recent_posts=lambda pub: [])), 0)
            rss = (settings.site / "feed.xml").read_text()
            page = (settings.site / "index.html").read_text()
            for value in ("PRIVATE_EPISODE_TITLE", "PRIVATE_FEED_TITLE", "personal.example", "private-audio.mp3"):
                self.assertIn(value, rss)
                self.assertNotIn(value, page)
            self.assertNotIn("feed.xml", page)

    def test_only_isolated_demo_page_advertises_its_synthetic_feed(self):
        page = website.render(sample=True, demo_url="http://localhost:8000")
        self.assertIn('href="http://localhost:8000/feed.xml"', page)
        self.assertIn("Open original demo feed", page)
        self.assertIn("Original demo only", page)
        for url in ("javascript:alert(1)", "https://user:pass@example.com", "https://example.com/#fragment"):
            with self.assertRaises(ValueError):
                website.render(demo_url=url)


class BundledDemoTests(unittest.TestCase):
    def test_documented_demo_cli_runs_offline_and_serves_matching_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "demo"
            with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", ["main", "--demo", "--demo-dir", str(output)]), \
                    patch("main.Substack", side_effect=AssertionError("Demo must not read configured sources")), \
                    patch("main.shutil.which", side_effect=AssertionError("Demo must not require ffmpeg")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.main(), 0)
                self.assertEqual(main.main(), 0)
            item = ET.parse(output / "feed.xml").getroot().find("channel/item")
            enclosure = item.find("enclosure")
            self.assertEqual(enclosure.get("url"), "http://localhost:8000/episodes/demo.mp3")
            audio = output / "episodes" / "demo.mp3"
            self.assertEqual(int(enclosure.get("length")), audio.stat().st_size)
            self.assertEqual(audio.read_bytes(), (ROOT / "samples" / "demo.mp3").read_bytes())
            self.assertTrue((output / "index.html").exists())
            self.assertFalse((output / "state.json").exists())
            self.assertIn("original-demo", item.findtext("guid"))

    def test_demo_refuses_existing_production_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            feed = output / "feed.xml"
            feed.write_text("existing personal feed")
            with self.assertRaisesRegex(ValueError, "not empty"):
                demo.build(output)
            self.assertEqual(feed.read_text(), "existing personal feed")


if __name__ == "__main__":
    unittest.main()
