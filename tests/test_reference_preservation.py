"""Editorial references survive density pruning; verified return links do not speak."""
import contextlib
from datetime import datetime, timezone
from html import escape
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from article_extract import preserve_reference_lists
from article_scope import remove_resolved_footnote_backlinks
from config import Settings
from substack import Substack, html_to_text
import main
import preview

URL = 'https://fictional.example/story'
TITLE = 'What the research showed'
AUTHOR = 'Alex Writer'
FIRST = ('The research team compared measurements taken in different regions and checked the results '
         'against earlier observations. Their work explains why independent measurements matter and '
         'how future studies can build on the evidence.')
LAST = 'The team plans to publish further measurements after the next field season.'
LINKS = ('<ul><li><a href="https://research.example/guide">A practical field guide</a></li>'
         '<li><a href="https://data.example/report">A report on measurement methods</a></li></ul>')
REFERENCES = '<h3>Some references</h3><p>Additional resources used for the research:</p>' + LINKS


def document(body, wrapper='article'):
    return ('<title>' + TITLE + '</title><meta name="author" content="' + AUTHOR + '"><' + wrapper + '>'
            '<header><h1>' + TITLE + '</h1></header>' + body + '</' + wrapper.split()[0] + '>')


def read(body, wrapper='article'):
    with patch('substack.Substack.get', return_value=document(body, wrapper)) as download, \
            contextlib.redirect_stderr(io.StringIO()):
        text = preview.article_text(URL)
    download.assert_called_once()
    return text


def notes(prefix=URL):
    return ('<p>' + FIRST + '<sup class="footnote-reference" id="ref-1"><a href="' + prefix + '#note-1">[1]</a></sup></p>'
            '<section class="footnotes"><ol class="footnotes-list"><li id="note-1"><p>'
            'A retained research citation. <a href="' + prefix + '#ref-1">↩</a></p></li></ol></section>')


class ReferenceListTests(unittest.TestCase):
    def test_terminal_linked_references_follow_the_original_prose(self):
        text = read('<main><p>' + FIRST + '</p><p>' + LAST + '</p>' + REFERENCES + '</main>')
        body = text.partition('\n')[2]
        self.assertIn(FIRST, body)
        self.assertIn(LAST, body)
        self.assertTrue(body.endswith('A practical field guide A report on measurement methods'))
        values = [FIRST, LAST, 'Some references', 'Additional resources used for the research:',
                  'A practical field guide', 'A report on measurement methods']
        positions = [body.index(value) for value in values]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count(TITLE), 1)
        self.assertEqual(text.count(AUTHOR), 1)

    def test_reference_heading_variants_and_ordered_lists_preserve_short_labels(self):
        for heading in ('References', 'REFERENCES:', '<em>Some references</em>'):
            for intro in ('', '<p>Background reading:</p>'):
                body = '<p>' + FIRST + '</p><h3>' + heading + '</h3>' + intro + LINKS.replace('ul>', 'ol>')
                self.assertIn('A practical field guide A report on measurement methods', read(body))

    def test_inline_reference_words_and_intentional_repeated_citations_survive(self):
        links = ('<ul><li><a href="https://research.example/one"><span>Re</span>search <em>guide</em></a></li>'
                 '<li><a href="https://research.example/two">Research guide</a></li></ul>')
        body = read('<p>' + FIRST + '</p><h2>References</h2>' + links).partition('\n')[2]
        self.assertEqual(body.count('Research guide'), 2)
        self.assertNotIn('Re search', body)

    def test_explicit_body_and_imported_feed_references_keep_their_text(self):
        body = '<p>' + FIRST + '</p>' + REFERENCES
        text = read('<div class="entry-content">' + body + '</div>')
        self.assertIn('A practical field guide A report on measurement methods', text)
        imported = html_to_text(body, url=URL)
        self.assertIn('A practical field guide', imported)
        self.assertIn('A report on measurement methods', imported)

    def test_reference_cleanup_does_not_promote_navigation_cards_or_other_articles(self):
        widget = '<h3>References</h3>' + LINKS.replace('A practical field guide', 'Unrelated link card')
        for extra in ('<nav>' + widget + '</nav>', '<aside>' + widget + '</aside>',
                      '<footer>' + widget + '</footer>', '<div class="related-posts">' + widget + '</div>',
                      '<div class="comments">' + widget + '</div>',
                      '<article><h2>Another story</h2>' + widget + '</article>',
                      '<div class="sidebar">' + widget + '</div>'):
            text = read('<p>' + FIRST + '</p>' + REFERENCES + extra)
            self.assertNotIn('Unrelated link card', text)
            self.assertIn('A report on measurement methods', text)

    def test_unscoped_pages_quoted_lists_and_ambiguous_links_are_not_normalized(self):
        variants = (
            '<h3>Related articles</h3>' + LINKS,
            '<blockquote><h3>References</h3>' + LINKS + '</blockquote>',
            '<h3>References</h3>' + LINKS.replace('https://research.example/guide', '#section'),
            '<h3>References</h3>' + LINKS.replace('https://research.example/guide', URL + '#section'),
            '<h3>References</h3>' + LINKS.replace('https://research.example/guide', 'javascript:void(0)'),
            '<h3>References</h3>' + LINKS.replace('https://research.example/guide', 'http://[broken'),
            '<h3>References</h3>' + LINKS.replace('<li>', '<li><img src="/thumbnail.jpg">', 1),
        )
        for markup in variants:
            soup = BeautifulSoup('<article><p>' + FIRST + '</p>' + markup + '</article>', 'html.parser')
            before = str(soup)
            preserve_reference_lists(soup.article, URL)
            self.assertEqual(str(soup), before)
        soup = BeautifulSoup('<p>' + FIRST + '</p><h3>References</h3>' + LINKS, 'html.parser')
        before = str(soup)
        preserve_reference_lists(soup, URL)
        self.assertEqual(str(soup), before)


