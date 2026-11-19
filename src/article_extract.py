"""Find narration text in already-downloaded HTML; never fetch extra resources."""
import re
from html import unescape
from urllib.parse import unquote, urlsplit
from soupsieve import match
from article_scope import BODY_SELECTORS, DATE, FOOTNOTE_NAV, STRONG_TOWNS_HOSTS, article_labels, article_scope, editorial, explicitly_hidden, heading_matches, heading_text, masthead_body, opening_writer_credits, plover_story_title, readable_prose, remove_resolved_footnote_backlinks, url_identity
from imported_content import (
    COLOSSAL_HOSTS, HARVARD_HOSTS, OUTSIDE_HOSTS, WYOFILE_HOSTS,
    remove_openculture_endmatter, remove_outside_newsletter, wyofile_feature,
)
from tts import speech_text


EXCLUDED = (
    'script, style, noscript, template, nav, header, footer, aside, form, '
    'button, input, select, textarea, svg, video, audio, figcaption, '
    '[hidden], [aria-hidden="true"], [role="button"], [role="navigation"], '
    '[role="complementary"], [role="dialog"], .visually-hidden, .sr-only, '
    f'{FOOTNOTE_NAV}, '
    '.post-header, .post-footer, .post-meta, .post-metadata, .post-actions, .share-buttons, '
    '[data-block="byline"], [data-testid="multi-byline"], '
    '[itemprop="datePublished"], [itemprop="dateModified"], [data-testid="timestamp"], '
    '.subscription-widget, .entryFooter, .mobile-date-eyebrow, .edit-page-link, '
    '.posted, .publish-date-author, .basic-hero--blog-detail__description, '
    '.author-bio, .post-author, .post-categories, .related-posts, .related-articles, '
    '.comments, #comments, #Sidebar, #Footer, .linkedlist .smallprint, '
    '.gh-post-upgrade-cta, .gh-post-upgrade-cta-content, .post-access-cta, '
    '.j-icon, .sharedaddy, .translate-post, #jp-relatedposts, .harvard-sharing, '
    '.article-cta-box, .collection-cta, .collection-dateline, [class*="AscendiumAdUnit_wrapper__"], '
    '.wp-block-image, .wp-caption, .wp-block-video, .caption, .featured-img__caption, '
    'figure:has(img), figure:has(video), figure:has(audio)'
)


def remove_opening_metadata(root, author):
    """Remove consecutive opening labels, preserving dates and credits in prose."""
    for paragraph in list(root.find_all('p')):
        value = ' '.join(speech_text(paragraph.get_text(' ', strip=True)).split())
        if not value:
            continue
        if paragraph.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figure', 'figcaption']):
            break
        links = paragraph.find_all('a')
        outside = ' '.join(' '.join(str(node) for node in paragraph.find_all(string=True)
                                   if node.find_parent('a') is None).split())
        translation = (bool(links) and all(link.get('href') for link in links) and
                       re.fullmatch(r'Translations?\s*:[\s,;|/·•()\[\]]*',
                                    re.sub(r'\band\b', '', outside, flags=re.I), re.I))
        byline = author and re.fullmatch(r'by\s*:?\s*' + re.escape(author) + r'\.?', value, re.I)
        history = (len(links) == 1 and links[0].get('href', '').startswith('#') and
                   links[0].get_text(' ', strip=True).casefold() in ('changes', 'updates', 'changelog') and
                   DATE.fullmatch(outside.strip('()[] ')))
        # A standalone emphasized date is an opening publication label. Stop
        # at the first prose paragraph, leaving story dates and quotes intact.
        date = DATE.fullmatch(value) and paragraph.find('em') is not None
        if not (translation or byline or history or date):
            break
        paragraph.decompose()


