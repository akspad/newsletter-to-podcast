"""Generation failures alert after durable output; expected deferrals stay healthy."""
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import feed
import main
import monitoring
import security
from test_workflow_security import workflow

ROOT = Path(__file__).resolve().parents[1]


def health_script():
    health = workflow(ROOT / '.github/workflows/daily.yml')['jobs']['health']
    return health['steps'][0]['run'].split("<<'PYHEALTH'\n", 1)[1].rsplit('\nPYHEALTH', 1)[0]


class GenerationMonitoringTests(unittest.TestCase):
    def run_case(self, root, outcomes, maximum=20):
        env = {'SITE_DIR': str(root / 'site'), 'STATE_DIR': str(root / 'state'),
               'GITHUB_OUTPUT': str(root / 'outputs'), 'GITHUB_STEP_SUMMARY': str(root / 'summary'),
               'MAX_EPISODES_PER_RUN': str(maximum), 'EPISODE_MODE': 'full'}
        now = datetime.now(timezone.utc).isoformat()
        pub = {'base': 'https://fictional.example', 'name': 'PRIVATE PUBLICATION', 'mode': 'full'}
        posts = [{'id': index, 'title': 'PRIVATE TITLE', 'slug': str(index), 'wordcount': 100,
                  'post_date': now, 'body_html': 'PRIVATE ARTICLE'} for index in range(len(outcomes))]
        source = types.SimpleNamespace(recent_posts=lambda _: posts)
        def generate(sub, publication, post, timestamp, state, settings):
            result = outcomes[post['id']]
            if result:
                raise result
            path = settings.site / 'episodes' / f"new-{post['id']}.mp3"
            path.write_bytes(b'fictional audio')
            state['episodes'].append({'guid': f"new-{post['id']}", 'source_key': f"new-{post['id']}",
                'title': 'PRIVATE TITLE', 'description': 'PRIVATE ARTICLE', 'link': pub['base'],
                'published': now, 'file': path.name, 'bytes': path.stat().st_size, 'duration': 1})
        with patch.dict(os.environ, env, clear=True), patch('main.make_episode', side_effect=generate), \
                patch('main.refresh_descriptions'), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            settings = config.Settings.from_env()
            result = main.run(settings, [pub], source)
        counts = dict(line.split('=', 1) for line in (root / 'outputs').read_text().splitlines())
        return result, counts, json.loads((root / 'state/state.json').read_text())

    def health(self, root, counts, build='success', publish='success', public='true'):
        env = {'BUILD_RESULT': build, 'PUBLISH_RESULT': publish, 'PUBLISH_TO_PAGES': public,
               'GITHUB_STEP_SUMMARY': str(root / 'health-summary')}
        env.update({key.upper(): value for key, value in counts.items()})
        return subprocess.run([sys.executable, '-I', '-c', health_script()], env=env,
                              capture_output=True, text=True)

    def test_partial_failure_preserves_feed_audio_and_retry_before_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, counts, state = self.run_case(root, [None, RuntimeError('PRIVATE raw provider error')])
            self.assertEqual(result, 0)  # keep the publisher eligible
            self.assertEqual(counts['failed_articles'], '1')
            self.assertEqual(counts['created_audio_files'], '1')
            self.assertEqual(counts['queued_articles'], '1')
            self.assertEqual(len(state['episodes']), 1)
            self.assertEqual(len(state['retry']), 1)
            self.assertEqual(len(feed.read(root / 'site/feed.xml')), 1)
            self.assertTrue((root / 'site/episodes/new-0.mp3').exists())
            self.assertEqual(self.health(root, counts).returncode, 1)
            self.assertNotIn('PRIVATE', (root / 'summary').read_text())
            self.assertNotIn('PRIVATE', (root / 'health-summary').read_text())

    def test_all_generation_failures_are_reported_while_retries_are_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, counts, state = self.run_case(root, [RuntimeError('failed'), RuntimeError('failed')])
            self.assertEqual(result, 0)
            self.assertEqual(counts['failed_articles'], '2')
            self.assertEqual(counts['created_audio_files'], '0')
            self.assertEqual(len(state['retry']), 2)
            self.assertEqual(self.health(root, counts).returncode, 1)

    def test_empty_run_and_successful_generation_stay_healthy(self):
        for outcomes in ([], [None]):
            with self.subTest(outcomes=outcomes), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result, counts, _ = self.run_case(root, outcomes)
                self.assertEqual(result, 0)
                self.assertEqual(counts['failed_articles'], '0')
                self.assertEqual(self.health(root, counts).returncode, 0)

    def test_security_skips_run_budget_and_article_cap_deferrals_do_not_alert(self):
        cases = [([security.BudgetExceeded('limit')], 20, 'skipped_articles', '0'),
                 ([security.RunBudgetExceeded('limit')], 20, 'deferred_articles', '1'),
                 ([None, None], 1, 'deferred_articles', '1')]
        for outcomes, maximum, category, queued in cases:
            with self.subTest(category=category, maximum=maximum), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, counts, _ = self.run_case(root, outcomes, maximum)
                self.assertEqual(counts[category], '1')
                self.assertEqual(counts['queued_articles'], queued)
                self.assertEqual(counts['failed_articles'], '0')
                self.assertEqual(self.health(root, counts).returncode, 0)

    def test_invalid_or_missing_report_and_build_or_publisher_failure_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, counts, _ = self.run_case(root, [])
            for altered in ({}, {**counts, 'failed_articles': '1\n::warning::fake'},
                            {**counts, 'failed_articles': '-1'}):
                self.assertEqual(self.health(root, altered).returncode, 1)
            self.assertEqual(self.health(root, counts, build='failure').returncode, 1)
            self.assertEqual(self.health(root, counts, build='cancelled').returncode, 1)
            self.assertEqual(self.health(root, counts, publish='failure').returncode, 1)
            self.assertEqual(self.health(root, counts, publish='skipped', public='false').returncode, 0)

    def test_report_rejects_noninteger_counts_and_appends_only_numeric_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            output.write_text('existing=value\n')
            with patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}, clear=True):
                monitoring.GenerationReport(created_articles=1).emit()
                self.assertTrue(output.read_text().startswith('existing=value\n'))
                for value in (-1, True, '1\n::error::fake'):
                    with self.assertRaises(ValueError):
                        monitoring.GenerationReport(failed_articles=value).emit()

    def test_workflow_checks_health_after_publication_without_secret_or_write_access(self):
        jobs = workflow(ROOT / '.github/workflows/daily.yml')['jobs']
        self.assertEqual(jobs['health']['needs'], ['build', 'publish'])
        self.assertIn('always()', jobs['health']['if'])
        self.assertIn("due == 'true'", jobs['health']['if'])
        self.assertIn("!= 'skipped'", jobs['health']['if'])
        self.assertEqual(jobs['publish']['needs'], 'build')
        self.assertEqual(jobs['health']['permissions'], {'contents': 'read'})
        self.assertNotIn('secrets.', json.dumps(jobs['health']))
        self.assertNotIn('uses', jobs['health']['steps'][0])
        self.assertIn('steps.generation.outputs.failed_articles', jobs['build']['outputs']['failed_articles'])


if __name__ == '__main__':
    unittest.main()
