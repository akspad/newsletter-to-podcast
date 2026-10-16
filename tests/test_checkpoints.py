"""Recovery across independent rendering attempts, without publishing partial articles."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import checkpoints
import config
import main
import security
import tts


class CheckpointTests(unittest.TestCase):
    def speech(self, text, path):
        path.write_bytes(text.encode())
        return True

    def test_interrupted_article_reuses_completed_passage_and_stays_out_of_feed(self):
        for interruption in (RuntimeError, KeyboardInterrupt):
            with self.subTest(interruption=interruption), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                    "STATE_DIR": str(Path(tmp) / "state"), "SITE_DIR": str(Path(tmp) / "site"),
                    "EPISODE_MODE": "full"}, clear=True):
                settings = config.Settings.from_env()
                pub = {"base": "https://example.com", "name": "Example"}
                post = {"id": 1, "title": "Article", "slug": "article"}
                source = types.SimpleNamespace(post_text=lambda *args: ({}, "First. Second."))
                state = {"episodes": []}
                def interrupted(text, path):
                    if text == "Second.":
                        raise interruption("throttled or interrupted")
                    return self.speech(text, path)
                def join(paths, output, maximum=None):
                    output.write_bytes(b" ".join(p.read_bytes() for p in paths))
                    return 10
                with patch("tts.article_chunks", return_value=["First.", "Second."]), \
                        patch("tts.duration", return_value=10), patch("tts.join_audio", side_effect=join):
                    with patch("tts.speak", side_effect=interrupted):
                        with self.assertRaises(interruption):
                            main.make_episode(source, pub, post, datetime.now(timezone.utc), state, settings)
                    self.assertEqual(state["episodes"], [])
                    self.assertFalse(list(settings.site.rglob("*.mp3")))
                    with patch("tts.speak", side_effect=self.speech) as speech:
                        main.make_episode(source, pub, post, datetime.now(timezone.utc), state, settings)
                    self.assertEqual([call.args[0] for call in speech.call_args_list],
                                     ["Second.", "Example. Article. By Example."])
                    self.assertEqual(len(state["episodes"]), 1)
                    audio = settings.site / "episodes" / state["episodes"][0]["file"]
                    self.assertIn(b"First. Second.", audio.read_bytes())

    def test_split_recovery_skips_failed_parent_and_finished_child(self):
        text = " ".join(f"Sentence number {i}." for i in range(30))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), \
                patch("tts.duration", return_value=60):
            root = Path(tmp)
            calls = []
            def speech(value, path):
                calls.append(value)
                if value == text:
                    return False
                if len(calls) == 3:
                    raise RuntimeError("throttle")
                return self.speech(value, path)
            with checkpoints.use(root / "state"), patch("tts.speak", side_effect=speech):
                with self.assertRaises(RuntimeError):
                    tts.speak_pieces(text, root, "first")
            with checkpoints.use(root / "state"), patch("tts.speak", side_effect=self.speech) as render:
                paths = tts.speak_pieces(text, root, "retry")
            self.assertEqual(render.call_count, 1)
            self.assertEqual(" ".join(p.read_text() for p in paths), text.strip())

    def test_identity_corruption_encryption_and_bounds(self):
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "STATE_ENCRYPTION_KEY": Fernet.generate_key().decode()}, clear=True):
            cache = checkpoints.Checkpoints(Path(tmp) / "encrypted", True)
            key = cache.key("private article", "voice", "+0%")
            cache.put(key, b"audio:private audio")
            path = next(cache.root.glob("*.enc"))
            self.assertNotIn(b"private", path.read_bytes())
            self.assertEqual(cache.get(key), b"audio:private audio")
            for identity in [("changed", "voice", "+0%"), ("private article", "other", "+0%"),
                             ("private article", "voice", "+10%")]:
                self.assertIsNone(cache.get(cache.key(*identity)))
            path.write_bytes(b"corrupted")
            self.assertIsNone(cache.get(key))
            cache.put(key, b"audio:new")
            with patch("checkpoints.MAX_CACHE_BYTES", 1):
                cache.prune()
            self.assertFalse(list(cache.root.iterdir()))

    def test_invalid_cached_audio_is_regenerated(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            with checkpoints.use(root / "state"):
                cache = checkpoints.current()
                key = cache.key("Text.", tts.VOICE, tts.RATE)
                cache.put(key, b"audio:broken")
                with patch("tts.duration", side_effect=[0, 1]), patch("tts.speak", side_effect=self.speech) as render:
                    paths = tts.speak_pieces("Text.", root, "retry")
                render.assert_called_once()
                self.assertEqual(paths[0].read_text(), "Text.")
                self.assertEqual(cache.get(key), b"audio:Text.")

    def test_reused_audio_still_obeys_article_budget(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), \
                patch("tts.duration", return_value=1), patch("tts.speak", side_effect=self.speech):
            root = Path(tmp)
            with checkpoints.use(root / "state"):
                tts.speak_pieces("Text.", root, "first")
            with checkpoints.use(root / "state"), patch("security.MAX_AUDIO_SECONDS", 0.5):
                with self.assertRaises(security.BudgetExceeded):
                    tts.speak_pieces("Text.", root, "retry")


if __name__ == "__main__":
    unittest.main()
