"""A stale state snapshot must not erase published episodes or regenerate queued copies."""
import contextlib
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import feed
import main
import storage

NOW = datetime.now(timezone.utc).isoformat()


def episode(key):
    return {'guid': key, 'source_key': key, 'title': 'An original episode', 'description': 'Preserved notes.',
            'link': 'https://fictional.example/story', 'published': NOW, 'file': key+'.mp3', 'bytes': 123, 'duration': 10}


class PublishedFeedRecoveryTests(unittest.TestCase):
    def test_missing_public_episodes_recover_exact_client_metadata_without_losing_unpublished_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'feed.xml'
            old, missing, unpublished = (episode(key) for key in ('post-old', 'post-missing', 'post-unpublished'))
            original = feed.build('https://original.example', [old, missing])
            path.write_text(original)
            state = storage.migrate({'episodes': [old, unpublished], 'seen': ['retired-history'], 'retry': []}, path)
            self.assertEqual({e['guid'] for e in state['episodes']}, {'post-old', 'post-missing', 'post-unpublished'})
            self.assertTrue({'retired-history', 'post-old', 'post-missing', 'post-unpublished'} <= set(state['seen']))
            rebuilt = ET.fromstring(feed.build('https://different.example', state['episodes']))
            before = ET.fromstring(original)
            wanted = next(e for e in rebuilt.findall('channel/item') if e.findtext('guid').endswith('/post-missing'))
            public = next(e for e in before.findall('channel/item') if e.findtext('guid').endswith('/post-missing'))
            for tag in ('guid', 'description', 'pubDate', 'title', 'link'):
                self.assertEqual(wanted.findtext(tag), public.findtext(tag))
            self.assertEqual(wanted.find('enclosure').attrib, public.find('enclosure').attrib)

    def test_recovered_split_parts_keep_one_seen_source_and_do_not_duplicate_on_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'feed.xml'
            parts = [episode('post-shared-part-'+str(i).zfill(3)) for i in (1, 2)]
            path.write_text(feed.build('https://fictional.example', parts))
            state = storage.migrate({'episodes': [], 'seen': [], 'retry': []}, path)
            state = storage.migrate(state, path)
            self.assertEqual(len(state['episodes']), 2)
            self.assertEqual(state['seen'], ['post-shared'])

    def test_published_copy_of_queued_article_is_preserved_without_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full'}, clear=True):
            settings = config.Settings.from_env()
            settings.site.mkdir()
            pub = {'base': 'https://fictional.example/feed', 'name': 'Research Notes', 'rss': True, 'mode': 'full'}
            post = {'id': 2, 'title': 'A published report', 'post_date': NOW, 'body_html': '<p>Already published.</p>'}
            key = main.post_key(pub, post)
            old, recovered = episode('post-old'), episode(key)
            (settings.site/'feed.xml').write_text(feed.build('https://original.example', [old, recovered]))
            storage.save(settings, {'episodes': [old], 'seen': ['retired-history'],
                                    'retry': [{'pub': pub, 'post': post}], 'last_run': None})
            source = types.SimpleNamespace(recent_posts=lambda _: [post])
            with patch('main.make_episode', side_effect=AssertionError('Published audio must not be regenerated')), \
                    patch('main.refresh_descriptions'), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.run(settings, [pub], source), 0)
            state = storage.load(settings)
            self.assertEqual(len(state['episodes']), 2)
            self.assertEqual(len(feed.read(settings.site/'feed.xml')), 2)
            self.assertEqual(state['retry'], [])
            self.assertIn('retired-history', state['seen'])
            self.assertIn(key, state['seen'])

    def test_source_outage_leaves_retry_payload_and_publication_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full'}, clear=True):
            settings = config.Settings.from_env()
            settings.site.mkdir()
            pub = {'base': 'https://fictional.example/feed', 'name': 'Research Notes', 'rss': True, 'mode': 'full'}
            queued = {'id': 3, 'title': 'A queued report', 'post_date': NOW, 'body_html': '<p>Original text.</p>'}
            document = feed.build('https://original.example', [episode('post-old'), episode('post-missing')])
            (settings.site/'feed.xml').write_text(document)
            storage.save(settings, {'episodes': [episode('post-old')], 'seen': ['retired-history'],
                                   'retry': [{'pub': pub, 'post': queued}], 'last_run': None})
            saved = (settings.state_dir/'state.json').read_bytes()
            def unavailable(_):
                raise OSError('PRIVATE fictional provider details')
            source = types.SimpleNamespace(recent_posts=unavailable)
            with patch('main.make_episode', side_effect=AssertionError('Outage must not consume retries')), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main.run(settings, [pub], source), 1)
            self.assertEqual((settings.state_dir/'state.json').read_bytes(), saved)
            self.assertEqual((settings.site/'feed.xml').read_text(), document)
            self.assertNotIn('PRIVATE', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
