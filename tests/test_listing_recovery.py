"""Listing imports retain distinct articles and recover incomplete source scans."""
import contextlib
from datetime import datetime, timedelta, timezone
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
from curl_cffi.requests.exceptions import Timeout

PUB = {'base': 'https://fictional.example', 'page': '/stories/', 'name': 'Science Notes', 'mode': 'full'}
BODY = ('An original article describes how researchers compare careful observations across several seasons '
        'and use those measurements to plan better experiments for the next year.')
NOW = datetime.now(timezone.utc)


def article(title, days=1, body=BODY):
    date = (NOW - timedelta(days=days)).strftime('%B %d, %Y')
    return ('<title>'+title+'</title><main><h1>'+title+'</h1><p>'+date+'</p>'
            '<div class="w-richtext"><p>'+body+'</p></div></main>')


class ListingRecoveryTests(unittest.TestCase):
    def run_pipeline(self, fetch, *, runs=1, scheduled=False, manual_backfill=False):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full',
                **({'GITHUB_EVENT_NAME': 'schedule'} if scheduled else {})}, clear=True):
            settings = config.Settings.from_env()
            initial = {'episodes': [], 'seen': [], 'retry': [], 'last_run': (NOW-timedelta(days=2 if manual_backfill else 30)).isoformat(),
                       'last_scheduled_run': (NOW-timedelta(days=30)).isoformat()}
            storage.save(settings, initial)
            source = Substack('')
            spoken, snapshots = [], []
            def narrate(text, path, limit, intro):
                spoken.append(intro)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'ID3-fixture')
                return [path]
            with patch.object(source, 'get', side_effect=fetch), patch('tts.synthesize_full', side_effect=narrate), \
                    patch('tts.duration', return_value=10), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                for index in range(runs):
                    if manual_backfill and index == 0:
                        os.environ['LOOKBACK_HOURS'] = '720'
                    else:
                        os.environ.pop('LOOKBACK_HOURS', None)
                    settings = config.Settings.from_env()
                    status = main.run(settings, [PUB], source)
                    snapshots.append((status, storage.load(settings)))
            return initial, snapshots, spoken, errors.getvalue()

    def test_same_title_at_distinct_urls_publishes_both_and_deduplicates_reruns(self):
        def fetch(url, **kwargs):
            if url == PUB['base']:
                return '<a href="/stories/one">One</a><a href="/stories/two">Two</a>'
            return article('Weekly Roundup', 1 if url.endswith('/one') else 2,
                           BODY if url.endswith('/one') else BODY+' A separate region has different results.')
        _, snapshots, spoken, _ = self.run_pipeline(fetch, runs=2)
        self.assertEqual(len(spoken), 2)
        for status, state in snapshots:
            self.assertEqual(status, 0)
            self.assertEqual(len(state['episodes']), 2)
            self.assertEqual(len(set(e['source_key'] for e in state['episodes'])), 2)
            self.assertEqual(state['retry'], [])

    def test_partial_download_preserves_catchup_and_scheduled_window_until_recovery(self):
        attempts = []
        def fetch(url, **kwargs):
            if url == PUB['base']:
                return '<a href="/stories/old">Old</a><a href="/stories/recent">Recent</a>'
            if url.endswith('/old'):
                attempts.append(url)
                if len(attempts) == 1:
                    raise Timeout('PRIVATE source detail')
                return article('Older story', 10)
            return article('Recent story')
        for scheduled in (False, True):
            attempts.clear()
            with self.subTest(scheduled=scheduled):
                initial, snapshots, spoken, errors = self.run_pipeline(fetch, runs=2, scheduled=scheduled)
                first_status, first = snapshots[0]
                status, recovered = snapshots[1]
                self.assertEqual((first_status, status), (0, 0))
                self.assertEqual(len(first['episodes']), 1)
                self.assertEqual(first['last_run'], initial['last_run'])
                self.assertEqual(first['last_scheduled_run'], initial['last_scheduled_run'])
                self.assertEqual(len(recovered['episodes']), 2)
                self.assertNotEqual(recovered['last_run'], initial['last_run'])
                self.assertIn('catchup_since', first)
                self.assertNotIn('catchup_since', recovered)
                if scheduled:
                    self.assertNotEqual(recovered['last_scheduled_run'], initial['last_scheduled_run'])
                self.assertEqual(len(spoken), 2)
                self.assertIn('Older story', spoken[-1])
                self.assertNotIn('PRIVATE', errors)

    def test_manual_backfill_window_survives_the_next_default_run(self):
        attempts = []
        def fetch(url, **kwargs):
            if url == PUB['base']:
                return '<a href="/stories/old">Old</a><a href="/stories/recent">Recent</a>'
            if url.endswith('/old'):
                attempts.append(url)
                if len(attempts) == 1:
                    raise Timeout('Fixture timeout')
                return article('Older story', 10)
            return article('Recent story')
        initial, snapshots, spoken, _ = self.run_pipeline(fetch, runs=2, manual_backfill=True)
        first, recovered = snapshots[0][1], snapshots[1][1]
        self.assertEqual(first['last_run'], initial['last_run'])
        self.assertLess(datetime.fromisoformat(first['catchup_since']), NOW-timedelta(days=29))
        self.assertEqual(len(recovered['episodes']), 2)
        self.assertEqual(len(spoken), 2)
        self.assertNotIn('catchup_since', recovered)

    def test_all_article_downloads_failed_preserves_state_and_fails_the_run(self):
        def fetch(url, **kwargs):
            if url == PUB['base']:
                return '<a href="/stories/old">Old</a>'
            raise Timeout('PRIVATE source detail')
        initial, snapshots, spoken, errors = self.run_pipeline(fetch, scheduled=True)
        status, state = snapshots[0]
        self.assertEqual(status, 1)
        self.assertEqual(state, initial)
        self.assertEqual(spoken, [])
        self.assertIn('All sources unavailable', errors)
        self.assertNotIn('PRIVATE', errors)

    def test_header_date_does_not_make_a_recent_article_ineligible(self):
        def fetch(url, **kwargs):
            if url == PUB['base']:
                return '<a href="/stories/one">One</a>'
            return '<header>Serving readers since January 1, 2000.</header>'+article('A discovery')
        _, snapshots, spoken, _ = self.run_pipeline(fetch)
        self.assertEqual(snapshots[0][0], 0)
        self.assertEqual(len(spoken), 1)


