"""Description regressions using fictional sources and synthetic audio only."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config
import feed
import main

PUB = {"base": "https://fictional.example/feed", "name": "Fictional Source", "mode": "full", "rss": True}
POST = {"id": 123, "title": "Fictional title", "canonical_url": "https://fictional.example/article",
        "audience": "everyone", "post_date": datetime.now(timezone.utc).isoformat()}
ARTICLE = "First paragraph with <literal tags> & punctuation.\nSecond paragraph: café."


class DescriptionTests(unittest.TestCase):
    def settings(self, root):
        with patch.dict(os.environ, {"SITE_DIR": str(root / "site"), "STATE_DIR": str(root / "state")}, clear=True):
            return config.Settings.from_env()

    def old_episode(self, **changes):
        key = main.post_key(PUB, POST)
        return {"guid": key, "source_key": key, "title": "Fictional title",
                "description": main.FULL_PLACEHOLDER, "link": POST["canonical_url"],
                "published": "2026-01-01T12:00:00+00:00", "file": "old.mp3", "bytes": 3,
                "duration": 12, **changes}

    def test_new_split_full_episodes_include_entire_article_and_escape_html(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            settings = self.settings(Path(tmp))
            (settings.site / "episodes").mkdir(parents=True)
            def synthesize(script, path, maximum):
                self.assertIn(ARTICLE, script)
                path.write_bytes(b"synthetic audio")
            def split(path, maximum):
                parts = [path.with_name(path.stem + f"-part-{i:03d}.mp3") for i in (1, 2)]
                for part in parts:
                    part.write_bytes(b"synthetic part")
                path.unlink()
                return parts
            state = {"episodes": []}
            source = types.SimpleNamespace(post_text=lambda pub, post: (post, ARTICLE))
            with patch("tts.synthesize", side_effect=synthesize), patch("tts.split_episode", side_effect=split), \
                    patch("tts.duration", return_value=12), contextlib.redirect_stdout(io.StringIO()) as logs:
                main.make_episode(source, PUB, POST, datetime.now(timezone.utc), state, settings)
            items = ET.fromstring(feed.build(settings.site_url, state["episodes"])).findall("channel/item")
            self.assertEqual(len(items), 2)
            for item in items:
                self.assertEqual(item.findtext("description"), feed.html(ARTICLE))
                self.assertNotIn(main.FULL_PLACEHOLDER, item.findtext("description"))
            for value in (ARTICLE, PUB["name"], PUB["base"], POST["title"]):
                self.assertNotIn(value, logs.getvalue())

    def test_summaries_stay_brief_and_restricted_full_text_keeps_notice(self):
        self.assertEqual(main.episode_description("summary", ARTICLE, False),
                         "Spoken summary of the text available from the source.")
        self.assertEqual(main.episode_description("full", ARTICLE, True), main.RESTRICTED_NOTICE + "\n" + ARTICLE)
        self.assertNotIn(ARTICLE, main.episode_description("summary", ARTICLE, True))

    def test_existing_notes_are_repaired_without_changing_audio_or_rss_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            settings = self.settings(Path(tmp))
            (settings.site / "episodes").mkdir(parents=True)
            (settings.site / "episodes" / "old.mp3").write_bytes(b"old")
            settings.state_dir.mkdir()
            old = self.old_episode()
            state = {"episodes": [old], "seen": [old["guid"]], "retry": [], "last_run": None}
            (settings.state_dir / "state.json").write_text(json.dumps(state))
            (settings.site / "feed.xml").write_text(feed.build(settings.site_url, [old]))
            before = ET.parse(settings.site / "feed.xml").getroot().find("channel/item")
            # Completed articles are repaired even outside generation's lookback window.
            old_post = {**POST, "post_date": (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()}
            text = Mock(return_value=(POST, ARTICLE))
            source = types.SimpleNamespace(recent_posts=lambda pub: [old_post], post_text=text)
            with patch("tts.synthesize", side_effect=AssertionError("Existing audio must not regenerate")), \
                    contextlib.redirect_stdout(io.StringIO()) as logs:
                self.assertEqual(main.run(settings, [PUB], source), 0)
                self.assertEqual(main.run(settings, [PUB], source), 0)
            after = ET.parse(settings.site / "feed.xml").getroot().find("channel/item")
            self.assertEqual(after.findtext("description"), feed.html(ARTICLE))
            for tag in ("guid", "title", "pubDate", "link"):
                self.assertEqual(before.findtext(tag), after.findtext(tag))
            self.assertEqual(before.find("enclosure").attrib, after.find("enclosure").attrib)
            self.assertEqual((settings.site / "episodes" / "old.mp3").read_bytes(), b"old")
            self.assertEqual(text.call_count, 1)
            saved = json.loads((settings.state_dir / "state.json").read_text())
            self.assertEqual(saved["seen"], [old["guid"]])
            self.assertEqual(saved["retry"], [])
            page = (settings.site / "index.html").read_text()
            for value in (ARTICLE, PUB["base"], POST["title"]):
                self.assertNotIn(value, logs.getvalue())
                self.assertNotIn(value, page)

    def test_backfill_updates_all_parts_and_legacy_link_but_preserves_summary(self):
        key = main.post_key(PUB, POST)
        episodes = [self.old_episode(guid=key + "-part-001"), self.old_episode(guid=key + "-part-002"),
                    self.old_episode(guid="substack-123", source_key="substack-123"),
                    self.old_episode(guid="summary", description="Spoken summary of the text available from the source.")]
        text = Mock(return_value=(POST, ARTICLE))
        with contextlib.redirect_stdout(io.StringIO()):
            main.refresh_descriptions(types.SimpleNamespace(post_text=text), PUB, [POST], {"episodes": episodes})
        self.assertEqual(text.call_count, 1)
        for episode in episodes[:3]:
            self.assertEqual(episode["description"], ARTICLE)
        self.assertEqual(episodes[3]["description"], "Spoken summary of the text available from the source.")

    def test_failed_or_empty_refresh_preserves_old_notes_and_sanitizes_errors(self):
        private = "PRIVATE_SOURCE_URL COOKIE PRIVATE_ARTICLE"
        for response in (RuntimeError(private), (POST, " \n")):
            episode = self.old_episode(description_html=feed.html(main.FULL_PLACEHOLDER))
            original = dict(episode)
            text = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                main.refresh_descriptions(types.SimpleNamespace(post_text=text), PUB, [POST], {"episodes": [episode]})
            self.assertEqual(episode, original)
            self.assertIn("will retry", errors.getvalue())
            self.assertNotIn(private, errors.getvalue())

    def test_existing_article_notes_and_unmatched_posts_are_left_alone(self):
        episodes = [self.old_episode(description=ARTICLE),
                    self.old_episode(source_key="unmatched", link="https://fictional.example/older")]
        original = [dict(e) for e in episodes]
        text = Mock(side_effect=AssertionError("No text fetch expected"))
        main.refresh_descriptions(types.SimpleNamespace(post_text=text), PUB, [POST], {"episodes": episodes})
        self.assertEqual(episodes, original)
        text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
