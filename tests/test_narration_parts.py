"""Speech grouping uses real text; audio encoding is also checked with ffmpeg."""
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import security
import tts


class NarrationPartsTests(unittest.TestCase):
    def fake_audio(self, text, path, maximum):
        self.assertIsNone(maximum, "Full narration must never request truncation")
        path.write_text(json.dumps([text]))
        return self.seconds(text)

    def seconds(self, text):
        if text.startswith("Article title."):
            return 1.0 if "Part" not in text else 2.0
        return len(text.split()) * 0.5

    def join(self, paths, output, maximum=None):
        self.assertIsNone(maximum)
        texts = [text for path in paths for text in json.loads(path.read_text())]
        output.write_text(json.dumps(texts))
        return sum(self.seconds(text) for text in texts)

    def narrate(self, root, body, cap):
        with patch("tts.synthesize", side_effect=self.fake_audio), patch("tts.join_audio", side_effect=self.join):
            return tts.synthesize_full(body, root / "article.mp3", cap, "Article title")

    def test_every_part_has_correct_spoken_title_and_count_and_preserves_sentences(self):
        body = "First sentence is complete. Second sentence is complete. Third sentence is complete. Fourth sentence is complete."
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.narrate(root, body, 6.5)
            self.assertGreater(len(paths), 1)
            passages = []
            for index, path in enumerate(paths, 1):
                texts = json.loads(path.read_text())
                self.assertEqual(texts[0], f"Article title. Part {index} of {len(paths)}.")
                self.assertLessEqual(sum(self.seconds(text) for text in texts), 6.5)
                self.assertTrue(texts[-1].endswith("."))
                passages.extend(texts[1:])
            self.assertEqual(" ".join(passages).split(), body.split())
            self.assertFalse((root / "article.mp3").exists())

    def test_long_sentence_falls_back_to_words_without_omissions_or_repetition(self):
        body = " ".join(f"word{i}" for i in range(35))
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.narrate(Path(tmp), body, 5)
            passages = [text for path in paths for text in json.loads(path.read_text())[1:]]
            self.assertEqual(" ".join(passages).split(), body.split())

    def test_unsplit_and_unlimited_narration_has_title_without_part_number(self):
        for cap in (None, 30):
            with self.subTest(cap=cap), tempfile.TemporaryDirectory() as tmp:
                paths = self.narrate(Path(tmp), "Complete short article.", cap)
                self.assertEqual(len(paths), 1)
                self.assertEqual(json.loads(paths[0].read_text()), ["Article title.", "Complete short article."])

    def test_actual_longer_numbered_headings_replan_with_final_count(self):
        original = self.seconds
        def seconds(text):
            match = re.search(r"Part (\d+) of (\d+)", text)
            if match and int(match[2]) >= 10:
                return 3
            return original(text)
        body = " ".join(f"Sentence number {i}." for i in range(40))
        with patch.object(self, "seconds", side_effect=seconds), tempfile.TemporaryDirectory() as tmp:
            paths = self.narrate(Path(tmp), body, 7)
            self.assertGreaterEqual(len(paths), 10)
            for i, path in enumerate(paths, 1):
                texts = json.loads(path.read_text())
                self.assertEqual(texts[0], f"Article title. Part {i} of {len(paths)}.")
                self.assertLessEqual(sum(seconds(t) for t in texts), 7)
            self.assertEqual(" ".join(t for p in paths for t in json.loads(p.read_text())[1:]).split(), body.split())

    def test_impossible_heading_and_failed_assembly_leave_no_publishable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "spoken title"):
                self.narrate(root, "A sufficiently long article to split.", 1.5)
            self.assertEqual(list(root.glob("*.mp3")), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def fail(paths, output, maximum=None):
                seconds = self.join(paths, output, maximum)
                if "part-002" in output.name:
                    raise RuntimeError("Synthetic encoder failure")
                return seconds
            with patch("tts.synthesize", side_effect=self.fake_audio), patch("tts.join_audio", side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, "encoder failure"):
                    tts.synthesize_full("One complete sentence. Another complete sentence. A final complete sentence.",
                                        root / "article.mp3", 4, "Article title")
            self.assertEqual(list(root.glob("*.mp3")), [])

    def test_limits_apply_before_work_and_across_numbered_outputs(self):
        with tempfile.TemporaryDirectory() as tmp, patch("tts.synthesize") as render:
            for cap in (0, -1, math.inf, math.nan):
                with self.assertRaises(ValueError):
                    tts.synthesize_full("Article.", Path(tmp) / "a.mp3", cap, "Title")
            render.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp, patch("security.MAX_AUDIO_PARTS", 2):
            with self.assertRaises(security.BudgetExceeded):
                self.narrate(Path(tmp), "One sentence. Two sentences. Three sentences. Four sentences.", 4)
            self.assertEqual(list(Path(tmp).glob("*.mp3")), [])
        with tempfile.TemporaryDirectory() as tmp, patch("security.MAX_AUDIO_BYTES", 1):
            with self.assertRaises(security.BudgetExceeded):
                self.narrate(Path(tmp), "One sentence. Two sentences. Three sentences.", 3.5)
            self.assertEqual(list(Path(tmp).glob("*.mp3")), [])

    def test_abbreviations_quotes_and_paragraphs_keep_text_in_order(self):
        text = 'Dr. Smith met Ms. Jones. “Is it ready?” Yes, it is!\nNext paragraph.'
        pieces = [text[a:b].strip() for a, b in zip([0] + tts.text_breaks(text), tts.text_breaks(text) + [len(text)])]
        self.assertEqual(pieces, ['Dr. Smith met Ms. Jones.', '“Is it ready?”', 'Yes, it is!', 'Next paragraph.'])
        with patch("tts.CHUNK_CHARS", 30):
            self.assertEqual(" ".join(tts.article_chunks(text)).split(), text.split())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
    def test_real_encoded_parts_include_headers_and_stay_under_cap(self):
        calls, joined, texts = [], [], {}
        real_join = tts.join_audio
        def speech(text, path, maximum):
            self.assertIsNone(maximum)
            calls.append(text)
            texts[path] = text
            seconds = max(0.3, len(text.split()) * 0.12)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"sine=frequency=440:duration={seconds}", "-ar", "44100",
                            "-ac", "1", "-b:a", "64k", str(path)], check=True)
            return tts.duration(path)
        def join(paths, output, maximum=None):
            result = real_join(paths, output, maximum)
            if "part-" in output.name:
                joined.append([texts[p] for p in paths])
            return result
        body = " ".join(f"This is complete sentence number {i}." for i in range(8))
        with tempfile.TemporaryDirectory() as tmp, patch("tts.synthesize", side_effect=speech), patch("tts.join_audio", side_effect=join):
            paths = tts.synthesize_full(body, Path(tmp) / "article.mp3", 3.5, "Article title")
            self.assertGreater(len(paths), 1)
            self.assertTrue(all(0 < tts.duration(p) <= 3.5 for p in paths))
            for i, group in enumerate(joined, 1):
                self.assertEqual(group[0], f"Article title. Part {i} of {len(paths)}.")
            self.assertEqual(" ".join(t for group in joined for t in group[1:]).split(), body.split())


if __name__ == "__main__":
    unittest.main()
