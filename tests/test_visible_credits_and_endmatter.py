"""Visible writers beat posting accounts while citations and prose survive cleanup."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import preview
from substack import html_to_text

URL='https://fictional.example/story'
BODY=('The research team compared careful observations from several regions and explained how the measurements fit together. '
      'Independent reviewers checked the records and repeated the experiments before publishing their conclusions.')


def read(content, authors=None):
    schema={'@type':'Article','url':URL,'headline':'A discovery','author':authors or {'name':'Posting Account'}}
    html=('<title>A discovery</title><meta property="og:site_name" content="Research Notes">'
          '<script type="application/ld+json">'+json.dumps(schema)+'</script>'+content)
    with patch('substack.Substack.get',return_value=html),contextlib.redirect_stderr(io.StringIO()):
        return preview.article_text(URL)


class VisibleCreditTests(unittest.TestCase):
    def test_single_linked_byline_overrides_posting_account(self):
        text=read('<article><h1>A discovery</h1><p class="byline">By '
                  '<a href="/author/alex">Alex Writer</a></p><div class="entry-content"><p>'+BODY+'</p></div></article>')
        self.assertEqual(text.partition('\n')[0],'Research Notes. A discovery. By Alex Writer.')
        self.assertEqual(text.partition('\n')[2],BODY)

    def test_visible_single_author_does_not_remove_agreeing_structured_coauthors(self):
        text=read('<article><h1>A discovery</h1><p class="byline">By '
                  '<a href="/author/alex">Alex Writer</a></p><p>'+BODY+'</p></article>',
                  [{'name':'Alex Writer'},{'name':'Sam Writer'}])
        self.assertTrue(text.partition('\n')[0].endswith('By Alex Writer, Sam Writer.'))

    def test_article_header_byline_taxonomy_overrides_editor_without_borrowing_other_cards(self):
        header=('<div class="single-article-meta"><span class="bylines">'
                '<a href="/by/alex/" rel="tag">Alex Writer</a> and '
                '<a href="/by/sam/" rel="tag">Sam Writer</a></span></div>')
        text=read('<aside>'+header.replace('Alex Writer','Other Writer')+'</aside>'+header+
                  '<article><h1>A discovery</h1><p>'+BODY+'</p></article>')
        self.assertTrue(text.partition('\n')[0].endswith('By Alex Writer, Sam Writer.'))
        self.assertNotIn('Other Writer',text)

    def test_quoted_byline_cannot_override_article_attribution(self):
        for name in ('Quoted Writer', 'Posting Account'):
            text=read('<article><h1>A discovery</h1><div class="entry-content"><p>'+BODY+'</p><blockquote><p class="byline">By '
                      '<a href="/author/quoted" rel="author">'+name+'</a></p></blockquote></div></article>')
            self.assertTrue(text.partition('\n')[0].endswith('By Posting Account.'))
            self.assertEqual(text.partition('\n')[2],BODY+' By '+name)


class EndmatterTests(unittest.TestCase):
    def test_partial_emphasis_in_caption_named_prose_is_preserved(self):
        for label in ('Lead Image:', 'Banner Image:'):
            prose = label + ' The Illustrated World is the name of the exhibition discussed in this article.'
            text = read('<article><div class="entry-content"><p>' + BODY + '</p><p>' + label +
                        ' <em>The Illustrated World</em> is the name of the exhibition discussed in this article.</p>'
                        '</div></article>')
            self.assertEqual(text.partition('\n')[2], BODY + ' ' + prose)

    def test_marked_feedback_and_author_bio_are_omitted_but_reporting_credit_remains(self):
        content=('<article><h1>A discovery</h1><p class="byline"><a href="/author/alex">Alex Writer</a></p>'
                 '<div class="entry-content"><p>'+BODY+'</p><p><i>Sam Writer contributed reporting.</i></p>'
                 '<p><i><b>Banner image:</b> An image of the research site.</i></p>'
                 '<p><i>Alex Writer is a staff writer. Find them on <a href="https://social.example/alex">Social</a>.</i></p>'
                 '<p><b>FEEDBACK: <a href="https://forms.example">Use this form</a> to contact us.</b></p>'
                 '<div id="single-article-footer">Cite this article. Credits and related stories.</div></div></article>')
        text=read(content)
        self.assertEqual(text.partition('\n')[2],BODY+' Sam Writer contributed reporting.')

    def test_unmarked_feedback_narrative_and_quoted_footer_are_preserved(self):
        tail=('<p><i>Alex Writer is explaining the results. Find them on '
              '<a href="https://research.example">the project page</a>.</i></p>'
              '<p><b>FEEDBACK: <a href="https://forms.example">Use this form</a> to contact us.</b></p>')
        for value in (tail,'<blockquote>'+tail+'<div id="single-article-footer">Quoted footer details.</div></blockquote>'):
            with self.subTest(value=value[:80]):
                text=read('<article><div class="entry-content"><p>'+BODY+'</p>'+value+'</div></article>')
                self.assertIn('Alex Writer is explaining the results.',text)
                self.assertIn('FEEDBACK:',text)

    def test_prose_before_a_marked_footer_is_not_treated_as_an_author_bio(self):
        prose='Alex Writer is explaining the measurements. Find them on the project page.'
        content=('<article><p class="byline"><a href="/author/alex">Alex Writer</a></p>'
                 '<div class="entry-content"><p>'+BODY+'</p><p><i>Alex Writer is explaining the measurements. '
                 'Find them on <a href="https://research.example">the project page</a>.</i></p>'
                 '<p><b>FEEDBACK: <a href="https://forms.example">Use this form</a> to contact us.</b></p>'
                 '<div id="single-article-footer">Footer controls.</div></div></article>')
        self.assertEqual(read(content).partition('\n')[2],BODY+' '+prose)

    def test_labelled_return_arrows_are_removed_without_losing_citations_or_plain_symbols(self):
        body=('<p>'+BODY+' The return symbol is ⏎.</p><ol><li id="f1">'
              '<a href="https://research.example/paper">A research citation</a>. '
              '<a href="#reference1" aria-label="Back to reference 1">⏎</a></li></ol>')
        text=read('<article><div class="entry-content">'+body+'</div></article>').partition('\n')[2]
        self.assertEqual(text,BODY+' The return symbol is ⏎. A research citation.')
        imported=html_to_text(body)
        self.assertEqual(imported.count('⏎'),1)
        self.assertIn('A research citation',imported)


if __name__=='__main__':unittest.main()
