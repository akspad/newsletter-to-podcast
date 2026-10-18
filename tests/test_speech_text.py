"""Invisible source formatting must not fragment words sent to the speech service."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import checkpoints
import tts


class SpeechTextTests(unittest.TestCase):
    def test_obfuscated_english_words_are_rejoined_without_changing_visible_text(self):
        text = "The a\u200bgents ha\u200dnded over b\u200citcoin and satoshi\u2060s.\u200d Nobody."
        self.assertEqual(tts.speech_text(text), "The agents handed over bitcoin and satoshis. Nobody.")
        self.assertEqual(tts.speech_text("\ufeffA soft\u00adhyphen and a\u200b\u200c\u200d\u2060gent."),
                         "A softhyphen and agent.")

    def test_normal_punctuation_accents_and_meaningful_joiners_survive(self):
        text = "Dr. García paid $1,000—really?\nمی\u200cروم क्\u200dष 👩\u200d💻"
        self.assertEqual(tts.speech_text(text), text)
        self.assertEqual(tts.speech_text(tts.speech_text(text)), text)

    def test_direct_provider_call_gets_clean_words(self):
        received = []

        class Communicate:
            def __init__(self, text, *args, **kwargs):
                received.append(text)

            async def stream(self):
                yield {"type": "audio", "data": b"audio"}

        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(sys.modules, {"edge_tts": types.SimpleNamespace(Communicate=Communicate)}), \
                patch("tts.duration", return_value=2):
            self.assertTrue(tts.speak("The b\u200citcoin a\u200bgents.", Path(tmp) / "clip.mp3"))
        self.assertEqual(received, ["The bitcoin agents."])

    def test_full_narration_cleans_body_and_introduction_before_splitting(self):
        def render(text, path, maximum):
            path.write_text(text)
            return 2

        def join(parts, output, maximum=None):
            output.write_text("\n".join(p.read_text() for p in parts))
            return 4

        with tempfile.TemporaryDirectory() as tmp, \
                patch("tts.synthesize", side_effect=render), patch("tts.join_audio", side_effect=join):
            outputs = tts.synthesize_full("The b\u200citcoin a\u200bgents.", Path(tmp) / "a.mp3", None,
                                          "News\u2060letter. By Au\u200dthor.")
            self.assertEqual(outputs[0].read_text(), "Newsletter. By Author.\nThe bitcoin agents.")

    def test_summary_script_is_cleaned_before_chunking_and_speech(self):
        def render(text, tmp, name):
            path = tmp / (name + ".mp3")
            path.write_text(text)
            return [path]

        def join(parts, output, maximum=None):
            output.write_text("\n".join(p.read_text() for p in parts))
            return 4

        with tempfile.TemporaryDirectory() as tmp, \
                patch("tts.speak_pieces", side_effect=render), patch("tts.join_audio", side_effect=join), \
                patch("tts.chunks", wraps=tts.chunks) as chunks:
            output = Path(tmp) / "summary.mp3"
            tts.synthesize("The b\u200citcoin a\u200bgents.", output)
            chunks.assert_called_once_with("The bitcoin agents.")
            self.assertEqual(output.read_text(), "The bitcoin agents.")

    def test_corrupted_checkpoint_is_ignored_and_clean_checkpoint_is_reused(self):
        dirty, clean = "The b\u200citcoin a\u200bgents.", "The bitcoin agents."

        def render(text, path):
            path.write_text(text)
            return True

        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {}, clear=True), \
                patch("tts.duration", return_value=2):
            root = Path(tmp)
            with checkpoints.use(root / "state"):
                cache = checkpoints.current()
                cache.put(cache.key(dirty, tts.VOICE, tts.RATE), b"audio:bad pronunciation")
                with patch("tts.speak", side_effect=render) as speech:
                    paths = tts.speak_pieces(dirty, root, "first")
                    speech.assert_called_once_with(clean, paths[0])
                self.assertEqual(paths[0].read_text(), clean)
                with patch("tts.speak") as speech:
                    paths = tts.speak_pieces(dirty, root, "retry")
                    speech.assert_not_called()
                self.assertEqual(paths[0].read_text(), clean)

    def test_invisible_only_input_fails_before_provider_call(self):
        with tempfile.TemporaryDirectory() as tmp, patch("tts.speak") as speech:
            path = Path(tmp) / "a.mp3"
            with self.assertRaises(ValueError):
                tts.synthesize("\u200b\u00ad\ufeff", path)
            with self.assertRaises(ValueError):
                tts.speak_pieces("\u200b\u00ad\ufeff", Path(tmp), "empty")
            speech.assert_not_called()


if __name__ == "__main__":
    unittest.main()
