"""Feed-entry recovery and Atom link resolution without network requests."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from substack import Substack

PUB = {'base': 'https://fictional.example/feed.xml', 'rss': True}


class FeedAdapterTests(unittest.TestCase):
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
