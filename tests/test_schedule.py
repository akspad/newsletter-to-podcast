"""Offline coverage for configurable cadence and missing-article catch-up."""
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
import schedule
import substack

NOW = datetime(2026, 10, 8, 18, 17, tzinfo=timezone.utc)
PUB = {"base": "https://fictional.example/feed", "name": "Fictional", "rss": True, "mode": "full"}


class CadenceTests(unittest.TestCase):
    def test_default_and_configurable_run_counts(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = config.Settings.from_env()
            self.assertEqual(settings.runs_per_day, 4)
            self.assertEqual(settings.lookback_hours, 168)
        for count in (1, 2, 4, 7, 24):
            with patch.dict(os.environ, {"RUNS_PER_DAY": str(count)}, clear=True):
                self.assertEqual(config.Settings.from_env().runs_per_day, count)
        for value in ("0", "-1", "25", "4.5", "nan", "invalid"):
            with patch.dict(os.environ, {"RUNS_PER_DAY": value}, clear=True), self.assertRaises(ValueError):
                config.Settings.from_env()

    def test_hourly_checks_yield_requested_number_of_windows(self):
        for count in (1, 2, 4, 7, 24):
            state = {}
            completed = 0
            for hour in range(24):
                now = NOW.replace(hour=hour)
                if schedule.scheduled_run_due(state, now, count):
                    completed += 1
                    state["last_scheduled_run"] = now.isoformat()
                self.assertFalse(schedule.scheduled_run_due(state, now, count))
            self.assertEqual(completed, count)
            self.assertTrue(schedule.scheduled_run_due(state, NOW.replace(hour=0) + timedelta(days=1), count))

    def test_old_once_daily_state_does_not_block_later_window(self):
        state = {"last_scheduled_run": NOW.replace(hour=13).isoformat()}
        self.assertFalse(schedule.scheduled_run_due(state, NOW.replace(hour=14), 4))
        self.assertTrue(schedule.scheduled_run_due(state, NOW, 4))
        # Different offsets representing the same instant map to the same UTC window.
        state["last_scheduled_run"] = "2026-10-08T11:17:00-07:00"
        self.assertFalse(schedule.scheduled_run_due(state, NOW, 4))

    def test_cli_marks_skipped_and_manual_checks_without_exposing_state(self):
        for event, due in (("schedule", "false"), ("workflow_dispatch", "true")):
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "output"
                private = "PRIVATE_URL PRIVATE_ARTICLE COOKIE"
                state = {"last_scheduled_run": NOW.isoformat(), "private": private}
                with patch.dict(os.environ, {"GITHUB_EVENT_NAME": event, "GITHUB_OUTPUT": str(output)}, clear=True), \
                        patch("schedule.storage.load", return_value=state) as load, \
                        patch("schedule.datetime", wraps=datetime) as clock, contextlib.redirect_stdout(io.StringIO()) as logs:
                    clock.now.return_value = NOW
                    self.assertEqual(schedule.main(), 0)
                self.assertEqual(output.read_text(), f"due={due}\n")
                self.assertNotIn(private, logs.getvalue())
                self.assertEqual(load.call_count, int(event == "schedule"))

    def test_unreadable_state_fails_closed_with_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule", "GITHUB_OUTPUT": str(output)}, clear=True), \
                    patch("schedule.storage.load", side_effect=ValueError("PRIVATE_COOKIE")), \
                    contextlib.redirect_stderr(io.StringIO()) as logs:
                self.assertEqual(schedule.main(), 1)
            self.assertFalse(output.exists())
            self.assertNotIn("PRIVATE_COOKIE", logs.getvalue())


class CatchUpTests(unittest.TestCase):
    def settings(self, root, **extra):
        with patch.dict(os.environ, {"SITE_DIR": str(root / "site"), "STATE_DIR": str(root / "state"),
                                     "MAX_EPISODES_PER_RUN": "1", **extra}, clear=True):
            return config.Settings.from_env()

    def test_missing_articles_are_queued_then_appended_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            posts = [{"id": i, "title": f"Fictional {i}", "audience": "everyone",
                      "canonical_url": f"https://fictional.example/article/{i}",
                      "post_date": (NOW - timedelta(days=days)).isoformat()} for i, days in ((1, 5), (2, 6))]
            state = {"episodes": [], "seen": [], "retry": [], "last_run": (NOW - timedelta(hours=1)).isoformat()}
            settings.state_dir.mkdir()
            (settings.state_dir / "state.json").write_text(json.dumps(state))
            source = types.SimpleNamespace(recent_posts=lambda pub: posts, post_text=lambda pub, post: (post, "Fictional text"))
            def audio(script, path, cap):
                path.write_bytes(b"synthetic")
            with patch.dict(os.environ, {}, clear=True), patch("main.datetime", wraps=datetime) as clock, \
                    patch("tts.synthesize", side_effect=audio) as generated, patch("tts.duration", return_value=20), \
                    patch("tts.split_episode", side_effect=lambda path, cap: [path]), contextlib.redirect_stdout(io.StringIO()):
                clock.now.return_value = NOW
                self.assertEqual(main.run(settings, [PUB], source), 0)
                saved = json.loads((settings.state_dir / "state.json").read_text())
                self.assertEqual(len(saved["retry"]), 1)
                # Queued articles still complete after disappearing from the current source feed.
                source.recent_posts = lambda pub: []
                self.assertEqual(main.run(settings, [PUB], source), 0)
                source.recent_posts = lambda pub: posts
                self.assertEqual(main.run(settings, [PUB], source), 0)
                self.assertEqual(generated.call_count, 2)
            items = ET.parse(settings.site / "feed.xml").getroot().findall("channel/item")
            self.assertEqual(len(items), 2)
            self.assertEqual(len({item.findtext("guid") for item in items}), 2)

    def test_gap_overlap_recovers_post_dated_before_previous_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            state = {"episodes": [], "seen": [], "retry": [], "last_run": (NOW - timedelta(days=10)).isoformat()}
            post = {"id": 1, "title": "Fictional", "post_date": (NOW - timedelta(days=11)).isoformat()}
            source = types.SimpleNamespace(recent_posts=lambda pub: [post])
            with patch.dict(os.environ, {}, clear=True), patch("main.load_state", return_value=state), \
                    patch("main.datetime", wraps=datetime) as clock, patch("main.make_episode") as create, \
                    contextlib.redirect_stdout(io.StringIO()):
                clock.now.return_value = NOW
                self.assertEqual(main.run(settings, [PUB], source), 0)
            create.assert_called_once()

    def test_partial_source_outage_does_not_consume_scheduled_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            last = NOW.replace(hour=12).isoformat()
            state = {"episodes": [], "seen": [], "retry": [], "last_run": last, "last_scheduled_run": last}
            def recent(pub):
                if pub["base"] == PUB["base"]:
                    raise RuntimeError("PRIVATE_SOURCE")
                return []
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True), \
                    patch("main.load_state", return_value=state), patch("main.datetime", wraps=datetime) as clock, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                clock.now.return_value = NOW
                self.assertEqual(main.run(settings, [PUB, {**PUB, "base": "https://other.example/feed"}],
                                          types.SimpleNamespace(recent_posts=recent)), 0)
            self.assertEqual(state["last_run"], last)
            self.assertEqual(state["last_scheduled_run"], last)
            self.assertTrue(schedule.scheduled_run_due(state, NOW, settings.runs_per_day))

    def test_rss_catch_up_does_not_truncate_available_entries(self):
        source = substack.Substack("")
        xml = "<rss><channel>" + "".join(
            f"<item><guid>{i}</guid><title>Fictional {i}</title><link>https://fictional.example/{i}</link>"
            "<pubDate>Thu, 08 Oct 2026 12:00:00 GMT</pubDate><description>Fictional text</description></item>"
            for i in range(75)) + "</channel></rss>"
        with patch.object(source, "get", return_value=xml):
            self.assertEqual(len(source.recent_posts(PUB)), 75)
        with patch.object(source, "get", return_value=[]) as get:
            source.recent_posts({**PUB, "rss": False})
            self.assertEqual(get.call_args.kwargs["limit"], 50)


if __name__ == "__main__":
    unittest.main()
