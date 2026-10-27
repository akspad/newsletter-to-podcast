"""A broken optional feed URL must not block readable articles or other entries."""
import contextlib
from datetime import datetime, timezone
import hashlib
from html import escape
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import storage
from substack import Substack

PUB = {'base': 'https://fictional.example/feed.xml', 'name': 'Science Notes', 'rss': True, 'mode': 'full'}
NOW = datetime.now(timezone.utc).isoformat()
BODY = ('An original article describes how researchers compare careful observations across several seasons '
        'and use those measurements to plan better experiments for the following year.')


def entry(kind, identity, link, extra=''):
    if kind == 'atom':
        return ('<entry><id>urn:story:'+identity+'</id><title>Story '+identity+'</title>'
                '<published>'+NOW+'</published><link href="'+escape(link, quote=True)+'"/>'+extra+
                '<content type="text">'+BODY+'</content></entry>')
    if kind == 'rss1':
        return ('<item rdf:about="urn:story:'+identity+'"><title>Story '+identity+'</title>'
                '<dc:date>'+NOW+'</dc:date><link>'+escape(link)+'</link>'+extra+
                '<description>'+BODY+'</description></item>')
    return ('<item><guid isPermaLink="false">urn:story:'+identity+'</guid><title>Story '+identity+'</title>'
            '<pubDate>'+NOW+'</pubDate><link>'+escape(link)+'</link>'+extra+
            '<description>'+BODY+'</description></item>')


def document(kind, entries, attributes=''):
    if kind == 'atom':
        return '<feed xmlns="http://www.w3.org/2005/Atom" '+attributes+'>'+entries+'</feed>'
    if kind == 'rss1':
        return ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                'xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">'+entries+'</rdf:RDF>')
    return '<rss><channel>'+entries+'</channel></rss>'


