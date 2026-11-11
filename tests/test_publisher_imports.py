"""Writer credits and publisher widgets must preserve prose in both input paths."""
import contextlib
from datetime import datetime, timezone
from html import escape
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from article_metadata import article_metadata
from substack import Substack, html_to_text
import main
import preview
from config import Settings

NASA = 'https://science.nasa.gov/earth/earth-observatory/testing/'
ARS = 'https://arstechnica.com/ai/2026/11/testing/'
PROSE = ('<p>The researchers compared several measurements across the region and checked the evidence '
         'against earlier observations. Their results show why independent measurements remain essential '
         'to understanding how the landscape changes.</p>')
CREDIT = ('<p class="wp-block-paragraph"><em>NASA Earth Observatory images by Morgan Artist, using data from '
          '</em><a href="https://data.example/"><em>A Research Institute</em></a>'
          '<em>. Story by Alex Writer.</em></p>')
WIDGETS = ('<div class="wp-block-nasa-blocks-secondary-navigation"><nav>Earth Science Navigation</nav></div>'
           '<div class="wp-block-nasa-blocks-file-list hds-featured-file-list"><h2>Downloads</h2>'
           '<a href="/picture.jpg">JPEG (5 MB)</a></div>'
           '<div class="wp-block-nasa-blocks-content-lists"><h2>You may also be interested in:</h2>'
           '<a class="hds-content-item-heading" href="/other">Unrelated recommendation</a></div>'
           '<div class="wp-block-nasa-blocks-topic-cards"><h2>Discover More from NASA Earth Science</h2>'
           '<a class="topic-card" href="/subscribe">Subscribe to a newsletter</a></div>')
MEDIA = ('<div class="wp-block-nasa-blocks-image-before-after"><img-comparison-slider><img src="/first.jpg">'
         '<img src="/second.jpg"></img-comparison-slider><div class="curtain-view-label-wrapper">September 20, 2026</div>'
         '<figcaption>A useful image caption.<div class="hds-credits">NASA Earth Observatory/Morgan Artist</div></figcaption>'
         '<figcaption><div class="hds-credits">NASA Earth Observatory/Morgan Artist</div></figcaption></div>')
NAV = '<p><a href="' + ARS + '">Read full article</a></p><p><a href="' + ARS + '#comments">Comments</a></p>'


def page(body, url=NASA, author='NASA Earth Observatory'):
    schema = {'@type': 'Article', 'url': url, 'headline': 'A discovery', 'author': {'name': author}}
    return ('<title>A discovery</title><script type="application/ld+json">' + json.dumps(schema) +
            '</script><article><h1>A discovery</h1><div class="entry-content">' + body + '</div></article>')


