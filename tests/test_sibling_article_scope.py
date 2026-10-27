"""A separate headline hero must not replace the matching article body."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview
from substack import html_to_text, page_body, page_date

URL = 'https://fictional.example/story'
TITLE = 'A discovery about bats'
DECK = ('An overview introduces the latest discoveries about bats and explains why researchers '
        'are interested in how these animals use sound to navigate in the dark.')
FIRST = ('Researchers recorded the sounds of bats as they flew through a forest. '
         'They compared the recordings with careful measurements of each animal to understand '
         'how it avoided obstacles and found its food.')
LAST = 'The team plans to repeat the experiment in another forest next year.'
OTHER = 'An unrelated recommendation discusses a completely different subject.'
HEAD = ('<title>'+TITLE+'</title><meta property="og:site_name" content="Science Notes">')


def read(html):
    with patch('substack.Substack.get', return_value=HEAD+html) as get, \
            contextlib.redirect_stderr(io.StringIO()):
        text = preview.article_text(URL)
    get.assert_called_once()
    return text


def story(*, attributes='', body_class=''):
    return ('<article '+attributes+'><header><h1>'+TITLE+'</h1>'
            '<p class="byline">Alex Writer</p><time datetime="2026-10-25">October 25, 2026</time></header>'
            '<div class="'+body_class+'"><p>'+FIRST+'</p><p>'+LAST+'</p></div></article>')


class SiblingArticleTests(unittest.TestCase):
    def test_short_sibling_hero_never_replaces_matching_article(self):
        for tag in ('main', 'div role="main"'):
            close = tag.split()[0]
            hero = '<'+tag+'><h1>'+TITLE+'</h1><p>'+DECK+'</p></'+close+'>'
            for body_class in ('', 'entry-content'):
                article = story(body_class=body_class)
                for layout in (hero+article, article+hero):
                    with self.subTest(tag=tag, body_class=body_class, hero_first=layout.startswith(hero)):
                        text = read(layout)
                        self.assertEqual(text.partition('\n')[0], 'Science Notes. '+TITLE+'. By Alex Writer.')
                        self.assertEqual(text.partition('\n')[2], FIRST+' '+LAST)
                        self.assertIn(FIRST, preview.excerpt(text))
                        self.assertNotIn(DECK, text)

    def test_explicit_hero_body_does_not_override_a_longer_matching_article(self):
        hero = '<main><h1>'+TITLE+'</h1><div class="entry-content"><p>'+DECK+'</p></div></main>'
        self.assertEqual(read(hero+story()).partition('\n')[2], FIRST+' '+LAST)

    def test_listing_body_and_publication_date_use_the_same_article(self):
        hero = '<main><h1>'+TITLE+'</h1><time datetime="2026-10-27">October 27, 2026</time><p>'+DECK+'</p></main>'
        soup = BeautifulSoup(HEAD+hero+story(body_class='entry-content'), 'html.parser')
        body = html_to_text(page_body(soup, TITLE, URL))
        self.assertIn(FIRST+'\n'+LAST, body)
        self.assertNotIn(DECK, body)
        self.assertEqual(page_date(soup, TITLE, URL).isoformat(), '2026-10-25T00:00:00+00:00')

    def test_long_unrelated_article_does_not_displace_unwrapped_main_story(self):
        main = '<main><h1>'+TITLE+'</h1><p>'+FIRST+'</p><p>'+LAST+'</p></main>'
        other = '<article><h1>Another story</h1><p>'+(OTHER+' ')*20+'</p></article>'
        text = read(main+other)
        self.assertEqual(text.partition('\n')[2], FIRST+' '+LAST)
        self.assertNotIn(OTHER, text)

    def test_permalink_identity_keeps_priority_over_another_articles_headline(self):
        main = '<main data-url="'+URL+'"><h1>'+TITLE+'</h1><p>'+FIRST+'</p><p>'+LAST+'</p></main>'
        other = '<article><h1>'+TITLE+'</h1><p>'+(OTHER+' ')*20+'</p></article>'
        self.assertEqual(read(main+other).partition('\n')[2], FIRST+' '+LAST)

    def test_nested_semantic_article_and_its_body_survive(self):
        self.assertEqual(read('<main><h1>'+TITLE+'</h1><p>'+DECK+'</p>'+story()+'</main>').partition('\n')[2],
                         FIRST+' '+LAST)


if __name__ == '__main__':
    unittest.main()