class FeedLinkRecoveryTests(unittest.TestCase):
    def discover(self, xml):
        source = Substack('')
        with patch.object(source, 'get', return_value=xml) as get:
            posts = source.recent_posts(PUB)
        get.assert_called_once()  # Resolving metadata never fetches linked resources.
        return posts

    def test_malformed_link_is_omitted_and_other_entries_and_stable_ids_survive(self):
        for kind in ('rss', 'rss1', 'atom'):
            for link in ('https://[broken', 'https://fictional.example:bad/story',
                         'https://fictional.example:0/story', 'javascript:alert(1)',
                         'https://user:password@fictional.example/story'):
                rows = entry(kind, 'one', 'https://fictional.example/one')+entry(kind, 'bad', link)+entry(kind, 'two', 'https://fictional.example/two')
                with self.subTest(kind=kind, link=link):
                    posts = self.discover(document(kind, rows))
                    control = self.discover(document(kind, rows.replace(escape(link, quote=True), 'https://fictional.example/repaired')))
                    self.assertEqual(len(posts), 3)
                    self.assertEqual([p['canonical_url'] for p in posts],
                                     ['https://fictional.example/one', '', 'https://fictional.example/two'])
                    self.assertEqual([p['id'] for p in posts], [p['id'] for p in control])
                    self.assertTrue(all(p['body_html'] == BODY for p in posts))

    def test_valid_http_links_queries_fragments_ipv6_and_ports_are_preserved(self):
        for kind in ('rss', 'atom'):
            for link in ('http://fictional.example/story?view=full#opening',
                         'https://fictional.example:8443/story', 'https://[2606:4700::1111]/story'):
                with self.subTest(kind=kind, link=link):
                    post = self.discover(document(kind, entry(kind, 'one', link)))[0]
                    self.assertEqual(post['canonical_url'], link)

    def test_rss_relative_links_use_final_feed_url_without_changing_fallback_identity(self):
        source = Substack('')
        xml = '<rss><channel><item><link>../story</link><pubDate>'+NOW+'</pubDate><description>'+BODY+'</description></item></channel></rss>'
        def fetch(*args, **kwargs):
            source.last_url = 'https://publication.example/feeds/current.xml'
            return xml
        with patch.object(source, 'get', side_effect=fetch) as get:
            post = source.recent_posts(PUB)[0]
        get.assert_called_once()
        self.assertEqual(post['canonical_url'], 'https://publication.example/story')
        self.assertEqual(post['id'], int(hashlib.sha1(b'../story').hexdigest()[:10], 16))

    def test_rss_bad_link_can_fall_back_to_an_explicit_permalink_guid(self):
        xml = ('<rss><channel><item><guid>https://fictional.example/one</guid><link>https://[broken</link>'
               '<pubDate>'+NOW+'</pubDate><description>'+BODY+'</description></item></channel></rss>')
        post = self.discover(xml)[0]
        self.assertEqual(post['canonical_url'], 'https://fictional.example/one')
        self.assertEqual(post['id'], int(hashlib.sha1(b'https://fictional.example/one').hexdigest()[:10], 16))

    def test_atom_uses_a_later_valid_alternate_and_audio_enclosure(self):
        extra = ('<link href="../story?view=full#opening"/>'
                 '<link rel="enclosure" type="audio/mpeg" href="https://[broken"/>'
                 '<link rel="enclosure" type="audio/mpeg" href="../speech.mp3"/>')
        xml = document('atom', entry('atom', 'one', 'https://[broken', extra), 'xml:base="https://publication.example/posts/"')
        post = self.discover(xml)[0]
        self.assertEqual(post['canonical_url'], 'https://publication.example/story?view=full#opening')
        self.assertEqual(post['podcast_url'], 'https://publication.example/speech.mp3')

    def test_atom_bad_xml_bases_do_not_block_siblings_or_absolute_links(self):
        bad_entry = entry('atom', 'bad', 'relative').replace('<entry>', '<entry xml:base="https://[broken">')
        absolute = entry('atom', 'absolute', 'https://other.example/story')
        sibling = entry('atom', 'sibling', '../healthy')
        posts = self.discover(document('atom', bad_entry+absolute+sibling))
        self.assertEqual([p['canonical_url'] for p in posts], ['', 'https://other.example/story', 'https://fictional.example/healthy'])
        # A malformed feed-level base cannot invalidate self-contained absolute URLs.
        posts = self.discover(document('atom', absolute, 'xml:base="https://[broken"'))
        self.assertEqual(posts[0]['canonical_url'], 'https://other.example/story')
        bad_link_base = entry('atom', 'one', 'relative').replace('<link ', '<link xml:base="https://[broken" ')
        self.assertEqual(self.discover(document('atom', bad_link_base+sibling))[0]['canonical_url'], '')

    def test_bad_enclosure_is_not_treated_as_playable_audio(self):
        for kind, extra in (
                ('rss', '<enclosure url="https://[broken" type="audio/mpeg"/>'),
                ('atom', '<link href="https://[broken" rel="enclosure" type="audio/mpeg"/>')):
            with self.subTest(kind=kind):
                post = self.discover(document(kind, entry(kind, 'one', 'https://fictional.example/one', extra)))[0]
                self.assertFalse(post['podcast_url'])

    def test_all_readable_entries_publish_and_repaired_links_do_not_duplicate_them(self):
        for kind in ('rss', 'rss1', 'atom'):
            rows = entry(kind, 'one', 'https://fictional.example/one')+entry(kind, 'bad', 'https://[broken')+entry(kind, 'two', 'https://fictional.example/two')
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                    'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full'}, clear=True):
                settings = config.Settings.from_env()
                spoken = []
                def narrate(text, path, limit, intro):
                    spoken.append(text)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'ID3-fixture')
                    return [path]
                source = Substack('')
                with patch.object(source, 'get', return_value=document(kind, rows)) as get, \
                        patch('tts.synthesize_full', side_effect=narrate), patch('tts.duration', return_value=10), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main.run(settings, [PUB], source), 0)
                    state = storage.load(settings)
                    get.return_value = document(kind, rows.replace('https://[broken', 'https://fictional.example/repaired'))
                    self.assertEqual(main.run(settings, [PUB], source), 0)
                    recovered = storage.load(settings)
                self.assertEqual(spoken, [BODY]*3)
                self.assertEqual(len(state['episodes']), 3)
                self.assertEqual(len(recovered['episodes']), 3)
                self.assertEqual(len(state['seen']), 3)
                self.assertEqual(state['retry'], [])
                self.assertEqual(next(e for e in state['episodes'] if 'Story bad' in e['title'])['link'], PUB['base'])
                self.assertNotIn('https://[broken', (settings.site/'feed.xml').read_text())


if __name__ == '__main__':
    unittest.main()
