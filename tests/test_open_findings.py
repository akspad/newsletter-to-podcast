"""Regression coverage for import isolation, retention, redirects and attribution."""
import contextlib
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
from html import escape
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import feed
import main
import preview
import security
import storage
from article_metadata import article_details, article_metadata
from substack import Substack, SourceDownloadError

PUB = {'base': 'https://fictional.example/feed.xml', 'name': 'Science Notes', 'rss': True, 'mode': 'full'}
PROSE = ('This article explains how careful observation helps people understand the natural world. '
         'Researchers compare measurements across several seasons and use the results to plan better experiments.')
CHINESE = ('我们在城市公园里观察树木和鸟类，记录每一天的变化。研究人员把这些记录整理成数据，'
           '比较不同季节的温度与降雨情况。这样的长期观察能够帮助我们理解环境变化，也能为社区保护自然提供可靠的依据。')
URL = 'https://fictional.example/story'


def rss(entries):
    return '<rss version="2.0"><channel>' + ''.join(entries) + '</channel></rss>'


def item(title, body=PROSE, extra=''):
    return ('<item><title>' + title + '</title><pubDate>' + format_datetime(datetime.now(timezone.utc)) +
            '</pubDate><description>' + escape(body) + '</description>' + extra + '</item>')


def page(extra='', metadata='', prose=PROSE):
    return ('<title>A discovery</title>' + metadata + '<article itemscope itemtype="https://schema.org/BlogPosting">'
            '<h1>A discovery</h1>' + extra + '<div class="entry-content"><p>' + prose + '</p></div></article>')


class ImportRecoveryTests(unittest.TestCase):
    def test_identifierless_rss_ids_are_distinct_stable_and_preserve_existing_ids(self):
        first, second = item('First article'), item('Second article')
        source = Substack('')
        with patch.object(source, 'get', return_value=rss([first, second])):
            posts = source.recent_posts(PUB)
        with patch.object(source, 'get', return_value=rss([second, first])):
            reversed_posts = source.recent_posts(PUB)
        self.assertNotEqual(posts[0]['id'], posts[1]['id'])
        self.assertEqual([p['id'] for p in posts], [p['id'] for p in reversed(reversed_posts)])
        for extra, identity in (('<guid>stable-id</guid>', 'stable-id'),
                                ('<link>https://fictional.example/one</link>', 'https://fictional.example/one')):
            with self.subTest(extra=extra), patch.object(source, 'get', return_value=rss([item('First article', extra=extra)])):
                self.assertEqual(source.recent_posts(PUB)[0]['id'], int(hashlib.sha1(identity.encode()).hexdigest()[:10], 16))
        with patch.object(source, 'get', return_value=rss([first.replace(escape(PROSE), escape('<p>' + PROSE + '</p>'))])):
            self.assertEqual(source.recent_posts(PUB)[0]['id'], posts[0]['id'])

    def run_source(self, directory, document):
        with patch.dict(os.environ, {'SITE_DIR': str(directory / 'site'), 'STATE_DIR': str(directory / 'state'),
                                    'EPISODE_MODE': 'full', 'MIN_WORDS': '0'}, clear=True):
            settings = config.Settings.from_env()
            source = Substack('')
            spoken = []
            def narrate(text, path, limit, intro):
                spoken.append(text)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'ID3-fixture')
                return [path]
            with patch.object(source, 'get', return_value=document), patch('tts.synthesize_full', side_effect=narrate), \
                    patch('tts.duration', return_value=10), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = main.run(settings, [PUB], source)
            return status, storage.load(settings), spoken

    def test_identifierless_articles_both_publish_and_do_not_repeat_on_next_run(self):
        document = rss([item('First article'), item('Second article')])
        with tempfile.TemporaryDirectory() as tmp:
            status, state, spoken = self.run_source(Path(tmp), document)
            self.assertEqual((status, len(state['episodes']), len(spoken)), (0, 2, 2))
            self.assertTrue(all(episode['link'] == PUB['base'] for episode in state['episodes']))
            status, state, spoken = self.run_source(Path(tmp), document)
            self.assertEqual((status, len(state['episodes']), len(spoken)), (0, 2, 0))

    def test_oversized_entry_does_not_block_normal_entries_or_enter_retry_queue(self):
        normal = item('Normal article', extra='<guid>normal</guid>')
        large = item('Oversized article', 'large ' * 45000, '<guid>large</guid>')
        for entries in ([large, normal], [normal, large]):
            with self.subTest(large_first=entries[0] == large), tempfile.TemporaryDirectory() as tmp:
                status, state, spoken = self.run_source(Path(tmp), rss(entries))
                self.assertEqual((status, len(state['episodes']), len(spoken)), (0, 1, 1))
                self.assertIn('Normal article', state['episodes'][0]['title'])
                self.assertEqual(state['retry'], [])

    def test_feed_order_and_retention_compare_instants_and_preserve_audio(self):
        episodes = []
        for key, published in [('newer', '2026-10-24T08:00:00+00:00'), ('older', '2026-10-24T09:00:00+02:00')]:
            episodes.append(dict(guid=key, source_key=key, published=published, title=key, file=key+'.mp3',
                                 duration=10, bytes=11, description=PROSE, link=URL))
        document = ET.fromstring(feed.build('https://fictional.example', episodes))
        self.assertEqual([node.findtext('title') for node in document.findall('channel/item')], ['newer', 'older'])
        self.assertEqual(feed.published_time({'published': '2026-10-24T08:00:00'}), feed.published_time(episodes[0]))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'KEEP_EPISODES': '1'}, clear=True):
            settings = config.Settings.from_env()
            (settings.site / 'episodes').mkdir(parents=True)
            for episode in episodes:
                (settings.site / 'episodes' / episode['file']).write_bytes(b'ID3-fixture')
            state = {'episodes': episodes, 'seen': ['newer', 'older'], 'retry': [], 'last_run': None}
            with patch('main.load_state', return_value=state), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.run(settings, [PUB], types.SimpleNamespace(recent_posts=lambda p: [])), 0)
            self.assertEqual([e['guid'] for e in state['episodes']], ['newer'])
            self.assertTrue((settings.site / 'episodes/newer.mp3').exists())
            self.assertFalse((settings.site / 'episodes/older.mp3').exists())


