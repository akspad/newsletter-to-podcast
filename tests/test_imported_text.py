"""Narration text must retain readable facts and inline word boundaries."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from substack import html_to_text


class ImportedTextTests(unittest.TestCase):
    def test_explicitly_hidden_nodes_and_their_children_are_not_narrated(self):
        html = ('<p>A visible opening.</p><div hidden><p>Hidden draft.</p><span hidden>Nested draft.</span></div>'
                '<p style="DISPLAY: /* layout */ none !important; display: block">Hidden copy.</p>'
                '<p aria-hidden="TRUE">Hidden accessibility duplicate.</p><p>A visible ending.</p>')
        self.assertEqual(html_to_text(html), 'A visible opening.\nA visible ending.')

    def test_visibility_cleanup_keeps_visible_overrides_and_unresolved_classes(self):
        html = ('<p style="display: none; display: block">Visible override.</p>'
                '<p style="display: block !important; display: none">Visible priority.</p>'
                '<p aria-hidden="false">Visible accessibility text.</p><p class="hidden">Class-only prose.</p>'
                '<p>H<sub>2</sub>O and &lt;vector&gt; remain.</p>')
        self.assertEqual(html_to_text(html), 'Visible override.\nVisible priority.\nVisible accessibility text.\nClass-only prose.\nH2O and <vector> remain.')

    def test_tables_code_and_direct_text_survive_beside_paragraphs(self):
        html = ('An introduction.<p>Available memory:</p><table><caption>Device details</caption>'
                '<tr><th>Model</th><th>Memory</th></tr><tr><td>Atlas</td><td>16 GB</td></tr></table>'
                '<pre>limit = 16\nuse &lt;vector&gt;</pre><div>An ending.</div>')
        self.assertEqual(html_to_text(html), 'An introduction.\nAvailable memory:\nDevice details\nModel Memory\nAtlas 16 GB\nlimit = 16\nuse <vector>\nAn ending.')

    def test_inline_words_punctuation_and_entities_remain_intact(self):
        html = ('<!doctype html><html><head><title>Do not read metadata</title></head><body>'
                '<p><span>A</span>n <em>example</em>s sentence, with a <a>link</a> and &amp; entity.</p>'
                '<!-- Do not narrate comments --><p>Before<br>After</p>'
                '<button>Do not read controls</button></body></html>')
        self.assertEqual(html_to_text(html), 'An examples sentence, with a link and & entity.\nBefore\nAfter')

    def test_nested_lists_quotes_and_captions_are_read_once(self):
        html = ('<blockquote><p>A quoted sentence.</p><p>Another quoted sentence.</p></blockquote>'
                '<ul><li><p>First item.</p><ul><li>Nested item.</li></ul></li><li>Second item.</li></ul>'
                '<figure><figcaption><p>A caption.</p></figcaption></figure>'
                '<div class="subscription-widget-wrap"><p>Do not read subscribe.</p></div>')
        self.assertEqual(html_to_text(html), 'A quoted sentence.\nAnother quoted sentence.\nFirst item.\nNested item.\nSecond item.\nA caption.')


if __name__ == '__main__':
    unittest.main()
