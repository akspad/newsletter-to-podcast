"""Nonempty provider output must not silently complete a truncated episode."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tts


class TruncationTests(unittest.TestCase):
    def run_speech(self, text, durations, rate="+0%"):
        class Communicate:
            def __init__(self, *args, **kwargs):
                pass

            async def stream(self):
                yield {"type": "audio", "data": b"provider-audio"}

        sdk = types.SimpleNamespace(Communicate=Communicate)
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(sys.modules, {"edge_tts": sdk}), \
                patch.dict("os.environ", {"TTS_RATE": rate}), \
                patch("tts.duration", side_effect=durations) as probe, \
                patch("tts.time.sleep"):
            path = Path(directory) / "speech.mp3"
            success = tts.speak(text, path)
            return success, path.exists(), probe.call_count

    def test_five_seconds_for_long_article_retries_then_recovers(self):
        self.assertEqual(self.run_speech("fictional " * 340, [5, 120]), (True, True, 2))

    def test_persistent_truncation_fails_and_removes_partial_audio(self):
        self.assertEqual(self.run_speech("fictional " * 340, [5, 5, 5]), (False, False, 3))

    def test_short_complete_passage_is_valid(self):
        self.assertEqual(self.run_speech("A short fictional title.", [1]), (True, True, 1))

    def test_rate_adjusts_minimum_duration(self):
        self.assertEqual(self.run_speech("fictional " * 100, [6], "+100%"), (True, True, 1))

    def test_invalid_audio_duration_retries(self):
        for invalid in (0, float("nan"), float("inf"), -1):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.run_speech("A fictional sentence.", [invalid, 2]),
                                 (True, True, 2))

    def test_unrecoverable_short_passage_raises_for_pipeline_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch("tts.speak", return_value=False):
            with self.assertRaises(RuntimeError):
                tts.speak_pieces("A fictional passage.", Path(directory), "clip")


if __name__ == "__main__":
    unittest.main()
