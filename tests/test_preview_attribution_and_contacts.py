"""Visible author groups and marked press contacts should not corrupt narration."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview

URL = 'https://fictional.example/story'
BODY = ('The research team compared measurements from several regions and explained how each observation supported the conclusion. '
        'Independent reviewers checked the records and repeated the experiments before publishing a detailed account of the results.')


def read(html):
    with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text(URL)


class AttributionAndContactTests(unittest.TestCase):
    def test_visible_author_group_overrides_publishing_account(self):
        schema = {'@type': 'Article', 'url': URL, 'headline': 'A discovery', 'author': {'name': 'Posting Editor'}}
        for authors, expected in (('<a href="/authors/alex/">Alex Writer</a>', 'Alex Writer'),
                                 ('<a href="/authors/alex/">Alex Writer</a> and '
                                  '<a href="/authors/sam/">Sam Poet</a>', 'Alex Writer, Sam Poet')):
            with self.subTest(expected=expected):
                html = ('<title>A discovery</title><meta name="author" content="Posting Editor">'
                        '<script type="application/ld+json">'+json.dumps(schema)+'</script>'
                        '<aside><div class="c-article-author"><a href="/authors/other">Other Writer</a></div></aside>'
                        '<main><h1>A discovery</h1><div class="c-article-author"><span>By</span>'+authors+'</div>'
                        '<div class="entry-content"><p>'+BODY+'</p></div></main>')
                text = read(html)
                self.assertIn('By '+expected+'.', text.partition('\n')[0])
                self.assertNotIn('Posting Editor', text)
                self.assertNotIn('Other Writer', text)
                self.assertEqual(text.partition('\n')[2], BODY)

    def test_standalone_outer_by_label_is_removed_with_author_span(self):
        html = ('<title>A discovery</title><article><h1>A discovery</h1>'
                '<p>By <span class="byline"><a rel="author">Alex Writer</a></span></p>'
                '<p>'+BODY+'</p></article>')
        self.assertEqual(read(html).partition('\n')[2], BODY)

    def test_byline_cleanup_preserves_surrounding_prose_and_quotes(self):
        for paragraph in ('<p>By <a rel="author">Alex Writer</a>, the discovery was described in detail.</p>',
                          '<blockquote><p>By <span class="byline">Alex Writer</span></p></blockquote>'):
            html = '<title>A discovery</title><article><p>'+BODY+'</p>'+paragraph+'</article>'
            text = read(html).partition('\n')[2]
            self.assertIn(BODY, text)
            self.assertIn('By', text)
            if 'described' in paragraph:
                self.assertIn('the discovery was described in detail.', text)

    def test_explicit_release_end_removes_only_contact_tail(self):
        contacts = ('<p>Alex Contact<br>Research office<br>555-0100<br>'
                    '<a href="mailto:press@fictional.example">press@fictional.example</a></p>')
        html = '<title>A discovery</title><article><div class="entry-content"><p>'+BODY+'</p><p>-end-</p>'+contacts+'</div></article>'
        self.assertEqual(read(html).partition('\n')[2], BODY)

    def test_unmarked_contacts_and_end_markers_in_narrative_are_retained(self):
        contact = '<p>Alex Contact<br><a href="mailto:press@fictional.example">press@fictional.example</a></p>'
        for tail, expected in ((contact, 'Alex Contact'),
                ('<p>-end-</p><p>An appendix explains why the researchers used that unusual marker.</p>', 'An appendix'),
                ('<blockquote><p>-end-</p>'+contact+'</blockquote>', 'Alex Contact'),
                ('<p>-end-</p>'+contact+'<p>Further discussion continues here with important new observations.</p>', 'Further discussion')):
            with self.subTest(expected=expected):
                text = read('<title>A discovery</title><article><div class="entry-content"><p>'+BODY+'</p>'+tail+'</div></article>')
                self.assertIn(expected, text)


if __name__ == '__main__':
    unittest.main()
