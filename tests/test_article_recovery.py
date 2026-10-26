"""Preserve article prose through cleanup and recover individual archive failures."""
import contextlib
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import preview
import storage
from article_extract import extract_text, extract_structured_text
from substack import Substack, html_to_text

URL = 'https://fictional.example/story'
FIRST = ('The first section explains how a research team collected careful observations across several seasons, '
         'compared their measurements, and documented every change in the natural environment.')
SECOND = ('The second section describes the results of those experiments and explains why the findings matter '
          'for future studies, practical decisions, and the wider scientific community.')


def read(html):
    with patch('substack.Substack.get', return_value=html):
        return preview.article_text(URL)


class CleanupRecoveryTests(unittest.TestCase):
    def test_direct_author_or_tag_labels_never_delete_article_or_main(self):
        for container in ('article', 'main', 'div class="entry-content"'):
            tag = container.split()[0]
            for labels in ('<h2>Written by</h2><p><a rel="author">Alice Writer</a></p>',
                           '<h2>Tags</h2><div class="post-tags"><a>Science</a></div>'):
                html = '<title>A discovery</title><'+container+'><h1>A discovery</h1>'+labels+'<p>'+FIRST+'</p></'+tag+'>'
                with self.subTest(container=container, labels=labels):
                    result = read(html)
                    self.assertEqual(result.partition('\n')[2], FIRST)
                    self.assertNotIn('Written by', result)
                    self.assertNotIn('Tags', result)

    def test_unmarked_wrapper_with_readable_prose_survives_author_cleanup(self):
        html = '<div><h2>Written by</h2><p><a rel="author">Alice Writer</a></p><p>'+FIRST+'</p></div>'
        self.assertEqual(extract_structured_text(html, author='Alice Writer'), FIRST)
        self.assertEqual(extract_text(BeautifulSoup('<article>'+html+'</article>', 'html.parser'), author='Alice Writer'), FIRST)

    def test_quoted_author_heading_and_non_metadata_tags_discussion_remain(self):
        html = ('<div class="entry-content"><blockquote><h2>Written by</h2><p>A quoted credit.</p></blockquote>'
                '<h2>Tags</h2><p>'+FIRST+'</p><div class="post-tags"><a>Science</a></div></div>')
        self.assertEqual(extract_text(BeautifulSoup(html, 'html.parser')), 'Written by A quoted credit. Tags '+FIRST)

    def test_anonymous_author_cards_and_adjacent_tag_labels_are_still_omitted(self):
        html = ('<div class="entry-content"><p>'+FIRST+'</p><div><h2>Written by</h2>'
                '<a class="author">Alice Writer</a><p>Senior Technical Advocate</p></div>'
                '<div><h2>Tags:</h2><ul class="post-tags"><li>Science</li></ul></div></div>')
        self.assertEqual(extract_text(BeautifulSoup(html, 'html.parser')), FIRST)


class StreamedBodyRecoveryTests(unittest.TestCase):
    def test_sections_keep_order_and_later_repetition_without_repeating_layout_copies(self):
        body = ''.join('<div class="PostsPage-postContent"><p>'+value+'</p></div>' for value in (FIRST, FIRST, SECOND, FIRST))
        result = read('<title>A discovery</title><article><h1>A discovery</h1>'+body+'</article>')
        self.assertEqual(result.partition('\n')[2], ' '.join((FIRST, SECOND, FIRST)))

    def test_nested_sections_empty_placeholders_hidden_streams_and_other_articles(self):
        body = ('<div class="PostsPage-postContent"></div><div hidden><div class="PostsPage-postContent">'
                '<div class="PostsPage-postContent"><p>'+FIRST+'</p></div></div>'
                '<div class="PostsPage-postContent"><p>'+SECOND+'</p></div></div>')
        other = '<article><h2>Another story</h2><div class="PostsPage-postContent"><p>Unrelated text.</p></div></article>'
        html = '<title>A discovery</title><main>'+other+'<article><h1>A discovery</h1>'+body+'</article>'+other+'</main>'
        self.assertEqual(read(html).partition('\n')[2], FIRST+' '+SECOND)


