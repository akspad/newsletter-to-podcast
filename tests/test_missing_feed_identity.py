"""Malformed feed entries without identifiers must not silently share one episode."""
import contextlib
from datetime import datetime, timezone
import hashlib
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

PUB = {'base': 'https://fictional.example/feed', 'name': 'Research Notes', 'rss': True, 'mode': 'full'}
NOW = datetime.now(timezone.utc).isoformat()


def entry(kind, name, identity='', link=''):
    title = 'Report '+name
    body = 'A fictional article describes observations from experiment '+name+'.'
    if kind == 'atom':
        return ('<entry><id>'+identity+'</id><title>'+title+'</title><updated>'+NOW+'</updated>'
                '<link href="'+link+'"/><content>'+body+'</content></entry>')
    return ('<item><guid isPermaLink="false">'+identity+'</guid><title>'+title+'</title><pubDate>'+NOW+'</pubDate>'
            '<link>'+link+'</link><description>'+body+'</description></item>')


def document(kind, rows):
    return ('<feed xmlns="http://www.w3.org/2005/Atom">'+rows+'</feed>' if kind == 'atom'
            else '<rss><channel>'+rows+'</channel></rss>')


class MissingFeedIdentityTests(unittest.TestCase):
    def discover(self, kind, rows):
        source = Substack('')
        with patch.object(source, 'get', return_value=document(kind, rows)):
            return source.recent_posts(PUB)

    def test_missing_and_whitespace_identities_are_distinct_and_stable_when_reordered(self):
        for kind in ('rss', 'atom'):
            for identity in ('', ' \n '):
                with self.subTest(kind=kind, identity=identity):
                    first, second = entry(kind, 'one', identity), entry(kind, 'two', identity)
                    rows = self.discover(kind, first+second)
                    self.assertEqual(len({p['id'] for p in rows}), 2)
                    self.assertEqual({p['title']: p['id'] for p in rows},
                                     {p['title']: p['id'] for p in self.discover(kind, second+first)})

    def test_valid_ids_and_link_fallback_keep_their_existing_hashes(self):
        for kind in ('rss', 'atom'):
            for identity, link in (('urn:report:one', ''), ('', 'https://fictional.example/one')):
                with self.subTest(kind=kind, identity=identity):
                    post = self.discover(kind, entry(kind, 'one', identity, link))[0]
                    self.assertEqual(post['id'], int(hashlib.sha1((identity or link).encode()).hexdigest()[:10], 16))

    def test_publisher_id_survives_article_edits_and_link_changes(self):
        for kind in ('rss', 'atom'):
            for identity in ('urn:report:one', ' urn:report:one '):
                with self.subTest(kind=kind, identity=identity):
                    before = self.discover(kind, entry(kind, 'one', identity, 'https://fictional.example/old'))[0]
                    after = self.discover(kind, entry(kind, 'revised', identity, 'https://fictional.example/new'))[0]
                    self.assertEqual(before['id'], after['id'])

    def test_every_unlinked_entry_publishes_once_and_reordering_does_not_duplicate(self):
        for kind in ('rss', 'atom'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                    'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full'}, clear=True):
                settings = config.Settings.from_env()
                source = Substack('')
                one, two = entry(kind, 'one'), entry(kind, 'two')
                spoken = []
                def narrate(text, path, limit, intro):
                    spoken.append(text)
                    path.write_bytes(b'ID3-fictional')
                    return [path]
                with patch.object(source, 'get', return_value=document(kind, one+two)) as get, \
                        patch('tts.synthesize_full', side_effect=narrate), patch('tts.duration', return_value=10), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main.run(settings, [PUB], source), 0)
                    get.return_value = document(kind, two+one)
                    self.assertEqual(main.run(settings, [PUB], source), 0)
                self.assertEqual(len(spoken), 2)
                self.assertIn('experiment one.', spoken[0])
                self.assertIn('experiment two.', spoken[1])
                state = storage.load(settings)
                self.assertEqual(len(state['episodes']), 2)
                self.assertEqual(len(state['seen']), 2)
                self.assertEqual(state['retry'], [])


if __name__ == '__main__':
    unittest.main()
