"""Syndication credits must not reach scheduled narration or eat short prose."""
from datetime import datetime, timezone
from html import escape
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from config import Settings
from substack import Substack, html_to_text
import main

URL = 'https://fictional.example/story'
TITLE = 'A discovery?'
BODY = '<blockquote><p>A brief but legitimate quotation.</p></blockquote>'
FOOTER = ('<p>The post <a href="/story">A discovery?</a> appeared first on '
          '<a href="https://fictional.example">Science Notes</a>.</p>')
PUB = {'base': 'https://fictional.example/feed', 'rss': True, 'name': 'Science Notes'}


class SyndicationFooterTests(unittest.TestCase):
    def test_identified_terminal_footer_leaves_a_short_quotation(self):
        self.assertEqual(html_to_text(BODY + FOOTER, title=TITLE, url=URL),
                         'A brief but legitimate quotation.')
        self.assertEqual(html_to_text(BODY + FOOTER, title=TITLE, url=URL + '?utm_source=rss'),
                         'A brief but legitimate quotation.')

    def test_missing_context_cannot_strip_prose(self):
        for context in ({}, {'title': TITLE}, {'url': URL}):
            self.assertIn('appeared first on', html_to_text(BODY + FOOTER, **context))

    def test_quoted_code_list_and_nonterminal_mentions_survive(self):
        for markup in ('<blockquote>' + FOOTER + '</blockquote>', '<pre>' + FOOTER + '</pre>',
                       '<ul><li>' + FOOTER + '</li></ul>', FOOTER + '<p>The narrative continues.</p>'):
            self.assertIn('appeared first on', html_to_text(BODY + markup, title=TITLE, url=URL))

    def test_different_titles_urls_homepages_and_extra_prose_survive(self):
        for markup in (FOOTER.replace('A discovery?', 'Other article'),
                       FOOTER.replace('href="/story"', 'href="/other"'),
                       FOOTER.replace('https://fictional.example', 'https://other.example'),
                       FOOTER.replace('https://fictional.example', 'https://fictional.example/about'),
                       FOOTER.replace('https://fictional.example', 'https://fictional.example?edition=2'),
                       FOOTER.replace('href="/story"', ''),
                       FOOTER.replace('href="/story"', 'href="http://[broken"'),
                       FOOTER.replace('</p>', ' This is part of the argument.</p>'),
                       '<p>The post A discovery? appeared first on Science Notes.</p>'):
            with self.subTest(markup=markup):
                self.assertIn('appeared first on', html_to_text(BODY + markup, title=TITLE, url=URL))

    def test_linked_unicode_title_and_comment_after_footer(self):
        title = 'Évidence & observations?'
        footer = FOOTER.replace('A discovery?', '<em>Évidence</em> &amp; observations?')
        self.assertEqual(html_to_text(BODY + footer + '<!-- publisher comment -->', title=title, url=URL),
                         'A brief but legitimate quotation.')

    def test_rss_and_atom_discovery_and_post_text_share_clean_wordcounts(self):
        body = BODY + FOOTER
        feeds = (
            '<rss><channel><item><guid>fixed-id</guid><title>' + TITLE + '</title><link>' + URL + '</link>'
            '<pubDate>Tue, 10 Nov 2026 12:00:00 GMT</pubDate><description>' + escape(body) +
            '</description></item></channel></rss>',
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>fixed-id</id><title>' + TITLE +
            '</title><link href="' + URL + '"/><updated>2026-11-10T12:00:00Z</updated>'
            '<content type="html">' + escape(body) + '</content></entry></feed>')
        for feed in feeds:
            source = Substack('')
            with patch.object(source, 'get', return_value=feed):
                post = source.recent_posts(PUB)[0]
            self.assertEqual(post['wordcount'], 5)
            self.assertEqual(post['canonical_url'], URL)
            self.assertEqual(source.post_text(PUB, post)[1], 'A brief but legitimate quotation.')
            self.assertEqual(post['body_html'], body)

    def test_full_narration_and_summary_input_receive_no_syndication_credit(self):
        source = Substack('')
        post = {'id': 42, 'slug': 'story', 'title': TITLE, 'canonical_url': URL,
                'body_html': BODY + FOOTER, 'audience': 'everyone'}
        for mode in ('full', 'summary'):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                    'SITE_DIR': str(Path(tmp) / 'site'), 'STATE_DIR': str(Path(tmp) / 'state')}, clear=True):
                spoken = []
                def narrate(text, path, *args):
                    spoken.append(text)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'ID3-fixture')
                    return [path]
                def summarize(publication, author, title, text, *args):
                    self.assertEqual(text, 'A brief but legitimate quotation.')
                    return text
                state = {'episodes': []}
                with patch('tts.synthesize_full', side_effect=narrate), patch('tts.synthesize', side_effect=narrate), \
                        patch('tts.duration', return_value=3), patch('summarize.write_script', side_effect=summarize):
                    main.make_episode(source, {**PUB, 'mode': mode}, post, datetime.now(timezone.utc),
                                      state, Settings.from_env())
                self.assertEqual(spoken, ['A brief but legitimate quotation.'])
                self.assertNotIn('appeared first on', state['episodes'][0]['description'])


if __name__ == '__main__':
    unittest.main()