class ResolvedBacklinkTests(unittest.TestCase):
    def test_absolute_relative_and_fragment_returns_are_removed_from_both_paths(self):
        for prefix in (URL, '/story', '', URL + '?utm_source=feed'):
            body = notes(prefix)
            preview_text = read(body)
            imported = html_to_text(body, url=URL)
            for text in (preview_text, imported):
                self.assertNotIn('↩', text)
                self.assertIn('A retained research citation.', text)
                self.assertIn('[1]', text)

    def test_semantic_endnote_roles_and_encoded_reference_ids_work(self):
        body = ('<p>' + FIRST + '<a id="ref 1" role="doc-noteref" href="#note-1">1</a></p>'
                '<div id="note-1" role="doc-endnote"><p>A retained note. '
                '<a href="#ref%201">↩️</a></p></div>')
        soup = BeautifulSoup(body, 'html.parser')
        remove_resolved_footnote_backlinks(soup, URL)
        self.assertNotIn('↩', soup.get_text())
        self.assertIn('A retained note.', soup.get_text())

    def test_external_unresolved_duplicate_or_nonreciprocal_returns_survive(self):
        for body in (
            notes().replace(URL + '#ref-1', 'https://other.example/story#ref-1'),
            notes().replace(URL + '#ref-1', URL + '?edition=other#ref-1'),
            notes().replace(URL + '#ref-1', URL + '#missing'),
            notes().replace(URL + '#ref-1', 'http://[broken'),
            notes().replace(URL + '#note-1', URL + '#other-note'),
            notes().replace('id="ref-1"', 'id="ref-2"'),
            notes() + '<sup class="footnote-reference" id="ref-1"><a href="#note-1">1</a></sup>',
            notes() + '<div id="note-1">Another destination.</div>',
            notes().replace('class="footnotes"', 'class="ordinary-list"'),
            notes().replace('class="footnote-reference"', 'class="ordinary-reference"'),
            notes().replace('id="ref-1"', 'id="ref-1" hidden'),
        ):
            with self.subTest(body=body[-150:]):
                soup = BeautifulSoup(body, 'html.parser')
                remove_resolved_footnote_backlinks(soup, URL)
                self.assertIn('↩', soup.get_text())

    def test_quoted_arrows_and_ordinary_prose_symbols_survive(self):
        for wrapper in ('blockquote', 'pre', 'code'):
            soup = BeautifulSoup('<' + wrapper + '>' + notes() + '</' + wrapper + '>', 'html.parser')
            remove_resolved_footnote_backlinks(soup, URL)
            self.assertIn('↩', soup.get_text())
        body = '<p>' + FIRST + ' Use ↩ to return. <a href="https://other.example/">↩</a></p>'
        self.assertEqual(html_to_text(body, url=URL).count('↩'), 2)

    def test_reference_in_another_article_does_not_authorize_removal(self):
        body = notes().replace('<section class="footnotes">', '</article><article><section class="footnotes">')
        soup = BeautifulSoup('<article>' + body + '</article>', 'html.parser')
        remove_resolved_footnote_backlinks(soup, URL)
        self.assertIn('↩', soup.get_text())

    def test_links_without_page_identity_are_left_intact(self):
        self.assertIn('↩', html_to_text(notes()))
        self.assertIn('↩', html_to_text(notes('')))

    def test_anonymous_feed_content_and_its_identity_material_are_not_normalized(self):
        body = notes('')
        xml = ('<rss><channel><item><title>' + TITLE + '</title>'
               '<pubDate>Sat, 14 Nov 2026 12:00:00 GMT</pubDate><description>' + escape(body) +
               '</description></item></channel></rss>')
        source = Substack('')
        with patch.object(source, 'get', return_value=xml):
            post = source.recent_posts({'base': 'https://fictional.example/feed', 'rss': True})[0]
        self.assertEqual(post['canonical_url'], '')
        self.assertEqual(post['wordcount'], len(html_to_text(body).split()))
        self.assertEqual(source.post_text({'rss': True}, post)[1], html_to_text(body))
        self.assertIn('↩', source.post_text({'rss': True}, post)[1])

    def test_rss_and_atom_pipeline_inputs_keep_references_without_return_controls(self):
        body = notes() + REFERENCES
        feeds = (
            '<rss><channel><item><guid>fixed-id</guid><title>' + TITLE + '</title><link>' + URL + '</link>'
            '<pubDate>Sat, 14 Nov 2026 12:00:00 GMT</pubDate><description>' + escape(body) + '</description></item></channel></rss>',
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>fixed-id</id><title>' + TITLE + '</title>'
            '<link href="' + URL + '"/><updated>2026-11-14T12:00:00Z</updated><content type="html">' +
            escape(body) + '</content></entry></feed>',
        )
        class StopBeforeProvider(Exception):
            pass
        for feed in feeds:
            source = Substack('')
            publication = {'base': 'https://fictional.example/feed', 'rss': True, 'name': 'Research Notes'}
            with patch.object(source, 'get', return_value=feed):
                post = source.recent_posts(publication)[0]
            _, expected = source.post_text(publication, post)
            self.assertNotIn('↩', expected)
            self.assertIn('A retained research citation.', expected)
            self.assertIn('A practical field guide', expected)
            self.assertEqual(post['body_html'], body)
            self.assertEqual(post['wordcount'], len(expected.split()))
            for mode in ('full', 'summary'):
                with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                        'SITE_DIR': str(Path(tmp) / 'site'), 'STATE_DIR': str(Path(tmp) / 'state')}, clear=True):
                    captured = []
                    def full_entry(text, *args):
                        captured.append(text)
                        raise StopBeforeProvider()
                    def summary_entry(publication, author, title, text, *args):
                        captured.append(text)
                        raise StopBeforeProvider()
                    with patch.object(source, 'get', side_effect=AssertionError('No extra source fetch')), \
                            patch('tts.synthesize_full', side_effect=full_entry), \
                            patch('tts.synthesize', side_effect=AssertionError('No speech')), \
                            patch('summarize.write_script', side_effect=summary_entry):
                        with self.assertRaises(StopBeforeProvider):
                            main.make_episode(source, {**publication, 'mode': mode}, post,
                                              datetime.now(timezone.utc), {'episodes': []}, Settings.from_env())
                    self.assertEqual(captured, [expected])


if __name__ == '__main__':
    unittest.main()