class AttributionRecoveryTests(unittest.TestCase):
    def test_relative_graph_ids_resolve_in_both_directions_without_fetches(self):
        for definition, reference in ((URL+'#', '#'), ('#', URL+'#')):
            graph = {'@context': 'https://schema.org', '@graph': [
                {'@type': 'BlogPosting', 'url': URL, 'headline': 'A discovery',
                 'author': {'@id': reference+'author'}, 'publisher': {'@id': reference+'publisher'}},
                {'@id': definition+'author', '@type': 'Person', 'name': 'Alice Writer'},
                {'@id': definition+'publisher', '@type': 'Organization', 'name': 'Science Notes'}]}
            html = page(metadata='<script type="application/ld+json">'+json.dumps(graph)+'</script>')
            with self.subTest(definition=definition), patch('substack.Substack.get', return_value=html) as get:
                text = preview.article_text(URL)
                self.assertEqual(text.partition('\n')[0], 'Science Notes. A discovery. By Alice Writer.')
                get.assert_called_once_with(URL, raw=True)

    def test_relative_paid_section_references_still_exclude_structured_body(self):
        graph = {'@graph': [{'@type': 'Article', 'url': URL, 'headline': 'A discovery', 'articleBody': PROSE,
                            'hasPart': {'@id': '#paid'}}, {'@id': URL+'#paid', 'isAccessibleForFree': False}]}
        html = '<title>A discovery</title><script type="application/ld+json">'+json.dumps(graph)+'</script>'
        self.assertEqual(article_details(BeautifulSoup(html, 'html.parser'), URL)[3], '')

    def test_multi_property_microdata_author_and_name_are_supported(self):
        html = page('<span itemprop="author creator" itemscope itemtype="https://schema.org/Person">'
                    '<span itemprop="name alternateName">Alice Writer</span></span>')
        self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), URL)[2], 'Alice Writer')

    def test_hidden_group_members_are_never_announced(self):
        for hidden in ('hidden', 'aria-hidden="true"', 'style="display:none"'):
            html = page('<div class="article-authors"><a '+hidden+' href="/authors/draft">Hidden Writer</a>'
                        '<a href="/authors/alice"><span itemprop="name">Alice Writer</span></a></div>')
            with self.subTest(hidden=hidden), patch('substack.Substack.get', return_value=html):
                result = preview.article_text(URL)
                self.assertEqual(result.partition('\n')[0], 'fictional.example. A discovery. By Alice Writer.')
                self.assertNotIn('Hidden Writer', result)

    def test_empty_hidden_group_has_no_text_fallback_and_plain_names_still_work(self):
        for members, expected in (('<a hidden href="/authors/draft">Hidden Writer</a>', ''),
                                  ('Alice Writer<span hidden>Hidden Writer</span>', 'Alice Writer')):
            html = page('<div class="article-authors">'+members+'</div>')
            with self.subTest(members=members):
                self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), URL)[2], expected)

    def test_generic_feed_names_and_date_only_bylines_do_not_override_real_names(self):
        for label in ('RSS', 'Atom', 'RSS Feed', 'Recent Entries'):
            html = page('<div class="byline">January 4, 2020</div>',
                        '<a href="/">Science Notes</a><link rel="alternate" type="application/rss+xml" title="'+label+'">')
            with self.subTest(label=label):
                self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'), URL), ('Science Notes', 'A discovery', ''))
        self.assertEqual(article_metadata(BeautifulSoup(page('<p class="byline">May Writer</p>'), 'html.parser'), URL)[2], 'May Writer')

    def test_unspaced_prose_is_read_in_visible_and_structured_bodies(self):
        for html in (page(prose=CHINESE*4), '<script type="application/ld+json">'+json.dumps({
                '@type': 'Article', 'url': URL, 'headline': 'A discovery', 'articleBody': CHINESE*4})+'</script>'):
            with self.subTest(structured='application/ld' in html), patch('substack.Substack.get', return_value=html):
                text = preview.article_text(URL)
                self.assertIn(CHINESE, text)
                self.assertLessEqual(len(preview.excerpt(text)), 1000)
        for short in ('Too short.', 'x'*1000, '观察自然。'):
            with self.subTest(short=short[:15]), patch('substack.Substack.get', return_value=page(prose=short)):
                with self.assertRaises(ValueError):
                    preview.article_text(URL)


