"""Opening excerpts should reach prose instead of reading a navigation index."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview
from article_extract import extract_structured_text

URL = 'https://fictional.example/story'
TITLE = 'How a writing workshop works'
FIRST = ('Writers learn from reading one another\u2019s stories and explaining how those stories could improve. '
         'Each participant looks for an argument that is unclear or a scene that needs more detail. '
         'This process helps the whole group develop better judgment about their own work.')
LAST = 'The next meeting gives everyone an opportunity to try these ideas again.'
BODY = '<h2 id="story">The workshop</h2><p>'+FIRST+'</p><h2 id="next">Next steps</h2><p>'+LAST+'</p>'
LABEL = 'A navigation description of the section and the other material available on this page. '


def contents(prefix=URL):
    return ('<h1 class="toch1">Today\u2019s links</h1><ul class="toc">'
            '<li><a href="'+prefix+'#story">Workshop index entry</a>: '+LABEL*4+'</li>'
            '<li><a href="'+prefix+'#next">Next meeting index entry</a>: '+LABEL*4+'</li></ul>')


def read(body):
    html = ('<title>'+TITLE+'</title><meta property="og:site_name" content="Writing Notes">'
            '<meta name="author" content="Alex Writer">'+body)
    with patch('substack.Substack.get', return_value=html) as get, contextlib.redirect_stderr(io.StringIO()):
        text = preview.article_text(URL)
    get.assert_called_once()
    return text


class ContentsTests(unittest.TestCase):
    def test_absolute_same_article_contents_do_not_fill_the_preview(self):
        text = read('<article><h1>'+TITLE+'</h1><div class="entry-content">'+contents()+BODY+'</div></article>')
        self.assertIn(FIRST, preview.excerpt(text))
        self.assertNotIn('Workshop index entry', text)
        self.assertNotIn('Today\u2019s links', text)
        self.assertIn('The workshop '+FIRST+' Next steps '+LAST, text)
        self.assertEqual(text.partition('\n')[0], 'Writing Notes. '+TITLE+'. By Alex Writer.')

    def test_fragment_relative_and_tracking_links_work_across_body_layouts(self):
        for prefix in ('', '/story', URL+'?utm_source=feed'):
            for wrapper in ('div class="entry-content"', 'article', 'div class="PostsPage-postContent"'):
                with self.subTest(prefix=prefix, wrapper=wrapper):
                    text = read('<'+wrapper+'>'+contents(prefix)+BODY+'</'+wrapper.split()[0]+'>')
                    self.assertIn(FIRST, preview.excerpt(text))
                    self.assertNotIn('Workshop index entry', text)

    def test_nested_contents_and_named_encoded_targets_preserve_later_sections(self):
        body = ('<h2>Table of contents:</h2><div id="table-of-contents"><ol>'
                '<li><a href="#first%20section">First index label</a><ul><li>'
                '<a href="#next">Second index label</a></li></ul></li></ol></div>'
                '<a name="first section"></a><p>'+FIRST+'</p><h2 id="next">Next steps</h2><p>'+LAST+'</p>')
        text = read('<div class="entry-content">'+body+'</div>')
        self.assertNotIn('index label', text)
        self.assertNotIn('Table of contents', text)
        self.assertIn(FIRST+' Next steps '+LAST, text)

    def test_json_ld_fallback_uses_the_same_navigation_cleanup(self):
        schema = {'@type': 'Article', 'url': URL, 'headline': TITLE, 'articleBody': contents()+BODY}
        text = read('<script type="application/ld+json">'+json.dumps(schema)+'</script>')
        self.assertIn(FIRST, preview.excerpt(text))
        self.assertNotIn('Workshop index entry', text)

    def test_structured_fragment_contents_do_not_require_a_page_url(self):
        text = extract_structured_text(contents('')+BODY)
        self.assertEqual(text, 'The workshop '+FIRST+' Next steps '+LAST)

    def test_ordinary_lists_inline_cross_references_and_external_reading_lists_survive(self):
        lists = ('<ul><li>A useful list item.</li><li><a href="#next">Read the next section</a></li></ul>'
                 '<p>Compare the <a href="#next">next steps</a> with this argument.</p>'
                 '<h2>Table of contents</h2><ul class="toc"><li>'
                 '<a href="https://other.example/story#next">An external reading recommendation</a></li></ul>')
        text = read('<div class="entry-content"><p>'+FIRST+'</p>'+lists+BODY+'</div>')
        for phrase in ('A useful list item.', 'Read the next section', 'Compare the next steps',
                       'Table of contents', 'An external reading recommendation'):
            self.assertIn(phrase, text)

    def test_contents_class_cannot_delete_a_wrapper_containing_the_actual_article(self):
        body = '<div class="toc"><a href="#story">Jump to the workshop</a>'+BODY+'</div>'
        text = read('<div class="entry-content">'+body+'</div>')
        self.assertIn(FIRST, text)
        self.assertIn(LAST, text)

    def test_quoted_indices_and_unresolved_or_malformed_links_are_preserved(self):
        for html, expected in (
                ('<blockquote>'+contents('')+'</blockquote>'+BODY, 'Workshop index entry'),
                ('<h2>Contents</h2><ul class="toc"><li><a href="#missing">Missing target label</a></li></ul>'+BODY,
                 'Missing target label'),
                ('<ul class="toc"><li><a href="https://[invalid#next">Malformed link label</a></li></ul>'+BODY,
                 'Malformed link label'),
                ('<h1 class="toch1">A real section heading</h1>'+BODY, 'A real section heading')):
            with self.subTest(expected=expected):
                self.assertIn(expected, read('<div class="entry-content">'+html+'</div>'))


if __name__ == '__main__':
    unittest.main()
