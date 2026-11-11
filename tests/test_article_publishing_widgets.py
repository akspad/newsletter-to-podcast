"""Publishing panels and opening writer credits must not replace or eat prose."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview
from substack import html_to_text

BODY = ('The researchers compared observations from several regions and carefully checked the evidence. '
        'Their report explains how each result was measured and why independent review matters for interpreting the findings.')
CREDIT = 'This blog was written and prepared by PLOS editor Jenna Scaramanga'
LICENSE = ('<div class="cc-attribution"><p>The text in this work is licensed under a '
           '<a href="https://creativecommons.org/licenses/by/4.0/">Creative Commons licence</a>. '
           'Images are copyright the university.</p></div>')
PANELS = ('<section id="article-citation"><h3>Cite this work</h3><p>A publisher citation.</p>'
          '<pre>@article{export, author={A Writer}}</pre></section>'
          '<section id="article-past-versions"><h3>Past versions</h3><p>Browse earlier versions.</p></section>'
          '<section id="article-licence"><h3>Reuse this work freely</h3><p>A publisher licence.</p></section>')


def read(body, author='PLOS ONE Editors', wrapper='article'):
    html = ('<title>A data story</title><meta name="author" content="' + author + '">'
            '<' + wrapper + '><h1>A data story</h1><div class="entry-content">' + body +
            '</div></' + wrapper.split()[0] + '>')
    with patch('substack.Substack.get', return_value=html), contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text('https://fictional.example/story')


class PublishingWidgetTests(unittest.TestCase):
    def test_cover_teaser_repeated_as_the_opening_sentence_is_read_once(self):
        sentence = 'A careful comparison of several regions revealed important new evidence for the research team'
        cover = '<div class="wp-block-cover__inner-container"><h1>A data story</h1><p>' + sentence + '</p></div>'
        text = read(cover + '<p>' + sentence + '. ' + BODY + '</p>').partition('\n')[2]
        self.assertEqual(text, sentence + '. ' + BODY)

    def test_distinct_decks_quotes_and_intentional_body_repetition_survive(self):
        sentence = 'A careful comparison of several regions revealed important new evidence for the research team'
        cover = '<div class="wp-block-cover__inner-container"><h1>A data story</h1><p>' + sentence + '</p></div>'
        for markup in (cover + '<p>' + BODY + '</p>', '<blockquote>' + cover + '</blockquote><p>' + sentence + '. ' + BODY + '</p>',
                       '<p>' + sentence + '.</p><p>' + sentence + '. ' + BODY + '</p>'):
            text = read(markup).partition('\n')[2]
            self.assertIn(sentence, text)
            if markup.startswith(('<blockquote>', '<p>')):
                self.assertEqual(text.count(sentence), 2)

    def test_marked_licence_is_omitted_but_research_reference_survives(self):
        reference = 'Reference: A research paper. DOI: 10.0000/research.'
        text = read('<p>' + BODY + '</p><p>' + reference + '</p>' + LICENSE)
        self.assertEqual(text.partition('\n')[2], BODY + ' ' + reference)

    def test_quoted_licence_and_unmarked_licence_prose_survive(self):
        for markup in ('<blockquote>' + LICENSE + '</blockquote>', LICENSE.replace('class="cc-attribution"', '')):
            with self.subTest(markup=markup[:30]):
                text = read('<p>' + BODY + '</p>' + markup)
                self.assertIn('The text in this work is licensed', text)

    def test_attribution_class_does_not_remove_other_or_continued_prose(self):
        for markup in ('<div class="cc-attribution"><p>A discussion of licence choices.</p></div>',
                LICENSE.replace('</div>', '<p>Further research conclusions belong here.</p></div>')):
            text = read('<p>' + BODY + '</p>' + markup)
            self.assertIn('licence', text.lower())
            if 'Further' in markup:
                self.assertIn('Further research conclusions belong here.', text)

    def test_marked_publication_panels_leave_endnotes_and_editorial_code_intact(self):
        prose = '<p>' + BODY + '</p><section class="footnote-container"><h3>Endnotes</h3>'
        prose += '<p>A research citation belongs to the article.</p></section><pre>@article{a legitimate code example}</pre>'
        text = read(prose + PANELS, wrapper='article class="centered-article-container"').partition('\n')[2]
        self.assertEqual(text, BODY + ' Endnotes A research citation belongs to the article. @article{a legitimate code example}')

    def test_unmatched_or_quoted_panels_are_not_removed(self):
        for markup, wrapper in ((PANELS, 'article'), ('<blockquote>' + PANELS + '</blockquote>',
                                                     'article class="centered-article-container"'),
                (PANELS.replace('Cite this work', 'An editorial section'), 'article class="centered-article-container"')):
            text = read('<p>' + BODY + '</p>' + markup, wrapper=wrapper)
            self.assertIn('A publisher citation.', text)

    def test_numbered_note_controls_are_removed_without_losing_math_or_citations(self):
        markup = ('<p>' + BODY + '<a class="ref" href="#note-1"><sup>1</sup></a></p>'
                  '<p>Carbon dioxide is CO<sub>2</sub>. See <a class="ref" href="#source">the study</a>.</p>'
                  '<section><p id="note-1">A retained research citation.</p></section>')
        body = read(markup).partition('\n')[2]
        self.assertEqual(body, BODY + ' Carbon dioxide is CO2. See the study. A retained research citation.')
        imported = html_to_text(markup)
        self.assertIn('A retained research citation.', imported)
        self.assertNotIn('findings.1', imported)


class OpeningWriterTests(unittest.TestCase):
    def test_explicit_opening_writer_replaces_posting_account_and_is_attributed_once(self):
        text = read('<div class="single-content"><p>' + CREDIT + '</p><p>' + BODY + '</p></div>')
        self.assertTrue(text.partition('\n')[0].endswith('By Jenna Scaramanga.'))
        self.assertEqual(text.partition('\n')[2], BODY)
        self.assertEqual(text.count('Jenna Scaramanga'), 1)

    def test_quote_hidden_unrelated_and_later_credits_cannot_set_the_author(self):
        cases = ('<blockquote><div class="single-content"><p>' + CREDIT + '</p></div></blockquote>',
                 '<div class="single-content"><p hidden>' + CREDIT + '</p></div>',
                 '<article><div class="single-content"><p>' + CREDIT + '</p></div></article>',
                 '<div class="single-content"><p>' + BODY + '</p><p>' + CREDIT + '</p></div>')
        for markup in cases:
            with self.subTest(markup=markup[:40]):
                text = read('<p>' + BODY + '</p>' + markup)
                self.assertTrue(text.partition('\n')[0].endswith('By PLOS ONE Editors.'))

    def test_named_author_and_coauthors_survive_an_opening_contributor_credit(self):
        markup = '<div class="single-content"><p>' + CREDIT + '</p><p>' + BODY + '</p></div>'
        for author in ('Alex Writer', 'Alex Writer, Sam Writer'):
            text = read(markup, author=author)
            self.assertTrue(text.partition('\n')[0].endswith('By ' + author + '.'))
            self.assertIn(CREDIT, text.partition('\n')[2])

    def test_unicode_writer_name_survives_inline_markup(self):
        credit = CREDIT.replace('Jenna Scaramanga', '<strong>Éléonore O’Neill</strong>')
        text = read('<div class="single-content"><p>' + credit + '</p><p>' + BODY + '</p></div>')
        self.assertTrue(text.partition('\n')[0].endswith('By Éléonore O’Neill.'))
        self.assertEqual(text.partition('\n')[2], BODY)


if __name__ == '__main__':
    unittest.main()