class PublisherCreditTests(unittest.TestCase):
    def test_earth_observatory_story_writer_does_not_erase_other_contributors(self):
        html = page(PROSE + CREDIT)
        self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), NASA)[2], 'Alex Writer')
        with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
            text = preview.article_text(NASA)
        self.assertIn('By Alex Writer.', text.partition('\n')[0])
        for value in ('Morgan Artist', 'A Research Institute', 'Story by Alex Writer.', 'independent measurements'):
            self.assertIn(value, text.partition('\n')[2])

    def test_writer_credit_is_scoped_to_publisher_and_emphasized_editorial_credit(self):
        for body, url in ((PROSE + '<blockquote>' + CREDIT + '</blockquote>', NASA),
                          (PROSE + CREDIT.replace('<p ', '<p hidden '), NASA),
                          (PROSE + CREDIT.replace('<em>', '').replace('</em>', ''), NASA),
                          (PROSE + '<article>' + CREDIT + '</article>', NASA),
                          (PROSE + CREDIT, 'https://science.nasa.gov.example/earth/earth-observatory/testing/'),
                          (PROSE + CREDIT, 'https://science.nasa.gov/other/testing/'),
                          (PROSE + CREDIT + CREDIT.replace('Alex Writer', 'Sam Writer'), NASA)):
            with self.subTest(body=body[:80], url=url):
                self.assertEqual(article_metadata(BeautifulSoup(page(body, url), 'html.parser'), url)[2],
                                 'NASA Earth Observatory')

    def test_explicit_named_authors_and_coauthors_are_not_replaced_by_story_credit(self):
        for author in ('Sam Writer', 'Sam Writer, Alex Writer'):
            self.assertEqual(article_metadata(BeautifulSoup(page(PROSE + CREDIT, author=author), 'html.parser'), NASA)[2], author)

    def test_header_profile_link_overrides_generic_schema_account(self):
        byline = '<header><a href="/author/syndicated/">Alex Writer, partner.example</a></header>'
        html = page(PROSE, ARS, 'Partner Publication').replace('<h1>', byline + '<h1>')
        self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), ARS)[2], 'Alex Writer, partner.example')
        self.assertEqual(article_metadata(BeautifulSoup(html.replace('<header>', '<header hidden>'), 'html.parser'), ARS)[2],
                         'Partner Publication')

    def test_profile_link_in_prose_cannot_become_a_byline(self):
        html = page(PROSE + '<p>See <a href="/author/alex/">Alex Writer</a> for further details.</p>', ARS, 'Partner Publication')
        self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), ARS)[2], 'Partner Publication')

    def test_unrelated_card_header_cannot_override_schema_for_a_main_story(self):
        schema = {'@type': 'Article', 'url': ARS, 'headline': 'A discovery', 'author': {'name': 'Correct Writer'}}
        html = ('<script type="application/ld+json">' + json.dumps(schema) + '</script><main><h1>A discovery</h1>' +
                PROSE + '<article><header><h2>Other article</h2><a href="/author/other/">Other Writer</a>'
                '</header><p>Another story.</p></article></main>')
        self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), ARS)[2], 'Correct Writer')

    def test_hidden_quoted_and_template_header_links_cannot_hide_visible_writer(self):
        link = '<a href="/author/other/">Other Writer</a>'
        for markup in ('<div hidden>' + link + '</div>', '<blockquote>' + link + '</blockquote>',
                       '<template>' + link + '</template>'):
            byline = '<header>' + markup + '<a href="/author/alex/">Alex Writer</a></header>'
            html = page(PROSE, ARS, 'Partner Publication').replace('<h1>', byline + '<h1>')
            self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), ARS)[2], 'Alex Writer')

    def test_single_link_does_not_shorten_an_agreeing_schema_coauthor_list(self):
        schema = {'@type': 'Article', 'url': ARS, 'headline': 'A discovery',
                  'author': [{'name': 'Alex Writer'}, {'name': 'Sam Writer'}]}
        html = ('<script type="application/ld+json">' + json.dumps(schema) + '</script>'
                '<article><header><h1>A discovery</h1><a href="/author/alex/">Alex Writer</a></header>' + PROSE + '</article>')
        self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), ARS)[2], 'Alex Writer, Sam Writer')