def remove_site_endmatter(root):
    """Recognize a divided site footer, rather than matching prose about ads."""
    for paragraph in list(root.find_all('p')):
        if (not editorial(paragraph) or
                paragraph.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figure', 'figcaption'])):
            continue
        value = ' '.join(paragraph.get_text(' ', strip=True).split())
        separator = paragraph.find_previous_sibling()
        recommendations = paragraph.find(['ul', 'ol'])
        if recommendations is None:
            following = paragraph.find_next_sibling()
            if following is not None and following.name in ('ul', 'ol'):
                recommendations = following
        # This combination marks the start of site endmatter: a divider, a
        # self-description linked to the homepage, then recommended articles.
        # Remove only the remainder of that same container, never its ancestors.
        if (separator is None or separator.name != 'hr' or
                not re.match(r"^You['’]re reading\s+", value, re.I) or
                not re.search(r'If you liked this you might also enjoy:\s*', value, re.I) or
                paragraph.select_one('a[href="/"]') is None or
                recommendations is None or not recommendations.select('li a[href]')):
            continue
        preceding = ' '.join(node.get_text(' ', strip=True) for node in separator.find_previous_siblings()
                             if editorial(node))
        if not readable_prose(preceding):
            continue
        for node in [separator, *separator.next_siblings]:
            node.extract()


def remove_press_contacts(root):
    """Recognize contact-only tails after a press release's explicit end marker."""
    for marker in list(root.find_all('p')):
        if (marker.get_text(' ', strip=True).casefold() != '-end-' or
                marker.find_parent(['blockquote', 'pre', 'code', 'li', 'table'])):
            continue
        following = [node for node in marker.next_siblings if str(node).strip()]
        if not following or len(following) > 8:
            continue
        if not all(getattr(node, 'name', '') == 'p' and node.find('br') and
                   node.select_one('a[href^="mailto:"]') and
                   len(node.get_text(' ', strip=True)) < 600 and
                   not readable_prose(node.get_text(' ', strip=True)) for node in following):
            continue
        preceding = ' '.join(node.get_text(' ', strip=True) for node in marker.find_previous_siblings())
        if not readable_prose(preceding):
            continue
        for node in [marker, *following]:
            node.decompose()


def remove_article_footer(root, author):
    """Remove a marked footer and its adjacent author-bio/feedback labels."""
    for footer in root.select('#single-article-footer'):
        if footer.parent is None or footer.find_parent(['blockquote', 'pre', 'code']):
            continue
        feedback = footer.find_previous_sibling()
        if (feedback is not None and feedback.name == 'p' and feedback.find('a') and
                feedback.find(['b', 'strong']) and len(feedback.get_text(' ', strip=True)) < 350 and
                re.match(r'^FEEDBACK:\s*Use this form\b', feedback.get_text(' ', strip=True), re.I)):
            biography = feedback.find_previous_sibling()
            feedback.decompose()
            if (author and biography is not None and biography.name == 'p' and
                    biography.find(['i', 'em']) and biography.find('a') and
                    len(biography.get_text(' ', strip=True)) < 500 and
                    re.match(re.escape(author)+r' is (?:a|an) .{0,100}\b(?:writer|reporter|journalist|editor)\b',
                             biography.get_text(' ', strip=True)) and
                    re.search(r'\bFind (?:him|her|them)\s+on\b', biography.get_text(' ', strip=True), re.I)):
                biography.decompose()
        footer.decompose()


def remove_publication_notices(root):
    """Omit marked publishing widgets while retaining article references/prose."""
    for node in root.select('.cc-attribution'):
        if node.parent is None or node.find_parent(['blockquote', 'pre', 'code']):
            continue
        paragraphs = node.find_all('p')
        if (len(paragraphs) == 1 and len(node.get_text(' ', strip=True)) < 1500 and
                paragraphs[0].get_text(' ', strip=True).startswith('The text in this work is licensed under a Creative Commons') and
                node.select_one('a[href*="creativecommons.org/licenses/"]')):
            node.decompose()
    labels = {'article-citation': 'cite this work', 'article-past-versions': 'past versions',
              'article-licence': 'reuse this work freely'}
    for node in root.select('section#article-citation, section#article-past-versions, section#article-licence'):
        if (node.parent is None or node.find_parent(['blockquote', 'pre', 'code']) or
                not node.find_parent('article', class_='centered-article-container')):
            continue
        heading = node.find(['h2', 'h3'])
        if heading and heading.get_text(' ', strip=True).casefold() == labels[node['id']]:
            node.decompose()


def remove_repeated_cover_deck(root, title):
    """Avoid reading a title-cover teaser again at the start of the body."""
    for cover in root.select('.wp-block-cover__inner-container'):
        if not editorial(cover) or cover.find_parent(['blockquote', 'pre', 'code']):
            continue
        heading = cover.find('h1')
        paragraphs = cover.find_all('p')
        owner = next((node for node in cover.parents if match(BODY_SELECTORS, node)), None)
        if (owner is None or heading is None or len(paragraphs) != 1 or
                not heading_matches(heading_text(heading), title)):
            continue
        deck = paragraphs[0]
        following = deck.find_next('p')
        if (following is None or not editorial(following) or
                following.find_parent(['blockquote', 'pre', 'code']) or
                not any(node is owner for node in following.parents)):
            continue
        value = ' '.join(deck.get_text(' ', strip=True).split()).rstrip('.!?')
        body = ' '.join(following.get_text(' ', strip=True).split())
        if len(value) > 40 and re.match(re.escape(value) + r'[.!?](?:\s|$)', body):
            deck.decompose()


def remove_table_of_contents(root, url):
    """Remove marked section indexes, keeping their destination prose intact."""
    contents = list(root.select('.toc, #toc, .table-of-contents, #table-of-contents'))
    if not contents:
        return
    targets = {}
    for node in root.select('[id], a[name]'):
        for label in (node.get('id'), node.get('name') if node.name == 'a' else None):
            if label:
                targets.setdefault(label, []).append(node)
    requested = url_identity(url)
    for toc in contents:
        if toc.parent is None or toc.find_parent(['blockquote', 'pre', 'code']):
            continue

        def section_link(link):
            href = link.get('href', '').strip()
            try:
                fragment = unquote(urlsplit(href).fragment)
            except ValueError:
                return False
            if not fragment or not (href.startswith('#') or
                                    requested and url_identity(href, url) == requested):
                return False
            # A class on a wrapper containing the article itself is not an
            # instruction to discard that wrapper and all its destination text.
            return any(node.parent is not None and node is not toc and
                       not any(parent is toc for parent in node.parents)
                       for node in targets.get(fragment, []))

        links = toc.select('a[href]')
        if not links or not all(section_link(link) for link in links):
            continue
        heading = toc.find_previous_sibling()
        if heading is not None and heading.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            label = heading.get_text(' ', strip=True).rstrip(':').casefold().replace('\u2019', "'")
            if ('toch1' in heading.get('class', []) or
                    label in ('contents', 'table of contents', 'on this page', "today's links")):
                heading.decompose()
        toc.decompose()


def clean_tree(root, title, author, url=''):
    remove_resolved_footnote_backlinks(root, url)
    for block, _ in article_labels(root, title):
        block.decompose()
    # RebelMouse recommendation widgets can sit inside the article body.
    # Require their complete component structure; retain quotations and prose.
    for widget in root.select('.around-the-web'):
        children = [node for node in widget.children if str(node).strip()]
        headings = widget.select(':scope > .from-your-site__headline, :scope > .around-the-web__headline')
        if (not widget.find_parent(['blockquote', 'pre', 'code']) and
                headings and all(node.get_text(' ', strip=True).casefold() in
                                 {'from your site articles', 'related articles around the web'} for node in headings) and
                widget.select_one('ul.around-the-web__list li a[href]') and
                all(getattr(node, 'name', None) and match(
                    '.from-your-site__headline, .around-the-web__headline, .around-the-web__list', node)
                    for node in children)):
            widget.decompose()
    remove_site_endmatter(root)
    remove_press_contacts(root)
    remove_article_footer(root, author)
    remove_publication_notices(root)
    remove_repeated_cover_deck(root, title)
    for paragraph, writer in opening_writer_credits(root):
        if writer == author:
            paragraph.decompose()
    for node in root.select('[style], [hidden], [aria-hidden]'):
        if node.parent is not None and explicitly_hidden(node):
            node.decompose()
    identity = url_identity(url)
    if identity and identity[1] == 'creativecommons.org':
        body = 'body.blog-post main > .content'
        for opening in root.select(body + ' > aside.opening:first-child'):
            if opening.find('p', recursive=False):
                opening.name = 'div'
        for stamp in root.select(body + ' > span.pub-date'):
            label = stamp.get_text(' ', strip=True)
            if label.startswith('Posted ') and DATE.fullmatch(label.removeprefix('Posted ')):
                stamp.decompose()
    if identity and identity[1] == 'blog.openstreetmap.org':
        for menu in root.select('p.icl_post_in_other_langs.wpml-ls-statics-post_translations'):
            if (menu.select_one('[role="navigation"] a.wpml-ls-link[hreflang]')
                    and not menu.find_parent(['blockquote', 'pre', 'code'])):
                menu.decompose()
    if identity and identity[1] == 'blog.pypi.org':
        for anchor in root.select('.md-content--post :is(h1,h2,h3,h4,h5,h6) > a.headerlink'):
            heading_id = anchor.parent.get('id')
            if heading_id and anchor.get('href') == '#' + heading_id and anchor.get_text(strip=True) == '¶':
                anchor.decompose()
    if identity and identity[1] == 'freebsdfoundation.org' and identity[2].startswith('/blog/'):
        for rel, label in (('prev', 'Previous'), ('next', 'Next')):
            for link in root.select(f'.post-content > span.nav-{label.lower()} > a[rel~="{rel}"][href]'):
                if link.get_text(' ', strip=True) == label:
                    link.decompose()
    if identity and identity[1] in {'openculture.com', 'www.openculture.com'}:
        for body in root.select('.recent_post > .colorcontrast > .entry'):
            if editorial(body):
                remove_openculture_endmatter(body, url)
    if identity and identity[1] == 'inkscape.org' and identity[2].startswith('/news/'):
        for stamp in root.select('#content .wrapper > h1 + p.postdate'):
            label = ' '.join(stamp.stripped_strings)
            date = re.sub(r',\s+\d{1,2}:\d{2}(?:\s+[ap]\.m\.)?$', '', label, flags=re.I)
            if DATE.fullmatch(date):
                stamp.decompose()
    if identity and identity[1] == 'earthsky.org':
        for widget in root.select('.post-rich-text > .ns-buttons.ns-inline-below'):
            if widget.select_one('.ns-buttons-wrapper a[aria-label^="Share on "]'):
                widget.decompose()
    if identity and identity[1] in {'robinsloan.com', 'www.robinsloan.com'}:
        for stamp in root.select('main > article > h1 + date-stamp'):
            if DATE.fullmatch(' '.join(stamp.stripped_strings)):
                stamp.decompose()
        for link in root.select('main > article > a.button[href="/lab/"]'):
            if link.get_text(' ', strip=True) == 'To the blog home page':
                link.decompose()
    if identity and identity[1] in {'popsci.com', 'www.popsci.com'}:
        for body in root.select('article > .article-content-featured-image + .entry-content'):
            featured = body.find_previous_sibling()
            caption = featured.select_one('figure:has(img) > figcaption.article-featured-image-caption')
            if caption and editorial(caption) and editorial(body):
                caption.name = 'div' if caption.find('p') else 'p'
                credit = caption.select_one(':scope > .article-featured-image-caption-credits')
                if credit:
                    credit.insert_before(' ')
                body.insert(0, caption.extract())
        for widget in root.select('.entry-content section.content-widget.pw-incontent-excluded'):
            if widget.select_one('a[href*="/home-of-the-future-awards-"]'):
                widget.decompose()
    if identity and identity[1] in {'sapiens.org', 'www.sapiens.org'}:
        # SAPIENS puts its editorial caption and photo credit in a figure footer.
        for footer in root.select('.c-article-content :is(.m-article-img-header, .m-image-video) '
                                  '> figure.c-image-video > footer.c-image-video__footer:has(> .c-media-caption)'):
            figure = footer.parent
            if editorial(figure) and figure.find('img'):
                footer.name = 'p'
                footer.attrs = {}
                labels = footer.select(':scope > .c-media-caption, :scope > .c-media-credits')
                footer.string = ' '.join(label.get_text().strip() for label in labels)
                figure.parent.insert_before(footer.extract())
    if identity and identity[1] in {'niemanlab.org', 'www.niemanlab.org'}:
        for card in root.select('.roscoe-body > p > div.embed-relatedstory'):
            if card.select_one(':scope > a.embed-relatedstory-imagelink[href]') and not card.find_parent(
                    ['blockquote', 'pre', 'code']):
                card.decompose()
    if identity and identity[1] in {'lithub.com', 'www.lithub.com'}:
        for bio in root.select('.story-content > .bio-container:has(> .bio)'):
            if not bio.find_parent(['blockquote', 'pre', 'code']):
                bio.decompose()
    if identity and identity[1] == 'buttondown.com' and '/archive/' in identity[2]:
        for deck in root.select('article.email-body > h1.subject + h2.description'):
            body = deck.find_next_sibling()
            if (body and match('.email-body-content', body) and editorial(body) and editorial(deck)
                    and heading_matches(heading_text(deck.find_previous_sibling()), title)):
                body.insert(0, deck.extract())
    if identity and identity[1] in WYOFILE_HOSTS:
        feature = wyofile_feature(root, title)
        if feature:
            bodies = feature.parent.select(':scope > .main-content > article > .entry-content')
            caption = feature.select_one(':scope > figure.post-thumbnail:has(img) > figcaption')
            if len(bodies) == 1 and caption and editorial(caption) and editorial(bodies[0]):
                caption.name = 'p'
                bodies[0].insert(0, caption.extract())
        for player in root.select('article > .entry-content > .article-summary:has(> .instaread-player-slot)'):
            for label in player.select(':scope > p.instaread-disclaimer'):
                label.decompose()
    if identity and identity[1] in {'mentalfloss.com', 'www.mentalfloss.com'}:
        for article in root.select('article#main-article'):
            bodies = article.select('.odesa-article-main .article-content')
            if len(bodies) != 1 or not editorial(bodies[0]):
                continue
            body = bodies[0]
            for caption in body.select(':scope > figure > div > figcaption'):
                figure = caption.parent.parent
                if editorial(caption) and figure.find('img'):
                    caption.name = 'p'
                    figure.insert_before(caption.extract())
            lead = article.select_one('figure:has(> [data-lead-image]) > div > figcaption')
            if lead and editorial(lead) and lead.parent.parent.find('img'):
                lead.name = 'p'
                body.insert(0, lead.extract())
    if identity and identity[1] in {'hakaimagazine.com', 'www.hakaimagazine.com'}:
        for heading in root.select('article > section.maincontent > h3.invis'):
            if heading.get_text(strip=True) == 'Article body copy':
                heading.decompose()
    if identity and identity[1] in OUTSIDE_HOSTS:
        for body in root.select('.article-template .js-body-content > .content-wrap.fp-contentTarget'):
            if not editorial(body):
                continue
            remove_outside_newsletter(body, url)
            for ad in body.select(':scope > .ad-placeholder-wrapper'):
                if ad.get_text(' ', strip=True).casefold() == 'advertisement':
                    ad.decompose()
            for stamp in body.select(':scope > .article-body > .pub-date'):
                if stamp.get_text(strip=True).startswith('Published '):
                    stamp.decompose()
            credit = body.parent.select_one(
                ':scope > .article-header > div:has(> img) > p.fp-leadCaption')
            if credit and editorial(credit):
                body.insert(0, credit.extract())
    if identity and identity[1] in {'smashingmagazine.com', 'www.smashingmagazine.com'}:
        for caption in root.select('.c-garfield-the-cat > figure > figcaption'):
            if not editorial(caption):
                continue
            # A positioning class makes density pruning treat the detached
            # caption as overlay text even after its figure is gone.
            if 'op-vertical-bottom' in caption.get('class', []):
                caption['class'].remove('op-vertical-bottom')
            image_link = caption.parent.select_one(':scope > a[href]:has(> img)')
            if not image_link:
                continue
            image = url_identity(image_link['href'], url)
            for link in caption.select(':scope > a[href]'):
                before, after = link.previous_sibling, link.next_sibling
                if (image and url_identity(link['href'], url) == image and link.get_text(strip=True) == 'Large preview'
                        and isinstance(before, str) and before.rstrip().endswith('(')
                        and isinstance(after, str) and after.strip() == ')' and after.next_sibling is None):
                    before.replace_with(before.rstrip()[:-1].rstrip())
                    after.extract()
                    link.decompose()
    if identity and identity[1] == 'zed.dev' and identity[2].startswith('/blog/'):
        for caption in root.select('main article > a[href] > button.cursor-zoom-in > figure:has(> img) > figcaption'):
            if editorial(caption):
                zoom_link = caption.parent.parent.parent
                caption.name = 'p'
                zoom_link.insert_before(caption.extract())
        for widget in root.select('main article > div.flex.flex-col.gap-5:last-of-type > div:has(> h3)'):
            heading = widget.find('h3', recursive=False)
            prompt = heading.find_next_sibling()
            if (heading.get_text(strip=True) == 'Related Posts' and prompt and prompt.name == 'p'
                    and prompt.get_text(strip=True) == 'Check out similar blogs from the Zed team.'
                    and widget.select_one('a[href^="/blog/"]')):
                widget.decompose()
    caption_selectors = {
        **dict.fromkeys({'smashingmagazine.com', 'www.smashingmagazine.com'},
                        '.c-garfield-the-cat > figure:has(img) > figcaption'),
        **dict.fromkeys(WYOFILE_HOSTS, 'article > .entry-content > figure.wp-block-image > figcaption.wp-element-caption, '
                        'article > .entry-content > .wp-block-image > figure > figcaption.wp-element-caption'),
        **dict.fromkeys(COLOSSAL_HOSTS, 'article .entry-content > .entry-header '
                        '> figure.colo-post-featured-image > figcaption.wp-element-caption'),
        **dict.fromkeys(HARVARD_HOSTS,
                        '.block-field-blocknodearticlebody > .field--name-body figure.caption.caption-img > figcaption'),
        'theguardian.com': '.article-body-viewer-selector figure > figcaption[data-spacefinder-role="inline"]',
        'www.theguardian.com': '.article-body-viewer-selector figure > figcaption[data-spacefinder-role="inline"]',
        'hakaimagazine.com': '.maincontent > div.wp-caption > p.wp-caption-text',
        'www.hakaimagazine.com': '.maincontent > div.wp-caption > p.wp-caption-text',
        'www.filfre.net': '.post.hentry > .entry > div.wp-caption > p.wp-caption-text',
        'filfre.net': '.post.hentry > .entry > div.wp-caption > p.wp-caption-text',
        'astronomy.com': '.entry-content > figure.wp-block-image > figcaption.wp-element-caption',
        'www.astronomy.com': '.entry-content > figure.wp-block-image > figcaption.wp-element-caption',
        'www.experimental-history.com': '.available-content .body.markup .captioned-image-container > figure > figcaption.image-caption',
        'experimental-history.com': '.available-content .body.markup .captioned-image-container > figure > figcaption.image-caption',
        'earthsky.org': '.post-rich-text > figure.wp-block-image > figcaption.wp-element-caption',
        'www.futilitycloset.com': '.entry-content > figure.wp-caption > figcaption.wp-caption-text',
        'futilitycloset.com': '.entry-content > figure.wp-caption > figcaption.wp-caption-text',
        'blogs.loc.gov': '.entry-content > figure.wp-caption > figcaption.wp-caption-text',
        'blogs.egu.eu': ('.entry-content > figure.post-thumbnail.wp-caption > figcaption.featured_caption, '
                         '.entry-content > div.wp-caption > p.wp-caption-text'),
        'webkit.org': 'article .bodycopy > figure > figcaption',
        'smithsonianmag.com': '.articleWrap > figure.article-image > figcaption.caption',
        'www.smithsonianmag.com': '.articleWrap > figure.article-image > figcaption.caption',
        'www.nist.gov': '.text-with-summary figure.nist-image > figcaption.nist-image__caption',
        'blog.cloudflare.com': '.article-content figure.emdash-image > figcaption',
        'www.raspberrypi.com': '.c-post-content__wysiwyg .wp-block-image > figure > figcaption.wp-element-caption',
    }
    if identity and identity[1] in caption_selectors:
        for caption in root.select(caption_selectors[identity[1]]):
            if editorial(caption) and caption.parent.find('img'):
                figure = caption.parent
                caption.name = 'div' if caption.find('p') else 'p'
                if 'caption' in caption.get('class', []):
                    caption['class'].remove('caption')
                container = figure.parent if 'wp-block-image' in figure.parent.get('class', []) else figure
                container.insert_before(caption.extract())
    if identity and identity[1] in {'theguardian.com', 'www.theguardian.com'}:
        for card in root.select('.article-body-viewer-selector figure[data-spacefinder-role="richLink"]'):
            if card.select_one('[data-component="rich-link"] a[href]') and not card.find_parent('blockquote'):
                card.decompose()
    for node in root.select('p.date, p.mobile-date'):
        if (DATE.fullmatch(node.get_text(' ', strip=True)) and
                not node.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figure'])):
            node.decompose()
    # Relative-age badges decorate a year; they are not mathematical subscripts.
    for badge in root.select('sub.styled-sub'):
        label = re.fullmatch(r'(\d{4}) was \d+ years? ago', badge.parent.get('title', ''))
        if (label and re.fullmatch(r'\d+ya', badge.get_text(strip=True)) and
                badge.parent.get_text('', strip=True) == label[1] + badge.get_text(strip=True)):
            badge.decompose()
    for paragraph in list(root.find_all('p')):
        if paragraph.find_parent(['blockquote', 'pre', 'code']):
            continue
        value = paragraph.get_text(' ', strip=True)
        # Short, standalone promotional/caption paragraphs inside the prose.
        # Do not match ordinary sentences mentioning reading or newsletters.
        related = (re.match(r'^Read more:', value, re.I) and paragraph.find('a') and
                   paragraph.find('strong') and len(value) < 250)
        newsletter = (re.match(r'^Enjoying .{1,100}\?\s*Subscribe to our free newsletter', value, re.I)
                      and paragraph.find('a') and len(value) < 250)
        credit = (re.match(r'^(?:Lead|Banner) Image:', value, re.I) and
                  paragraph.find(['em', 'i']) and len(value) < 300 and
                  not any(str(text).strip() for text in paragraph.find_all(string=True)
                          if text.find_parent(['em', 'i']) is None))
        if related or newsletter or credit:
            paragraph.decompose()
    for heading in list(root.find_all(['h2', 'h3'])):
        if heading.parent is None or heading.find_parent(['blockquote', 'pre', 'code']):
            continue
        if heading.get_text(' ', strip=True).casefold() == 'written by':
            parent = heading.parent
            # Anonymous short author cards may contain a name and job title.
            # A readable body or semantic article container must survive cleanup.
            value = parent.get_text(' ', strip=True)
            if (parent is not root and parent.name in ('div', 'section') and
                    not match(BODY_SELECTORS, parent) and not parent.find(['h1', 'article', 'main']) and
                    len(value) < 600 and not readable_prose(value)):
                parent.decompose()
            else:
                heading.decompose()
    # Remove an audio player's label and duration together. Removing only its
    # button leaves labels such as "Listen to this essay / 27 minute listen".
    for label in list(root.find_all(string=re.compile(r'^Listen to this\s*$', re.I))):
        parent = label.parent
        for _ in range(3):
            if parent is None or parent is root:
                break
            value = parent.get_text(' ', strip=True)
            if parent.find('button') and len(value) < 150:
                parent.decompose()
                break
            parent = parent.parent
    # Remove a standalone byline's outer label with its author span. Keep
    # paragraphs that use the same link as part of a sentence or quotation.
    for byline in root.select('.byline, [rel~="author"], [itemprop~="author"]'):
        parent = byline.parent
        if parent is None or parent.name != 'p' or parent.find_parent(['blockquote', 'pre', 'code']):
            continue
        outside = ' '.join(str(text) for text in parent.strings
                           if not any(ancestor is byline for ancestor in text.parents))
        if re.fullmatch(r'\s*By\s*:?\s*', outside, re.I):
            parent.decompose()
    for credit in root.select('.byline, .c-article-author, .c-article__author'):
        if credit.parent is not None and not credit.find_parent(['blockquote', 'pre', 'code']):
            credit.decompose()
    for node in root.select(EXCLUDED):
        if node.parent is not None:
            node.decompose()
    remove_table_of_contents(root, url)
    # Attribute the article once, outside its narration body.
    for node in root.select('h1, h2, h3, dt, [rel~="author"], [itemprop~="author"]'):
        if node.find_parent(['blockquote', 'pre', 'code']):
            continue
        value = heading_text(node) if node.name in ('h1', 'h2', 'h3') else ' '.join(node.get_text(' ', strip=True).split())
        if ((title and heading_matches(value[:160].strip(), title)) or
                (author and re.sub(r'^by\s+', '', value, flags=re.I)[:100].strip() == author)):
            node.decompose()
    for tags in list(root.select('.post-tags')):
        if tags.parent is None:
            continue
        heading = tags.find_previous_sibling()
        if (heading and heading.name in ('h2', 'h3') and
                heading.get_text(' ', strip=True).rstrip(':').casefold() == 'tags'):
            heading.decompose()
        tags.decompose()
    for node in root.select('time'):
        if not node.find_parent(['p', 'li', 'blockquote', 'pre', 'code']):
            node.decompose()
    # Older pages often put a standalone date before a <br>. Preserve dates
    # embedded in prose and quotations, including stories that open on a date.
    for node in list(root.find_all(string=True)):
        before_break = (node.previous_sibling is None and
                        getattr(node.next_sibling, 'name', '') == 'br')
        prose = node.find_parent(['p', 'li', 'blockquote', 'pre', 'code'])
        quoted = node.find_parent(['blockquote', 'pre', 'code'])
        if DATE.fullmatch(str(node).strip()) and not quoted and (not prose or before_break):
            node.extract()
    remove_opening_metadata(root, author)


def plain_text(root):
    # Add separators around blocks, without inserting spaces inside inline words
    # (for example, a drop cap's <span>A</span>s or an emphasized word ending).
    for node in root.find_all(['p', 'div', 'section', 'blockquote', 'li', 'h1', 'h2',
                               'h3', 'h4', 'h5', 'h6', 'pre', 'table', 'thead', 'tbody',
                               'tfoot', 'tr', 'th', 'td', 'caption', 'dl', 'dt', 'dd', 'br']):
        node.insert_before('\n')
        node.insert_after('\n')
    return ' '.join(root.get_text('', strip=False).split())


def extract_structured_text(body, title='', author='', url=''):
    """Normalize an already-selected JSON-LD body; never execute or fetch it."""
    from bs4 import BeautifulSoup
    # Preserve plain-text comparisons and code such as C++'s <vector>.
    if not re.search(r'</?(?:p|div|section|article|h[1-6]|br|ul|ol|li|blockquote|pre|table|thead|tbody|tfoot|tr|th|td|caption|dl|dt|dd|a|em|strong|span|script|style)\b[^>]*>', body, re.I):
        return ' '.join(unescape(body).split())
    fragment = BeautifulSoup(body, 'html.parser')
    clean_tree(fragment, title, author, url)
    return plain_text(fragment)


def preserve_reference_lists(scope, url):
    """Keep editorial reference labels from being pruned solely for link density."""
    if scope.name == '[document]':
        return
    for heading in scope.find_all(['h2', 'h3', 'h4', 'h5', 'h6']):
        if (not editorial(heading) or heading.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figcaption']) or
                ' '.join(heading.get_text('', strip=False).split()).casefold().rstrip(':') not in
                {'references', 'some references'}):
            continue
        following = heading.find_next_sibling()
        if following is not None and following.name == 'p' and len(following.get_text()) <= 300:
            following = following.find_next_sibling()
        if following is None or following.name not in ('ul', 'ol') or not editorial(following):
            continue
        items = following.find_all('li', recursive=False)
        links = following.find_all('a', href=True)
        if (not items or not links or following.find(['img', 'picture', 'figure', 'button', 'article', 'div', 'section', 'ul', 'ol']) or
                any(not item.find('a', href=True) for item in items) or
                any(not url_identity(link['href'], url) or url_identity(link['href'], url) == url_identity(url)
                    for link in links)):
            continue
        # Labels and inline formatting stay in place; only the link markup is
        # normalized. No references are fetched and no prose is reconstructed.
        for link in links:
            link.unwrap()


def extract_text(soup, title='', author='', url=''):
    scope = article_scope(soup, title, url)
    plover_title = plover_story_title(soup, url)
    plover_body = None
    if plover_title:
        plover_body = plover_title.parent.parent
        permalink = url_identity(plover_title['href'], url)
        plover_title.decompose()
        for date in plover_body.select(':scope > span.dateheader'):
            date.decompose()
        footer = plover_body.find_all('p', recursive=False)[-1]
        for link in footer.select(':scope > i > a[href]'):
            if (link.get_text(strip=True) == 'permanent link' and url_identity(link['href'], url) == permalink
                    and footer.get_text(' ', strip=True).startswith('[ Other articles in category ')):
                footer.decompose()
                break
    # Capture the layout evidence before cleanup removes its masthead. This
    # body uses the same structure-preserving path as explicit article bodies.
    recovered_body = masthead_body(soup, title)
    # LessWrong streams its explicit post body inside an initially hidden React
    # container. Detach only that body before discarding hidden page sections.
    candidates = []
    for node in soup.select('.PostsPage-postContent'):
        if not editorial(node, allow_hidden=True):
            continue
        owner = node if node.name == 'article' else node.find_parent('article')
        if owner is not None and owner is not scope:
            if scope.name == 'article':
                continue
            headings = owner.select('h1, h2, .entry-title')
            if title and headings and not any(heading_matches(heading_text(h), title) for h in headings):
                continue
        candidates.append(node)
    identities = {id(node) for node in candidates}
    sections = [node for node in candidates if not any(id(parent) in identities for parent in node.parents)]
    deferred = []
    for node in sections:
        node.extract()
        clean_tree(node, title, author, url)
        if speech_text(node.get_text('', strip=True)).strip():
            text = plain_text(node)
            # Streaming can repeat the same body for another layout. Keep
            # distinct sections and intentional repetition later in the story.
            if not deferred or text != deferred[-1]:
                deferred.append(text)
    identity = url_identity(url)
    if identity and identity[1] in {'longreads.com', 'www.longreads.com'} | WYOFILE_HOSTS:
        # Strip the Newspack list while its cards still identify the heading.
        for listing in scope.select('.entry-content .wp-block-newspack-blocks-homepage-articles.wpnbha '
                                    '> div:has(> h2.article-section-title):has(> article.type-post)'):
            if identity[1] in WYOFILE_HOSTS:
                heading = listing.select_one(':scope > h2.article-section-title')
                if heading.get_text(' ', strip=True).casefold() != 'related':
                    continue
            if (not listing.find_parent(['blockquote', 'pre', 'code'])
                    and all(match('h2.article-section-title, article.type-post', child)
                            for child in listing.find_all(recursive=False))):
                listing.decompose()
    # Select before cleanup removes the headline used to identify the article.
    for node in list(soup.select('article, .recommendations, .related-posts, .related-articles')):
        if node.parent is not None and (not editorial(node) or
                (node is not scope and not any(parent is node for parent in scope.parents)
                 and node.name == 'article' and scope is not soup)):
            node.decompose()
    clean_tree(soup, title, author, url)
    if deferred:
        return ' '.join(deferred)
    candidates = scope.select(BODY_SELECTORS)
    if plover_body:
        candidates = [plover_body]
    elif match(BODY_SELECTORS, scope) or scope is recovered_body:
        candidates = [scope]
    body_selector = None
    if identity:
        if identity[1] in {'theguardian.com', 'www.theguardian.com'}:
            body_selector = '[data-gu-name="body"] .article-body-viewer-selector'
        elif identity[1] in {'hakaimagazine.com', 'www.hakaimagazine.com'} and scope.name == 'article':
            body_selector = ':scope > section.maincontent'
        elif identity[1] in HARVARD_HOSTS and match('article.node--type-article', scope):
            body_selector = '.block-field-blocknodearticlebody > .field--name-body.field--type-text-with-summary'
        elif identity[1] in OUTSIDE_HOSTS:
            body_selector = '.article-template .js-body-content > .content-wrap.fp-contentTarget'
        elif identity[1] in STRONG_TOWNS_HOSTS and identity[2].startswith('/journal/'):
            body_selector = '.thought-leadership_wrap .mast-article-rich-text.w-richtext'
        elif (identity[1] == 'buttondown.com' and '/archive/' in identity[2]
              and match('article.email-body', scope)):
            body_selector = ':scope > .email-body-content'
        elif identity[1] == 'www.internetsociety.org' and identity[2].startswith('/blog/') and scope.name == 'article':
            body_selector = ':scope > .body-text'
        elif identity[1] == 'webkit.org' and identity[2].startswith('/blog/') and scope.name == 'article':
            body_selector = ':scope > .bodycopy'
        elif identity[1] in {'filfre.net', 'www.filfre.net'}:
            body_selector = 'div.post.hentry > div.entry'
        elif identity[1] == 'blogs.kde.org' and match('article.post-content', scope):
            body_selector = ':scope > .jumbotron ~ .content-width'
        elif identity[1] in {'openculture.com', 'www.openculture.com'}:
            body_selector = '.recent_post > .colorcontrast > .entry'
        elif (identity[1] in {'robinsloan.com', 'www.robinsloan.com'} and identity[2].startswith('/lab/')
              and match('main > article', scope)):
            candidates = [scope]
        elif identity[1] in {'aeon.co', 'www.aeon.co'} and identity[2].startswith('/videos/'):
            body_selector = '.article-content'
        elif identity[1] == 'earthsky.org':
            body_selector = '.post-body > .post > .post-rich-text'
        elif (identity[1] == 'blog.r-project.org' and identity[2].startswith('/posts/')
              and match('main#quarto-document-content.quarto-banner-title-block:has(> section.level2)', scope)):
            candidates = [scope]
        elif identity[1] == 'www.nist.gov' and identity[2].startswith('/news-events/news/'):
            body_selector = '.nist-page__region--content .text-with-summary'
        elif identity[1] == 'www.djangoproject.com' and identity[2].startswith('/weblog/'):
            body_selector = '.blog-entry-body'
        elif identity[1] == 'www.raspberrypi.com' and identity[2].startswith('/news/'):
            body_selector = '.c-post-content__wysiwyg'
    if body_selector:
        bodies = scope.select(body_selector)
        if len(bodies) == 1 and editorial(bodies[0]) and readable_prose(plain_text(bodies[0])):
            candidates = bodies
    if candidates:
        # Some publications split the article among sibling body containers.
        # Read each outermost section once, inside the same semantic article.
        identities = {id(node) for node in candidates}
        sections = [node for node in candidates if not any(id(parent) in identities for parent in node.parents)]
        pieces = []
        for section in sections:
            clean_tree(section, title, author, url)
            # Empty placeholders must not suppress the density-based fallback.
            if speech_text(section.get_text('', strip=True)).strip():
                pieces.append(plain_text(section))
            elif section is not scope:
                section.decompose()
        selected = ' '.join(filter(None, pieces))
        if selected:
            return selected

    # Density-based extraction handles unmarked layouts and separates article
    # prose from metadata, related stories, controls and comments.
    # Links and attribution classes inside an editorial quotation describe its
    # source, not navigation. Normalize the cleaned quotation to narration text
    # before density pruning, retaining its position and the surrounding layout.
    preserve_reference_lists(scope, url)
    quotes = [node for node in scope.select('blockquote') if not node.find_parent('blockquote')]
    for quote in quotes:
        quote.string = plain_text(quote)
    # Empty inline diagram markers can make the density extractor discard
    # their following text. Unwrap them first, including nested empty spans.
    for span in reversed(scope.select('span')):
        if not span.contents:
            span.unwrap()
    # With images disabled, the extractor drops entire figures. Code figures
    # are text: keep their pre blocks in place without enabling image content.
    for figure in scope.select('figure:has(pre)'):
        figure.unwrap()
    from trafilatura import bare_extraction
    body = scope if scope is not soup else None
    source = str(body if body is not None else soup)
    if body is not None or soup.find('html') is None:
        source = '<html><body>' + source + '</body></html>'
    for precision in (True, False):
        document = bare_extraction(source, include_comments=False, include_tables=True,
                                   include_images=False, favor_precision=precision)
        # Read the extracted tree directly so layout tables don't turn into
        # spoken Markdown pipes and separators.
        if document is not None and document.body is not None:
            text = ' '.join(' '.join(document.body.itertext()).split())
            if readable_prose(text):
                return text
    # Preserve short semantic articles when the density heuristic declines them.
    if body is not None and body.find(['p', 'blockquote']) is not None:
        return plain_text(body)
    return ''
