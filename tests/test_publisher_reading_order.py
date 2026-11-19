"""Publisher templates must keep article content separate from page controls."""
import json
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
    def test_nasa_keeps_captions_when_wordpress_nests_an_image_inside_a_paragraph(self):
        html = f'''<article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <p class="wp-block-paragraph"><div class="hds-media wp-block-image"><div class="hds-media-wrapper">
        <img src="/tray"><figcaption class="hds-caption"><div>The trial tray at dawn.</div></figcaption>
        </div></div></p><p>{LAST}</p></div></article>'''
        self.assertEqual(narrate('https://www.nasa.gov/centers-and-facilities/seed-trials/', html)[1],
                         f'{FIRST} The trial tray at dawn. {LAST}')

    def test_wyofile_preserves_column_image_captions_in_reading_order(self):
        html = f'''<article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <div class="wp-block-columns"><div class="wp-block-column">
        <figure class="wp-block-image"><img src="/one"><figcaption class="wp-element-caption">
        Tray one.</figcaption></figure></div><div class="wp-block-column"><figure class="wp-block-image">
        <img src="/two"><figcaption class="wp-element-caption">Tray two.</figcaption></figure></div></div>
        <p>{LAST}</p></div></article>'''
        self.assertEqual(narrate('https://wyofile.com/seed-trials/', html)[1], f'{FIRST} Tray one. Tray two. {LAST}')

    def test_reason_omits_its_email_widget_without_removing_newsletter_prose(self):
        html = f'''<article class="rcom-standard-article"><h1>Seed trials</h1><div class="entry-content">
        <p>{FIRST}</p><div class="gform_wrapper incontent-email-signup_wrapper">
        <div class="gform_heading"><p>Sign up for more.</p></div><form><input type="email"></form></div>
        <p>The newsletter published the first report.</p><p>{LAST}</p></div></article>'''
        self.assertEqual(narrate('https://reason.com/2026/11/19/seed-trials/', html)[1],
                         f'{FIRST} The newsletter published the first report. {LAST}')

    def test_raspberry_pi_preserves_the_group_caption_of_a_gallery(self):
        html = f'''<title>Seed trials</title><div class="c-post-content__wysiwyg">
        <p>{FIRST}</p><figure class="wp-block-gallery has-nested-images">
        <figure class="wp-block-image"><img src="/seeds"></figure>
        <figcaption class="blocks-gallery-caption">Seeds of each variety.</figcaption></figure>
        <p>{LAST}</p></div>'''
        self.assertEqual(narrate('https://www.raspberrypi.com/news/seed-trials/', html)[1],
                         f'{FIRST} Seeds of each variety. {LAST}')

    def test_quillette_reads_visible_prose_section_captions(self):
        html = f'''<main><article class="post"><h1>Seed trials</h1><section class="prose prose-brand">
        <p>{FIRST}</p><figure class="kg-card kg-image-card"><img src="/tray">
        <figcaption>A tray at the end of the trial.</figcaption></figure>
        <p>{LAST}</p><aside>Another article.</aside></section>
        <section hidden class="prose prose-brand"><p>Hidden layout content.</p></section></article></main>'''
        self.assertEqual(narrate('https://quillette.com/2026/11/19/seed-trials/', html)[1],
                         f'{FIRST} A tray at the end of the trial. {LAST}')

    def test_mozilla_omits_the_language_picker_but_keeps_translation_prose(self):
        html = f'''<article><h1>Seed trials</h1><div class="ft-c-single-post__body entry-content">
        <p class="wpml-ls-statics-post_translations wpml-ls">This post is also available in:
        <a href="/de/seed-trials/"><span class="wpml-ls-native" lang="de">Deutsch</span></a></p>
        <p>{FIRST}</p><p>Our translated notes helped other gardeners.</p><p>{LAST}</p></div></article>'''
        self.assertEqual(narrate('https://blog.mozilla.org/en/seed-trials/', html)[1],
                         f'{FIRST} Our translated notes helped other gardeners. {LAST}')

    def test_inkscape_reads_embedded_picture_captions_and_keeps_news_sections(self):
        html = f'''<body class="news"><main id="content"><div class="wrapper">
        <div class="breadcrumbs"><a href="/news/">News</a></div><h1>Seed trials</h1>
        <p class="postdate">19 November 2026</p><p>{FIRST}</p><div><figure class="plugin_picture">
        <img src="/tray.gif"><figcaption>The trays after rain.</figcaption></figure></div>
        <h2>Results</h2><p>{LAST}</p></div></main></body>'''
        self.assertEqual(narrate('https://inkscape.org/news/2026/11/19/seed-trials/', html)[1],
                         f'{FIRST} The trays after rain. Results {LAST}')

    def test_bgs_preview_keeps_the_caption_inside_its_editorial_figure(self):
        html = f'''<main><section class="hero-section-article"><div class="hero-info-wrap">
        <div class="hero-info"><h1>Seed trials</h1><p>How the trials went.</p><span>19/11/2026</span></div>
        </div></section><section class="wp-block-bgs-blocks-content-container content-section">
        <div class="container"><p>{FIRST}</p><figure class="img-wrap"><img src="/tray">
        <figcaption class="caption"><div class="caption-text"><p>Gardens after rain.</p></div></figcaption>
        </figure><p>{LAST}</p></div></section><section><p>Was this page helpful?</p></section></main>'''
        self.assertEqual(narrate('https://www.bgs.ac.uk/news/seed-trials/', html)[1],
                         f'How the trials went. {FIRST} Gardens after rain. {LAST}')

    def test_smashing_feed_omits_the_exported_course_checkout_and_keeps_its_references(self):
        course = 'https://ai-design-patterns.com/'
        payment = 'https://smart-interface-design-patterns.thinkific.com/enroll/'
        body = f'''<p>{FIRST}</p><p>Meet <a href="{course}">Design Patterns For AI Interfaces</a> and its video lessons.</p>
        <a href="{course}">Design Patterns For AI Interfaces</a><div><div><ul><li><a href="#">Video only</a></li></ul>
        <div><h3>Video only</h3><a href="{payment}1">Buy now</a></div>
        <div><h3>Video + UX Training</h3><a href="{payment}2">Buy with training</a></div></div></div>
        <p>{LAST}</p><ul><li><a href="/growing">Garden references</a></li></ul>'''
        self.assertEqual(html_to_text(body, url='https://smashingmagazine.com/2026/11/seed-trials/'),
                         f'{FIRST}\n{LAST}\nGarden references')

    def test_w3c_reads_editorial_images_without_importing_sidebar_captions(self):
        html = f'''<body class="post"><main id="main"><div class="content"><article><h1>Seed trials</h1>
        <div class="sub-head">Part of <a href="/blog/category/gardens/">Gardens</a></div>
        <section class="meta"><dl><dt>Published:</dt><dd><time datetime="2026-11-19">Today</time></dd></dl></section>
        <figure class="component component--image">
        <img src="/tray"><figcaption><p>The seed tray at the event.</p></figcaption></figure>
        <div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div>
        <aside><figure class="component component--image"><img src="/ad"><figcaption>
        Unrelated image.</figcaption></figure></aside></article></div></main></body>'''
        _, text = narrate('https://www.w3.org/blog/2026/seed-trials/', html)
        self.assertEqual(text, f'The seed tray at the event. {FIRST} {LAST}')

    def test_creative_commons_omits_feed_series_cards_and_keeps_article_sections(self):
        url = 'https://creativecommons.org/2026/11/19/seed-trials/'
        cards = f'''<article class="posts"><ul>
        <li><article class="post"><header><h3 class="title"><a href="{url}">Seed trials</a></h3></header></article></li>
        <li><article class="post"><header><h3 class="title"><a href="/2026/11/20/another-trial/">
        Another trial</a></h3></header></article></li></ul></article>'''
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{cards}<p>{LAST}</p>', url=url), f'{FIRST}\n{LAST}')
        editorial = cards.replace('</header></article>', '</header><p>Further observations.</p></article>', 1)
        self.assertIn('Further observations.', html_to_text(editorial, url=url))

    def test_nasa_apod_feed_omits_its_repeated_hero_title_and_keeps_caption(self):
        url = 'https://science.nasa.gov/image-article/apod-2026-november-19-seed-trials/'
        title = 'APOD: 2026 November 19 – Seed trials'
        body = f'''<div class="wp-block-nasa-blocks-media-detail-hero"><div class="grid-container">
        <h1>Seed trials</h1><p>{FIRST}</p></div></div><p>{LAST}</p>'''
        self.assertEqual(html_to_text(body, title=title, url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Seed trials', html_to_text(body, title='Other title', url=url))

    def test_nieman_omits_related_news_timeline_without_losing_sidebar_prose(self):
        url = 'https://www.niemanlab.org/2026/11/seed-trials/'
        timeline = '''<aside class="rsc-collbox rsc-collbox-side"><div class="rsc-collbox-body">
        <div class="rsc-collbox-title">More about seed testing</div><ol class="rsc-collbox-list">
        <li class="rsc-collbox-item"><a class="rsc-collbox-link" href="/another/">
        <span class="rsc-collbox-date">November 18</span><span class="rsc-collbox-hed">Another trial</span></a></li>
        <li class="rsc-collbox-item is-current"><span class="rsc-collbox-link">
        <span class="rsc-collbox-date">November 19</span><span class="rsc-collbox-hed">Seed trials</span></span></li>
        </ol></div></aside>'''
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{timeline}<p>{LAST}</p>', url=url), f'{FIRST}\n{LAST}')
        control = timeline.replace('</aside>', '<p>Additional methods.</p></aside>')
        self.assertIn('Additional methods.', html_to_text(control, url=url))

    def test_wikimedia_keeps_standalone_gallery_and_slideshow_captions_in_order(self):
        html = f'''<article><h1>Seed trials</h1><div class="entry-content wrapper-small"><p>{FIRST}</p>
        <div class="wp-block-image"><figure><img src="/tray"><figcaption class="wp-element-caption">
        Single image.</figcaption></figure></div>
        <figure class="wp-block-gallery has-nested-images"><figure class="wp-block-image"><img src="/roots">
        <figcaption class="wp-element-caption">Gallery image.</figcaption></figure></figure>
        <div class="wp-block-jetpack-slideshow"><ul><li class="wp-block-jetpack-slideshow_slide">
        <figure><img src="/leaves"><figcaption>Slideshow image.</figcaption></figure></li></ul>
        <button>Pause slideshow</button></div><p>{LAST}</p></div></article>'''
        self.assertEqual(narrate('https://diff.wikimedia.org/2026/11/19/seed-trials/', html)[1],
                         f'{FIRST} Single image. Gallery image. Slideshow image. {LAST}')

    def test_strong_towns_reads_byline_from_action_content_masthead(self):
        html = f'''<title>Seed trials | Strong Towns</title><div class="action-content_wrap">
        <section class="cc-action-content"><div class="mast-col"><div class="heading-component"><h1>Seed trials</h1></div>
        <div class="w-dyn-list"><div class="w-dyn-items"><div class="w-dyn-item"><div class="row-component">
        <div class="slot cc-column"><div class="mast-paragraph"><div>Ash Grower</div></div></div>
        </div></div></div></div></div></section></div>
        <article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>'''
        intro, body = narrate('https://www.strongtowns.org/journal/seed-trials/', html)
        self.assertTrue(intro.endswith('By Ash Grower.'), intro)
        self.assertEqual(body, f'{FIRST} {LAST}')

    def test_strong_towns_action_content_keeps_cover_caption_and_omits_bio_card(self):
        html = f'''<title>Seed trials</title><div class="action-content_wrap">
        <div class="mast-section"><div class="img-component"><img src="/seed"></div><div>
        <div class="rich-text-component mast-mt-xs"><div class="mast-rich-text w-richtext">
        <p>View of the seed tray.</p></div></div></div></div>
        <section><div class="mast-article-rich-text w-richtext"><p>{FIRST}</p><p>{LAST}</p></div>
        <div class="mast-card"><p>The author grows plants for a living.</p></div></section></div>'''
        self.assertEqual(narrate('https://www.strongtowns.org/journal/seed-trials/', html)[1],
                         f'View of the seed tray. {FIRST} {LAST}')

    def test_universal_hub_keeps_article_caption_link_and_submitted_byline(self):
        html = f'''<article class="node-story view-mode-full"><h1>Seed trials</h1><div class="content">
        <span class="submitted-by">By <a class="username" href="/users/lee">Lee</a> on Tuesday</span>
        <div class="field-name-field-top-photo"><img src="/seed"></div>
        <div class="field-name-field-caption"><p>Two varieties of seed.</p></div>
        <div class="field-name-body"><div class="field-items"><div class="field-item">
        <p>{FIRST}</p><p><a href="/report">The published report.</a></p><p>{LAST}</p></div></div></div>
        <div class="field-name-field-topics">Topics: Gardens</div></div>
        <section class="comments">By <a class="username" href="/users/ash">Ash</a> on Friday</section></article>'''
        intro, body = narrate('https://www.universalhub.com/2026/seed-trials', html)
        self.assertTrue(intro.endswith('By Lee.'), intro)
        self.assertEqual(body, f'Two varieties of seed. {FIRST} The published report. {LAST}')

    def test_sapiens_reads_the_caption_of_an_image_in_prose(self):
        html = f'''<title>Seed trials</title><div class="c-article-content" data-article-content><div class="c-modules">
        <p>{FIRST}</p><div class="m-text-insert-image__media"><figure class="c-image-video"><img src="/seed">
        <footer class="c-image-video__footer"><div class="c-media-caption"><p>The seed tray.</p></div>
        <div class="c-media-credits">Photo by Lee.</div></footer></figure></div><p>{LAST}</p></div></div>'''
        self.assertEqual(narrate('https://www.sapiens.org/archaeology/seed-trials/', html)[1],
                         f'{FIRST} The seed tray. Photo by Lee. {LAST}')

    def test_buttondown_omits_exact_exported_subject_and_keeps_other_headings(self):
        body = f'<h3>Announcement</h3><p>{FIRST}</p><h1>Seed trials</h1><h2>Results</h2><p>{LAST}</p>'
        url = 'https://buttondown.com/garden/archive/seed-trials/'
        self.assertEqual(html_to_text(body, title='Seed trials', url=url), f'Announcement\n{FIRST}\nResults\n{LAST}')
        self.assertIn('Seed trials at night', html_to_text(body.replace('Seed trials', 'Seed trials at night'),
                                                         title='Seed trials', url=url))

    def test_geographyrealm_skips_related_link_list_with_one_exported_label_as_url(self):
        html = f'''<article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <h2 class="wp-block-heading">Related resources:</h2><p>{LAST}</p>
        <h2 class="wp-block-heading" id="h-more-geography-articles-of-interest">More Geography Articles of Interest</h2>
        <ul class="wp-block-list"><li><a href="Soil: a Gardener's Guide">Soil: a Gardener’s Guide</a></li>
        <li><a href="/leaves/">More Leaves</a></li></ul></div></article>'''
        self.assertEqual(narrate('https://www.geographyrealm.com/seed-trials/', html)[1],
                         f'{FIRST} Related resources: {LAST}')

    def test_jstor_feed_omits_the_recommendation_teaser_and_its_byline(self):
        url = 'https://daily.jstor.org/seed-trials/'
        related = '''<div class="daily-explore story-list more-to-explore">
        <h2 class="story-list-header">More to Explore</h2><div class="article-tease"><div class="article-tease__text">
        <a href="/different">Different trials</a><div class="byline">Lee Grower</div></div></div></div>'''
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{related}<p>{LAST}</p>', url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Lee Grower', html_to_text(f'<blockquote>{related}</blockquote>', url=url))

    def test_bgs_feed_omits_tag_links_and_keeps_webinar_registration(self):
        url = 'https://www.bgs.ac.uk/news/seed-trials/'
        body = f'''<section class="wp-block-bgs-blocks-content-container"><p>{FIRST}</p>
        <p><a href="/events/seed">Register online</a></p><div class="relatives"><h5>Relative topics</h5>
        <div><a class="button" href="/tag/gardens/">Gardens</a></div></div><p>{LAST}</p></section>'''
        self.assertEqual(html_to_text(body, url=url), f'{FIRST}\nRegister online\n{LAST}')
        self.assertIn('Another detail.', html_to_text(body.replace('<h5>Relative topics</h5>',
                                                                  '<h5>Relative topics</h5><p>Another detail.</p>'), url=url))

    def test_conversation_preserves_editorial_figure_caption_and_credit(self):
        html = f'''<article id="article"><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <figure class="zoomable"><img src="/seed">
        <figcaption><span class="caption">The seed tray.</span><span class="attribution">Credit: Lee</span></figcaption>
        </figure><p>{LAST}</p></div></article>'''
        self.assertEqual(narrate('https://theconversation.com/seed-trials-123456', html)[1],
                         f'{FIRST} The seed tray. Credit: Lee {LAST}')

    def test_conversation_preserves_the_magazine_lead_caption_once(self):
        html = f'''<article id="article"><figure class="magazine"><div><img src="/tray"></div>
        <div class="caption-wrapper"><figcaption>The trays at sunrise. <span class="attribution">Photo by Lee.</span>
        </figcaption></div></figure><h1>Seed trials</h1>
        <div class="entry-content content-body"><p>{FIRST}</p><p>{LAST}</p></div></article>'''
        self.assertEqual(narrate('https://theconversation.com/seed-trials-123456', html)[1],
                         f'The trays at sunrise. Photo by Lee. {FIRST} {LAST}')

    def test_atlas_obscura_keeps_linked_article_section_titles(self):
        html = f'''<article><h1>Seed trials</h1><section id="article-body" class="ArticleBody">
        <p>{FIRST}</p><h3 class="article-second-subheading-pre-rd"><a href="/event"><strong>First harvest</strong></a></h3>
        <p>{LAST}</p></section></article>'''
        self.assertEqual(narrate('https://www.atlasobscura.com/articles/seed-trials', html)[1],
                         f'{FIRST} First harvest {LAST}')

    def test_lit_hub_daily_keeps_today_line_and_omits_nested_advertisement(self):
        html = f'''<title>Seed trials</title><div class="story-content"><div class="story-body">
        <p><span class="caption">TODAY: Seeds arrived.</span></p><p>{FIRST}
        <div class="insert-post-ads"><span>Article continues after advertisement</span><script>ad()</script></div></p>
        <p>{LAST}</p></div></div>'''
        self.assertEqual(narrate('https://lithub.com/lit-hub-daily-seed-trials/', html)[1],
                         f'TODAY: Seeds arrived. {FIRST} {LAST}')

    def test_daring_fireball_keeps_leading_links_and_omits_article_navigation(self):
        html = f'''<title>Seed trials</title><div id="Main"><div class="article"><h1>Seed trials</h1>
        <h6 class="dateline">Thursday, 19 November 2026</h6><ul><li><a href="/sheet">Trial schedule</a></li>
        <li><a href="/guide">Field guide</a></li></ul><p>{FIRST}</p><p>{LAST}</p>
        <div id="PreviousNext"><table><tr><td><a href="/past">Previous article</a></td></tr></table></div>
        </div></div>'''
        self.assertEqual(narrate('https://daringfireball.net/2026/11/seed_trials', html)[1],
                         f'Trial schedule Field guide {FIRST} {LAST}')

    def test_universal_hub_uses_the_confirmed_reprint_byline_and_skips_feed_controls(self):
        credit = ('<p><em>This article is republished from The Conversation. It was written by: '
                  '<a href="https://theconversation.com/profiles/lee">Lee Writer</a>.</em></p>')
        body = (f'<div class="field-name-body"><div class="field-items"><div class="field-item">'
                f'<p><em>By Lee Writer, Garden School</em></p><p>{FIRST}</p><p>{LAST}</p>{credit}</div></div></div>')
        url = 'https://www.universalhub.com/2026/seed-trials'
        intro, narrated = narrate(url, f'<article><h1>Seed trials</h1>{body}</article>')
        self.assertTrue(intro.endswith('By Lee Writer.'))
        self.assertTrue(narrated.startswith(FIRST))
        payload = body + ('<div class="field-name-field-topics field-type-taxonomy-term-reference">Topics: Gardens</div>'
                          '<div class="rrssb"><ul class="rrssb-buttons"><li><a href="mailto:">Email</a></li></ul></div>')
        post = {'title': 'Seed trials', 'canonical_url': url, 'body_html': payload,
                'publishedBylines': [{'name': 'The Conversation'}]}
        full, text = Substack('').post_text({'rss': True}, post)
        self.assertEqual(full['publishedBylines'], [{'name': 'Lee Writer'}])
        self.assertTrue(text.startswith(FIRST))
        self.assertNotIn('Topics:', text)
        self.assertNotIn('Email', text)
        _, unconfirmed = narrate(url, f'<article><h1>Seed trials</h1>{body.replace(credit, "")}</article>')
        self.assertIn('Lee Writer, Garden School', unconfirmed)

    def test_conversation_reads_all_names_in_the_articles_accessible_byline(self):
        html = f'''<meta name="author" content="Ash Reporter"><article id="article"><h1>Seed trials</h1>
        <aside class="content-sidebar"><section class="content-authors"><div class="content-authors-synopsis">
        <button class="content-authors-toggle"><span class="nobr">Lee Writer</span>,
        <span class="nobr">Ash Reporter</span>, <span class="nobr" hidden>Unshown Author</span>
        <em>Garden School</em></button></div></section></aside>
        <div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>'''
        intro, body = narrate('https://theconversation.com/seed-trials-123456', html)
        self.assertTrue(intro.endswith('By Lee Writer, Ash Reporter.'))
        self.assertEqual(body, f'{FIRST} {LAST}')

    def test_creative_commons_keeps_a_body_heading_matching_the_headline_suffix(self):
        html = f'''<body class="blog-post"><main><h1>Seed trials: Results</h1><div class="content">
        <p>{FIRST}</p><h2>Results</h2><p>{LAST}</p></div></main></body>'''
        self.assertEqual(narrate('https://creativecommons.org/2026/11/19/seed-trials/', html)[1], f'{FIRST} Results {LAST}')

    def test_lit_hub_omits_only_the_advertisement_widget(self):
        html = f'''<title>Seed trials</title><div class="story-content"><div class="story-body">
        <p>{FIRST}</p><div class="insert-post-ads"><span>Article continues after advertisement</span>
        <script>insertAd()</script></div><p>{LAST}</p></div></div>'''
        self.assertEqual(narrate('https://lithub.com/seed-trials/', html)[1], f'{FIRST} {LAST}')

    def test_pluralistic_feed_omits_its_marked_index_and_keeps_destinations(self):
        url = 'https://pluralistic.net/2026/11/19/seed-trials/'
        body = f'''<h1 class="toch1">Today's links</h1><ul class="toc">
        <li><a href="{url}#results">Results teaser</a></li></ul><h2 id="results">Results</h2><p>{FIRST}</p>'''
        self.assertEqual(html_to_text(body, url=url), f'Results\n{FIRST}')
        self.assertIn('Results teaser', html_to_text(body.replace('id="results"', 'id="different"'), url=url))

    def test_plover_preview_keeps_the_story_fragment_across_a_trailing_slash_redirect(self):
        requested = 'https://blog.plover.com/2026/09/22#seeds'
        other = 'https://blog.plover.com/2026/09/22/'
        html = f'''<div class="mainsection"><p><a class="storytitle" href="/other.html" name="different">
        Another story</a></p><p>Some separate text about another post.</p></div>
        <div class="mainsection"><p><a class="storytitle" href="/seeds.html" name="seeds">Seed trials</a></p>
        <p>{FIRST}</p><p>{LAST}</p></div>'''

        def redirected(client, *args, **kwargs):
            client.last_url = other
            return html

        with patch.object(Substack, 'get', redirected):
            intro, body = preview.article_text(requested).split('\n', 1)
        self.assertIn('Seed trials.', intro)
        self.assertEqual(body, f'{FIRST} {LAST}')

    def test_tim_bray_keeps_a_caption_anchored_to_an_article_image(self):
        html = f'''<title>Seed trials</title><h1>Seed trials</h1><div id="center-and-right"><div id="centercontent">
        <p>{FIRST}</p><div class="main-image"><a href="/large"><img src="tray"></a></div>
        <div class="caption"><p>The narrow tray.</p></div><p>{LAST}</p>
        <aside><div class="caption"><p>Unrelated image caption.</p></div></aside>
        <div id="footer"><p class="footer"><b data-pagefind-meta="date: today">Updated today</b></p></div></div></div>'''
        _, body = narrate('https://www.tbray.org/ongoing/When/202x/2026/08/08/seed-trials', html)
        self.assertEqual(body, f'{FIRST} The narrow tray. {LAST}')

    def test_old_new_thing_uses_the_inline_code_titles_original_punctuation(self):
        html = f'''<article><h1>Can I use <code>seed()</code>?</h1><div class="entry-content">
        <p>{FIRST}</p><p>{LAST}</p></div></article>'''
        intro, _ = narrate('https://devblogs.microsoft.com/oldnewthing/seed-trials', html)
        self.assertIn('Can I use seed()?', intro)
        self.assertNotIn('seed() ?', intro)

    def test_earthsky_keeps_inline_captions_inside_an_image_wrapper(self):
        html = f'''<main><h1>Seed trials</h1><div class="post-body"><div class="post"><div class="post-rich-text">
        <p>{FIRST}</p><div class="wp-block-image"><figure><img src="tray"><figcaption class="wp-element-caption">
        Diagram by Lee.</figcaption></figure></div><p>{LAST}</p></div></div></div></main>'''
        self.assertEqual(narrate('https://earthsky.org/space/seed-trials/', html)[1], f'{FIRST} Diagram by Lee. {LAST}')

    def test_cal_newport_does_not_read_study_hacks_as_the_writers_name(self):
        html = f'''<meta property="og:site_name" content="Cal Newport"><meta name="author" content="Study Hacks">
        <article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>'''
        url = 'https://calnewport.com/seed-trials/'
        self.assertEqual(narrate(url, html)[0], 'Cal Newport. Seed trials.')
        self.assertEqual(narrate(url, html.replace('Study Hacks', 'Lee Writer'))[0], 'Cal Newport. Seed trials. By Lee Writer.')

    def test_article_metadata_keeps_a_long_list_of_named_contributors(self):
        writers = ('Lee Gardener, Ash Reporter, Jules Greenhouse, Morgan Planter, '
                   'Drew Experimentalist, Charlie Coordinator, and Terry Botanist')
        html = f'''<article><h1>Seed trials</h1><div class="byline">{writers}</div>
        <div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>'''
        self.assertTrue(narrate('https://garden.example/seed-trials/', html)[0].endswith(f'By {writers}.'))

    def test_postgres_news_preserves_release_headings_and_lists_without_page_navigation(self):
        html = f'''<title>Seed trials</title><div id="pgContentWrap"><h1>Seed trials</h1><div class="newsdate">Posted today</div>
        <p>{FIRST}</p><h2>Results</h2><ul><li>Green shoots.</li><li>Wide leaves.</li></ul>
        <p>{LAST}</p></div><p>Unrelated release archive.</p>'''
        _, body = narrate('https://www.postgresql.org/about/news/seed-trials/', html)
        self.assertEqual(body, f'{FIRST} Results Green shoots. Wide leaves. {LAST}')

    def test_jstor_does_not_repeat_a_pull_quote_but_keeps_a_unique_one(self):
        url = 'https://daily.jstor.org/seed-trials/'
        text = 'Our smallest tray had more growth.'
        widget = f'<aside class="pull-quote center"><div class="pull-quote__text">{text}</div></aside>'
        body = f'<p>{FIRST}</p>{widget}<p>{text} {LAST}</p>'
        page = f'<article><h1>Seed trials</h1><div class="entry-content">{body}</div></article>'
        self.assertEqual(narrate(url, page)[1].count(text), 1)
        self.assertEqual(html_to_text(body, url=url).count(text), 1)
        self.assertIn(text, narrate(url, page.replace(f'{text} {LAST}', LAST))[1])
        self.assertIn(text, html_to_text(body.replace(f'{text} {LAST}', LAST), url=url))

    def test_simon_release_feed_skips_only_its_repeated_opening_heading(self):
        url = 'https://simonwillison.net/2026/Nov/14/seed-trials/'
        title = 'Release: seed-trials 1.0'
        opening = '<p><strong>Release:</strong> <a href="https://github.com/example/seed-trials/releases/tag/v1">seed-trials 1.0</a></p>'
        self.assertEqual(html_to_text(opening + f'<p>{FIRST}</p>', title=title, url=url), FIRST)
        self.assertIn(title, html_to_text(opening, title=title, url=url))
        self.assertIn(title, html_to_text(opening + f'<p>{FIRST}</p>', title='Different entry', url=url))
        paragraph = '<p>This release adds a new measurement tool.</p>'
        self.assertEqual(html_to_text(opening + paragraph, title='seed-trials 1.0', url=url),
                         'This release adds a new measurement tool.')
        self.assertEqual(html_to_text(opening + f'<p>{FIRST}</p>', title='seed-trials 1.0', url=url), FIRST)
        extra = opening.replace('</p>', ' in our report.</p>')
        self.assertIn('in our report.', html_to_text(extra + f'<p>{FIRST}</p>', title='seed-trials 1.0', url=url))

    def test_webb_article_keeps_the_sibling_caption_and_removes_download_instructions(self):
        html = f'''<article><h1>Seed trials</h1><div class="usa-article-content"><div class="entry-content">
        <p>{FIRST}</p><div class="stma-image-wrapper"><img src="tray"></div>
        <figcaption class="hds-caption"><div>A tray at dusk.</div><div>Credit: Lee.</div></figcaption>
        <p>{LAST}</p><h2 class="wp-block-heading">Downloads &amp; Related Information</h2>
        <p>The following sections contain links to download this article's images and videos.</p>
        </div></div></article>'''
        _, body = narrate('https://science.nasa.gov/missions/webb/seed-trials/', html)
        self.assertEqual(body, f'{FIRST} A tray at dusk. Credit: Lee. {LAST}')

    def test_webb_rss_prunes_export_widgets_but_retains_unique_hero_and_inline_image_credits(self):
        url = 'https://science.nasa.gov/missions/webb/seed-trials/'
        title = 'Seed trials'
        caption = ('<figcaption class="hds-caption"><div class="hds-caption-text">Tray at dusk.</div>'
                   '<div class="hds-credits">Credit: Lee.</div></figcaption>')
        hero_caption = caption.replace('Credit: Lee.', 'Credits: Credit: Lee.')
        payload = f'''<div class="wp-block-nasa-blocks-secondary-navigation"><nav>Mission links</nav></div>
        <div class="wp-block-nasa-blocks-article-hero-header"><p>5 Min Read</p><h1>{title}</h1>{hero_caption}
        <figcaption class="hds-caption">A unique hero credit.</figcaption></div><p>{FIRST}</p>
        <div class="wp-block-image"><figure><img src="tray">{caption}</figure></div><p>{LAST}</p>
        <div class="wp-block-nasa-blocks-featured-link-list"><h2>Related Multimedia</h2>More photos</div>
        <h2>Related Links</h2><p>More Webb: <a href="/one">News</a> | <a href="/two">Science</a></p>
        <p>A final look at the <a href="/report">research report</a>.</p>
        <div class="wp-block-nasa-blocks-topic-cards"><h2>Related Topics</h2>Other stories</div>'''
        text = html_to_text(payload, title=title, url=url)
        self.assertEqual(text.split(), f'A unique hero credit. {FIRST} Tray at dusk. Credit: Lee. {LAST} '
                         'A final look at the research report.'.split())
        self.assertIn('5 Min Read', html_to_text(payload, title=title, url=url.replace('/webb/', '/other/')))

    def test_mit_skips_a_repeated_caption_quote_but_keeps_its_photo_credit_and_original(self):
        quote = '“The smallest seedlings grew best in the light,”'
        image = f'''<div class="news-article--inline-image--descr">
        <div class="news-article--inline-image--caption"><div>{quote} Lee says.</div></div>
        <div class="news-article--inline-image--credits"><div>Credit: Ash</div></div></div>'''
        html = f'''<article><h1>Seed trials</h1><div class="entry-content news-article--content--body--inner">
        <p>{FIRST}</p>{image}<div class="paragraph--type--content-block-text">
        <p>{quote} she says.</p><p>{LAST}</p></div></div></article>'''
        url = 'https://news.mit.edu/2026/seed-trials'
        _, body = narrate(url, html)
        self.assertEqual(body, f'{FIRST} Credit: Ash {quote} she says. {LAST}')
        control = html.replace('light,” Lee says.', 'shade,” Lee says.')
        self.assertIn('shade,” Lee says.', narrate(url, control)[1])

    def test_high_country_news_keeps_a_credit_and_nested_print_note_without_letter_prompt(self):
        html = f'''<article><h1>Seed trials</h1><div class="entry-content">
        <figure class="wp-block-image"><img src="tray"><figcaption><span class="image-credit">Credit: Lee</span></figcaption></figure>
        <p>{FIRST}</p><p class="wp-block-paragraph"><em>We welcome reader letters. Email </em>High Country News
        <a href="mailto:editor@hcn.org">our editors</a> or submit a <a href="/feedback/contact-us">letter</a>.
        See our <a href="/policies/lte">policy</a>.<p class="wp-block-paragraph">{LAST}</p></div></article>'''
        _, body = narrate('https://www.hcn.org/articles/seed-trials/', html)
        self.assertEqual(body, f'Credit: Lee {FIRST} {LAST}')
        emphasized = html.replace('<a href="mailto:editor@hcn.org">', '<em> at <a href="mailto:editor@hcn.org">')
        emphasized = emphasized.replace('>policy</a>.<p', '>policy</a>.</em><p')
        self.assertEqual(narrate('https://www.hcn.org/articles/seed-trials/', emphasized)[1],
                         f'Credit: Lee {FIRST} {LAST}')
        control = emphasized.replace('/policies/lte', '/about/editor')
        self.assertIn('We welcome reader letters.', narrate('https://www.hcn.org/articles/seed-trials/', control)[1])

    def test_aeon_feed_omits_the_duplicate_credit_and_matching_read_on_link(self):
        url = 'https://aeon.co/essays/seed-trials'
        ending = f'<p><em>- by Lee Writer</em></p><p><a href="{url}">Read on Aeon</a></p>'
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{ending}', url=url), FIRST)
        self.assertIn('Read on Aeon', html_to_text(f'<p>{FIRST}</p>{ending}<p>{LAST}</p>', url=url))
        self.assertIn('Read on Aeon', html_to_text(ending.replace('seed-trials', 'other-story'), url=url))

    def test_hyperallergic_preserves_ghost_image_captions_in_article_order(self):
        html = f'''<article class="gh-article"><h1>Seed trials</h1><section class="gh-content is-body">
        <figure class="kg-image-card"><img src="one"><figcaption>Tray one.</figcaption></figure><p>{FIRST}</p>
        <figure class="kg-image-card"><img src="two"><figcaption>Tray <em>two</em>.</figcaption></figure>
        <p>{LAST}</p></section><aside><figure class="kg-image-card"><img src="ad">
        <figcaption>Ad caption.</figcaption></figure></aside></article>'''
        _, body = narrate('https://hyperallergic.com/seed-trials/', html)
        self.assertEqual(body, f'Tray one. {FIRST} Tray two. {LAST}')

    def test_universe_today_preserves_the_lead_caption_and_stops_at_article_text(self):
        html = f'''<main class="container"><article><header class="article-header"><h1>Seed trials</h1></header>
        <figure><img src="tray"><figcaption>A tray. Credit: Lee.</figcaption></figure>
        <div class="article-content"><div class="text"><p>{FIRST}</p><p>{LAST}</p></div></div>
        <a class="plus-video-cta" href="/interview">Watch a trailer</a>
        <div class="author-footer"><p>Bio of Lee.</p></div></article></main>'''
        _, body = narrate('https://www.universetoday.com/articles/seed-trials', html)
        self.assertEqual(body, f'A tray. Credit: Lee. {FIRST} {LAST}')

    def test_freebsd_signed_travel_report_uses_the_named_guest_in_both_paths(self):
        url = 'https://freebsdfoundation.org/blog/event-report/'
        title = 'BSDCan 2026 Travel Report – Lee Writer'
        body = f'<p>{FIRST}</p><p>{LAST}<br>Be well,<br>Lee Writer bsdtv / bsdcan 2026 con chair</p>'
        html = f'<meta name="author" content="Site Editor"><article><h1>{title}</h1><div class="post-content">{body}</div></article>'
        intro, text = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertIn('Be well, Lee Writer', text)
        self.assertIn('By Site Editor.', narrate(url, html.replace('Lee Writer bsdtv', 'Ash Reporter bsdtv'))[0])
        post = {'title': title, 'canonical_url': url, 'body_html': body, 'publishedBylines': [{'name': 'Site Editor'}]}
        full, _ = Substack('').post_text({'rss': True}, post)
        self.assertEqual(full['publishedBylines'], [{'name': 'Lee Writer'}])
        feed = (f'<section class="block-tadv-classic-paragraph">{body}</section>'
                f'<p>The post <a href="{url}">{title}</a> first appeared on '
                '<a href="/">FreeBSD Foundation</a>.</p>')
        full, _ = Substack('').post_text({'rss': True}, {**post, 'body_html': feed})
        self.assertEqual(full['publishedBylines'], [{'name': 'Lee Writer'}])
        full, _ = Substack('').post_text({'rss': True}, {**post, 'body_html': f'<blockquote>{body}</blockquote>'})
        self.assertEqual(full['publishedBylines'], [{'name': 'Site Editor'}])

    def test_creative_commons_feed_spaces_exported_author_separators(self):
        source = Substack('')
        post = {'canonical_url': 'https://creativecommons.org/2026/10/02/seed-trials/', 'title': 'Seed trials',
                'body_html': f'<p>{FIRST}</p>', 'publishedBylines': [{'name': 'Lee Writer,Ash Reporter'}]}
        full, body = source.post_text({'rss': True}, post)
        self.assertEqual(full['publishedBylines'], [{'name': 'Lee Writer, Ash Reporter'}])
        self.assertEqual(body, FIRST)

    def test_propublica_project_preserves_visible_static_deck_and_linked_contributors(self):
        html = f'''<meta property="og:site_name" content="ProPublica"><main><article><header class="opener">
        <div class="opener__text"><h1 class="opener__hed">Seed trials</h1><p class="opener__dek">{FIRST}</p>
        <div class="opener__meta"><p class="opener__byline">by
        <a href="https://www.propublica.org/people/lee">Lee Writer</a> and
        <a href="https://www.propublica.org/people/ash">Ash Reporter</a></p></div></div></header>
        <div class="p-grid-container"><section class="stat-row" aria-label="Totals">
        <div class="stat"><span class="stat__value">5</span> <span class="stat__label">Trials completed</span></div>
        </section><div class="wide-block"><div class="callout-box">
        <h3 class="callout-box__hed">Send news tips</h3><div class="callout-box__text">
        <a href="https://www.propublica.org/tips/">Contact our reporters</a></div></div></div>
        <p>{LAST}</p></div></article></main>'''
        url = 'https://projects.propublica.org/seed-trials/'
        intro, body = narrate(url, html)
        self.assertEqual(intro, 'ProPublica. Seed trials. By Lee Writer, Ash Reporter.')
        self.assertEqual(body, f'{FIRST} Trials completed: 5. {LAST}')

    def test_internet_archive_uses_linked_masthead_and_keeps_inline_image_caption(self):
        html = f'''<meta property="og:site_name" content="Fictional Archive - Latest updates">
        <header><h1 class="site-title"><a href="/" rel="home">Fictional Archive</a></h1></header>
        <article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <figure class="wp-block-image"><img src="/trays"><figcaption class="wp-element-caption">
        Trays on the windowsill.</figcaption></figure><p>{LAST}</p></div></article>'''
        url = 'https://blog.archive.org/2026/11/17/seed-trials/'
        self.assertEqual(narrate(url, html),
                         ['Fictional Archive. Seed trials.', f'{FIRST} Trays on the windowsill. {LAST}'])
        external = html.replace('href="/"', 'href="https://example.com/"')
        self.assertTrue(narrate(url, external)[0].startswith('Fictional Archive - Latest updates.'))

    def test_react_uses_the_blog_brand_and_moves_dated_author_into_intro(self):
        html = f"""<title>Seed trials – React</title><a href="/">logo by Lee</a><main><article>
        <div><h1 class="mdx-heading">Seed trials</h1></div>
        <p>November 19, 2026 by <a href="/about">Lee Writer</a></p><hr>
        <p>{FIRST}</p><p>{LAST}</p></article></main>"""
        self.assertEqual(narrate('https://react.dev/blog/2026/11/19/seed-trials', html),
                         ['React. Seed trials. By Lee Writer.', f'{FIRST} {LAST}'])
        multiple = html.replace('Lee Writer</a></p>', 'Lee Writer</a> and <a href="/ash">Ash Editor</a></p>')
        self.assertEqual(narrate('https://react.dev/blog/2026/11/19/seed-trials', multiple),
                         ['React. Seed trials. By Lee Writer and Ash Editor.', f'{FIRST} {LAST}'])

    def test_eff_keeps_a_nested_caption_inside_the_full_deeplinks_article(self):
        caption = ('<div class="caption caption-center"><div class="caption-inner">'
                   '<img src="/tray"><p class="caption-text">A side view.</p></div></div>')
        html = f'''<article class="node--blog--full"><h1>Seed trials</h1><div class="node__content">
        <div class="field--name-body"><div class="field__items"><div class="field__item">
        <p>{FIRST}</p><p><span><i>{caption}</i></span></p><p>{LAST}</p>
        </div></div></div></div></article><article class="node--teaser"><h2>Other news</h2>
        {caption.replace('A side view.', 'Unrelated image.')}</article>'''
        self.assertEqual(narrate('https://www.eff.org/deeplinks/2026/11/seed-trials', html)[1],
                         f'{FIRST} A side view. {LAST}')

    def test_nieman_lab_keeps_the_editorial_quiz_photo_caption(self):
        html = f'''<article><h1>Seed trials</h1><div class="roscoe-article-body">
        <div class="roscoe-body"><p>{FIRST}</p><div class="rsc-quiz">
        <figure class="rsc-quiz-fig"><img src="/tray">
        <figcaption class="rsc-quiz-credit">A view of the tray.</figcaption></figure></div>
        <p>{LAST}</p><aside><div class="rsc-quiz"><figure class="rsc-quiz-fig"><img src="/ad">
        <figcaption class="rsc-quiz-credit">Sponsored image.</figcaption></figure></div></aside>
        </div></div></article>'''
        self.assertEqual(narrate('https://www.niemanlab.org/2026/11/seed-trials/', html)[1],
                         f'{FIRST} A view of the tray. {LAST}')

    def test_bicycle_retailer_uses_the_author_block_only_for_the_matching_article(self):
        url = 'https://www.bicycleretailer.com/retail-news/2026/11/19/seed-trials'
        html = f'''<title>Seed trials</title><article about="{url}"><h1>Seed trials</h1>
        <div class="entry-content"><p>{FIRST}</p><p>{LAST}</p><p>Lee Reader</p></div></article>
        <div id="block-views-author-block"><div class="view-author"><div class="authname">
        <a href="/authors/ash-writer">Ash Writer</a></div></div></div>'''
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('By Ash Writer.'), intro)
        self.assertEqual(body, f'{FIRST} {LAST} Lee Reader')
        self.assertNotIn('Ash Writer', narrate(f'{url}-different', html)[0])

    def test_rust_release_keeps_stabilized_api_links_and_matching_inline_punctuation(self):
        html = f'''<title>Seed trials</title><section class="white" id="Seed-trials"><div>
        <h1>Seed trials</h1><div class="post"><p>{FIRST}</p><h2>Stabilized APIs</h2>
        <ul><li><a href="/seed"><code><span>Tray</span><span>::</span>seed</code></a></li>
        <li><a href="/water"><code><span>Tray</span><span>::</span>water</code></a></li></ul>
        <p>{LAST}</p></div></div></section><section><h2>Other stories</h2></section>'''
        self.assertEqual(narrate('https://blog.rust-lang.org/2026/11/19/seed-trials/', html)[1],
                         f'{FIRST} Stabilized APIs Tray::seed Tray::water {LAST}')

    def test_julia_evans_keeps_inline_code_and_its_adjacent_punctuation(self):
        html = f'''<article class="hentry"><header><h1>Seed trials</h1><p>19 November 2026</p></header>
        <main><p>{FIRST}</p><h2>The first run</h2><p>The <code>seed</code>'s first run took an hour.</p>
        <pre><code><span>seed</span> --dry-run</code></pre><p>{LAST}</p></main>
        <footer><p>More articles and newsletter links</p></footer></article>'''
        self.assertEqual(narrate('https://jvns.ca/blog/2026/11/19/seed-trials/', html)[1],
                         f"{FIRST} The first run The seed's first run took an hour. seed --dry-run {LAST}")

    def test_main_with_external_heading_does_not_discard_an_explicit_article_body(self):
        html = f'''<title>Seed trials</title><main><header><h1>Seed trials</h1><p>Lee Writer</p></header>
        <article class="entry-content"><p>{FIRST}</p><p>{LAST}</p></article></main>'''
        self.assertEqual(narrate('https://garden.example/seed-trials', html)[1], f'{FIRST} {LAST}')

    def test_kde_skips_its_listmonk_prompt_and_preserves_editorial_newsletter_prose(self):
        html = f'''<article class="post-content"><h1>Seed trials</h1><div class="jumbotron"></div>
        <div class="content-width"><p>{FIRST}</p><h2>Newsletter findings</h2><p>{LAST}</p>
        <h2 id="newsletter">Newsletter</h2>
        <p>Enter your email address to follow this blog and receive notifications of new posts by email.</p>
        <form class="listmonk-form" action="https://newsletter.kde.org/subscription/form">
        <button>Subscribe</button></form></div></article>'''
        self.assertEqual(narrate('https://blogs.kde.org/2026/11/19/seed-trials/', html)[1],
                         f'{FIRST} Newsletter findings {LAST}')

    def test_bgs_skips_the_identified_related_news_carousel_in_both_paths(self):
        url = 'https://www.bgs.ac.uk/news/seed-trials/'
        editorial_body = f'<section class="content-section"><p>{FIRST}</p><h2>Related news</h2><p>{LAST}</p></section>'
        carousel = '''<section class="cards-carousel-section"><div class="container">
        <div class="header-of-section"><div class="col-12"><h2>Related news</h2></div></div>
        <div class="cards-find-more"><h4><a href="/other">Other story</a></h4></div></div></section>'''
        html = f'<main><h1>Seed trials</h1><div class="entry-content">{editorial_body}</div>{carousel}</main>'
        self.assertEqual(narrate(url, html)[1], f'{FIRST} Related news {LAST}')
        self.assertEqual(html_to_text(editorial_body + carousel, url=url), f'{FIRST}\nRelated news\n{LAST}')

    def test_nautilus_preserves_caption_and_credit_in_article_order(self):
        html = f"""<article><h1>Seed trials</h1><div class="entry-content">
        <div class="PostContent_content__fictional"><p>{FIRST}</p><figure class="wp-block-image"><img src="/plot">
        <figcaption class="wp-element-caption">Seeds after rain. <em>Photo by Lee.</em></figcaption>
        </figure><p>{LAST}</p></div></div></article>"""
        self.assertEqual(narrate('https://nautil.us/seed-trials-123/', html)[1],
                         f'{FIRST} Seeds after rain. Photo by Lee. {LAST}')

    def test_hcn_keeps_cover_and_inline_captions_without_republishing_widget(self):
        html = f"""<main class="site-main"><div class="featured-image-beside"><img src="/cover">
        <figcaption>Cover by Lee.</figcaption></div><div class="main-content"><article>
        <h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p><div class="wp-block-image">
        <figure><img src="/plot"><figcaption class="wp-element-caption">After rain.</figcaption></figure></div>
        <p>{LAST}</p><section class="below-content widget republication_tracker_tool">Republish This Story
        <p>Reuse details for newsrooms.</p></section></div></article></div></main>"""
        self.assertEqual(narrate('https://www.hcn.org/articles/seed-trials/', html)[1],
                         f'Cover by Lee. {FIRST} After rain. {LAST}')

    def test_damn_interesting_keeps_caption_and_one_rights_notice_without_donation_prompt(self):
        rights = '<p class="print-only print-copyright">Copyright belongs to the author.</p>'
        html = f"""<article><h1>Seed trials</h1>{rights}<div class="entry-content"><p>{FIRST}</p></div>
        <figure class="entry-image"><img src="/plot"><figcaption>After rain.</figcaption></figure>
        <div class="entry-content"><p>{LAST}</p></div>{rights}{rights}<p class="print-only">
        Since you enjoyed our work enough to print it out, <a href="/donate">give a little</a>.</p></article>"""
        # The publisher's full-width body uses the density fallback.
        html = html.replace(' class="entry-content"', '')
        _, body = narrate('https://www.damninteresting.com/seed-trials/', html)
        self.assertIn('After rain.', body)
        self.assertLessEqual(body.count('Copyright belongs to the author.'), 1)
        self.assertTrue(body.startswith(FIRST), body)
        self.assertNotIn('give a little', body)

    def test_outside_keeps_the_marked_inline_photo_caption_without_reading_sidebar_images(self):
        html = f'''<main><h1>Seed trials</h1><div class="article-template"><div class="js-body-content">
        <div class="content-wrap fp-contentTarget"><p>{FIRST}</p>
        <figure class="pom-image-wrap"><img src="tray"><figcaption class="pom-caption">
        <span class="article__caption">A tray in a greenhouse.</span> (Photo: Lee)</figcaption></figure><p>{LAST}</p></div>
        <aside><figure class="pom-image-wrap"><img src="ad"><figcaption class="pom-caption">
        Sponsored image.</figcaption></figure></aside></div></div></main>'''
        _, body = narrate('https://www.outsideonline.com/adventure-travel/seed-trials/', html)
        self.assertEqual(body, f'{FIRST} A tray in a greenhouse. (Photo: Lee) {LAST}')

    def test_kottke_untitled_post_does_not_read_clipped_opening_as_a_title(self):
        url = 'https://kottke.org/26/11/0054321-seed-trials'
        quote = f'“{FIRST} {LAST}”'
        schema = {'@type': 'BlogPosting', 'headline': quote[:64], 'url': url,
                  'author': {'name': 'Lee Writer'}, 'publisher': {'name': 'Garden Notes'}}
        html = f"""<title>{quote[:34]}...</title><link rel="canonical" href="{url}">
        <script type="application/ld+json">{json.dumps(schema)}</script>
        <div class="post"><div class="post-meta"><a href="{url}">Published today</a></div>
        <p>{quote}</p></div>"""
        self.assertEqual(narrate(url, html), ['Garden Notes. By Lee Writer.', quote])
        titled = html.replace(f'<p>{quote}', f'<h2 class="post-title">Seed trials</h2><p>{quote}')
        self.assertIn('Seed trials.', narrate(url, titled)[0])

    def test_mit_news_feed_byline_omits_branding_and_keeps_specific_affiliations(self):
        url = 'https://news.mit.edu/2026/seed-trials-1119'
        names = ['Lee Writer | MIT News', 'Ash Gardener | School of Science']
        expected = [{'name': 'Lee Writer'}, {'name': names[1]}]
        rss = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
        <title>Seed trials</title><link>{url}</link><pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate>
        <description><![CDATA[<p>{FIRST}</p>]]></description>
        {''.join(f'<dc:creator>{name}</dc:creator>' for name in names)}
        </item></channel></rss>"""
        atom = f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Seed trials</title>
        <link href="{url}"/><updated>2026-11-18T13:57:06Z</updated><content>{FIRST}</content>
        {''.join(f'<author><name>{name}</name></author>' for name in names)}
        </entry></feed>"""
        source = Substack('')
        pub = {'base': 'https://news.mit.edu/rss/feed', 'rss': True}
        for feed in (rss, atom):
            with patch.object(source, 'get', return_value=feed):
                post, = source.recent_posts(pub)
            self.assertEqual(post['publishedBylines'], expected)
            legacy = {**post, 'publishedBylines': [{'name': name} for name in names]}
            full, body = source.post_text(pub, legacy)
            self.assertEqual(full['publishedBylines'], expected)
            self.assertEqual(body, FIRST)
            self.assertEqual(legacy['publishedBylines'][0]['name'], names[0])

    def test_pluralistic_keeps_the_article_license_but_skips_the_verified_site_footer(self):
        url = 'https://pluralistic.net/2026/11/19/seed-trials/'
        license_note = 'This article uses a Creative Commons Attribution 4.0 license.'
        footer = ('<hr><h1>How to get Pluralistic:</h1>'
                  '<p><a href="https://pluralistic.net/plura-list">Newsletter</a></p>'
                  '<p>READ CAREFULLY: By reading this, you agree to the fictional site terms.</p>'
                  '<p>ISSN: 1234-567X</p>')
        markup = f'<p>{FIRST}</p><p>{LAST}</p><p>{license_note}</p>{footer}'
        html = f"""<article><h1>Seed trials</h1><div class="entry-content">{markup}</div>
        <footer class="entry-footer"><span class="byline"><span class="author vcard">
        <a href="/author/lee/">Lee Writer</a></span></span></footer></article>"""
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('By Lee Writer.'), intro)
        self.assertEqual(body, f'{FIRST} {LAST} {license_note}')
        self.assertEqual(html_to_text(markup, url=url), f'{FIRST}\n{LAST}\n{license_note}')
        self.assertIn('Newsletter', html_to_text(markup + '<p>A substantive closing note.</p>', url=url))

    def test_sciencedaily_keeps_the_illustration_caption_and_credit(self):
        html = f"""<main><h1>Seed trials</h1><div id="story_text"><div id="featured">
        <figure class="mainimg"><img src="/plots">
        <figcaption>Testing the plots. Credit: Lee Writer.</figcaption></figure></div>
        <p>{FIRST}</p><p>{LAST}</p></div></main>"""
        self.assertEqual(narrate('https://www.sciencedaily.com/releases/2026/11/seed-trials.htm', html)[1],
                         f'Testing the plots. Credit: Lee Writer. {FIRST} {LAST}')

    def test_cc_keeps_the_image_attribution_separately_from_page_license_boilerplate(self):
        html = f"""<body class="blog-post"><title>Seed trials</title><main><header><h1>Seed trials</h1>
        <figure><img src="/cover"><figcaption><p>Trial photos by Lee — <a href="/licenses/by/4.0/">CC BY 4.0</a>.</p>
        </figcaption></figure></header><div class="content"><p>{FIRST}</p><p>{LAST}</p>
        <div class="cc-attribution"><p>The text in this work is licensed under a Creative Commons
        <a href="https://creativecommons.org/licenses/by/4.0/">license</a>.</p></div>
        </div><article class="posts related"><p>Another story.</p></article></main></body>"""
        self.assertEqual(narrate('https://creativecommons.org/2026/11/seed-trials/', html)[1],
                         f'Trial photos by Lee — CC BY 4.0. {FIRST} {LAST}')

    def test_bbc_keeps_editorial_caption_without_the_screen_reader_prefix(self):
        html = f"""<main><article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <div data-testid="image"><figure><img src="/cover"><figcaption>
        <span class="visually-hidden">Image caption, </span><div><p>Putting the plots in order.</p></div>
        </figcaption></figure></div><p>{LAST}</p></div></article></main>"""
        self.assertEqual(narrate('https://www.bbc.com/news/articles/seed-trials', html)[1],
                         f'{FIRST} Putting the plots in order. {LAST}')

    def test_filfre_rejects_a_link_only_post_without_filling_it_with_sidebar_text(self):
        url = 'https://www.filfre.net/2026/11/seed-trials/'
        html = f"""<title>Seed trials</title><link rel="canonical" href="{url}">
        <div class="post hentry"><h1 class="post-title">Seed trials</h1><div class="entry">
        <p><a href="/external">This week's results</a></p></div></div>
        <div class="sidebar"><p>{FIRST} {LAST}</p></div>"""
        with self.assertRaisesRegex(ValueError, 'too little readable text'):
            narrate(url, html)

    def test_nasa_removes_rss_metadata_modules_but_preserves_a_details_section_with_prose(self):
        url = 'https://www.nasa.gov/testing/'
        opening = ('<div class="wp-block-nasa-blocks-article-intro"><div class="article-header">'
                   '<p class="label">2 min read</p><h1>Other story</h1></div></div>')
        end = ('<div class="wp-block-nasa-blocks-credits-and-details"><h2>Share</h2>'
               '<h2>Details</h2><div>Last Updated Tuesday</div><h2>Related Terms</h2></div>')
        self.assertEqual(html_to_text(opening + f'<p>{FIRST}</p>' + end, url=url), FIRST)
        self.assertIn(LAST, html_to_text(end.replace('</div>', f'<p>{LAST}</p></div>', 1), url=url))
        html = f"""<article><h1>Seed trials</h1><div class="entry-content">
        <div class="hds-media wp-block-image"><div class="hds-media-wrapper">
        <img src="/image"><figcaption>Observations after rain.</figcaption></div></div>
        <p>{FIRST}</p><p>{LAST}</p></div></article>"""
        self.assertEqual(narrate(url, html)[1], f'Observations after rain. {FIRST} {LAST}')

    def test_experimental_history_preserves_prose_beside_the_editor_subscribe_widget(self):
        url = 'https://www.experimental-history.com/p/seed-trials'
        widget = ('<div class="subscription-widget-wrap-editor"><div class="subscription-widget show-subscribe">'
                  '<p class="cta-caption">Follow the next trial</p></div></div>')
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{widget}<p>{LAST}</p>', url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Follow the next trial', html_to_text('<blockquote>' + widget + '</blockquote>', url=url))

    def test_guardian_keeps_one_lead_caption_and_does_not_announce_the_staff_role(self):
        url = 'https://www.theguardian.com/society/seed-trials'
        caption = '<figure><img src="/tray"><figcaption data-spacefinder-role="inline">A tray after rain.</figcaption></figure>'
        html = f"""<article><h1>Seed trials</h1><aside><address data-component="meta-byline" data-gu-name="byline">
        <a rel="author" href="/profile/lee">Lee Writer</a><span> Health policy editor</span></address></aside>
        <div data-gu-name="media">{caption}{caption}</div>
        <div data-gu-name="body"><div class="article-body-viewer-selector"><p>{FIRST}</p><p>{LAST}</p></div></div>
        </article>"""
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('By Lee Writer.'), intro)
        self.assertEqual(body, f'A tray after rain. {FIRST} {LAST}')
        xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
        <title>Seed trials</title><link>{url}</link><pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate>
        <description><![CDATA[<p>{FIRST}</p>]]></description>
        <dc:creator>Lee Writer Health policy editor</dc:creator></item></channel></rss>"""
        source = Substack('')
        pub = {'base': 'https://www.theguardian.com/society/rss', 'rss': True}
        with patch.object(source, 'get', return_value=xml):
            post, = source.recent_posts(pub)
        self.assertEqual(post['publishedBylines'], [{'name': 'Lee Writer'}])

    def test_propublica_keeps_editorial_captions_without_the_duplicate_cover_copy(self):
        credit = '<span class="p-attribution__caption">Trial plots.</span> <span class="p-attribution__credit">Image by Lee.</span>'
        html = f"""<article><h1>Seed trials</h1><div class="entry-header"><div class="p-opener">
        <div class="p-opener__art-wrapper"><figure><img src="/cover">
        <figcaption class="p-attribution screen-reader-text">{credit}</figcaption></figure></div>
        <figcaption aria-hidden="true" class="p-attribution">{credit}</figcaption></div></div>
        <div class="article-body"><div class="entry-content"><p>{FIRST}</p>
        <figure class="wp-block-image"><img src="/plots"><figcaption class="attribution">After rain.</figcaption></figure>
        <p>{LAST}</p></div></div></article>"""
        _, body = narrate('https://www.propublica.org/article/seed-trials', html)
        self.assertEqual(body, f'Trial plots. Image by Lee. {FIRST} After rain. {LAST}')

    def test_popular_science_featured_template_keeps_cover_and_inline_captions(self):
        html = f"""<article class="featured-template-post"><h1>Seed trials</h1>
        <figure class="featured-image"><img src="/lead"><figcaption class="article-featured-image-caption">
        <span class="article-featured-image-caption-credits">Image by Lee.</span></figcaption></figure>
        <section class="featured-template-content"><div class="entry-content"><div class="content-wrapper">
        <p>{FIRST}</p><figure class="wp-block-image"><img src="/tray">
        <figcaption class="wp-element-caption">A tray after rain.</figcaption></figure><p>{LAST}</p>
        </div></div></section></article>"""
        self.assertEqual(narrate('https://www.popsci.com/science/seed-trials/', html)[1],
                         f'Image by Lee. {FIRST} A tray after rain. {LAST}')

    def test_quanta_keeps_figure_caption_and_credit_between_body_modules(self):
        html = f"""<title>Seed trials</title><main><div class="post"><div class="has-tombstone">
        <div class="acf-content"><div class="post__content">{FIRST}</div></div>
        <figure><img src="/map"><figcaption><div class="caption"><p>A map of the plots.</p></div>
        <div class="attribution"><p>Map by Lee.</p><p hidden>Hidden credit.</p></div></figcaption></figure>
        <div class="acf-content"><div class="post__content">{LAST}</div></div>
        </div></div></main>"""
        self.assertEqual(narrate('https://www.quantamagazine.org/seed-trials/', html)[1],
                         f'{FIRST} A map of the plots. Map by Lee. {LAST}')

    def test_loc_keeps_the_cover_credit_and_drops_the_verified_subscription_footer(self):
        url = 'https://blogs.loc.gov/loc/2026/11/seed-trials/'
        footer = ('<p><a href="https://public.govdelivery.com/accounts/USLOC/subscriber/new?topic_id=example">'
                  '<em>Subscribe</em></a><em> to the blog— it’s free!</em></p>')
        markup = f'<p>{FIRST}</p><p>{LAST}</p>{footer}'
        html = f"""<article><header class="entry-header"><h1>Seed trials</h1>
        <figure class="hero-post"><img src="/map"><figcaption>Map by Lee.</figcaption></figure></header>
        <div class="entry-content">{markup}</div></article>"""
        self.assertEqual(narrate(url, html)[1], f'Map by Lee. {FIRST} {LAST}')
        self.assertEqual(html_to_text(markup, url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Subscribe', html_to_text(markup.replace('public.govdelivery.com', 'fictional.example'), url=url))

    def test_earthsky_keeps_the_video_caption_with_the_rich_text(self):
        html = f"""<title>Seed trials</title><div class="post-body"><div class="post"><div class="post-rich-text">
        <p>{FIRST}</p><figure class="wp-block-embed-youtube"><div class="wp-block-embed__wrapper">
        <iframe src="/player"></iframe></div><figcaption class="wp-element-caption">A labeled recording.</figcaption>
        </figure><p>{LAST}</p></div></div></div>"""
        self.assertEqual(narrate('https://earthsky.org/seed-trials/', html)[1], f'{FIRST} A labeled recording. {LAST}')

    def test_earthsky_keeps_editorial_caption_for_hosted_video(self):
        html = f'''<title>Seed trials</title><div class="post-body"><div class="post"><div class="post-rich-text">
        <p>{FIRST}</p><figure class="wp-block-video"><video src="/recording.mp4">Playback unavailable.</video>
        <figcaption class="wp-element-caption">A labeled recording.</figcaption></figure>
        <p>{LAST}</p></div></div></div>'''
        self.assertEqual(narrate('https://earthsky.org/seed-trials/', html)[1],
                         f'{FIRST} A labeled recording. {LAST}')

    def test_dev_preview_keeps_internal_headings_and_ignores_neighboring_cards(self):
        html = f"""<article id="article-show-container" class="crayons-article"><h1>Seed trials</h1>
        <div class="crayons-article__main"><div id="article-body" class="crayons-article__body">
        <p>{FIRST}</p><h2><a href="#result" name="result"></a>Results after rain</h2><p>{LAST}</p></div>
        <aside><p>Suggested article.</p></aside></div></article>"""
        self.assertEqual(narrate('https://dev.to/writer/seed-trials', html)[1],
                         f'{FIRST} Results after rain {LAST}')

    def test_simon_release_keeps_the_short_summary_after_the_title_is_announced_once(self):
        html = f"""<title>Release: Seed trials</title><div class="entry entryPage">
        <div class="beat"><div class="beat-content"><div class="beat-row1">
        <a class="beat-label release" href="/elsewhere/release/">Release</a>
        <span class="beat-title"><a href="https://example.test/release">Seed trials</a></span>
        <span class="beat-commit">— Report from the garden.</span>
        </div></div></div><p>{FIRST}</p><p>{LAST}</p></div>"""
        intro, body = narrate('https://simonwillison.net/2026/Nov/11/seed-trials/', html)
        self.assertIn('Release: Seed trials.', intro)
        self.assertEqual(body, f'Report from the garden. {FIRST} {LAST}')

    def test_geography_realm_keeps_captions_and_paragraphs_after_removing_page_navigation(self):
        html = f"""<article><h1>Seed trials</h1><div class="entry-content">
        <div><strong>Browse by state:</strong><br><a href="#one">First</a> • <a href="#two">Second</a></div>
        <h2 id="one">First</h2><p>{FIRST}</p>
        <div class="wp-block-image"><figure><img src="/plot.png">
        <figcaption class="wp-element-caption">A map of the trial plots.</figcaption></figure></div>
        <h2 id="two">Second</h2><p>{LAST}</p><h2 class="wp-block-heading">Related</h2>
        <ul class="wp-block-list"><li><a href="/another-story/">Another story</a></li></ul>
        </div></article>"""
        _, body = narrate('https://www.geographyrealm.com/seed-trials/', html)
        self.assertEqual(body, f'First {FIRST} A map of the trial plots. Second {LAST}')
        see_also = html.replace('>Related</h2>', ' id="h-see-also">See Also</h2>')
        url = 'https://www.geographyrealm.com/seed-trials/'
        self.assertEqual(narrate(url, see_also)[1], body)
        self.assertIn('See Also', narrate(url, see_also.replace('id="h-see-also"', 'id="editorial"'))[1])

    def test_construction_physics_keeps_substack_caption_and_removes_feed_permalink_button(self):
        url = 'https://www.construction-physics.com/p/seed-trials'
        html = f"""<article><h1>Seed trials</h1><div class="available-content"><div class="body markup">
        <p>{FIRST}</p><div class="captioned-image-container"><figure><img src="/image">
        <figcaption class="image-caption">A plot after rain.</figcaption></figure></div><p>{LAST}</p>
        </div></div></article>"""
        self.assertEqual(narrate(url, html)[1], f'{FIRST} A plot after rain. {LAST}')
        feed = f'<p>{FIRST}</p><p><a href="{url}">Read more</a></p>'
        self.assertEqual(html_to_text(feed, url=url), FIRST)
        self.assertIn('Read more', html_to_text(feed.replace('/seed-trials', '/other'), url=url))

    def test_substack_footnotes_keep_prose_without_paired_reference_numbers(self):
        ref = ('<a class="footnote-anchor" data-component-name="FootnoteAnchorToDOM" '
               'id="footnote-anchor-1" href="#footnote-1">1</a>')
        note = ('<div class="footnote" data-component-name="FootnoteToDOM"><a class="footnote-number" '
                'contenteditable="false" id="footnote-1" href="#footnote-anchor-1">1</a>'
                f'<div class="footnote-content"><p>{LAST}</p></div></div>')
        body = f'<p>{FIRST}{ref}</p>{note}'
        url = 'https://www.construction-physics.com/p/seed-trials'
        page = f'<article><h1>Seed trials</h1><div class="body markup">{body}</div></article>'
        self.assertEqual(narrate(url, page)[1], f'{FIRST} {LAST}')
        self.assertEqual(html_to_text(body), f'{FIRST}\n{LAST}')
        for control in (body.replace('href="#footnote-1"', 'href="#different-note"'), f'<blockquote>{body}</blockquote>'):
            self.assertIn(FIRST + '1', html_to_text(control))

    def test_astronomy_removes_a_terminal_staff_bio_but_keeps_quoted_text(self):
        bio = '<p class="wp-block-paragraph"><em><strong>Lee Writer</strong> is a staff writer at Astronomy, based here.</em></p>'
        html = f"""<meta name="author" content="Lee Writer"><article><h1>Seed trials</h1>
        <div class="entry-content"><p>{FIRST}</p><blockquote>{bio}</blockquote><p>{LAST}</p>
        <hr class="wp-block-separator">{bio}</div></article>"""
        _, body = narrate('https://www.astronomy.com/science/seed-trials/', html)
        self.assertEqual(body.count('staff writer'), 1)
        self.assertTrue(body.endswith(LAST))

    def test_openculture_strips_the_plain_link_related_list_in_both_paths(self):
        url = 'https://www.openculture.com/2026/11/seed-trials.html'
        links = ('<p><strong>Related Content:</strong></p><p><a href="/2026/01/a.html">Another story</a></p>'
                 '<p><a href="/2026/02/b.html">A prior story</a></p>')
        markup = f'<p>{FIRST}</p><p>{LAST}</p>{links}'
        html = f'<title>Seed trials</title><div class="recent_post"><div class="colorcontrast"><div class="entry">{markup}</div></div></div>'
        self.assertEqual(narrate(url, html)[1], f'{FIRST} {LAST}')
        self.assertEqual(html_to_text(markup, url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Related Content:', html_to_text(markup.rsplit('<p>',1)[0], url=url))

    def test_open_culture_announces_the_signed_writer_and_prunes_both_own_host_variants(self):
        url = 'https://www.openculture.com/2026/11/seed-trials.html'
        bio = '<p><em>Ted Mills is a free&shy;lance writer on the arts.</em></p>'
        related = ('<p><strong>Related Content:</strong></p><p><a rel="bookmark" '
                   'href="https://openculture.com/2026/01/old.html">An unrelated story</a></p>')
        story = f'<p>{FIRST}</p><p>{LAST}</p>{related}{bio}'
        html = (f'<title>Seed trials</title><meta name="author" content="OC"><div class="recent_post">'
                f'<div class="colorcontrast"><div class="entry">{story}</div></div></div>')
        intro, body = narrate(url, html)
        self.assertIn('By Ted Mills.', intro)
        self.assertNotIn('An unrelated story', body)
        source = Substack('')
        post = {'title': 'Seed trials', 'canonical_url': url, 'body_html': story,
                'publishedBylines': [{'name': 'OC'}]}
        full, text = source.post_text({'rss': True}, post)
        self.assertEqual(full['publishedBylines'], [{'name': 'Ted Mills'}])
        self.assertNotIn('An unrelated story', text)
        for markup in (f'<blockquote>{bio}</blockquote>', bio + f'<p>{LAST}</p>'):
            control, _ = source.post_text({'rss': True}, {**post, 'body_html': markup})
            self.assertEqual(control['publishedBylines'], [{'name': 'OC'}])

    def test_astronomy_photo_feed_removes_only_its_own_read_more_control(self):
        title = 'Seed trials'
        url = 'https://www.astronomy.com/picture-of-the-day/photo/seed-trials/'
        link = (f'<a class="more-link" href="{url}">Continue reading '
                '<span class="screen-reader-text">"Seed trials"</span></a>')
        self.assertEqual(html_to_text(f'<p>{FIRST}{link}</p>', title=title, url=url), FIRST)
        for keep in (link.replace('seed-trials/', 'another/'), link + ' ' + LAST, link.replace('>"Seed trials"<', '>"Another story"<')):
            self.assertIn('Continue reading', html_to_text(f'<p>{FIRST}{keep}</p>', title=title, url=url))

    def test_raspberry_pi_keeps_the_video_caption_without_the_embed(self):
        html = f"""<article><h1>Seed trials</h1><div class="c-post-content__wysiwyg"><p>{FIRST}</p>
        <figure class="wp-block-embed-youtube"><div class="wp-block-embed__wrapper"><iframe src="/player"></iframe></div>
        <figcaption class="wp-element-caption">A demonstration after rain.</figcaption></figure>
        <p>{LAST}</p></div></article>"""
        self.assertEqual(narrate('https://www.raspberrypi.com/news/seed-trials/', html)[1],
                         f'{FIRST} A demonstration after rain. {LAST}')

    def test_jim_nielsen_uses_the_page_title_publication_instead_of_the_feed_format(self):
        html = f"""<title>Seed trials - Fictional Garden Notes</title>
        <link rel="alternate" type="application/rss+xml" href="/feed.xml" title="RSS: XML Feed">
        <meta name="author" content="Lee Writer">
        <a href="/">Garden Notes</a><article><h1>Seed trials</h1>
        <div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>"""
        intro, body = narrate('https://blog.jim-nielsen.com/2026/seed-trials/', html)
        self.assertEqual(intro, 'Fictional Garden Notes. Seed trials. By Lee Writer.')
        self.assertEqual(body, f'{FIRST} {LAST}')

    def test_public_domain_review_keeps_collection_captions_and_source_links_in_order(self):
        html = f"""<article><h1>Seed trials</h1><div class="collection-preamble">
        <div class="essay__content entry-content"><p>{FIRST}</p>
        <div class="essay__image"><div class="essay__center-content"><img src="/image">
        <div class="essay__image__caption"><p>A tray after <em>rain</em> — <a href="/source">Source</a>.</p>
        <p>Photograph by Ash.</p></div></div></div>
        <div hidden class="essay__image"><div class="essay__center-content"><img src="/hidden">
        <div class="essay__image__caption"><p>Hidden credit.</p></div></div></div>
        <p>{LAST}</p></div></div></article>"""
        _, body = narrate('https://publicdomainreview.org/collection/seed-trials', html)
        self.assertEqual(body, f'{FIRST} A tray after rain — Source. Photograph by Ash. {LAST}')

    def test_public_domain_review_reads_the_collection_writer_and_image_grid_captions(self):
        html = f'''<div class="collection-view" role="main"><h1>Seed trials</h1>
        <div class="collection-byline"><div class="attribution">Text by <a href="/contributor/lee/">Lee Writer</a></div></div>
        <div class="collection-preamble"><div class="essay__content"><p>{FIRST}</p>
        <div class="essay__multi-image"><div class="essay__image__wrapper"><img src="tray">
        <span class="undownloaded-image">Scroll through the whole page to download all images before printing.</span></div>
        <div class="essay__multi-image__caption"><p>Three trays after the storm.</p></div></div>
        <p>For details, see <a href="/source">the notebook</a>.</p><p>{LAST}</p></div></div>
        <p>Browse another collection.</p></div>'''
        url = 'https://publicdomainreview.org/collection/seed-trials'
        intro, body = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(body, f'{FIRST} Three trays after the storm. For details, see the notebook. {LAST}')
        self.assertNotIn('By Lee Writer.', narrate(url, html.replace('/contributor/lee/', '/collections/lee/'))[0])

    def test_smashing_caption_preserves_literal_code_and_omits_same_image_zoom_link(self):
        html = f"""<article><h1>Seed trials</h1><div class="c-garfield-the-cat"><p>{FIRST}</p>
        <figure><a href="/plot.png"><img src="/plot.png"></a><figcaption class="op-vertical-bottom">
        A plot for <code>&lt;seed&gt;</code>. (<a href="/plot.png">Large preview</a>)</figcaption></figure>
        <figure><a href="/samples.png"><img src="/samples.png"></a><figcaption class="op-vertical-bottom">
        Observations after rain. (<a href="/other">Large preview</a>)</figcaption></figure>
        <p>{LAST}</p></div></article>"""
        _, body = narrate('https://www.smashingmagazine.com/2026/11/seed-trials/', html)
        self.assertIn('A plot for <seed>.', body.replace('> .', '>.'))
        self.assertEqual(body.count('Large preview'), 1)
        self.assertIn(LAST, body)

    def test_smashing_preserves_complete_quick_summary_including_leading_text(self):
        summary = 'Thousands of trials helped us understand how seedlings react when the light changes.'
        html = f'''<article><h1>Seed trials</h1><div class="article__content"><div class="c-garfield-the-cat">
        <div class="c-garfield-summary"><section aria-label="Quick summary" class="article__summary">
        <span aria-hidden="true" class="summary__heading" id="article__start"></span>{summary}
        We also tested <code>seed()</code> before starting the growing trial.</section></div>
        <p>{FIRST}</p><p>{LAST}</p></div></div></article>'''
        _, body = narrate('https://smashingmagazine.com/2026/11/seed-trials/', html)
        self.assertTrue(body.startswith(summary), body)
        self.assertEqual(body.count(summary), 1)
        self.assertIn('seed()', body)
        self.assertTrue(body.endswith(LAST), body)

    def test_strong_towns_uses_authors_beside_matching_headline_and_ignores_bio_card(self):
        html = f"""<title>Seed trials | Strong Towns</title><main><div class="thought-leadership_wrap">
        <section><div class="mast-col"><div class="heading-component"><h1>Seed trials</h1></div>
        <div class="w-dyn-list"><div class="w-dyn-items">
        <div class="w-dyn-item"><div class="mast-paragraph"><div>Lee Writer</div></div></div>
        <div hidden class="w-dyn-item"><div class="mast-paragraph"><div>Hidden Author</div></div></div>
        <div class="w-dyn-item"><div class="mast-paragraph"><div>Ash Gardener</div></div></div>
        </div></div></div></section>
        <section><div class="mast-article-rich-text w-richtext"><p>{FIRST}</p><h2>Results</h2>
        <figure class="w-richtext-figure-type-image"><img src="tray"><figcaption>Two trays outside.</figcaption></figure>
        <figure hidden class="w-richtext-figure-type-image"><img src="archived"><figcaption>Hidden caption.</figcaption></figure>
        <p>{LAST}</p>
        <p>More next week.</p></div><div class="mast-card"><p>Lee Writer publishes across the country.</p></div>
        </section></div></main>"""
        intro, body = narrate('https://www.strongtowns.org/journal/seed-trials', html)
        self.assertEqual(intro, 'Strong Towns. Seed trials. By Lee Writer, Ash Gardener.')
        self.assertEqual(body, f'{FIRST} Results Two trays outside. {LAST} More next week.')

    def test_zed_zoom_caption_survives_and_only_related_widget_prompt_is_removed(self):
        html = f"""<main><article class="entry-content"><h1>Seed trials</h1><p>{FIRST}</p>
        <a href="/chart.png"><button class="cursor-zoom-in"><figure><img src="/chart.png">
        <figcaption>Harvest by season</figcaption></figure></button></a>
        <h3>Related Posts</h3><p>A phrase that belongs in the article.</p><p>{LAST}</p>
        <div class="flex flex-col gap-5"><div><h3>Related Posts</h3><p>Check out similar blogs from the Zed team.</p>
        <div><a href="/blog/recommended">A recommended story</a></div></div></div></article></main>"""
        _, body = narrate('https://zed.dev/blog/seed-trials', html)
        self.assertEqual(body, f'{FIRST} Harvest by season Related Posts A phrase that belongs in the article. {LAST}')

    def test_zed_uses_all_photo_label_authors_from_the_matching_article_header(self):
        html = f'''<meta name="author" content="Lee Writer"><main><header><h1>Seed trials</h1>
        <div class="flex flex-wrap"><a href="https://github.com/lee">
        <img alt="Lee Writer"><p class="text-sm">Lee Writer</p></a>
        <a href="/team#ash"><img alt="Ash Editor"><p class="text-sm">Ash Editor</p></a>
        <a href="/subscribe"><img alt="Mail"><p class="text-sm">Subscribe</p></a></div></header>
        <article><div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article></main>'''
        intro, body = narrate('https://zed.dev/blog/seed-trials', html)
        self.assertTrue(intro.endswith('By Lee Writer, Ash Editor.'), intro)
        self.assertEqual(body, f'{FIRST} {LAST}')

    def test_reason_reads_the_article_permalink_as_headline_and_deck_once(self):
        url = 'https://reason.com/volokh/2026/11/19/seed-trials/'
        deck = 'The latest experiment used new equipment.'
        html = f'''<title>Seed trials</title><article class="volokh-post"><header>
        <h2 class="entry-title"><a href="{url}">Seed trials</a><p class="entry-subtitle">{deck}</p>
        <p class="meta"><span class="byline"><a rel="author" href="/author/lee">Lee Writer</a></span></p>
        </h2></header><div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>'''
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('Seed trials. By Lee Writer.'), intro)
        self.assertEqual(body, f'{deck} {FIRST} {LAST}')
        repeated = html.replace(f'<p>{FIRST}', f'<p>{deck}</p><p>{FIRST}')
        self.assertEqual(narrate(url, repeated)[1], body)

    def test_visible_heading_matches_encoded_schema_outside_the_article(self):
        url = 'https://www.geographyrealm.com/seed-trials/'
        schema = {'@type': 'BlogPosting', 'headline': 'Lee&#8217;s trials', 'url': url}
        html = f'''<script type="application/ld+json">{json.dumps(schema)}</script>
        <div><h1>Lee’s trials</h1></div><article><div class="entry-content"><p>{FIRST}</p>
        <p>{LAST}</p></div></article>'''
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('Lee’s trials.'), intro)
        self.assertEqual(body, f'{FIRST} {LAST}')

    def test_lithub_keeps_the_source_credit_and_skips_the_sibling_author_card(self):
        html = f"""<meta name="author" content="Lee Writer"><main><h1 class="entry-title">Seed trials</h1>
        <div class="story-content"><div class="story-body entry-content"><p>{FIRST}</p><p>{LAST}</p>
        <p>From <a href="/book">The seed journal</a>, published by arrangement.</p></div>
        <div class="bio-container"><div class="bio"><p>Lee Writer teaches gardening.</p></div></div>
        </div></main>"""
        intro, body = narrate('https://lithub.com/seed-trials/', html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(body, f'{FIRST} {LAST} From The seed journal, published by arrangement.')

    def test_lithub_keeps_prose_wrapped_in_the_layouts_ad_container(self):
        html = f'''<h1 class="entry-title">Seed trials</h1><div class="story-content"><div class="story-body">
        <p>{FIRST}</p><div class="pw-ad-scroll-container pw-clearfix"><div class="pw-ad-container-logo">
        <script>ad()</script><p>The roots stayed close to the surface of the tray.</p></div></div>
        <p>{LAST}</p></div><aside><p>Browse more reviews.</p></aside></div>'''
        self.assertEqual(narrate('https://lithub.com/seed-trials/', html)[1],
                         f'{FIRST} The roots stayed close to the surface of the tray. {LAST}')

    def test_quillette_uses_the_visible_writer_and_keeps_only_the_public_teaser(self):
        bookmark = '''<figure class="kg-card kg-bookmark-card"><a class="kg-bookmark-container" href="/extra/">
        <div class="kg-bookmark-content"><div class="kg-bookmark-title">Another article</div></div></a></figure>'''
        body = f'<p>{FIRST}</p>{bookmark}<p>{LAST}</p>'
        html = f'''<article class="post"><header><h1>Seed trials</h1>
        <a href="/author/lee/"><figure><figcaption class="sr-only">headshot</figcaption></figure></a>
        <div><a href="/author/lee/">Lee Writer</a><a href="/author/other/">Other author</a></div>
        <figure class="gh-feature-image"><img src="/tray"><figcaption>Seed tray.</figcaption></figure></header>
        <section><div class="gh-content-fade">{body}</div><div><p>The rest is for paying subscribers.</p></div>
        </section></article>'''
        url = 'https://quillette.com/2026/11/17/seed-trials/'
        intro, text = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(text, f'Seed tray. {FIRST} {LAST}')
        self.assertEqual(html_to_text(body, url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Another article', html_to_text(f'<blockquote>{bookmark}</blockquote>', url=url))

    def test_wyofile_uses_signed_byline_and_captions_without_player_or_related_cards(self):
        byline = 'Lee Writer, Ash Gardener, Jules Grower and Pat Seed'
        html = f"""<meta name="author" content="Posting Account"><main class="site-main">
        <div class="featured-image-above"><figure class="post-thumbnail"><img src="/lead.png">
        <figcaption>A lead credit.</figcaption></figure><header class="entry-header">
        <h1 class="entry-title">Seed trials</h1><div class="entry-meta"><span class="byline">by {byline}</span></div>
        </header></div><div class="main-content"><article><div class="entry-content">
        <div class="article-summary"><div class="instaread-player-slot"></div>
        <p class="instaread-disclaimer">Play automatically generated audio.</p><p>Reported jointly.</p>
        <p>Do you have questions about this story? Or information to share? Reach out to Lee Writer at
        <a href="mailto:lee@wyofile.com">lee@wyofile.com</a>.</p></div>
        <p>{FIRST}</p><div class="wp-block-image"><figure><img src="/tray.png">
        <figcaption class="wp-element-caption">A tray after rain.</figcaption></figure></div>
        <p>{LAST}</p><div class="wp-block-newspack-blocks-homepage-articles wpnbha"><div>
        <h2 class="article-section-title">RELATED</h2><article class="type-post"><h3>Other story</h3></article>
        </div></div></div></article></div></main>"""
        intro, body = narrate('https://wyofile.com/seed-trials/', html)
        self.assertIn(f'By {byline}.', intro)
        self.assertEqual(body, f'A lead credit. Reported jointly. {FIRST} A tray after rain. {LAST}')

    def test_wyofile_feed_keeps_all_signed_writers_once_and_preserves_unrelated_creators(self):
        url = 'https://wyofile.com/seed-trials/'
        title = 'Seed trials'
        signed = 'Lee Writer, Ash Gardener and Pat Seed'
        authors = [f'by {signed}', 'Ash Gardener, Example Daily', 'Pat Seed']
        xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
        <title>{title}</title><link>{url}</link><pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate>
        <description><![CDATA[<p>{FIRST}</p><p>The post <a href="{url}">{title}</a> appeared first on
        <a href="https://wyofile.com">WyoFile </a>.</p>]]></description>
        {''.join(f'<dc:creator>{name}</dc:creator>' for name in authors)}
        </item></channel></rss>"""
        sub = Substack('')
        pub = {'base': 'https://wyofile.com/feed/', 'rss': True}
        with patch.object(sub, 'get', return_value=xml):
            post, = sub.recent_posts(pub)
        self.assertEqual(post['publishedBylines'], [{'name': signed}])
        cached = {**post, 'publishedBylines': [{'name': name} for name in authors]}
        full, body = sub.post_text(pub, cached)
        self.assertEqual(full['publishedBylines'], [{'name': signed}])
        self.assertEqual(body, FIRST)
        cached['publishedBylines'][-1] = {'name': 'Another Contributor'}
        self.assertEqual(sub.post_text(pub, cached)[0]['publishedBylines'], cached['publishedBylines'])

    def test_buttondown_keeps_the_subject_deck_and_inner_heading_but_skips_web_footer(self):
        html = f"""<article class="email-body"><h1 class="subject">Seed trials</h1>
        <h2 class="description">Field notes</h2><div class="email-body-content">
        <p>{FIRST}</p><hr><h1>Volunteer update</h1><p>{LAST}</p>
        <pre><code>model = &#60;Plant&#62;</code></pre></div>
        <div class="email-body-web-footer"><p>Subscribe to these updates.</p></div></article>"""
        _, body = narrate('https://buttondown.com/fictional/archive/trials/', html)
        self.assertEqual(body, f'Field notes {FIRST} Volunteer update {LAST} model = <Plant>')

    def test_colossal_preview_keeps_the_featured_credit_once_before_the_prose(self):
        url = 'https://www.thisiscolossal.com/2026/11/seed-trials/'
        html = f"""<article><h1>Seed trials</h1><p class="byline"><a rel="author">Lee Writer</a></p>
        <div class="entry-content"><div class="entry-header">
        <figure class="colo-post-featured-image"><img src="/tray.jpg">
        <figcaption class="wp-element-caption">All images courtesy of <strong>Ash</strong></figcaption></figure>
        </div><p>{FIRST}</p><figure class="wp-block-image"><img src="/tray-two.jpg">
        <figcaption class="wp-element-caption">The second trial. Photo by Lee.</figcaption></figure>
        <p>{LAST}</p><aside><figure class="colo-post-featured-image">
        <img src="/ad.jpg"><figcaption class="wp-element-caption">Advertisement caption</figcaption>
        </figure></aside></div></article>"""
        intro, body = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(body, f'All images courtesy of Ash {FIRST} The second trial. Photo by Lee. {LAST}')

    def test_paris_review_uses_the_visible_headline_beside_the_article_body(self):
        url = 'https://www.theparisreview.org/blog/2026/11/19/seed-trials/'
        schema = {'@type': 'Article', 'url': url, 'headline': 'A gardener&#8217;s notebook',
                  'author': {'name': 'Lee Writer'}}
        html = f"""<meta property="og:site_name" content="Example Review">
        <meta property="og:title" content="A gardener's notebook by Lee Writer">
        <script type="application/ld+json">{json.dumps(schema)}</script>
        <h1 hidden>A gardener’s notebook</h1><h1>Sign In</h1>
        <section id="content"><header class="titles"><h1>A gardener&rsquo;s notebook</h1></header>
        <div class="article-body-wrap"><main class="blog-body"><div class="entry-content">
        <p>{FIRST}</p><p>{LAST}</p></div></main></div></section>"""
        intro, body = narrate(url, html)
        self.assertEqual(intro, 'Example Review. A gardener’s notebook. By Lee Writer.')
        self.assertEqual(body, f'{FIRST} {LAST}')
        # Visible examples of character-reference syntax are intentional.
        literal = html.replace('gardener&rsquo;s', 'gardener&amp;#8217;s')
        self.assertIn('A gardener&#8217;s notebook.', narrate(url, literal)[0])

    def test_paris_review_keeps_editorial_div_between_prose_and_quotation(self):
        html = f'''<h1>Seed trials</h1><section id="content" role="main"><div class="article-body-wrap">
        <main class="article-body blog-body"><p>{FIRST}</p>
        <div class="wp-caption"><img src="tray"><p class="wp-caption-text">Tray photograph by Lee.</p></div>
        <div id="message-list_test"><div aria-roledescription="message"><div><div draggable="false">
        <div>One source is <a href="/diary"><em>A gardener’s diary</em></a>.</div>
        </div></div></div></div><blockquote>The plants bent toward the light.</blockquote>
        <p>{LAST}</p></main><aside><p>Unrelated subscription</p></aside></div></section>'''
        _, body = narrate('https://www.theparisreview.org/blog/2026/11/19/seed-trials/', html)
        self.assertEqual(body, f'{FIRST} Tray photograph by Lee. One source is A gardener’s diary. '
                         f'The plants bent toward the light. {LAST}')

    def test_harvard_preview_keeps_the_inline_caption_and_linked_scores_in_order(self):
        html = f"""<article class="node--type-article"><h1>Seed trials</h1>
        <div class="article_header_section"><div class="field--name-field-hero-image">
        <figure class="media--view-mode-article-hero"><img src="/hero.jpg"><figcaption>
        <p>The first three seedlings. Photographs by Lee.</p></figcaption></figure></div></div>
        <div class="block-field-blocknodearticlebody"><div class="field--name-body field--type-text-with-summary">
        <p>{FIRST}</p><figure class="caption caption-img"><img src="/tray.jpg">
        <figcaption><strong>Seed tray</strong> | Photograph by Ash</figcaption></figure>
        <p>Short result.</p><p>{LAST}</p><p><a href="/results">Earlier results</a></p></div></div>
        <aside><figure class="caption caption-img"><img src="/sidebar.jpg">
        <figcaption>Advertisement caption</figcaption></figure></aside></article>"""
        _, body = narrate('https://www.harvardmagazine.com/seed-trials', html)
        self.assertEqual(body, f'The first three seedlings. Photographs by Lee. {FIRST} '
                         f'Seed tray | Photograph by Ash Short result. {LAST} Earlier results')

    def test_harvard_export_drops_an_account_and_topics_without_guessing_attribution(self):
        url = 'https://www.harvardmagazine.com/seed-trials'
        account = 'fictional-user@harvard.edu'
        body = f'''<span class="field--name-title">Seed trials</span>
        <div class="field--name-body field--type-text-with-summary"><p>{FIRST}</p><p>{LAST}</p></div>
        by <a href="/writer/lee-writer">{account}</a>
        <div class="field--name-field-sub-topics"><div class="field__label">Related topics</div>Test tag</div>
        <div class="field--name-field-featured-topic"><div class="field__label">Primary Topic</div>News</div>'''
        entry = {'title': 'Seed trials', 'canonical_url': url, 'body_html': body,
                 'publishedBylines': [{'name': account}]}
        post, text = Substack('').post_text({'rss': True}, entry)
        self.assertEqual(post['publishedBylines'], [])
        self.assertEqual(text, f'{FIRST}\n{LAST}')
        self.assertIn(account, html_to_text(body, title='Different title', url=url))

    def test_harvard_rss_uses_the_exported_writer_and_removes_only_template_fields(self):
        url = 'https://www.harvardmagazine.com/seed-trials'
        html = f"""<span class="field--name-title">Seed trials</span>
        <span class="field--name-uid">Uploader</span><span class="field--name-created">Posted Tuesday</span>
        <div class="field--name-body field--type-text-with-summary"><p>{FIRST}</p>
        <figure><figcaption>A tray after rain.</figcaption></figure>
        <p>Hero image is the term we used in the experiment.</p><p>{LAST}</p></div>
        by <a href="/writer/lee">Lee Writer</a>
        <div class="field--name-field-external-description"><div class="field__label">Subhead (Required)</div>
        <div class="field__item">What the seedlings showed.</div></div>
        <div class="field--name-field-full-header-section">Deprecated header setting</div>
        <div class="field--name-field-hero-image">tray.webp</div>
        <div class="field--name-field-slug">Page Slug (Required)</div><p>Corrections added Tuesday.</p>"""
        xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
        <title>Seed trials</title><link>{url}</link><guid>trial-1</guid>
        <pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate>
        <dc:creator>uploader@example.test</dc:creator>
        <description><![CDATA[{html}]]></description></item></channel></rss>"""
        sub = Substack('')
        pub = {'base': 'https://www.harvardmagazine.com/rss.xml', 'rss': True}
        with patch.object(sub, 'get', return_value=xml):
            post, = sub.recent_posts(pub)
        self.assertEqual(post['publishedBylines'], [{'name': 'Lee Writer'}])
        cached = {**post, 'publishedBylines': [{'name': 'uploader@example.test'}]}
        full, body = sub.post_text(pub, cached)
        self.assertEqual(full['publishedBylines'], post['publishedBylines'])
        self.assertEqual(cached['publishedBylines'], [{'name': 'uploader@example.test'}])
        self.assertEqual(body.splitlines(), [
            'What the seedlings showed.', FIRST, 'A tray after rain.',
            'Hero image is the term we used in the experiment.', LAST, 'Corrections added Tuesday.',
        ])
        for other_url, other_title in ((url, 'Other title'), ('https://example.test/seed-trials', 'Seed trials')):
            with self.subTest(url=other_url, title=other_title):
                self.assertIn('Page Slug (Required)', html_to_text(html, title=other_title, url=other_url))

    def test_outside_keeps_headings_short_prose_and_photo_credit_but_drops_promotions(self):
        url = 'https://www.outsideonline.com/health/wellness/seed-trials/'
        footer = """<p><b>Want more <i>Outside</i> health stories?</b>
        <a href="https://hub.outsideinc.com/bodywork_newsletter_sign_up-0">Sign up for the Bodywork newsletter</a>.
        <a href="/newsletters/sweat-science-101/?utm_source=article">Sign up for the Sweat Science 101 newsletter</a>.</p>"""
        body = f"""<p>{FIRST}</p><h2>How we counted</h2><h3>1. Start at dawn</h3><p>Short result.</p>
        <blockquote>{footer}</blockquote><p>{LAST}</p>"""
        html = f"""<head><meta name="author" content="Lee Writer"></head>
        <div class="article-template"><div class="js-body-content"><div class="article-header"><h1>Seed trials</h1>
        <div><img src="/tray.jpg"><p class="fp-leadCaption">Photograph by Ash.</p></div></div>
        <div class="content-wrap fp-contentTarget"><div class="article-body"><div class="pub-date">Published today</div></div>
        <div class="ad-placeholder-wrapper">ADVERTISEMENT</div>{body}{footer}<span></span></div>
        <div class="article-bottom"><h2>More coverage</h2></div></div></div>"""
        intro, preview_body = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertTrue(preview_body.startswith(f'Photograph by Ash. {FIRST} How we counted 1. Start at dawn Short result.'))
        rss_body = html_to_text(
            body + footer + f'<p>The post <a href="{url}">Seed trials</a> appeared first on '
            '<a href="https://www.outsideonline.com">Outside Online</a>.</p>', title='Seed trials', url=url)
        for text in (preview_body, rss_body):
            self.assertEqual(text.count('Want more Outside health stories?'), 1)
            self.assertIn('1. Start at dawn', text)
            self.assertTrue(text.endswith(LAST))
            for excluded in ('ADVERTISEMENT', 'Published today', 'More coverage', 'appeared first'):
                self.assertNotIn(excluded, text)
        self.assertEqual(html_to_text(body + footer + '<p>Closing note.</p>', url=url).count('Want more'), 2)

    def test_outside_rss_treats_a_login_as_missing_byline_and_keeps_display_names(self):
        pub = {'base': 'https://www.outsideonline.com/feed/', 'rss': True}
        sub = Substack('')
        for creator, host, expected in (
                ('loadingeditor', 'www.outsideonline.com', []),
                ('Lee Writer', 'www.outsideonline.com', [{'name': 'Lee Writer'}]),
                ('loadingeditor', 'example.test', [{'name': 'loadingeditor'}])):
            with self.subTest(creator=creator, host=host):
                xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
                <title>Seed trials</title><link>https://{host}/seed-trials/</link>
                <pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate><dc:creator>{creator}</dc:creator>
                <description><![CDATA[<p>{FIRST}</p>]]></description></item></channel></rss>"""
                with patch.object(sub, 'get', return_value=xml):
                    post, = sub.recent_posts(pub)
                self.assertEqual(post['publishedBylines'], expected)
                cached = {**post, 'publishedBylines': [{'name': creator}]}
                self.assertEqual(sub.post_text(pub, cached)[0]['publishedBylines'], expected)

    def test_guardian_credits_the_visible_author_and_retains_only_inline_caption(self):
        html = f"""<head><meta name="author" content="Staff reporter"></head><article><h1>Seed trials</h1>
        <aside data-gu-name="meta"><address data-component="meta-byline" data-gu-name="byline">
        <div><span>Lee</span><span hidden>Other author</span></div></address></aside>
        <div data-gu-name="body"><div class="article-body-viewer-selector"><p>{FIRST}</p>
        <figure><img src="/photo"><figcaption data-spacefinder-role="inline">Photo by Lee.</figcaption></figure>
        <p>{LAST}</p></div></div></article>"""
        intro, body = narrate('https://www.theguardian.com/science/seed-trials', html)
        self.assertTrue(intro.endswith('By Lee.'), intro)
        self.assertEqual(body.split(), f'{FIRST} Photo by Lee. {LAST}'.split())

    def test_hakai_keeps_visible_coauthors_and_captions_without_the_hidden_body_label(self):
        html = f"""<article><header><h1>Seed trials</h1><section class="singlebyline">
        <a id="author_link_top" href="/profiles/lee/">Lee</a> and
        <a id="author_link_top" href="/profiles/ash/">Ash</a></section></header>
        <section class="maincontent"><h3 class="invis">Article body copy</h3><p>{FIRST}</p>
        <div class="wp-caption"><img src="/photo"><p class="wp-caption-text">A tray after rain.</p></div>
        <p>{LAST}</p></section></article>"""
        intro, body = narrate('https://hakaimagazine.com/features/seed-trials/', html)
        self.assertTrue(intro.endswith('By Lee, Ash.'), intro)
        self.assertEqual(body.split(), f'{FIRST} A tray after rain. {LAST}'.split())

    def test_plover_fragment_reads_story_title_once_and_keeps_series_links(self):
        archive = 'https://blog.plover.com/2026/09/24/#seed-trials'
        permalink = 'https://blog.plover.com/science/seed-trials.html'
        html = f"""<head><meta property="og:site_name" content="Example weblog : Seed trials"></head>
        <h1 class="pagetitle">Example weblog</h1><div class="mainsection"><span class="dateheader">Thu, 24 Sep 2026</span>
        <p><a class="storytitle" name="seed-trials" href="{permalink}">Seed trials</a><br>
        <p>{FIRST}</p><ol><li><a href="/prior">Earlier experiments</a></li></ol><p>{LAST}</p></p>
        <p>[ <a href="/science/">Other articles in category /science</a> ] <i><a href="{permalink}">permanent link</a></i></p>
        </div>"""
        for url in (archive, permalink):
            with self.subTest(url=url):
                intro, body = narrate(url, html)
                self.assertEqual(intro, 'Example weblog. Seed trials.')
                self.assertEqual(body.split(), f'{FIRST} Earlier experiments {LAST}'.split())

    def test_webdev_uses_the_visible_title_and_author_card(self):
        html = f"""<article><h1 class="devsite-page-title">Seed trials<devsite-actions hidden>
        <span>Save this page</span></devsite-actions></h1><div class="devsite-article-body entry-content">
        <p><div class="wd-authors"><div class="wd-author"><div><span>Lee</span>
        <span class="wd-author__title">Technical Writer</span></div></div>
        <div class="wd-author" hidden><div><span>Other author</span></div></div>
        </div></p><p>{FIRST}</p><p>{LAST}</p></div></article>"""
        intro, _ = narrate('https://web.dev/blog/seed-trials', html)
        self.assertEqual(intro, 'web.dev. Seed trials. By Lee.')

    def test_mental_floss_keeps_lead_and_inline_photo_credits_in_order(self):
        html = f"""<article id="main-article"><h1>Seed trials</h1>
        <figure><div data-lead-image="true"><picture><img src="tray"></picture></div>
        <div><figcaption>Lead photo by Lee.</figcaption></div></figure>
        <div class="odesa-article-main"><div class="entry-content article-content"><p>{FIRST}</p>
        <figure><div><picture><img src="another"></picture></div>
        <div><figcaption>Another photo by Ash.</figcaption></div></figure>
        <figure hidden><div><img src="hidden"></div><div><figcaption>Hidden caption.</figcaption></div></figure>
        <p>{LAST}</p></div></div></article>"""
        _, body = narrate('https://www.mentalfloss.com/history/seed-trials', html)
        self.assertEqual(body.split(), f'Lead photo by Lee. {FIRST} Another photo by Ash. {LAST}'.split())

    def test_nieman_keeps_prose_inside_paragraphs_that_start_with_a_related_story_card(self):
        card = ('<div class="embed-relatedstory"><a class="embed-relatedstory-imagelink" href="/other">Photo</a>'
                '<div class="embed-relatedstory-headline">A different story</div></div>')
        html = f"""<article><h1>Seed trials</h1><div class="entry-content roscoe-body"><p>{card}{FIRST}</p>
        <p>We <a href="/notes">checked the same plots</a> again.</p><p>{LAST}</p></div></article>"""
        _, body = narrate('https://www.niemanlab.org/2026/11/seed-trials/', html)
        self.assertEqual(body.split(), f'{FIRST} We checked the same plots again. {LAST}'.split())

    def test_nieman_preserves_chart_labels_and_footnotes_without_reading_controls(self):
        html = f'''<h1>Seed trials</h1><div class="roscoe-article-body"><div class="roscoe-body">
        <p>{FIRST}</p><div class="ljc"><div class="ljc-title">Tray measurements</div>
        <p>Measured at noon.</p><script>const data = []</script></div>
        <p>Seeds sprouted<sup><a class="footnote-identifier-link" id="reference" href="#note">1</a></sup>.</p>
        <p>{LAST}<ol class="footnotes"><li class="footnote" id="note">The trays were <a href="/trays">shallow</a>.
        [<a class="footnote-back-link" href="#reference">↩</a>]</li></ol></p>
        <blockquote>Use [<a class="footnote-back-link" href="#reference">↩</a>] to return.</blockquote>
        </div></div><p>Newsletter signup</p>'''
        _, body = narrate('https://www.niemanlab.org/2026/11/seed-trials/', html)
        self.assertEqual(body, f'{FIRST} Tray measurements Measured at noon. Seeds sprouted. {LAST} '
                         'The trays were shallow. Use [↩] to return.')

    def test_openstreetmap_diary_uses_the_permalink_title_and_profile(self):
        url = 'https://www.openstreetmap.org/user/lee/diary/42'
        html = f"""<head><title>Lee’s Diary | Paths near the greenhouse | OpenStreetMap</title>
        <meta property="og:site_name" content="OpenStreetMap"></head>
        <h1>Lee’s Diary</h1><article class="diary_post"><div class="mb-3">
        <h2><a href="/user/lee/diary/42">Paths near the greenhouse</a></h2>
        <small>Posted by <a href="/user/lee">Lee</a> in <a href="/diary/en">English</a>.</small></div>
        <div class="richtext"><p>{FIRST}</p><p>{LAST}</p></div></article>"""
        intro, body = narrate(url, html)
        self.assertEqual(intro, 'OpenStreetMap. Paths near the greenhouse. By Lee.')
        self.assertEqual(body.split(), f'{FIRST} {LAST}'.split())
        unrelated, _ = narrate(url, html.replace('/user/lee/diary/42', '/user/lee/diary/41'))
        self.assertNotIn('By Lee.', unrelated)

    def test_sapiens_keeps_image_footers_with_their_caption_and_credit(self):
        figure = """<figure class="c-image-video"><img src="/photo"><footer class="c-image-video__footer">
        <div class="c-media-caption"><p>A field study.</p></div>
        <div class="c-media-credits"><a href="/artist">Photo by Ash.</a></div>
        </footer></figure>"""
        html = f"""<article><h1>Seed trials</h1><div class="entry-content c-article-content">
        <div class="m-article-img-header">{figure}</div><p>{FIRST}</p>
        <div class="m-image-video">{figure.replace('A field study.', 'A second tray.')}</div>
        <div class="m-image-video" hidden>{figure}</div><p>{LAST}</p>
        <footer><p>Email the editors</p></footer></div></article>"""
        _, body = narrate('https://www.sapiens.org/culture/seed-trials/', html)
        self.assertEqual(body.split(), f'A field study. Photo by Ash. {FIRST} A second tray. Photo by Ash. {LAST}'.split())

    def test_sapiens_keeps_each_grid_caption_and_the_standfirst_but_not_archive_promo(self):
        photos = ''.join(f'<div class="m-two-images__media"><figure class="c-image-video"><img src="{label}">'
                         '<footer class="c-image-video__footer"><div class="c-media-caption">'
                         f'<p>A {label} tray.</p></div><div class="c-media-credits">Photo by Lee.</div>'
                         '</footer></figure></div>' for label in ('first', 'second'))
        html = f'''<title>Seed trials</title><div class="c-article-content" data-article-content><div class="p-header-article">
        <h1 class="p-header-article__title">Seed trials</h1><div class="p-header-article__standfirst">Opening context.</div>
        </div><div class="m-article-img-header"><figure class="c-image-video"><img src="cover">
        <footer class="c-image-video__footer"><div class="c-media-caption">The cover tray.</div></footer></figure></div>
        <div class="c-modules"><div class="m-wysiwyg"><div class="wysiwyg">
        <div class="paragraph-break">✽</div><p>{FIRST}</p></div></div><div class="m-two-images">{photos}</div>
        <div class="m-pull-quote"><blockquote><p>To learn more, read on from the SAPIENS archive:
        <a href="/culture/another/">A different story.</a></p></blockquote></div>
        <blockquote>Short original quotation.</blockquote><p>{LAST}</p></div><div class="m-authors">Bio.</div></div>'''
        _, body = narrate('https://www.sapiens.org/culture/seed-trials/', html)
        self.assertEqual(body, f'Opening context. The cover tray. {FIRST} A first tray. Photo by Lee. A second tray. Photo by Lee. '
                         f'Short original quotation. {LAST}')

    def test_longreads_omits_newspack_recommendations_and_keeps_the_editorial_heading(self):
        html = f"""<article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <h2 class="article-section-title">More picks from the greenhouse</h2><p>{LAST}</p>
        <div class="wp-block-newspack-blocks-homepage-articles wpnbha"><div>
        <h2 class="article-section-title">More picks from the archives</h2>
        <article class="type-post"><h3>Another story</h3></article></div></div></div></article>"""
        url = 'https://longreads.com/2026/11/18/seed-trials/'
        _, body = narrate(url, html)
        self.assertEqual(body.split(), f'{FIRST} More picks from the greenhouse {LAST}'.split())

    def test_robin_sloan_keeps_short_linked_paragraph_and_removes_home_button(self):
        html = f"""<main><article><h1>Seed trials</h1><date-stamp>November 11, 2026</date-stamp>
        <p>{FIRST}</p><p>Examples <a href="/one">here</a>, <a href="/two">here</a>.</p>
        <p>{LAST}</p><a class="button" href="/lab/">To the blog home page</a></article></main>"""
        _, body = narrate('https://www.robinsloan.com/lab/seed-trials/', html)
        self.assertEqual(body.split(), f'{FIRST} Examples here, here. {LAST}'.split())

    def test_popsci_keeps_featured_image_caption_and_omits_marked_awards_promo(self):
        html = f"""<article><h1>Seed trials</h1><div class="article-content-featured-image">
        <figure><img src="tray"><figcaption class="article-featured-image-caption">
        <span>A tray at rest.</span><span class="article-featured-image-caption-credits">Credit: Lee</span></figcaption></figure></div>
        <section class="entry-content"><p>{FIRST}</p><section class="content-widget pw-incontent-excluded">
        <a href="/gear/home-of-the-future-awards-2026/">See it</a></section>
        <p>The <a href="/gear/home-of-the-future-awards-2026/">awards page</a> mentions our trials.</p>
        <p>{LAST}</p></section></article>"""
        _, body = narrate('https://www.popsci.com/science/seed-trials/', html)
        self.assertEqual(body.split(),
                         f'A tray at rest. Credit: Lee {FIRST} The awards page mentions our trials. {LAST}'.split())

    def test_aeon_video_uses_the_description_instead_of_recommendations(self):
        html = f"""<main><h1>Seed trials</h1><div class="article-content"><p>{FIRST}</p><p>{LAST}</p></div>
        <div><p>Watch a different video about riding bicycles.</p></div></main>"""
        _, body = narrate('https://aeon.co/videos/seed-trials', html)
        self.assertEqual(body.split(), f'{FIRST} {LAST}'.split())

    def test_openculture_takes_author_from_its_footer_and_removes_template_endmatter(self):
        url = 'https://www.openculture.com/2026/11/seed-trials.html'
        appeal = ('<p><i>If you would like to sup&shy;port the mission of Open Culture, consider '
                  '<a href="/donate">making a donation to our site</a>. Thank you!</i></p>')
        related = ('<p><strong>Relat&shy;ed Content</strong></p>'
                   '<p><a rel="bookmark" href="/2026/10/another.html">Recommended article</a></p>')
        story = f'<p>{FIRST}</p>{appeal}<p>via Ash</p>{related}<p>{LAST}</p>'
        html = f"""<div class="recent_post"><h1>Seed trials</h1>
        <p class="byline"><a href="#respond">Leave a Comment</a></p>
        <div class="colorcontrast"><div class="entry">{story}</div></div>
        <div class="alignleft"><p class="author">by <a rel="author" href="/author/lee">Lee</a>
        <a title="Permalink" href="{url}">Permalink</a></p></div></div>"""
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('By Lee.'), intro)
        expected = f'{FIRST} via Ash {LAST}'.split()
        self.assertEqual(body.split(), expected)
        self.assertEqual(html_to_text(story, url=url).split(), expected)
        unmatched, _ = narrate(url, html.replace('title="Permalink"', 'title="Other post"'))
        self.assertNotIn('By ', unmatched)
        for editorial in ('<blockquote>' + appeal + '</blockquote>',
                          related.replace('rel="bookmark"', 'rel="citation"'),
                          related.replace('>Recommended article</a>', '>Recommended article</a> explains the result.')):
            with self.subTest(editorial=editorial):
                self.assertEqual(html_to_text(editorial, url=url), html_to_text(editorial))

    def test_digital_antiquarian_keeps_captions_in_the_article_body(self):
        html = f"""<div class="post hentry"><h2>Seed trials</h2><div class="entry">
        <p>{FIRST}</p><div class="wp-caption"><a href="/tray"><img src="tray"></a>
        <p class="wp-caption-text">A tray of seedlings photographed after rain.</p></div>
        <div><div class="wp-caption"><img src="wrapped-tray">
        <p class="wp-caption-text">A second tray on the windowsill.</p></div></div>
        <div class="wp-caption" hidden><img src="unpublished">
        <p class="wp-caption-text">Unpublished frame.</p></div><p>{LAST}</p>
        <h4>Footnotes</h4><ol><li>The study began in March.</li></ol></div>
        <p>Read another article.</p></div><aside><div class="wp-caption"><img src="ad">
        <p class="wp-caption-text">A sponsored image.</p></div></aside>"""
        _, body = narrate('https://www.filfre.net/2026/10/seed-trials/', html)
        self.assertEqual(body.split(),
                         f'{FIRST} A tray of seedlings photographed after rain. '
                         f'A second tray on the windowsill. {LAST} '
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

    def test_wordpress_editorial_photo_captions_stay_in_place(self):
        cases = [
            ('www.smithsonianmag.com', '<figure class="article-image"><img src="tray">'
             '<figcaption class="caption">The tray at sunrise. <span class="credit">Photo by Lee.</span>'
             '</figcaption></figure>', 'The tray at sunrise. Photo by Lee.'),
            ('www.astronomy.com', '<figure class="wp-block-image wp-lightbox-container"><img src="tray">'
             '<figcaption class="wp-element-caption">The robotic arm at rest.</figcaption></figure>',
             'The robotic arm at rest.'),
            ('blogs.loc.gov', '<figure class="wp-caption"><img src="tray">'
             '<figcaption class="wp-caption-text">Seeds in March.</figcaption></figure>', 'Seeds in March.'),
            ('www.futilitycloset.com', '<figure class="wp-caption"><img src="roots">'
             '<figcaption class="wp-caption-text">Image: <a href="/credits/one">Plant archive</a></figcaption></figure>'
             '<figure class="wp-caption"><img src="stems">'
             '<figcaption class="wp-caption-text">Image: <a href="/credits/two">Plant archive</a></figcaption></figure>',
             'Image: Plant archive Image: Plant archive'),
            ('blogs.egu.eu', '<figure class="wp-caption post-thumbnail"><img src="tray">'
             '<figcaption class="featured_caption">Early growth.</figcaption></figure>'
             '<div class="wp-caption"><a href="/photo"><img src="tray2"></a>'
             '<p class="wp-caption-text">Seeds in April.</p></div>', 'Early growth. Seeds in April.'),
        ]
        for host, photo, expected in cases:
            with self.subTest(host=host):
                html = (f'<article><h1>Seeds</h1><div class="entry-content"><p>{FIRST}</p>{photo}'
                        f'<div hidden>{photo}</div><aside>{photo}</aside><p>{LAST}</p></div></article>')
                if host == 'www.smithsonianmag.com':
                    html = html.replace('class="entry-content"', 'class="entry-content articleWrap"')
                _, body = narrate(f'https://{host}/seed-trials/', html)
                self.assertEqual(body.split(), f'{FIRST} {expected} {LAST}'.split())

    def test_experimental_history_preserves_linked_image_captions_in_source_order(self):
        html = f"""<article><h1>Seed trials</h1><div class="available-content"><div class="body markup">
        <p>{FIRST}</p><div class="captioned-image-container"><figure><a href="/photo"><img src="tray"></a>
        <figcaption class="image-caption">Early growth (<a href="/source">source</a>).</figcaption>
        </figure></div><p>{LAST}</p><div hidden class="captioned-image-container"><figure><img src="hidden">
        <figcaption class="image-caption">Hidden draft.</figcaption></figure></div></div></div></article>"""
        _, body = narrate('https://www.experimental-history.com/p/seed-trials', html)
        self.assertEqual(body.split(), f'{FIRST} Early growth (source). {LAST}'.split())

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