class PublisherWidgetTests(unittest.TestCase):
    def test_nasa_widgets_leave_prose_references_captions_and_contributor_credit(self):
        body = PROSE + CREDIT + MEDIA + WIDGETS + '<p>Reference: Research paper DOI 10.0000/example.</p>'
        text = html_to_text(body, url=NASA)
        for value in ('independent measurements', 'A useful image caption.', 'Morgan Artist', 'Alex Writer', 'DOI 10.0000/example'):
            self.assertIn(value, text)
        for value in ('NASA Earth Observatory/Morgan Artist', 'September 20, 2026', 'Downloads', 'JPEG',
                      'Unrelated recommendation', 'Subscribe to a newsletter', 'Earth Science Navigation'):
            self.assertNotIn(value, text)

    def test_image_contributor_remains_once_without_a_separate_credit(self):
        text = html_to_text(PROSE + MEDIA, url=NASA)
        self.assertEqual(text.count('NASA Earth Observatory/Morgan Artist'), 1)
        self.assertIn('A useful image caption.', text)
        different = MEDIA.replace('NASA Earth Observatory/Morgan Artist', 'NASA Earth Observatory/Other Artist')
        self.assertIn('Other Artist', html_to_text(PROSE + CREDIT + different, url=NASA))

    def test_quoted_credit_inside_a_comparison_caption_is_not_pruned(self):
        quoted = MEDIA.replace('A useful image caption.', '<blockquote><div class="hds-credits">NASA Earth Observatory/Morgan Artist</div></blockquote>')
        self.assertIn('NASA Earth Observatory/Morgan Artist', html_to_text(PROSE + CREDIT + quoted, url=NASA))

    def test_quotes_normal_dates_incomplete_widgets_and_other_publishers_survive(self):
        for markup, url in (('<blockquote>' + WIDGETS + MEDIA + '</blockquote>', NASA),
                            ('<figcaption>' + WIDGETS + MEDIA + '</figcaption>', NASA),
                            (WIDGETS + MEDIA, 'https://other.example/story'),
                            (WIDGETS.replace('Downloads', 'Editorial downloads').replace('You may also be interested in:', 'An editorial section').replace('Discover More from NASA Earth Science', 'Science findings'), NASA)):
            with self.subTest(url=url, markup=markup[:80]):
                text = html_to_text(PROSE + markup, url=url)
                self.assertIn('JPEG', text)
                self.assertIn('Unrelated recommendation', text)
        self.assertIn('September 20, 2026', html_to_text(PROSE + '<p>September 20, 2026</p>', url=NASA))

    def test_ars_removes_only_matching_terminal_navigation_pair(self):
        self.assertEqual(html_to_text(PROSE + NAV, url=ARS), html_to_text(PROSE))
        for markup, url in (('<blockquote>' + NAV + '</blockquote>', ARS),
                            ('<figcaption>' + NAV + '</figcaption>', ARS),
                            (NAV + '<p>The story continues here.</p>', ARS),
                            (NAV.replace('#comments', '#details'), ARS),
                            (NAV.replace('/testing/', '/other/'), ARS),
                            (NAV, 'https://other.example/story')):
            with self.subTest(markup=markup[:80], url=url):
                self.assertIn('Read full article', html_to_text(PROSE + markup, url=url))

    def test_rss_cleanup_and_writer_reach_both_pipeline_modes_without_network(self):
        source = Substack('')
        body = PROSE + CREDIT + MEDIA + WIDGETS
        xml = ('<rss><channel><item><guid>fixed-id</guid><title>A discovery</title><link>' + NASA + '</link>'
               '<pubDate>Wed, 11 Nov 2026 12:00:00 GMT</pubDate><description>' + escape(body) + '</description></item></channel></rss>')
        publication = {'base': 'https://www.nasa.gov/feed/', 'rss': True, 'name': 'Configured Publication'}
        with patch.object(source, 'get', return_value=xml):
            post = source.recent_posts(publication)[0]
        expected = html_to_text(PROSE + CREDIT + '<figcaption>A useful image caption.</figcaption>')
        self.assertEqual(post['publishedBylines'], [{'name': 'Alex Writer'}])
        self.assertEqual(post['wordcount'], len(expected.split()))
        self.assertEqual(post['body_html'], body)
        for mode in ('full', 'summary'):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                    'SITE_DIR': str(Path(tmp) / 'site'), 'STATE_DIR': str(Path(tmp) / 'state')}, clear=True):
                spoken = []
                existing = {'guid': 'old-episode', 'file': 'old.mp3', 'description': 'Original description.'}
                state = {'episodes': [existing.copy()]}
                settings = Settings.from_env()
                old = settings.site / 'episodes' / 'old.mp3'
                old.parent.mkdir(parents=True, exist_ok=True)
                old.write_bytes(b'preserve-existing-audio')
                def narrate(text, path, *args):
                    spoken.append(text)
                    path.write_bytes(b'ID3-fixture')
                    return [path]
                def summarize(publication, author, title, text, *args):
                    self.assertEqual(author, 'Alex Writer')
                    self.assertEqual(text, expected)
                    return text
                with patch.object(source, 'get', side_effect=AssertionError('No extra fetch')), \
                        patch('tts.synthesize_full', side_effect=narrate) as full, \
                        patch('tts.synthesize', side_effect=narrate), patch('tts.duration', return_value=12), \
                        patch('summarize.write_script', side_effect=summarize):
                    main.make_episode(source, {**publication, 'mode': mode}, post, datetime.now(timezone.utc), state, settings)
                    if mode == 'full':
                        self.assertIn('By Alex Writer.', full.call_args.args[3])
                self.assertEqual(spoken, [expected])
                self.assertEqual(state['episodes'][0], existing)
                self.assertEqual(old.read_bytes(), b'preserve-existing-audio')

    def test_retry_post_without_bylines_gets_writer_without_mutating_raw_post(self):
        source = Substack('')
        post = {'id': 42, 'canonical_url': NASA, 'body_html': PROSE + CREDIT, 'publishedBylines': []}
        full, _ = source.post_text({'rss': True}, post)
        self.assertEqual(full['publishedBylines'], [{'name': 'Alex Writer'}])
        self.assertEqual(post['publishedBylines'], [])
        self.assertEqual(full['id'], post['id'])


if __name__ == '__main__':
    unittest.main()
