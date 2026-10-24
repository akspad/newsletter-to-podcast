"""Feed-entry recovery and Atom link resolution without network requests."""
from pathlib import Path
from datetime import datetime, timezone
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from substack import Substack
from config import Settings
import main

PUB = {'base': 'https://fictional.example/feed.xml', 'rss': True}


class FeedAdapterTests(unittest.TestCase):
    def test_atom_titles_normalize_html_xhtml_and_literal_text(self):
        source = Substack('')
        cases = (
            ('<title type="html">Working with &lt;em&gt;vectors&lt;/em&gt;</title>', 'Working with vectors'),
            ('<title type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">Working with <em>vectors</em></div></title>', 'Working with vectors'),
            ('<title type="text">Use &lt;vector&gt; &amp; maps</title>', 'Use <vector> & maps'),
            ('<title>Use &lt;vector&gt; &amp; maps</title>', 'Use <vector> & maps'))
        for title, expected in cases:
            xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>one</id>' + title +
                   '<updated>2026-10-23T12:00:00Z</updated><content>Body.</content></entry></feed>')
            with self.subTest(title=title), patch.object(source, 'get', return_value=xml):
                self.assertEqual(source.recent_posts(PUB)[0]['title'], expected)

    def test_imported_facts_and_inherited_author_reach_full_narration(self):
        from html import escape
        article = '<p><span>A</span>n original sentence.</p><table><tr><td>Atlas</td><td>16 GB</td></tr></table><pre>limit = 16</pre>'
        rss1 = ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/"><item rdf:about="https://fictional.example/one">'
                '<title>An article</title><link>https://fictional.example/one</link><dc:date>2026-10-23T12:00:00Z</dc:date>'
                '<dc:creator>Alex Writer</dc:creator><description>' + escape(article) + '</description></item></rdf:RDF>')
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><author><name>Alex Writer</name></author><entry>'
                '<id>one</id><title>An article</title><updated>2026-10-23T12:00:00Z</updated><link href="/one"/>'
                '<content type="text">Use &lt;vector&gt; and &lt;optional&gt;.</content></entry></feed>')
        for xml, expected in ((rss1, 'An original sentence.\nAtlas 16 GB\nlimit = 16'),
                              (atom, 'Use <vector> and <optional>.')):
            source = Substack('')
            with self.subTest(xml=xml), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                    'SITE_DIR': str(Path(tmp) / 'site'), 'STATE_DIR': str(Path(tmp) / 'state'), 'EPISODE_MODE': 'full'}, clear=True):
                settings = Settings.from_env()
                publication = {**PUB, 'name': 'Science Notes', 'mode': 'full'}
                with patch.object(source, 'get', return_value=xml):
                    post = source.recent_posts(publication)[0]
                spoken = []
                def narrate(text, path, limit, intro):
                    spoken.append((text, intro))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'ID3-provider-fixture')
                    return [path]
                state = {'episodes': []}
                with patch('tts.synthesize_full', side_effect=narrate), patch('tts.duration', return_value=10):
                    main.make_episode(source, publication, post, datetime.now(timezone.utc), state, settings)
                self.assertEqual(spoken, [(expected, 'Science Notes. An article. By Alex Writer.')])
                self.assertEqual(state['episodes'][0]['description'], expected)
                self.assertEqual(state['episodes'][0]['link'], 'https://fictional.example/one')

    def test_rss1_reads_namespaced_metadata_body_and_stable_rdf_identity(self):
        source = Substack('')
        xml = ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" '
               'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
               '<channel rdf:about="https://fictional.example/feed.xml"><title>Science Notes</title></channel>'
               '<item rdf:about="https://fictional.example/stable-id"><title>A discovery</title>'
               '<link>https://fictional.example/one</link><dc:date>2026-10-23T12:00:00Z</dc:date>'
               '<dc:creator>Alex Writer</dc:creator><dc:creator>Sam Author</dc:creator>'
               '<description>Short summary.</description><content:encoded>&lt;p&gt;An original article body.&lt;/p&gt;</content:encoded>'
               '</item></rdf:RDF>')
        with patch.object(source, 'get', return_value=xml):
            post = source.recent_posts(PUB)[0]
        self.assertEqual(post['title'], 'A discovery')
        self.assertEqual(post['canonical_url'], 'https://fictional.example/one')
        self.assertEqual(post['post_date'], '2026-10-23T12:00:00+00:00')
        self.assertEqual(post['publishedBylines'], [{'name': 'Alex Writer'}, {'name': 'Sam Author'}])
        self.assertEqual(source.post_text(PUB, post)[1], 'An original article body.')
        with patch.object(source, 'get', return_value=xml.replace('/one', '/renamed')):
            self.assertEqual(source.recent_posts(PUB)[0]['id'], post['id'])
        rss2 = ('<rss><channel><item><guid>https://fictional.example/stable-id</guid>'
                '<pubDate>Fri, 23 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>')
        with patch.object(source, 'get', return_value=rss2):
            self.assertEqual(source.recent_posts(PUB)[0]['id'], post['id'])

    def test_rss1_keeps_the_scan_limit_and_skips_bad_dates(self):
        source = Substack('')
        xml = ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" '
               'xmlns:dc="http://purl.org/dc/elements/1.1/"><item rdf:about="bad"><dc:date>bad</dc:date></item>'
               '<item rdf:about="good"><dc:date>2026-10-23T12:00:00Z</dc:date></item>'
               '<item rdf:about="excess"><dc:date>2026-10-23T12:00:00Z</dc:date></item></rdf:RDF>')
        with patch.object(source, 'get', return_value=xml):
            self.assertEqual(source.rss_posts(PUB, 1), [])
            with patch('security.MAX_SOURCE_ENTRIES', 2):
                self.assertEqual(len(source.recent_posts(PUB)), 1)

    def test_atom_plain_text_and_default_type_preserve_literal_code(self):
        from html import escape
        source = Substack('')
        expected = 'Use <vector> and <optional> & keep the values.'
        for element in ('content', 'summary'):
            for attribute in ('', ' type="text"', ' type="text/plain"'):
                xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>one</id><updated>2026-10-23T12:00:00Z</updated>'
                       '<' + element + attribute + '>' + escape(expected) + '</' + element + '></entry></feed>')
                with self.subTest(element=element, attribute=attribute), patch.object(source, 'get', return_value=xml):
                    post = source.recent_posts(PUB)[0]
                    self.assertEqual(source.post_text(PUB, post)[1], expected)
                    self.assertEqual(post['wordcount'], len(expected.split()))

    def test_atom_xhtml_and_html_preserve_the_same_inline_words_and_blocks(self):
        from html import escape
        source = Substack('')
        fragment = '<p><span>A</span>n original sentence.</p><pre>Use &lt;vector&gt;.</pre><script>Do not read.</script>'
        expected = 'An original sentence.\nUse <vector>.'
        for content in ('<content type="html">' + escape(fragment) + '</content>',
                        '<content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">' + fragment + '</div></content>'):
            xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>one</id><updated>2026-10-23T12:00:00Z</updated>' +
                   content + '</entry></feed>')
            with self.subTest(content=content), patch.object(source, 'get', return_value=xml):
                self.assertEqual(source.post_text(PUB, source.recent_posts(PUB)[0])[1], expected)

    def test_atom_authors_inherit_from_feed_unless_entry_or_source_provides_them(self):
        source = Substack('')
        for authors, expected in (
                ('', ['Alex Writer', 'Sam Author']),
                ('<source><author><name>Source Writer</name></author></source>', ['Source Writer']),
                ('<source><author><name>Source Writer</name></author></source><author><name>Entry Writer</name></author>', ['Entry Writer'])):
            xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><author><name> Alex Writer </name></author>'
                   '<author><name>Sam Author</name></author><entry><id>one</id><updated>2026-10-23T12:00:00Z</updated>' +
                   authors + '<content>Body.</content></entry></feed>')
            with self.subTest(authors=authors), patch.object(source, 'get', return_value=xml):
                self.assertEqual(source.recent_posts(PUB)[0]['publishedBylines'], [{'name': name} for name in expected])

    def test_atom_remote_or_nontext_content_uses_available_summary_without_fetching(self):
        source = Substack('')
        for content in ('<content src="https://other.example/article"/>', '<content type="image/png">BASE64DATA</content>'):
            xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>one</id><updated>2026-10-23T12:00:00Z</updated>' +
                   content + '<summary type="text">Use &lt;vector&gt;.</summary></entry></feed>')
            with self.subTest(content=content), patch.object(source, 'get', return_value=xml) as get:
                post = source.recent_posts(PUB)[0]
                self.assertEqual(source.post_text(PUB, post)[1], 'Use <vector>.')
                get.assert_called_once()

    def test_invalid_dates_do_not_discard_other_rss_or_atom_entries(self):
        formats = (
            ('<rss><channel>{}</channel></rss>',
             '<item><guid>{}</guid><title>Article</title><pubDate>{}</pubDate><description>Body.</description></item>',
             'Fri, 23 Oct 2026 12:00:00 GMT'),
            ('<feed xmlns="http://www.w3.org/2005/Atom">{}</feed>',
             '<entry><id>{}</id><title>Article</title><published>{}</published><content>Body.</content></entry>',
             '2026-10-23T12:00:00Z'))
        for wrapper, entry, valid in formats:
            for invalid in ('not-a-date', '2026-02-30T12:00:00Z', '10000-01-01T00:00:00Z', ''):
                xml = wrapper.format(entry.format('one', valid) + entry.format('bad', invalid) + entry.format('two', valid))
                source = Substack('')
                with self.subTest(wrapper=wrapper, invalid=invalid), patch.object(source, 'get', return_value=xml):
                    posts = source.recent_posts(PUB)
                    self.assertEqual(len(posts), 2)
                    self.assertEqual(len({p['id'] for p in posts}), 2)
                    self.assertEqual([p['post_date'] for p in posts], ['2026-10-23T12:00:00+00:00'] * 2)

    def test_invalid_entries_still_count_toward_the_scan_ceiling(self):
        source = Substack('')
        xml = ('<rss><channel><item><pubDate>bad</pubDate></item>'
               '<item><guid>good</guid><pubDate>Fri, 23 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>')
        with patch.object(source, 'get', return_value=xml):
            self.assertEqual(source.rss_posts(PUB, 1), [])
            self.assertEqual(len(source.rss_posts(PUB, 2)), 1)

    def test_atom_xml_base_inherits_through_feed_entry_and_links(self):
        source = Substack('')
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://fictional.example/posts/">'
               '<entry xml:base="series/"><id>urn:one</id><title>Article</title><updated>2026-10-23T12:00:00Z</updated>'
               '<link xml:base="../articles/" href="one?view=full#opening"/>'
               '<link rel="enclosure" type="audio/mpeg" xml:base="../audio/" href="one.mp3"/>'
               '<content>Body.</content></entry></feed>')
        with patch.object(source, 'get', return_value=xml):
            post = source.recent_posts(PUB)[0]
        self.assertEqual(post['canonical_url'], 'https://fictional.example/posts/articles/one?view=full#opening')
        self.assertEqual(post['podcast_url'], 'https://fictional.example/posts/audio/one.mp3')

    def test_atom_relative_bases_use_final_feed_url_and_absolute_links_remain_absolute(self):
        source = Substack('')
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom" xml:base="../posts/">'
               '<entry><id>one</id><updated>2026-10-23T12:00:00Z</updated><link href="one"/></entry>'
               '<entry><id>two</id><updated>2026-10-23T12:00:00Z</updated>'
               '<link href="https://other.example/two"/></entry></feed>')
        def fetch(*args, **kwargs):
            source.last_url = 'https://publication.example/feeds/atom.xml'
            return xml
        with patch.object(source, 'get', side_effect=fetch) as get:
            posts = source.recent_posts(PUB)
        get.assert_called_once()
        self.assertEqual([post['canonical_url'] for post in posts],
                         ['https://publication.example/posts/one', 'https://other.example/two'])


if __name__ == '__main__':
    unittest.main()
