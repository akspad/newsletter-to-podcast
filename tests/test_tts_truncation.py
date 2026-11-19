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
    def run_speech(self, text, durations, rate="+0%", boundaries=None):
        class Communicate:
            def __init__(self, *args, **kwargs):
                pass

            async def stream(self):
                for boundary in boundaries if boundaries is not None else [text]:
                    yield {"type": "SentenceBoundary", "text": boundary, "offset": 0, "duration": 5_000_000}
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

    def test_missing_boundaries_never_accept_audio_by_length_alone(self):
        self.assertEqual(self.run_speech("A fictional sentence.", [], boundaries=[]), (False, False, 0))

    def test_complete_boundaries_tolerate_unicode_punctuation_and_sentence_segmentation(self):
        text = "Café & tea. 台灣的花。 A/B costs $12.50. 🌱"
        boundaries = ["CAFE\u0301 and tea", "台灣的花", "A / B costs 12,50"]
        self.assertEqual(self.run_speech(text.replace("&", "and"), [4], boundaries=boundaries), (True, True, 1))
        self.assertEqual(self.run_speech(text, [4], boundaries=["CAFE\u0301 tea", *boundaries[1:]]), (True, True, 1))

    def test_missing_middle_is_rejected_even_if_final_sentence_is_reported(self):
        text = "The trays arrived. Two were damaged. The lab kept the labels."
        self.assertEqual(self.run_speech(text, [], boundaries=["The trays arrived.", "The lab kept the labels."]),
                         (False, False, 0))

    def test_unrecoverable_short_passage_raises_for_pipeline_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch("tts.speak", return_value=False):
            with self.assertRaises(RuntimeError):
                tts.speak_pieces("A fictional passage.", Path(directory), "clip")


if __name__ == "__main__":
    unittest.main()
