"""Attribution and caption cases found in the bounded fresh-article batch."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview

URL = 'https://fictional.example/story'
TEXT = ('The research team compares observations made over several seasons to understand '
        'how animals respond to changing conditions. These measurements will help the scientists '
        'design a larger experiment and test their conclusions in another region.')


def read(head='', body=''):
    html = ('<title>A discovery</title>'+head+'<article><h1>A discovery</h1>'
            '<div class="entry-content">'+body+'<p>'+TEXT+'</p></div></article>')
    with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text(URL)


class FreshAttributionTests(unittest.TestCase):
    def test_open_graph_article_author_credit_is_read(self):
        text = read('<meta property="og:article:author" content="Alex Writer and the Research Board">')
        self.assertIn('By Alex Writer and the Research Board.', text.partition('\n')[0])

    def test_author_profile_name_excludes_its_job_title(self):
        profile = ('<div class="c-article__author"><span class="c-article__author__name">Alex Writer</span>'
                   '<span class="c-article__author__title">Staff Scientist</span></div>')
        text = read(body=profile)
        self.assertIn('By Alex Writer.', text.partition('\n')[0])
        self.assertEqual(text.partition('\n')[2], TEXT)

    def test_hidden_or_other_article_author_profile_is_not_borrowed(self):
        profile = '<span class="c-article__author__name">Wrong Author</span>'
        head = '<div hidden>'+profile+'</div><article class="related-articles">'+profile+'</article>'
        self.assertNotIn('Wrong Author', read(head))

    def test_feed_label_suffix_is_not_part_of_the_spoken_publication(self):
        for suffix in (' ATOM Feed', ' - RSS Feed', ' | Atom', ' — RSS'):
            with self.subTest(suffix=suffix):
                text = read('<link rel="alternate" type="application/atom+xml" title="Science Notes'+suffix+'">')
                self.assertTrue(text.startswith('Science Notes. A discovery.\n'))
        self.assertTrue(read('<link rel="alternate" type="application/atom+xml" title="Animal Feed">').startswith('Animal Feed.'))

    def test_featured_image_caption_is_excluded_while_story_mentions_of_credit_remain(self):
        body = ('<div class="featured-img"><img src="https://fictional.example/image.jpg">'
                '<div class="featured-img__caption">A picture of a forest. Credit: Image Agency.</div></div>'
                '<p>The team gives credit to earlier researchers in its report.</p>')
        text = read(body=body)
        self.assertNotIn('Image Agency', text)
        self.assertIn('The team gives credit to earlier researchers in its report.', text)
        self.assertIn(TEXT, text)


if __name__ == '__main__':
    unittest.main()
