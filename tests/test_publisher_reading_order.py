"""Publisher templates must keep article content separate from page controls."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview
from substack import html_to_text, Substack

FIRST = 'We measured how quickly the fictional seedlings grew in different conditions.'
LAST = 'The final observations recorded the effect of light on every individual plant.'


def narrate(url, html):
    with patch.object(Substack, 'get', return_value=html):
        return preview.article_text(url).split('\n', 1)


class PublisherReadingOrderTests(unittest.TestCase):
    def test_digital_antiquarian_keeps_captions_in_the_article_body(self):
        html = f"""<div class="post hentry"><h2>Seed trials</h2><div class="entry">
        <p>{FIRST}</p><div class="wp-caption"><a href="/tray"><img src="tray"></a>
        <p class="wp-caption-text">A tray of seedlings photographed after rain.</p></div>
        <div class="wp-caption" hidden><img src="unpublished">
        <p class="wp-caption-text">Unpublished frame.</p></div><p>{LAST}</p>
        <h4>Footnotes</h4><ol><li>The study began in March.</li></ol></div>
        <p>Read another article.</p></div><aside><div class="wp-caption"><img src="ad">
        <p class="wp-caption-text">A sponsored image.</p></div></aside>"""
        _, body = narrate('https://www.filfre.net/2026/10/seed-trials/', html)
        self.assertEqual(body.split(),
                         f'{FIRST} A tray of seedlings photographed after rain. {LAST} '
                         'Footnotes The study began in March.'.split())

    def test_inkscape_uses_brand_and_skips_placeholder_and_header_timestamp(self):
        html = f"""<head><title>Seed trials | Inkscape</title><meta name="author" content="None">
        <link rel="alternate" type="application/rss+xml" title="News Feed" href="/news/feed/"></head>
        <div id="logo"><a href="/en/"><img alt="Inkscape"></a></div>
        <div id="content"><div class="wrapper"><h1>Seed trials</h1>
        <p class="postdate">May 2, 2026, 7:10 p.m.</p><p>{FIRST}</p>
        <p>Measurements on May 2, 2026 were repeated at 7:10 p.m.</p><p>{LAST}</p></div></div>"""
        url = 'https://inkscape.org/news/2026/05/02/seed-trials/'
        intro, body = narrate(url, html)
        self.assertEqual(intro, 'Inkscape. Seed trials.')
        self.assertEqual(body.split(), f'{FIRST} Measurements on May 2, 2026 were repeated at 7:10 p.m. {LAST}'.split())
        named, _ = narrate(url, html.replace('content="None"', 'content="Lee"'))
        self.assertTrue(named.endswith('By Lee.'), named)

    def test_kde_reads_article_author_once_and_skips_header_metadata(self):
        html = f"""<article class="post-content"><div class="jumbotron"><div class="content-width">
        <h1 class="page-header">Seed trials</h1><p class="meta">Friday, 6 November 2026 |
        <a href="/authors/ash">Ash Linden</a></p><div class="blog-tags">#research</div>
        </div></div><div class="content-width"><p>{FIRST}</p>
        <p>Read <a href="/authors/lee">Lee’s article</a> for the earlier protocol.</p>
        <p>{LAST}</p></div></article>"""
        intro, body = narrate('https://blogs.kde.org/2026/11/06/seed-trials/', html)
        self.assertTrue(intro.endswith('By Ash Linden.'), intro)
        self.assertEqual(body.split(), f'{FIRST} Read Lee’s article for the earlier protocol. {LAST}'.split())

    def test_gds_byline_keeps_both_names_without_job_titles(self):
        html = f"""<article><header><h1>Seed trials</h1><div class="govuk-body-s">
        <a rel="author" href="/author/ash">Ash Linden, Head of Policy, Partnerships, and Program Delivery</a>
        and <a rel="author" href="/author/lee">Lee Cooper-Quinn, Head of Product, and Program Delivery</a>
        <a rel="category" href="/topics">Research</a></div></header>
        <div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>"""
        intro, _ = narrate('https://gds.blog.gov.uk/2026/10/19/seed-trials/', html)
        self.assertTrue(intro.endswith('By Ash Linden, Lee Cooper-Quinn.'), intro)

    def test_earthsky_reads_the_rich_text_and_captions_without_controls(self):
        html = f"""<h1>Seed trials</h1><div class="post-content"><div class="post-body">
        <div class="post-share">Share this page</div><div class="post">
        <div class="post-rich-text"><p>{FIRST}</p><figure class="wp-block-image"><img src="sample">
        <figcaption class="wp-element-caption">A tray after rain.</figcaption></figure>
        <p>{LAST}</p><div class="ns-buttons ns-inline-below"><div class="ns-buttons-wrapper">
        <a href="/share" aria-label="Share on Bluesky">Share on Bluesky</a></div></div></div></div></div>
        <div class="post-subscribe">Join our list</div><div class="post-more">Another story</div></div>"""
        _, body = narrate('https://earthsky.org/science/seed-trials/', html)
        self.assertEqual(body.split(), f'{FIRST} A tray after rain. {LAST}'.split())

    def test_r_project_preserves_short_command_before_its_output(self):
        html = f"""<main id="quarto-document-content" class="quarto-banner-title-block">
        <h1>Seed trials</h1><section class="level2"><h2>Results</h2>
        <p>{FIRST}</p><div class="cell"><div class="code-copy-outer-scaffold"><pre class="sourceCode">
        <code><span>(fit &lt;- count(x ~ g))</span></code></pre><button>Copy example</button></div>
        <div class="cell-output"><pre>Group 1: 20 samples</pre></div></div>
        <p>{LAST}</p></section></main>"""
        _, body = narrate('https://blog.r-project.org/posts/seed-trials/', html)
        self.assertEqual(body.split(), f'Results {FIRST} (fit <- count(x ~ g)) Group 1: 20 samples {LAST}'.split())

    def test_loc_and_geolog_keep_editorial_photo_captions_in_place(self):
        cases = [
            ('blogs.loc.gov', '<figure class="wp-caption"><img src="tray">'
             '<figcaption class="wp-caption-text">Seeds in March.</figcaption></figure>', 'Seeds in March.'),
            ('blogs.egu.eu', '<figure class="wp-caption post-thumbnail"><img src="tray">'
             '<figcaption class="featured_caption">Early growth.</figcaption></figure>'
             '<div class="wp-caption"><a href="/photo"><img src="tray2"></a>'
             '<p class="wp-caption-text">Seeds in April.</p></div>', 'Early growth. Seeds in April.'),
        ]
        for host, photo, expected in cases:
            with self.subTest(host=host):
                html = (f'<article><h1>Seeds</h1><div class="entry-content"><p>{FIRST}</p>{photo}'
                        f'<div hidden>{photo}</div><aside>{photo}</aside><p>{LAST}</p></div></article>')
                _, body = narrate(f'https://{host}/seed-trials/', html)
                self.assertEqual(body.split(), f'{FIRST} {expected} {LAST}'.split())

    def test_webkit_author_line_caption_and_linked_code_examples(self):
        html = f"""<article><h1>Seeds</h1><div class="byline"><p class="date">May 18, 2026</p>
        <p class="author">by <span>Ash and Lee</span></p></div><div class="bodycopy"><p>{FIRST}</p>
        <figure><picture><img src="seeds"></picture><figcaption>A tray of seedlings.</figcaption></figure>
        <ul><li><a href="/sample"><code>&lt;seed&gt;</code></a></li>
        <li><a href="/size"><code>size()</code></a></li></ul><p>{LAST}</p></div></article>"""
        intro, body = narrate('https://webkit.org/blog/123/seeds', html)
        self.assertIn('By Ash and Lee.', intro)
        self.assertNotIn('2026', intro)
        self.assertEqual(body.split(), f'{FIRST} A tray of seedlings. <seed> size() {LAST}'.split())

    def test_freebsd_post_navigation_and_feed_footer_keep_editorial_links(self):
        url = 'https://freebsdfoundation.org/blog/seeds/'
        html = f"""<article><h1>Seeds</h1><div class="post-content"><p>{FIRST}</p>
        <p><a rel="prev" href="/prior">Previous</a> trials had a different result.</p><p>{LAST}</p>
        <span class="nav-previous"><a href="/old" rel="prev">Previous</a></span>
        <span class="nav-next"><a href="/new" rel="next">Next</a></span></div></article>"""
        _, body = narrate(url, html)
        self.assertEqual(body.split(), f'{FIRST} Previous trials had a different result. {LAST}'.split())
        credit = (f'<p>The post <a href="{url}">Seeds</a> first appeared on '
                  '<a href="https://freebsdfoundation.org/">The Journal</a>.</p>')
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>'+credit, title='Seeds', url=url), FIRST)
        for retained in ('<blockquote>'+credit+'</blockquote>', credit+f'<p>{LAST}</p>',
                         credit.replace('/blog/seeds/', '/blog/other/')):
            self.assertIn('first appeared on', html_to_text(retained, title='Seeds', url=url))

    def test_internet_society_uses_matching_article_header_and_keeps_linked_prose(self):
        html = f"""<meta name="author" content="Publishing Account"><main>
        <div class="content-wrapper"><header><h1>Seed trials</h1><div class="author-box"><div class="author-meta">
        <span class="author-name">By <a href="/author/ash/">Ash</a></span>
        <span class="author-name"><a href="/author/lee/">Lee</a><a hidden href="/author/old/">Old name</a></span>
        <a href="/author/ash/feed">RSS</a></div></div></header>
        <article><h2 class="entry-title">Seed trials</h2><div class="body-text"><p>{FIRST}</p>
        <p><a href="/map">See the individual trial results.</a></p><h4>Findings</h4><p>{LAST}</p></div>
        <div class="tags">Other topics</div></article></div></main>"""
        url = 'https://www.internetsociety.org/blog/seed-trials/'
        intro, body = narrate(url, html)
        self.assertIn('By Ash, Lee.', intro)
        self.assertEqual(body.split(), f'{FIRST} See the individual trial results. Findings {LAST}'.split())
        for alternative in (html.replace('<h1>Seed trials', '<h1>Other story'),
                            html.replace('class="content-wrapper"', 'class="other"')):
            self.assertIn('By Publishing Account.', narrate(url, alternative)[0])

    def test_creative_commons_preserves_opening_and_removes_only_the_posting_stamp(self):
        html = f"""<body class="blog-post"><main><header><h1>Seed trials</h1></header><div class="content">
        <aside class="opening"><p>How did the experiment begin? We asked the gardeners.</p></aside>
        <p>{FIRST}</p><aside class="opening"><p>More stories from the archive.</p></aside>
        <p>Our notebook reads <span class="pub-date">Posted 18 May 2026</span> on its cover.</p>
        <p>{LAST}</p><span class="pub-date">Posted 19 May 2026</span></div></main></body>"""
        url = 'https://creativecommons.org/2026/05/19/seed-trials/'
        _, body = narrate(url, html)
        self.assertEqual(body.split(), ('How did the experiment begin? We asked the gardeners. '
                         + FIRST + ' Our notebook reads Posted 18 May 2026 on its cover. ' + LAST).split())

    def test_pypi_post_identity_and_heading_links(self):
        html = f"""<header><a class="md-logo" data-md-component="logo" title="Seed Journal"></a></header>
        <aside class="md-sidebar--post"><nav><a href="/">Back to index</a><div class="md-post__authors">
        <div class="md-profile__description"><strong><a href="/author/ash">Ash<span hidden>Other</span></a></strong>
        Scientist</div></div></nav></aside>
        <main><div class="md-content--post"><article><h1>Seeds</h1><p>{FIRST}</p>
        <h2 id="data">Results<a class="headerlink" href="#data">¶</a></h2>
        <p>The symbol <a class="headerlink" href="#data">¶</a> marks a paragraph.</p>
        <p>{LAST}</p></article></div></main>"""
        intro, body = narrate('https://blog.pypi.org/posts/seeds/', html)
        self.assertEqual(intro, 'Seed Journal. Seeds. By Ash.')
        self.assertEqual(body.split(), f'{FIRST} Results The symbol ¶ marks a paragraph. {LAST}'.split())

    def test_nist_retains_visible_image_caption_and_credit_in_order(self):
        html = f"""<main><h1>Seeds</h1><div class="nist-page__region--content"><div class="text-with-summary">
        <p>{FIRST}</p><figure class="nist-image"><img src="sample"><figcaption class="nist-image__caption">
        <div><p>The seeds after rain.</p></div><div>Credit: Ash</div></figcaption></figure>
        <figure hidden class="nist-image"><img src="other"><figcaption class="nist-image__caption">
        Hidden caption</figcaption></figure><p>{LAST}</p></div></div></main>"""
        _, body = narrate('https://www.nist.gov/news-events/news/seeds', html)
        self.assertEqual(body.split(), f'{FIRST} The seeds after rain. Credit: Ash {LAST}'.split())

    def test_eff_drops_only_the_embedded_player_disclosure(self):
        url = 'https://www.eff.org/deeplinks/seeds'
        widget = ('<div class="mytube"><div class="mytubetrigger"></div><div class="mytubetext">'
                  '<a href="/deeplinks/2008/02/embedded-video-and-your-privacy">Privacy info.</a> '
                  'This embed will serve content from <a href="https://player.example">player.example</a></div></div>')
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{widget}<p>{LAST}</p>', url=url).split(),
                         f'{FIRST} {LAST}'.split())
        for retained in ('<blockquote>' + widget + '</blockquote>', widget.replace('mytubetrigger', 'other'),
                         widget.replace('This embed', 'We reported why this embed')):
            self.assertIn('Privacy info.', html_to_text(retained, url=url))

    def test_coauthors_and_visible_image_caption(self):
        html = f"""<article><div class="post-content"><header><h1>Seedlings</h1><p>
        <span><a href="/author/ash/"><bdi>Ash</bdi></a></span>
        <span hidden><a href="/author/fake/"><bdi>Hidden</bdi></a></span>
        <span><a href="/author/lee/"><bdi>Lee</bdi></a></span></p></header>
        <div class="article-content"><p>{FIRST}</p>
        <figure class="emdash-image"><img src="one"><figcaption>The shaded tray.</figcaption></figure>
        <figure class="emdash-image" hidden><img src="two"><figcaption>Hidden</figcaption></figure>
        <p>{LAST}</p></div></div></article>"""
        intro, body = narrate('https://blog.cloudflare.com/seedlings/', html)
        self.assertIn('By Ash, Lee.', intro)
        self.assertEqual(body.split(), f'{FIRST} The shaded tray. {LAST}'.split())

    def test_guardian_excludes_card_and_topic_widgets_but_keeps_prose_links(self):
        html = f"""<article><h1>Notes</h1><div data-gu-name="body">
        <div class="article-body-viewer-selector"><p>{FIRST}</p>
        <figure data-spacefinder-role="richLink"><div data-component="rich-link">
        <a href="/other">Another story</a></div></figure>
        <p><a href="/source">Read more</a> about this result.</p><p>{LAST}</p></div>
        <div>Topic widgets</div></div></article>"""
        _, body = narrate('https://www.theguardian.com/science/notes', html)
        self.assertEqual(body.split(), f'{FIRST} Read more about this result. {LAST}'.split())

    def test_guardian_feed_removes_only_terminal_standalone_permalink(self):
        url = 'https://www.theguardian.com/science/notes'
        link = '<a href="/science/notes">Continue reading...</a>'
        body = f'<p>{FIRST}</p>'
        self.assertEqual(html_to_text(body + link, url=url), FIRST)
        for html in (body + '<blockquote>' + link + '</blockquote>', link + body,
                     body + link.replace('/notes', '/other')):
            self.assertIn('Continue reading...', html_to_text(html, url=url))

    def test_go_atom_uses_matching_wrapper_and_preserves_navigation_words_in_prose(self):
        html = f"""<div id="blog"><div class="Article" data-slug="/blog/notes">
        <h1 class="small"><a href="/blog/">Example blog</a></h1><h1>Notes</h1>
        <p class="author">Ash</p><div class="markdown"><p>{FIRST}</p>
        <p>Next article: a quotation.</p></div></div>
        <div class="Article prevnext"><a href="/blog/all">Blog Index</a></div></div>"""
        url = 'https://go.dev/blog/notes'
        self.assertEqual(html_to_text(html, title='Notes', url=url).split(),
                         f'{FIRST} Next article: a quotation.'.split())
        for other, title in ((url, 'Different'), (url + '-other', 'Notes'), ('https://example.org/blog/notes', 'Notes')):
            self.assertIn('Blog Index', html_to_text(html, title=title, url=other))

    def test_wordpress_footer_credit_and_language_menu(self):
        html = f"""<article><h1>Notes</h1><div class="entry-content"><p>{FIRST} {LAST}</p>
        <p>This post is also available in our library.</p>
        <p class="icl_post_in_other_langs wpml-ls-statics-post_translations">Translation menu
        <span role="navigation"><a class="wpml-ls-link" hreflang="es">Spanish</a></span></p></div>
        <footer class="entry-meta"><span class="by-author"><span class="vcard">
        <a rel="author">Ash<span hidden>Wrong</span></a><a hidden rel="author">Other</a>
        </span></span></footer></article>"""
        intro, body = narrate('https://blog.openstreetmap.org/notes/', html)
        self.assertIn('By Ash.', intro)
        self.assertNotIn('Wrong', intro)
        self.assertEqual(body.split(), f'{FIRST} {LAST} This post is also available in our library.'.split())

    def test_w3c_credit_stays_with_its_label(self):
        html = f"""<article><h1>Notes</h1><section class="meta"><dl>
        <dt>By:</dt><dd><ul><li hidden>Hidden</li><li>Lee</li><li>Ash</li></ul></dd>
        <dt>Published:</dt><dd>Some date</dd></dl></section><p>{FIRST} {LAST}</p></article>"""
        intro, _ = narrate('https://www.w3.org/blog/notes/', html)
        self.assertIn('By Lee, Ash.', intro)
        self.assertNotIn('Hidden', intro)
        self.assertNotIn('By ', narrate('https://www.w3.org/blog/notes/', html.replace('By:', 'Editors:'))[0])

    def test_django_body_keeps_link_only_items_in_source_order(self):
        items = ''.join(f'<li><a href="/idea/{i}/">Idea {i}</a></li>' for i in range(6))
        html = f"""<main><h1>Notes</h1><div class="blog-entry-body"><p>{FIRST}</p>
        <ol>{items}</ol><p>{LAST}</p></div><nav>Other news</nav></main>"""
        _, body = narrate('https://www.djangoproject.com/weblog/2026/notes/', html)
        self.assertEqual(body.split(), (FIRST + ' ' + ' '.join(f'Idea {i}' for i in range(6)) + ' ' + LAST).split())

    def test_raspberry_pi_only_editorial_image_captions_are_retained(self):
        html = f"""<article><h1>Notes</h1><div class="c-post-content__wysiwyg"><p>{FIRST}</p>
        <div class="wp-block-image"><figure><img src="/one"><figcaption class="wp-element-caption">A useful diagram.</figcaption></figure></div>
        <div class="wp-block-image" hidden><figure><img src="/two"><figcaption class="wp-element-caption">Hidden caption.</figcaption></figure></div>
        <p>{LAST}</p></div></article>"""
        _, body = narrate('https://www.raspberrypi.com/news/notes/', html)
        self.assertEqual(body.split(), f'{FIRST} A useful diagram. {LAST}'.split())