class ListingDateAndStatusTests(unittest.TestCase):
    def discover(self, html):
        source = Substack('')
        with patch.object(source, 'get', side_effect=['<a href="/stories/one">One</a>', html]):
            return source.recent_posts(PUB)

    def test_publication_metadata_wins_over_dates_in_prose_and_site_chrome(self):
        html = ('<meta property="article:published_time" content="2026-10-25T09:30:00-07:00">'
                '<header>January 1, 2000</header>'+article('A discovery', 100))
        self.assertEqual(self.discover(html)[0]['post_date'], '2026-10-25T09:30:00-07:00')

    def test_article_datetime_is_scoped_and_hidden_or_modified_values_are_ignored(self):
        html = ('<header><time datetime="2000-01-01">January 1, 2000</time></header>'
                '<main><h1>A discovery</h1><time hidden datetime="2001-01-01"></time>'
                '<time itemprop="dateModified" datetime="2002-01-01"></time>'
                '<time itemprop="datePublished" datetime="2026-10-25T14:00:00Z"></time>'
                '<div class="w-richtext"><p>'+BODY+'</p></div></main>')
        self.assertEqual(self.discover(html)[0]['post_date'], '2026-10-25T14:00:00+00:00')

    def test_unmarked_layout_ignores_global_header_footer_and_hidden_dates(self):
        html = ('<title>A discovery</title><header><time datetime="2000-01-01">January 1, 2000</time></header>'
                '<div hidden>January 2, 2000</div><div><h1>A discovery</h1><p>October 25, 2026</p>'
                '<div class="w-richtext"><p>'+BODY+'</p></div></div><footer>January 3, 2000</footer>')
        self.assertEqual(self.discover(html)[0]['post_date'], '2026-10-25T12:00:00+00:00')

    def test_other_article_metadata_cannot_supply_the_publication_date(self):
        other = ('<article><h2>Another story</h2>'
                 '<meta itemprop="datePublished" content="2000-01-01"></article>')
        html = article('A discovery')+other
        expected = (NOW-timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
        self.assertEqual(self.discover(html)[0]['post_date'], expected)

    def test_unmarked_article_header_keeps_its_date_when_the_headline_matches(self):
        for date in ('<p>October 25, 2026</p>', '<time datetime="2026-10-25T12:00:00Z">October 25, 2026</time>'):
            html = ('<title>A discovery</title><header>January 1, 2000</header>'
                    '<div><header><h1>A discovery</h1>'+date+'</header>'
                    '<div class="w-richtext"><p>'+BODY+'</p></div></div>')
            with self.subTest(date=date):
                self.assertEqual(self.discover(html)[0]['post_date'], '2026-10-25T12:00:00+00:00')

    def test_copy_drafts_still_skip_and_incomplete_status_does_not_leak_to_next_source(self):
        source = Substack('')
        listing = '<a href="/stories/bad">Bad</a><a href="/stories/one-copy">Copy</a><a href="/stories/good">Good</a>'
        with patch.object(source, 'get', side_effect=[listing, Timeout('Fixture timeout'),
                article('A discovery Copy'), article('A discovery'), '<a href="/stories/good">Good</a>', article('A discovery')]):
            partial = source.recent_posts(PUB)
            complete = source.recent_posts(PUB)
        self.assertEqual(len(partial), 1)
        self.assertFalse(partial.complete)
        self.assertEqual(len(complete), 1)
        self.assertTrue(complete.complete)


if __name__ == '__main__':
    unittest.main()
