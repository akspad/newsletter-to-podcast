"""Marked recommendation widgets must not absorb citations or editorial reading lists."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview

BODY = ('The researchers compared measurements from several regions and explained the patterns in detail. '
        'Independent teams checked the observations and repeated the experiments before publishing their results.')
WIDGET = ('<div class="around-the-web"><div class="from-your-site__headline">From Your Site Articles</div>'
          '<ul class="around-the-web__list"><li><a href="https://fictional.example/related">Unrelated recommendation</a>'
          '</li></ul></div>')


def read(tail):
    html = '<title>A discovery</title><article><div class="entry-content"><p>'+BODY+'</p>'+tail+'</div></article>'
    with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text('https://fictional.example/story').partition('\n')[2]


class InlineRecommendationTests(unittest.TestCase):
    def test_widget_is_omitted_but_adjacent_editorial_links_and_conclusion_remain(self):
        before = '<p>See the <a href="https://research.example/paper">original research paper</a> for all measurements.</p>'
        self.assertEqual(read(before+WIDGET+'<p>A short conclusion.</p>'),
                         BODY+' See the original research paper for all measurements. A short conclusion.')

    def test_quoted_widgets_and_editorial_lists_are_preserved(self):
        for tail in ('<blockquote>'+WIDGET+'</blockquote>',
                     WIDGET.replace('<div class="from-your-site__headline">From Your Site Articles</div>', ''),
                     WIDGET.replace('</div>', '<p>This editorial note explains why the list is relevant.</p></div>', 1)):
            with self.subTest(tail=tail[:80]):
                self.assertIn('Unrelated recommendation', read(tail))


if __name__ == '__main__':
    unittest.main()
