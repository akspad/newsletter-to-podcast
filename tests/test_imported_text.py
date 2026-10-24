"""Narration text must retain readable facts and inline word boundaries."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from substack import html_to_text


class ImportedTextTests(unittest.TestCase):
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