class HtmlRedirectTests(unittest.TestCase):
    def transport(self, responses, calls):
        responses = iter(responses)
        fake = types.ModuleType('curl_cffi')
        fake.CurlOpt = types.SimpleNamespace(RESOLVE=1, PROXY=2, MAXFILESIZE_LARGE=3)
        def get(url, **kwargs):
            calls.append((url, kwargs))
            data, headers, redirect = next(responses)
            result = kwargs['content_callback'](data.encode())
            if result == 0xFFFFFFFF:
                raise RuntimeError('Aborted response')
            return types.SimpleNamespace(is_redirect=redirect, status_code=302 if redirect else 200, headers=headers)
        fake.requests = types.SimpleNamespace(get=get)
        return fake

    def dns(self, host, port, **kwargs):
        address = '127.0.0.1' if host == '127.0.0.1' else '93.184.216.34'
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', (address, port))]

    def test_meta_and_http_redirects_share_validated_navigation_and_final_url(self):
        first = '<head><base href="/moved/"><meta content="0.0; URL=\'story\'" http-equiv="Refresh"></head>'
        calls = [];source = Substack('cookie')
        source.auth_hosts = {'fictional.example'}
        fake = self.transport([(first, {}, False), ('', {'Location': 'https://other.example/final'}, True), ('Actual article.', {}, False)], calls)
        with patch.dict(sys.modules, {'curl_cffi': fake}), patch('security.socket.getaddrinfo', side_effect=self.dns):
            self.assertEqual(source.get(URL, raw=True), 'Actual article.')
        self.assertEqual([c[0] for c in calls], [URL, 'https://fictional.example/moved/story', 'https://other.example/final'])
        self.assertEqual(source.last_url, 'https://other.example/final')
        self.assertIn('Cookie', calls[0][1]['headers'])
        self.assertNotIn('Cookie', calls[-1][1]['headers'])
        self.assertTrue(all(c[1]['curl_options'][1][0].endswith(b':93.184.216.34') for c in calls))

    def test_meta_redirect_rejects_private_credentials_and_https_downgrades(self):
        for destination in ('https://127.0.0.1/secret', 'https://user@fictional.example/secret', 'http://fictional.example/story'):
            calls = [];source = Substack('')
            fake = self.transport([('<meta http-equiv="refresh" content="0;url='+destination+'">', {}, False)], calls)
            with self.subTest(destination=destination), patch.dict(sys.modules, {'curl_cffi': fake}), \
                    patch('security.socket.getaddrinfo', side_effect=self.dns), self.assertRaises(ValueError):
                source.get(URL, raw=True)
            self.assertEqual(len(calls), 1)
            self.assertIsNone(source.last_url)

    def test_delayed_canonical_and_template_links_do_not_navigate(self):
        for html in ('<meta http-equiv="refresh" content="5;url=/other">', '<link rel="canonical" href="/other">',
                     '<template><meta http-equiv="refresh" content="0;url=/other"></template>'):
            calls=[];fake=self.transport([(html, {}, False)], calls)
            with self.subTest(html=html), patch.dict(sys.modules, {'curl_cffi': fake}), \
                    patch('security.socket.getaddrinfo', side_effect=self.dns):
                self.assertEqual(Substack('').get(URL, raw=True), html)
            self.assertEqual(len(calls), 1)

    def test_refresh_cycles_and_aggregate_bytes_remain_bounded(self):
        html = '<meta http-equiv="refresh" content="0;url=/story">'
        calls=[];fake=self.transport([(html, {}, False)]*5, calls)
        with patch.dict(sys.modules, {'curl_cffi': fake}), patch('security.socket.getaddrinfo', side_effect=self.dns):
            with self.assertRaises(SourceDownloadError):
                Substack('').get(URL, raw=True)
        self.assertEqual(len(calls), 5)
        calls=[];fake=self.transport([(html, {}, False), (PROSE, {}, False)], calls)
        with patch.dict(sys.modules, {'curl_cffi': fake}), patch('security.socket.getaddrinfo', side_effect=self.dns), \
                patch('security.MAX_DOWNLOAD_BYTES', len(html.encode()) + 1), self.assertRaises(security.BudgetExceeded):
            Substack('').get(URL, raw=True)


if __name__ == '__main__':
    unittest.main()
