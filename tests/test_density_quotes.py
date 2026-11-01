"""Density fallback keeps editorial quotations without rescuing link widgets."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview

BODY = ('The research team compared careful observations from several regions and explained how the measurements fit together. '
        'Independent reviewers checked the records and repeated the experiments before publishing their conclusions.')
TAIL = 'Following the investigation, the team reviewed all records and explained why the evidence supports their findings.'
URL = 'https://fictional.example/story'


def read(content):
    html = ('<title>A discovery</title><meta name="author" content="Correct Writer">'
            '<meta property="og:site_name" content="Research Notes">' + content)
    with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text(URL)


class DensityQuoteTests(unittest.TestCase):
    def test_short_linked_quotes_keep_source_order_and_inline_spelling(self):
        cases = (
            ('<a href="https://research.example/paper">A useful quoted observation.</a>', 'A useful quoted observation.'),
            ('inter<a href="https://research.example/paper">operable</a> systems', 'interoperable systems'),
            ('<a href="/one">Careful</a> <a href="/two">observations</a>.', 'Careful observations.'),
        )
        for quote, expected in cases:
            for position in (0, 1, 2):
                with self.subTest(quote=expected, position=position):
                    blocks = ['<p>' + BODY + '</p>', '<p>' + TAIL + '</p>']
                    blocks.insert(position, '<blockquote><p>' + quote + '</p></blockquote>')
                    values = [BODY, TAIL]
                    values.insert(position, expected)
                    text = read('<article><h1>A discovery</h1>' + ''.join(blocks) + '</article>')
                    self.assertEqual(text.partition('\n')[2], ' '.join(values))

    def test_quoted_attribution_survives_without_an_explicit_body_class(self):
        for name in ('Quoted Writer', 'Correct Writer'):
            text = read('<article><h1>A discovery</h1><p>' + BODY + '</p>'
                        '<blockquote><p class="byline">By <a rel="author" href="/author/quoted">' + name +
                        '</a></p></blockquote><p>' + TAIL + '</p></article>')
            self.assertEqual(text.partition('\n')[0], 'Research Notes. A discovery. By Correct Writer.')
            self.assertEqual(text.partition('\n')[2], BODY + ' By ' + name + ' ' + TAIL)

    def test_nested_and_repeated_quotes_keep_every_occurrence(self):
        quote = '<blockquote><p><a href="/paper">A repeated observation.</a></p></blockquote>'
        text = read('<article><p>' + BODY + '</p><blockquote><p>A witness explained:</p>' + quote +
                    '<p>Then the discussion continued.</p></blockquote><p>' + TAIL + '</p>' + quote + '</article>')
        self.assertEqual(text.partition('\n')[2], BODY + ' A witness explained: A repeated observation. '
                         'Then the discussion continued. ' + TAIL + ' A repeated observation.')

    def test_recommendations_navigation_and_footers_remain_excluded(self):
        noise = '<blockquote><p><a href="/other">Unrelated recommendation.</a></p></blockquote>'
        widgets = ('<nav>' + noise + '</nav><aside>' + noise + '</aside>'
                   '<div class="recommendations">' + noise + '</div>'
                   '<div id="single-article-footer">' + noise + '</div><footer>' + noise + '</footer>'
                   '<div hidden>' + noise + '</div>')
        text = read('<article><p>' + BODY + '</p>' + widgets + '<blockquote><p>'
                    '<a href="/paper">A useful quoted observation.</a></p></blockquote><p>' + TAIL + '</p></article>')
        self.assertEqual(text.partition('\n')[2], BODY + ' A useful quoted observation. ' + TAIL)

    def test_link_dense_unmarked_recommendations_are_not_rescued(self):
        cards = '<div>' + ''.join('<p><a href="/other' + str(i) + '">Another linked recommendation.</a></p>'
                                 for i in range(6)) + '</div>'
        text = read('<article><p>' + BODY + '</p>' + cards + '<blockquote><p>'
                    '<a href="/paper">A useful quoted observation.</a></p></blockquote><p>' + TAIL + '</p></article>')
        self.assertEqual(text.partition('\n')[2], BODY + ' A useful quoted observation. ' + TAIL)

    def test_quotes_in_unrelated_articles_do_not_enter_requested_story(self):
        other = ('<article><h1>Other story</h1><blockquote><p><a href="/other">'
                 'An unrelated quotation.</a></p></blockquote><p>' + BODY * 3 + '</p></article>')
        text = read(other + '<article><h1>A discovery</h1><p>' + BODY + '</p><blockquote><p>'
                    '<a href="/paper">A useful quoted observation.</a></p></blockquote></article>')
        self.assertEqual(text.partition('\n')[2], BODY + ' A useful quoted observation.')


if __name__ == '__main__':
    unittest.main()