class ArchiveDateRecoveryTests(unittest.TestCase):
    def run_archive(self, bad_value, missing=False):
        now = datetime.now(timezone.utc).isoformat()
        posts = [dict(id=i, slug='story-'+str(i), title='Story '+str(i), post_date=now, audience='everyone',
                      canonical_url='https://fictional.example/story-'+str(i)) for i in (1, 2, 3)]
        if missing:
            del posts[1]['post_date']
        else:
            posts[1]['post_date'] = bad_value
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full'}, clear=True):
            settings = config.Settings.from_env()
            source = Substack('')
            spoken = []
            def fetch(url, **kwargs):
                if url.endswith('/archive'):
                    return posts
                post = next(p for p in posts if url.endswith('/'+p['slug']))
                return {**post, 'body_html': '<p>'+FIRST+'</p>'}
            def narrate(text, path, limit, intro):
                spoken.append(intro)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'ID3-provider-fixture')
                return [path]
            pub = {'base': 'https://fictional.example', 'name': 'Science Notes', 'mode': 'full'}
            with patch.object(source, 'get', side_effect=fetch), patch('tts.synthesize_full', side_effect=narrate), \
                    patch('tts.duration', return_value=10), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                result = main.run(settings, [pub], source)
            state = storage.load(settings)
            return result, state, spoken, errors.getvalue()

    def test_invalid_null_and_missing_dates_do_not_block_other_archive_posts(self):
        for value, missing in (('not-a-date', False), (None, False), ('2026-02-30T12:00:00Z', False), (None, True)):
            with self.subTest(value=value, missing=missing):
                result, state, spoken, errors = self.run_archive(value, missing)
                self.assertEqual(result, 0)
                self.assertEqual(len(state['episodes']), 2)
                self.assertTrue(any('Story 1' in intro for intro in spoken))
                self.assertTrue(any('Story 3' in intro for intro in spoken))
                self.assertFalse(any('Story 2' in intro for intro in spoken))
                self.assertEqual(state['retry'], [])
                self.assertNotIn('All sources unavailable', errors)
                self.assertNotIn('not-a-date', errors)

    def test_invalid_retry_dates_are_omitted_and_iso_offsets_still_pass(self):
        pub = {'base': 'https://fictional.example', 'name': 'Science Notes'}
        entries = [dict(pub=pub, post=dict(id=i, title='Story', post_date=value)) for i, value in enumerate(
            ('not-a-date', None, '2026-10-24T12:00:00Z', '2026-10-24T14:00:00+02:00', '2026-10-24T12:00:00'))]
        with contextlib.redirect_stderr(io.StringIO()):
            retained = main.bounded_retries(entries)
        self.assertEqual([row['post']['id'] for row in retained], [2, 3, 4])


class FootnoteRecoveryTests(unittest.TestCase):
    def test_navigation_is_removed_but_citations_math_and_ordinary_links_remain(self):
        body = ('<p>Measurements<sup><a href="#fn:1" role="doc-noteref">1</a></sup> support x<sup>2</sup>'
                ' and H<sub>2</sub>O. Read the <a href="#methods">methods</a>.</p><ol><li id="fn:1">'
                'An original research citation.<a class="footnote-return" href="#fnref:1"><sup>[return]</sup></a>'
                '<a role="doc-backlink" href="#fnref:1">Back</a></li></ol>')
        expected = 'Measurements support x2 and H2O. Read the methods. An original research citation.'
        self.assertEqual(extract_structured_text(body), expected)
        self.assertEqual(' '.join(html_to_text(body).split()), expected)

    def test_full_episode_narration_and_notes_exclude_return_links(self):
        body = '<p>'+FIRST+'</p><ol><li>A research citation.<a class="footnote-return" href="#fnref:1">[return]</a></li></ol>'
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full'}, clear=True):
            settings = config.Settings.from_env()
            pub = {'base': 'https://fictional.example/feed.xml', 'rss': True, 'name': 'Science Notes', 'mode': 'full'}
            post = {'id': 1, 'slug': 'story', 'title': 'A discovery', 'body_html': body, 'canonical_url': URL}
            spoken = []
            def narrate(text, path, limit, intro):
                spoken.append(text)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'ID3-provider-fixture')
                return [path]
            state = {'episodes': []}
            with patch('tts.synthesize_full', side_effect=narrate), patch('tts.duration', return_value=10), \
                    contextlib.redirect_stdout(io.StringIO()):
                main.make_episode(Substack(''), pub, post, datetime.now(timezone.utc), state, settings)
            self.assertNotIn('[return]', spoken[0])
            self.assertIn('A research citation.', spoken[0])
            self.assertEqual(state['episodes'][0]['description'], spoken[0])


if __name__ == '__main__':
    unittest.main()
