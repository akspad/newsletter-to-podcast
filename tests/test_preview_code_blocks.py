"""Density fallback must keep article code figures in narration order."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview
from article_extract import extract_structured_text

URL = 'https://fictional.example/story'
OPENING = ('This article compares two ways to work with a shared project. '
           'Consider the following commands before reading the explanation.')
ENDING = ('The first command copies the current history from a remote project, while the second creates '
          'a local branch from that history. Comparing their arguments helps explain how names are resolved.')
COMMANDS = '$ git fetch origin main $ git switch -c my-feature origin/main'
FIGURE = ('<figure class="code-block"><pre><code><span class="line"><span class="prompt">$</span> '
          'git fetch origin main</span>\n<span class="line">$ git switch -c my-feature origin/main</span>'
          '</code></pre><figcaption>Code example caption.</figcaption><button>Copy code</button></figure>')


def read(body):
    html = '<title>A useful article</title>'+body
    with patch('substack.Substack.get', return_value=html) as get, contextlib.redirect_stderr(io.StringIO()):
        text = preview.article_text(URL)
    get.assert_called_once()  # No scripts, images or extra resources are fetched.
    return text.partition('\n')[2]


class PreviewCodeBlockTests(unittest.TestCase):
    def test_syntax_highlighted_code_appears_between_prose_and_in_the_opening_excerpt(self):
        body = read('<article><h1>A useful article</h1><p>'+OPENING+'</p>'+FIGURE+'<p>'+ENDING+'</p></article>')
        self.assertEqual(body, OPENING+' '+COMMANDS+' '+ENDING)
        self.assertIn(COMMANDS, preview.excerpt(body))
        self.assertNotIn('Code example caption', body)
        self.assertNotIn('Copy code', body)

    def test_unmarked_and_main_layouts_preserve_short_code_figures(self):
        for wrapper in ('main', 'div'):
            html = ('<'+wrapper+'><h1>A useful article</h1><p>'+OPENING+'</p>'
                    '<figure><pre><code>git status</code></pre></figure><p>'+ENDING+'</p></'+wrapper+'>')
            with self.subTest(wrapper=wrapper):
                self.assertEqual(read(html), OPENING+' git status '+ENDING)

    def test_multiple_code_blocks_and_intentional_repetition_stay_in_order(self):
        block = '<figure><pre><code>git status</code></pre></figure>'
        middle = 'Make a local change, then check the status again.'
        html = ('<article><h1>A useful article</h1><p>'+OPENING+'</p>'+block+
                '<p>'+middle+'</p>'+block+'<p>'+ENDING+'</p></article>')
        self.assertEqual(read(html), OPENING+' git status '+middle+' git status '+ENDING)

    def test_sidebar_recommendation_and_hidden_code_are_still_excluded(self):
        noise = '<figure><pre><code>unrelated private draft command</code></pre></figure>'
        html = ('<aside><article>'+noise+'</article></aside><main><article><h1>A useful article</h1>'
                '<p>'+OPENING+'</p>'+FIGURE+'<div hidden>'+noise+'</div><p>'+ENDING+'</p></article>'
                '<article class="related-posts">'+noise+'</article></main>')
        self.assertEqual(read(html), OPENING+' '+COMMANDS+' '+ENDING)

    def test_image_figures_and_captions_stay_excluded_beside_code(self):
        html = ('<article><h1>A useful article</h1><p>'+OPENING+'</p><figure>'
                '<img src="https://fictional.example/image.png" alt="An image">'
                '<figcaption>Image caption and photographer credit.</figcaption></figure>'+FIGURE+
                '<p>'+ENDING+'</p></article>')
        self.assertEqual(read(html), OPENING+' '+COMMANDS+' '+ENDING)

    def test_explicit_body_and_structured_body_already_preserve_the_same_code(self):
        html = '<div class="entry-content"><p>'+OPENING+'</p>'+FIGURE+'<p>'+ENDING+'</p></div>'
        expected = OPENING+' '+COMMANDS+' '+ENDING
        self.assertEqual(read(html), expected)
        self.assertEqual(extract_structured_text(html), expected)


if __name__ == '__main__':
    unittest.main()
