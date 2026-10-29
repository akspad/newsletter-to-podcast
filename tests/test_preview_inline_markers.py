"""Empty diagram markers must not discard subsequent prose in density extraction."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview

URL = 'https://fictional.example/story'
START = 'The researchers compared measurements from several regions and marked each region with a dashed box'
TAIL = 'on the map. For an observer standing beside the road, the surrounding air appears still, while the vehicle is moving.'
TEXT = START+' '+TAIL


def read(html):
    with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text(URL)


class InlineMarkerTests(unittest.TestCase):
    def test_empty_diagram_spans_preserve_all_following_prose(self):
        for marker in ('<span class="dashed_box"></span>', '<span><span></span></span>'):
            for wrapper in ('article', 'div class="entry-content"'):
                with self.subTest(marker=marker, wrapper=wrapper):
                    body = '<p>'+START+marker+' '+TAIL+'</p>'
                    text = read('<title>A discovery</title><'+wrapper+'>'+body+'</'+wrapper.split()[0]+'>')
                    self.assertEqual(text.partition('\n')[2], TEXT)

    def test_hidden_labels_remain_excluded_while_visible_tails_survive(self):
        body = ('<article><p>'+START+'<span></span> on the map. '
                '<span hidden>Hidden draft label.</span><span aria-hidden="true">Control label.</span>'
                '<strong>Important:</strong> '+TAIL+'</p></article>')
        text = read('<title>A discovery</title>'+body)
        self.assertIn('on the map. Important: '+TAIL, text)
        self.assertNotIn('Hidden draft', text)
        self.assertNotIn('Control label', text)

    def test_visible_post_heading_wins_over_legacy_document_title(self):
        html = ('<title> » A discovery Science Notes</title><meta property="og:site_name" content="Science Notes">'
                '<aside><h1 class="post-title">Unrelated recommendation</h1></aside>'
                '<div class="post"><header><h1 class="post-title">A discovery</h1></header>'
                '<div class="entry-content"><p>'+TEXT+'</p></div></div>')
        text = read(html)
        self.assertEqual(text.partition('\n')[0], 'Science Notes. A discovery.')
        self.assertEqual(text.partition('\n')[2], TEXT)


if __name__ == '__main__':
    unittest.main()
