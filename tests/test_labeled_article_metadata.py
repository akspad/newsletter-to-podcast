"""Labeled article mastheads must beat subsection headings without eating definitions."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview

BODY = ('This lab note describes a prototype that lets researchers compare measurements from several experiments. '
        'The team explains the design decisions and records the results so that other researchers can repeat the work.')
LABELS = ('<dl class="macrodata"><div><dt>title</dt><dd>Userspace experiments</dd></div>'
          '<div><dt>dated</dt><dd>October 2026</dd></div>'
          '<div><dt>author</dt><dd>Alex Researcher</dd></div></dl>')


def read(body):
    html = ('<title>Userspace experiments</title><meta property="og:title" content="Userspace experiments">'
            '<meta property="og:site_name" content="Research Notes"><main>'+body+'</main>')
    with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text('https://fictional.example/note')


class LabeledArticleMetadataTests(unittest.TestCase):
    def test_masthead_supplies_title_and_author_without_removing_first_subsection(self):
        text = read(LABELS+'<p>'+BODY+'</p><h1>A simple example</h1><p>A short conclusion.</p>')
        self.assertEqual(text.partition('\n')[0], 'Research Notes. Userspace experiments. By Alex Researcher.')
        self.assertEqual(text.partition('\n')[2], BODY+' A simple example A short conclusion.')

    def test_labeled_coauthors_survive_as_one_credit(self):
        labels = LABELS.replace('Alex Researcher', '<a href="/authors/alex">Alex Researcher</a> and '
                               '<a href="/authors/sam">Sam Researcher</a>')
        text = read(labels+'<p>'+BODY+'</p><h1>A subsection</h1><p>A short conclusion.</p>')
        self.assertIn('By Alex Researcher, Sam Researcher.', text.partition('\n')[0])
        self.assertEqual(text.partition('\n')[2], BODY+' A subsection A short conclusion.')

    def test_quoted_hidden_and_unmatched_labels_do_not_override_attribution(self):
        for labels in ('<blockquote>'+LABELS+'</blockquote>', '<div hidden>'+LABELS+'</div>',
                       LABELS.replace('<dd>Userspace experiments</dd>', '<dd hidden>Userspace experiments</dd>'),
                       LABELS.replace('Userspace experiments', 'An unrelated article')):
            with self.subTest(labels=labels[:80]):
                text = read('<h1>Userspace experiments</h1><p>'+BODY+'</p>'+labels)
                self.assertEqual(text.partition('\n')[0], 'Research Notes. Userspace experiments.')
                self.assertIn(BODY, text)
                if labels.startswith('<blockquote>'):
                    self.assertIn('Alex Researcher', text.partition('\n')[2])

    def test_ordinary_definitions_and_unrecognized_masthead_fields_are_preserved(self):
        for definitions in (LABELS.replace(' class="macrodata"', ''),
                            LABELS.replace('</dl>', '<div><dt>method</dt><dd>Compare all observations carefully.</dd></div></dl>')):
            with self.subTest(definitions=definitions[:80]):
                text = read('<h1>Userspace experiments</h1><p>'+BODY+'</p>'+definitions)
                self.assertIn('title Userspace experiments', text.partition('\n')[2])
                self.assertIn('author Alex Researcher', text.partition('\n')[2])


if __name__ == '__main__':
    unittest.main()
