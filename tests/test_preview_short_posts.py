"""Short permalink posts must survive without absorbing site boilerplate."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview

URL = 'https://fictional.example/notes/a-short-post'
TITLE = 'A short note'
TEXT = ('A new study compares observations made by several teams over twenty years. '
        'The researchers found that the same pattern appeared in different places, '
        'and they plan to investigate what causes it.')
NOISE = ('This site is made possible by member support. Thanks to our hosting company. '
         'Purchases through these links may earn an affiliate commission. Please log in to leave a comment.')


def post(url=URL, body=TEXT):
    return ('<div class="post"><p>'+body+'</p><div class="post-actions">'
            '<a href="'+url+'">Open post</a><a href="'+url+'">Copy link</a>'
            '<label>Share this post</label></div></div>')


def read(body):
    html = '<title>'+TITLE+'</title><meta property="og:site_name" content="Science Notes">'+body
    with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text(URL).partition('\n')[2]


class ShortPostTests(unittest.TestCase):
    def test_short_post_excludes_longer_sibling_footer_and_login_help(self):
        html = post()+'<div id="extras-container"><p>'+NOISE*3+'</p></div>'
        self.assertEqual(read(html), TEXT)
        self.assertIn(TEXT, preview.excerpt(read(html)))

    def test_post_inside_main_excludes_surrounding_boilerplate(self):
        html = '<main><h1>'+TITLE+'</h1>'+post()+'<div><p>'+NOISE*3+'</p></div></main>'
        self.assertEqual(read(html), TEXT)

    def test_permalink_selects_the_right_post_from_a_collection(self):
        other = post('https://fictional.example/notes/other', NOISE*3)
        self.assertEqual(read(other+post()+other), TEXT)

    def test_unrelated_semantic_article_and_nested_recommendation_are_excluded(self):
        recommendation = '<article><h2>A different story</h2><p>'+NOISE*3+'</p></article>'
        self.assertEqual(read(recommendation+post(body=TEXT+recommendation)), TEXT)

    def test_matching_semantic_article_has_priority_over_an_unmarked_teaser(self):
        story = ('<article itemid="'+URL+'"><h1>'+TITLE+'</h1><p>'+TEXT+'</p></article>')
        self.assertEqual(read(story+post(body=NOISE)), TEXT)

    def test_unverified_post_and_quoted_or_hidden_self_links_do_not_displace_article(self):
        story = '<article><h1>'+TITLE+'</h1><p>'+TEXT+'</p></article>'
        for unrelated in (post('https://fictional.example/other', NOISE),
                          '<blockquote>'+post(body=NOISE)+'</blockquote>',
                          '<div hidden>'+post(body=NOISE)+'</div>'):
            with self.subTest(unrelated=unrelated[:70]):
                self.assertEqual(read(story+unrelated), TEXT)

    def test_inline_links_quotes_and_short_followup_paragraphs_survive(self):
        body = TEXT+' <a href="https://research.example/paper">Read the paper.</a>'
        html = post(body=body).replace('</p>', '</p><blockquote><p>A quoted observation.</p></blockquote>'
                                      '<p>A short conclusion.</p>', 1)
        text = read(html)
        for expected in (TEXT, 'Read the paper.', 'A quoted observation.', 'A short conclusion.'):
            self.assertIn(expected, text)
        self.assertNotIn('Share this post', text)

    def test_other_unmarked_post_cannot_supply_the_selected_posts_author(self):
        other = post('https://fictional.example/other', '<span class="byline">Wrong Author</span>'+NOISE)
        html = '<title>'+TITLE+'</title><meta property="og:site_name" content="Science Notes">'+post()+other
        with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
            text = preview.article_text(URL)
        self.assertNotIn('Wrong Author', text)
        self.assertIn(TEXT, text)


if __name__ == '__main__':
    unittest.main()
