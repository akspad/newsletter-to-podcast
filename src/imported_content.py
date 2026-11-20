"""Recognize publisher credits and feed widgets using only supplied content."""
import re
from urllib.parse import urlsplit

from tts import speech_text

from article_scope import DATE, belongs_to_scope, editorial, explicitly_hidden, heading_matches, heading_text, readable_prose, remove_table_of_contents, url_identity


HARVARD_HOSTS = {'harvardmagazine.com', 'www.harvardmagazine.com'}
OUTSIDE_HOSTS = {'outsideonline.com', 'www.outsideonline.com'}
COLOSSAL_HOSTS = {'thisiscolossal.com', 'www.thisiscolossal.com'}
WYOFILE_HOSTS = {'wyofile.com', 'www.wyofile.com'}
GUARDIAN_HOSTS = {'theguardian.com', 'www.theguardian.com'}
OPEN_CULTURE_HOSTS = {'openculture.com', 'www.openculture.com'}
QUILLETTE_HOSTS = {'quillette.com', 'www.quillette.com'}


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


def remove_eff_embed_notice(root, url):
    for notice in root.select('.mytube > .mytubetext'):
        if notice.find_parent(['blockquote', 'pre', 'code']) or not notice.parent.select_one(':scope > .mytubetrigger'):
            continue
        links = notice.select('a[href]')
        if (len(links) == 2 and links[0].get_text(strip=True) == 'Privacy info.'
                and url_identity(links[0]['href'], url) == url_identity('/deeplinks/2008/02/embedded-video-and-your-privacy', url)
                and notice.get_text(' ', strip=True) == 'Privacy info. This embed will serve content from ' + links[1].get_text(strip=True)):
            notice.decompose()


def clean_nasa_carousel_captions(carousel):
    captions = {}
    for caption in carousel.select('.hds-image-carousel-slide .hds-media-wrapper:has(img) > figcaption.hds-caption'):
        if editorial(caption):
            text = ' '.join(caption.get_text(' ', strip=True).split())
            if text and text in captions:
                caption.decompose()
            elif text:
                captions[text] = caption
    return list(captions.values())


def guardian_author_label(name):
    return name.removesuffix(' Health policy editor') if isinstance(name, str) else name


def remove_bgs_related_news(root):
    for carousel in root.find_all('section', class_='cards-carousel-section', recursive=False):
        heading = carousel.select_one(':scope > .container > .header-of-section > .col-12 > h2')
        if heading and heading_text(heading) == 'Related news' and carousel.select_one('.cards-find-more h4 a[href]'):
            carousel.decompose()


def remove_bgs_topic_links(root, url):
    identity = url_identity(url)
    for topics in root.select('section.wp-block-bgs-blocks-content-container .relatives'):
        label = topics.find('h5', recursive=False)
        links = topics.select(':scope > div > a.button[href]')
        if (label and heading_text(label) == 'Relative topics' and links
                and topics.get_text(' ', strip=True) == ' '.join(
                    node.get_text(' ', strip=True) for node in (label, *links))
                and all((target := url_identity(link['href'], url)) and target[:2] == identity[:2]
                        and target[2].startswith('/tag/') for link in links)):
            topics.decompose()


def universal_hub_writer(root, url):
    identity = url_identity(url)
    if not identity or identity[1] not in {'universalhub.com', 'www.universalhub.com'}:
        return None, ''
    if isinstance(root, str):
        from bs4 import BeautifulSoup
        root = BeautifulSoup(root, 'html.parser')
    for body in root.select('.field-name-body > .field-items > .field-item'):
        opening = body.find('p', recursive=False)
        if not opening or not editorial(opening) or not opening.select_one(':scope > em:only-child'):
            continue
        name = re.fullmatch(r'By ([^,]{2,100}), .+', ' '.join(opening.get_text().split()))
        if not name:
            continue
        for link in body.select('p > em > a[href]'):
            profile = url_identity(link['href'], url)
            if (profile and profile[1] == 'theconversation.com' and profile[2].startswith('/profiles/')
                    and link.get_text(strip=True) == name[1] and editorial(link)
                    and link.parent.get_text(' ', strip=True).startswith('This article is republished from The Conversation')):
                return opening, name[1]
    return None, ''


def mit_news_author_label(name):
    if not isinstance(name, str):
        return name
    return re.sub(r'\s*\|\s*MIT News$', '', name).rstrip() or name


def freebsd_report_writer(root, url, title):
    """Use a travel report's named guest only when the same person signed it."""
    identity = url_identity(url)
    if not identity or identity[1] != 'freebsdfoundation.org' or not identity[2].startswith('/blog/'):
        return ''
    report = re.fullmatch(r'BSDCan \d{4} Travel Report\s+[–—-]\s+([^\d:;.!?\n]{3,100})', title)
    if not report:
        return ''
    if isinstance(root, str):
        from bs4 import BeautifulSoup
        root = BeautifulSoup(root, 'html.parser')
        sections = root.find_all('section', class_='block-tadv-classic-paragraph', recursive=False)
        if len(sections) == 1:
            root = sections[0]
    else:
        root = root.select_one(':scope > .post-content')
        if root is None:
            return ''
    last = next((p for p in reversed(root.find_all('p')) if editorial(p) and p.get_text(strip=True)), None)
    if not last or last.find_parent(['blockquote', 'pre', 'code']) or not last.find('br', recursive=False):
        return ''
    name = report[1].strip()
    lines = last.get_text('\n', strip=True).splitlines()
    if (len(lines) >= 2 and lines[-2] == 'Be well,' and
            re.fullmatch(re.escape(name) + r'(?: bsdtv / bsdcan \d{4} con chair)?', lines[-1])):
        return name
    return ''


def wyofile_feature(root, title):
    """Find the featured header for this story, outside the article element."""
    features = [
        heading.parent.parent for heading in root.select(
            'main.site-main > .featured-image-above > header.entry-header > h1.entry-title')
        if editorial(heading) and heading_matches(heading_text(heading), title)
    ]
    return features[0] if len(features) == 1 else None


def wyofile_feed_authors(names):
    """Prefer the signed group credit over repeated individual creator tags."""
    if len(names) > 1 and all(isinstance(name, str) for name in names) and names[0].lower().startswith('by '):
        group = names[0][3:].strip()
        members = re.split(r',\s+(?:and\s+)?|\s+and\s+', group)
        if (len(members) == len(names) and all(members)
                and all(label == member or label.startswith(member + ', ')
                        for member, label in zip(members[1:], names[1:]))):
            return [group]
    return names


def harvard_feed_body(root, url, title):
    """Identify the Drupal node exported as an RSS description."""
    identity = url_identity(url)
    if not identity or identity[1] not in HARVARD_HOSTS or not title:
        return None
    heading = root.find('span', class_='field--name-title', recursive=False)
    bodies = [body for body in root.find_all('div', class_='field--name-body', recursive=False)
              if 'field--type-text-with-summary' in body.get('class', []) and editorial(body)]
    if (heading and editorial(heading) and ' '.join(heading.get_text().split()) == ' '.join(title.split())
            and len(bodies) == 1 and bodies[0].get_text(strip=True)):
        return heading, bodies[0]
    return None


def harvard_writer_link(body, url):
    from bs4 import NavigableString

    label = body.next_sibling
    link = label.next_sibling if isinstance(label, NavigableString) and str(label).strip() == 'by' else None
    if getattr(link, 'name', None) == 'a' and editorial(link):
        person = url_identity(link.get('href'), url)
        name = ' '.join(link.get_text().split())
        if person and person[1] in HARVARD_HOSTS and re.fullmatch(r'/writer/[^/]+', person[2]):
            if harvard_account_name(name):
                return link, ''
            if '@' not in name and 0 < len(name) <= 100:
                return link, name
    return None


def harvard_account_name(name):
    return isinstance(name, str) and re.fullmatch(r'[^@\s]+@harvard\.edu', name, re.I) is not None


def harvard_feed_writer(html, url, title):
    identity = url_identity(url)
    if not identity or identity[1] not in HARVARD_HOSTS:
        return ''
    from bs4 import BeautifulSoup

    fields = harvard_feed_body(BeautifulSoup(html, 'html.parser'), url, title)
    if fields and (writer := harvard_writer_link(fields[1], url)):
        return writer[1]
    return ''


def remove_outside_newsletter(body, url):
    """Discard the end-of-story newsletter template in the page or feed."""
    paragraph = body.find_all('p', recursive=False)
    if not paragraph:
        return
    paragraph = paragraph[-1]
    if not editorial(paragraph) or any(
            (sibling.get_text(strip=True) if getattr(sibling, 'name', None) else str(sibling).strip())
            for sibling in paragraph.next_siblings):
        return
    links = paragraph.select('a[href]')
    if (len(links) == 2
            and ' '.join(paragraph.get_text().split()).startswith('Want more Outside health stories?')
            and [url_identity(link['href'], url) for link in links] == [
                url_identity('https://hub.outsideinc.com/bodywork_newsletter_sign_up-0'),
                url_identity('https://www.outsideonline.com/newsletters/sweat-science-101/')]
            and [' '.join(link.get_text().split()).casefold() for link in links] ==
            ['sign up for the bodywork newsletter', 'sign up for the sweat science 101 newsletter']):
        paragraph.decompose()


def outside_account_name(name, url):
    """Outside's RSS sometimes puts a WordPress login in the creator field."""
    identity = url_identity(url)
    return (identity and identity[1] in OUTSIDE_HOSTS and isinstance(name, str)
            and re.fullmatch(r'[a-z][a-z0-9_.-]*', name) is not None)


def earth_observatory_url(url):
    identity = url_identity(url)
    return bool(identity and identity[1] in {'science.nasa.gov', 'www.nasa.gov', 'nasa.gov'}
                and identity[2].startswith('/earth/earth-observatory/'))


def earth_credits(root, url):
    if not earth_observatory_url(url):
        return
    if isinstance(root, str):
        from bs4 import BeautifulSoup
        root = BeautifulSoup(root, 'html.parser')
    for paragraph in root.select('p.wp-block-paragraph'):
        if (not belongs_to_scope(paragraph, root) or
                paragraph.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figcaption'])):
            continue
        # This is an emphasized publisher credit, not a story mentioning a
        # writer. Preserve its image/data contributors in the article body.
        if any(str(text).strip() and text.find_parent(['em', 'i']) is None for text in paragraph.strings):
            continue
        value = ' '.join(paragraph.get_text('', strip=False).split())
        match = re.fullmatch(r'NASA Earth Observatory images? by (.{2,500})\. Story by ([^\d.!?:;\n]{2,100})\.?', value)
        if match:
            yield paragraph, match[1], match[2].strip()


def earth_observatory_writer(root, url):
    writers = {writer for _, _, writer in earth_credits(root, url)}
    return next(iter(writers)) if len(writers) == 1 else ''


def remove_webb_download_intro(body):
    for heading in body.find_all('h2', class_='wp-block-heading', recursive=False):
        intro = heading.find_next_sibling()
        if (heading_text(heading) == 'Downloads & Related Information' and intro and intro.name == 'p'
                and intro.get_text(' ', strip=True).replace('’', "'").startswith(
                    "The following sections contain links to download this article's images and videos")):
            heading.decompose()
            intro.decompose()


def clean_webb_rss(body, title):
    """Retain mission prose and editorial images from NASA's exported page blocks."""
    def caption_key(node):
        description = node.select_one(':scope > .hds-caption-text')
        credit = node.select_one(':scope > .hds-credits')
        if description and credit:
            return (' '.join(description.get_text(' ', strip=True).split()),
                    ' '.join(credit.get_text(' ', strip=True).split()).removeprefix('Credits: '))
        return tuple(node.get_text(' ', strip=True).split())

    inline = {caption_key(node) for node in body.select('.wp-block-image figcaption.hds-caption') if editorial(node)}
    remove_webb_download_intro(body)
    for widget in body.find_all('div', recursive=False):
        classes = widget.get('class', [])
        headings = [heading_text(h) for h in widget.select('h1, h2, h3')]
        if 'wp-block-nasa-blocks-article-hero-header' in classes and title and any(
                heading_matches(heading_text(h), title) for h in widget.select('h1')):
            # A responsive hero can repeat the inline caption. Keep a unique hero credit in its own block.
            for caption in widget.select('figcaption.hds-caption'):
                key = caption_key(caption)
                if key and key not in inline and editorial(caption):
                    inline.add(key)
                    widget.insert_before(caption.extract())
            widget.decompose()
        elif 'wp-block-nasa-blocks-secondary-navigation' in classes and widget.find('nav'):
            widget.decompose()
        elif 'wp-block-nasa-blocks-featured-link-list' in classes and headings[:1] == ['Related Multimedia']:
            related = widget.find_next_sibling()
            if related and related.name == 'h2' and heading_text(related) == 'Related Links':
                for paragraph in related.find_next_siblings():
                    if paragraph.name != 'p' or not paragraph.find('a', href=True):
                        break
                    labels = ''.join(str(node) for node in paragraph.strings if not node.find_parent('a'))
                    if not re.fullmatch(r'More [^:]+:\s*(?:\|\s*)*', labels.strip()):
                        break
                    paragraph.decompose()
                related.decompose()
            widget.decompose()
        elif 'wp-block-nasa-blocks-credits-and-details' in classes and headings == ['Share', 'Details', 'Related Terms']:
            widget.decompose()
        elif 'wp-block-nasa-blocks-topic-cards' in classes and headings[:1] == ['Related Topics']:
            widget.decompose()


def open_culture_writer(body, url):
    identity = url_identity(url)
    if not identity or identity[1] not in OPEN_CULTURE_HOSTS:
        return ''
    if isinstance(body, str):
        from bs4 import BeautifulSoup
        body = BeautifulSoup(body, 'html.parser')
    last = next((node for node in reversed(body.find_all('p', recursive=False)) if node.get_text(strip=True)), None)
    if last and editorial(last) and not last.find_parent(['blockquote', 'pre', 'code']):
        credit = last.find('em', recursive=False)
        text = ' '.join(speech_text(last.get_text()).split())
        if credit and text == ' '.join(speech_text(credit.get_text()).split()) == 'Ted Mills is a freelance writer on the arts.':
            return 'Ted Mills'
    return ''


def remove_jstor_recommendations(root):
    for recommendations in root.select('.daily-explore.story-list.more-to-explore'):
        heading = recommendations.select_one(':scope > h2.story-list-header')
        if (heading and heading_text(heading) == 'More to Explore'
                and recommendations.select_one(':scope > .article-tease .article-tease__text .byline')
                and not recommendations.find_parent(['blockquote', 'pre', 'code'])):
            recommendations.decompose()


def clean_jstor_pull_quotes(body):
    paragraphs = [' '.join(node.get_text().split()) for node in body.find_all('p')
                  if editorial(node) and not node.find_parent(['aside', 'blockquote', 'pre', 'code'])]
    for quote in body.select('aside.pull-quote'):
        text = quote.select_one(':scope > .pull-quote__text')
        if (not text or any(explicitly_hidden(node) for node in (text, *text.parents))
                or quote.find_parent(['aside', 'blockquote', 'pre', 'code'])
                or len(quote.find_all(recursive=False)) != 1):
            continue
        value = ' '.join(text.get_text().split())
        if value and any(value in paragraph for paragraph in paragraphs):
            quote.decompose()
        elif value:
            quote.name = 'div'


def remove_quillette_bookmarks(body, url):
    for card in body.select('figure.kg-card.kg-bookmark-card'):
        link = card.select_one(':scope > a.kg-bookmark-container[href]')
        target = url_identity(link['href'], url) if link else None
        if (target and target[1] in QUILLETTE_HOSTS and target != url_identity(url)
                and link.select_one('.kg-bookmark-content > .kg-bookmark-title')
                and not card.find_parent(['blockquote', 'pre', 'code'])):
            card.decompose()


def remove_openculture_endmatter(body, url):
    """Remove Open Culture's donation appeal and related-post navigation."""
    identity = url_identity(url)
    paragraphs = body.find_all('p', recursive=False)
    for paragraph in reversed(paragraphs):
        text = ' '.join(speech_text(paragraph.get_text()).split())
        if (paragraph is paragraphs[-1]
                and text.startswith('Based in Seoul, Colin Marshall writes and broadcasts on cities, language, and culture.')
                and paragraph.select_one('em > a[href="http://blog.colinmarshall.org/"]')
                and paragraph.select_one('a[href="https://colinmarshall.substack.com/"]')
                and 'Follow him on the social network' in text):
            paragraph.decompose()
            continue
        appeal = paragraph.find('i', recursive=False)
        if (appeal and paragraph.select_one('a[href]')
                and text == ' '.join(speech_text(appeal.get_text()).split())
                and text.startswith('If you would like to support the mission of Open Culture, '
                                    'consider making a donation to our site.')):
            paragraph.decompose()
            continue

        label = paragraph.find('strong', recursive=False)
        if (not label or text not in {'Related Content', 'Related Content:'}
                or ' '.join(speech_text(label.get_text()).split()) != text):
            continue
        cards = []
        for sibling in paragraph.next_siblings:
            if not str(sibling).strip():
                continue
            if getattr(sibling, 'name', None) == 'p' and not sibling.get_text(strip=True) and not sibling.find(True):
                continue
            if getattr(sibling, 'name', None) != 'p':
                break
            link = sibling.select_one(':scope > a[href]')
            target = url_identity(link['href'], url) if link else None
            if (not target or target[1] not in OPEN_CULTURE_HOSTS or not target[2].endswith('.html')
                    or target[2:] == identity[2:]
                    or ('bookmark' not in link.get('rel', []) and
                        (text != 'Related Content:' or not re.fullmatch(r'/\d{4}/\d{2}/[^/]+\.html', target[2])))
                    or len(sibling.find_all('a')) != 1 or sibling.get_text(strip=True) != link.get_text(strip=True)):
                break
            cards.append(sibling)
        if cards and ('bookmark' in cards[0].a.get('rel', []) or len(cards) >= 2):
            paragraph.decompose()
            for card in cards:
                card.decompose()


def remove_loc_subscription(body):
    paragraph = next((node for node in reversed(body.contents) if str(node).strip()), None)
    if getattr(paragraph, 'name', None) == 'p':
        links = paragraph.find_all('a', recursive=False, href=True)
        value = ' '.join(paragraph.get_text().split()).replace('— ', '—')
        if len(links) == 1 and value == 'Subscribe to the blog—it’s free!' and links[0].get_text(strip=True) == 'Subscribe':
            destination = url_identity(links[0]['href'])
            if destination and destination[1:3] == ('public.govdelivery.com', '/accounts/USLOC/subscriber/new'):
                paragraph.decompose()


def remove_pluralistic_footer(body):
    for heading in body.find_all('h1', recursive=False):
        divider = heading.find_previous_sibling()
        if heading.get_text(strip=True) != 'How to get Pluralistic:' or not divider or divider.name != 'hr':
            continue
        tail = heading.find_next_siblings()
        if (len(tail) >= 3 and all(node.name == 'p' for node in tail)
                and re.fullmatch(r'ISSN: \d{4}-\d{3}[\dX]', tail[-1].get_text(strip=True))
                and tail[-2].get_text(strip=True).startswith('READ CAREFULLY: By reading this, you agree')
                and any(node.select_one('a[href="https://pluralistic.net/plura-list"]') for node in tail)):
            for node in (divider, heading, *tail):
                node.decompose()


def clean_imported_widgets(root, url, title=''):
    if fields := harvard_feed_body(root, url, title):
        heading, body = fields
        if writer := harvard_writer_link(body, url):
            link, _ = writer
            link.previous_sibling.extract()
            link.decompose()
        heading.decompose()
        for widget in list(root.find_all(['div', 'span'], recursive=False)):
            classes = set(widget.get('class', []))
            if classes & {'field--name-uid', 'field--name-created', 'field--name-field-full-header-section',
                          'field--name-field-slug', 'field--name-field-hero-image', 'field--name-field-sub-topics',
                          'field--name-field-featured-topic'} and not widget.find('figcaption'):
                widget.decompose()
            elif 'field--name-field-external-description' in classes:
                label = widget.find(class_='field__label', recursive=False)
                if label:
                    label.decompose()
                    body.insert_before(widget.extract())
    if earth_observatory_url(url):
        credits = [images for _, images, _ in earth_credits(root, url)]
        widgets = (
            ('.wp-block-nasa-blocks-secondary-navigation', '', 'nav'),
            ('.wp-block-nasa-blocks-file-list.hds-featured-file-list', 'Downloads', 'a[href]'),
            ('.wp-block-nasa-blocks-content-lists', 'You may also be interested in:', 'a.hds-content-item-heading'),
            ('.wp-block-nasa-blocks-topic-cards', 'Discover More from NASA Earth Science', 'a.topic-card'),
        )
        for selector, label, content in widgets:
            for widget in root.select(selector):
                if not editorial(widget) or widget.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figcaption']):
                    continue
                heading = widget.find(['h2', 'h3'])
                if (widget.select_one(content) and
                        (not label or heading and heading.get_text(' ', strip=True) == label)):
                    widget.decompose()
        for widget in root.select('.wp-block-nasa-blocks-image-before-after:has(img-comparison-slider)'):
            if not editorial(widget) or widget.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figcaption']):
                continue
            for label in widget.select('.curtain-view-label-wrapper'):
                if (editorial(label) and not label.find_parent(['blockquote', 'pre', 'code']) and
                        DATE.fullmatch(label.get_text(' ', strip=True))):
                    label.decompose()
            seen = set()
            for credit in widget.select('figcaption .hds-credits'):
                if not editorial(credit) or credit.find_parent(['blockquote', 'pre', 'code']):
                    continue
                value = credit.get_text(' ', strip=True)
                owner, separator, person = value.partition('/')
                separately_credited = (separator and owner == 'NASA Earth Observatory' and person and
                                       any(images == person or images.startswith(person + ',') for images in credits))
                if separately_credited or value in seen:
                    credit.decompose()
                elif value:
                    seen.add(value)

    identity = url_identity(url)
    if identity and identity[1] in {'universalhub.com', 'www.universalhub.com'}:
        opening, _ = universal_hub_writer(root, url)
        if opening:
            opening.decompose()
        for node in root.find_all('div', recursive=False):
            classes = set(node.get('class', []))
            if ('field-type-taxonomy-term-reference' in classes and classes & {
                    'field-name-field-topics', 'field-name-field-neighborhoods', 'field-name-field-free-tagging'}
                    or 'rrssb' in classes and node.select_one('ul.rrssb-buttons > li > a[href]')):
                node.decompose()
    if identity and identity[1] == 'daily.jstor.org':
        clean_jstor_pull_quotes(root)
        remove_jstor_recommendations(root)
    if identity and identity[1] in {'damninteresting.com', 'www.damninteresting.com'} and title:
        opening = root.find('p', recursive=False)
        link = opening.select_one(':scope > b > a[href]') if opening else None
        if (link and url_identity(link['href'], url) == identity and heading_text(link) == title
                and ''.join(opening.stripped_strings) == f'{title}:' and opening.find_next_sibling('p')):
            opening.decompose()
    if identity and identity[1] == 'buttondown.com' and '/archive/' in identity[2] and title:
        headline = root.find('h1', recursive=False)
        if headline and heading_text(headline) == title:
            headline.decompose()
    if identity and identity[1] in {'smashingmagazine.com', 'www.smashingmagazine.com'}:
        for widget in root.find_all('div', recursive=False):
            plans = widget.select(':scope > div > div > a[href^="https://smart-interface-design-patterns.thinkific.com/enroll/"]')
            if len(plans) < 2 or not widget.select_one(':scope > div > ul a[href="#"]'):
                continue
            if {heading_text(h) for h in widget.select(':scope > div > div > h3')} != {'Video only', 'Video + UX Training'}:
                continue
            previous = widget.find_previous_sibling()
            while previous and not previous.get_text(strip=True):
                previous = previous.find_previous_sibling()
            if (previous and previous.name == 'a' and previous.get('href') == 'https://ai-design-patterns.com/'
                    and previous.get_text(strip=True) == 'Design Patterns For AI Interfaces'):
                heading = previous
                prompt = heading.find_previous_sibling()
                while prompt and not prompt.get_text(strip=True):
                    prompt = prompt.find_previous_sibling()
                heading.decompose()
                if (prompt and prompt.name == 'p' and prompt.get_text(' ', strip=True).startswith('Meet Design Patterns For AI Interfaces')
                        and prompt.select_one('a[href="https://ai-design-patterns.com/"]')):
                    prompt.decompose()
            widget.decompose()
    if identity and identity[1] == 'www.bgs.ac.uk':
        remove_bgs_related_news(root)
        remove_bgs_topic_links(root, url)
    if identity and identity[1] in {'niemanlab.org', 'www.niemanlab.org'}:
        for timeline in root.select('aside.rsc-collbox.rsc-collbox-side'):
            items = timeline.select(':scope > .rsc-collbox-body > ol.rsc-collbox-list > li.rsc-collbox-item')
            if (timeline.select_one(':scope > .rsc-collbox-body > .rsc-collbox-title')
                    and not timeline.find(['p', 'blockquote', 'figcaption'])
                    and any(item.select_one(':scope > a.rsc-collbox-link[href]') for item in items)
                    and any('is-current' in item.get('class', []) and
                            item.select_one(':scope > span.rsc-collbox-link > .rsc-collbox-hed') for item in items)
                    and all(item.select_one('.rsc-collbox-date') and item.select_one('.rsc-collbox-hed') for item in items)):
                timeline.decompose()
    if identity and identity[1] == 'creativecommons.org':
        for listing in root.find_all('article', class_='posts', recursive=False):
            cards = listing.select(':scope > ul > li > article.post')
            links = [card.select_one(':scope > header > h3.title > a[href]') for card in cards]
            targets = {url_identity(link['href'], url) for link in links if link}
            if (len(targets) > 1 and identity in targets and all(link is not None for link in links)
                    and all(target and target[:2] == identity[:2] for target in targets)
                    and len(listing.find_all(recursive=False)) == 1
                    and all(all(child.name in {'header', 'figure'} for child in card.find_all(recursive=False))
                            for card in cards)):
                listing.decompose()
    if identity and identity[1] == 'science.nasa.gov' and identity[2].startswith('/image-article/apod-'):
        match = re.fullmatch(r'APOD: \d{4} \w+ \d{1,2} [–—-] (.+)', title)
        if match:
            for hero in root.find_all('div', class_='wp-block-nasa-blocks-media-detail-hero', recursive=False):
                heading = hero.select_one(':scope > .grid-container > h1')
                if heading and heading_text(heading) == match[1]:
                    heading.decompose()
    if identity and identity[1] == 'science.nasa.gov' and identity[2].startswith('/missions/webb/'):
        clean_webb_rss(root, title)
    if identity and identity[1] in {'aeon.co', 'www.aeon.co'}:
        ending = next((node for node in reversed(root.contents) if str(node).strip()), None)
        if getattr(ending, 'name', None) == 'p':
            link = ending.find('a', recursive=False, href=True)
            if (link and url_identity(link['href'], url) == identity
                    and ending.get_text(' ', strip=True) == link.get_text(strip=True) == 'Read on Aeon'):
                credit = ending.find_previous_sibling()
                if credit and credit.name == 'p' and (name := credit.find('em', recursive=False)):
                    label = ' '.join(name.get_text().split())
                    if label == ' '.join(credit.get_text().split()) and re.fullmatch(r'- by [^\d.!?:;]{2,100}', label):
                        credit.decompose()
                ending.decompose()
    if identity and identity[1] in {'www.nasa.gov', 'nasa.gov', 'science.nasa.gov'}:
        if identity[2].startswith('/image-article/'):
            for carousel in root.select('.wp-block-nasa-blocks-image-carousel'):
                clean_nasa_carousel_captions(carousel)
        for wrapper in root.find_all('div', recursive=False):
            if 'wp-block-nasa-blocks-article-intro' in wrapper.get('class', []):
                read_time = wrapper.select('.article-header p.label')
                if (len(read_time) == 1 and wrapper.select_one('.article-header h1')
                        and re.fullmatch(r'\d+ min read', read_time[0].get_text(strip=True))
                        and wrapper.find_all('p') == read_time):
                    wrapper.decompose()
            elif 'wp-block-nasa-blocks-credits-and-details' in wrapper.get('class', []):
                headings = [tag.get_text(strip=True) for tag in wrapper.find_all(['h2', 'h3'])]
                if (headings == ['Share', 'Details', 'Related Terms']
                        and 'Last Updated' in wrapper.get_text(' ', strip=True)
                        and not wrapper.select('p, .author, .byline, a[rel~="author"]')):
                    wrapper.decompose()
        remove_press_contacts(root)
    if identity and identity[1] in {'www.experimental-history.com', 'experimental-history.com',
                                    'www.asimov.press', 'asimov.press'}:
        for widget in root.select('.subscription-widget-wrap-editor:has(.subscription-widget.show-subscribe)'):
            if widget.select_one('p.cta-caption') and not widget.find_parent(['blockquote', 'pre', 'code']):
                widget.decompose()
    if identity and identity[1] == 'blogs.loc.gov':
        remove_loc_subscription(root)
    if identity and identity[1] == 'pluralistic.net':
        remove_pluralistic_footer(root)
        remove_table_of_contents(root, url)
    if identity and identity[1] in {'openculture.com', 'www.openculture.com'}:
        remove_openculture_endmatter(root, url)
    if identity and identity[1] in QUILLETTE_HOSTS:
        remove_quillette_bookmarks(root, url)
    if identity and identity[1] in {'astronomy.com', 'www.astronomy.com'}:
        for link in root.select('p > a.more-link[href]'):
            teaser = link.select_one(':scope > .screen-reader-text')
            if (link.parent.parent is root and teaser and title and url_identity(link['href'], url) == identity
                    and heading_matches(heading_text(teaser).strip('"'), title)
                    and heading_text(link).startswith('Continue reading ')
                    and not link.find_next_sibling() and not any(str(text).strip() for text in link.next_siblings)):
                link.decompose()
    if identity and identity[1] in {'niemanlab.org', 'www.niemanlab.org'}:
        for paragraph in root.find_all('p', recursive=False):
            images = paragraph.select(':scope > img.inpost')
            markers = ''.join(paragraph.get_text().split())
            if (images and markers == '[img][/img]' * len(images)
                    and all(child.name in {'img', 'br'} for child in paragraph.find_all(recursive=False))):
                paragraph.decompose()
    if identity and identity[1] == 'blog.jim-nielsen.com':
        paragraph = next((node for node in reversed(root.contents) if str(node).strip()), None)
        if getattr(paragraph, 'name', None) == 'p':
            links = paragraph.find_all('a', recursive=False, href=True)
            if (len(links) == 3 and ' '.join(paragraph.get_text().split()) == 'Reply via: Email · Mastodon · Bluesky'
                    and [link.get_text(strip=True) for link in links] == ['Email', 'Mastodon', 'Bluesky']
                    and links[0]['href'].startswith('mailto:')
                    and url_identity(links[1]['href']) == url_identity('https://mastodon.social/@jimniels')
                    and url_identity(links[2]['href']) == url_identity('https://bsky.app/profile/jim-nielsen.com')):
                paragraph.decompose()
    if identity and identity[1] in {'construction-physics.com', 'www.construction-physics.com',
                                    'experimental-history.com', 'www.experimental-history.com'}:
        paragraph = next((node for node in reversed(root.contents) if str(node).strip()), None)
        if getattr(paragraph, 'name', None) == 'p':
            links = paragraph.select(':scope > a[href]')
            if (len(links) == 1 and url_identity(links[0]['href'], url) == identity
                    and paragraph.get_text(strip=True) == links[0].get_text(strip=True) == 'Read more'):
                paragraph.decompose()
    if identity and identity[1] == 'simonwillison.net':
        opening = root.find('p', recursive=False)
        if opening and title:
            label = opening.find('strong', recursive=False)
            release = opening.find('a', recursive=False, href=True)
            target = url_identity(release['href'], url) if release else None
            remainder = opening.find_next_sibling('p')
            prior_text = ''.join(str(node).strip() for node in opening.previous_siblings)
            release_name = heading_text(release) if release else ''
            duplicate = heading_matches(heading_text(opening), title) or (
                release_name == title and heading_text(opening) == f'Release: {release_name}')
            if (not prior_text and label and label.get_text(strip=True) == 'Release:' and target
                    and target[1] == 'github.com' and '/releases/tag/' in target[2]
                    and duplicate and remainder and remainder.get_text(strip=True)):
                opening.decompose()
        # The Atom feed appends a paragraph of category links after the story.
        # An omitted closing tag can put that template inside the last prose paragraph.
        paragraph = next((node for node in reversed(root.contents) if str(node).strip()), None)
        if getattr(paragraph, 'name', None) == 'p':
            ending = next((node for node in reversed(paragraph.contents) if str(node).strip()), None)
            if getattr(ending, 'name', None) == 'p':
                paragraph = ending
        if getattr(paragraph, 'name', None) == 'p':
            links = paragraph.find_all('a', recursive=False, href=True)
            tags = [link.get_text(strip=True) for link in links]
            if (tags and ' '.join(paragraph.get_text().split()) == 'Tags: ' + ', '.join(tags)
                    and all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', tag)
                            and url_identity(link['href'], url) == url_identity('/tags/' + tag, url)
                            for tag, link in zip(tags, links))):
                paragraph.decompose()
    if identity and identity[1] in {'eff.org', 'www.eff.org'}:
        remove_eff_embed_notice(root, url)
    if identity and identity[1] == 'go.dev' and identity[2].startswith('/blog/'):
        for article in root.select('#blog .Article[data-slug]'):
            if (url_identity(article.get('data-slug'), url) != identity or not editorial(article)
                    or article.find_parent(['blockquote', 'pre', 'code'])
                    or not article.select_one(':scope > .markdown')):
                continue
            # Only discard the template header when it agrees with this feed entry.
            heading = article.select_one(':scope > h1:not(.small)')
            if not title or not heading or heading.get_text(' ', strip=True) != title:
                continue
            for node in article.select(':scope > h1.small:has(a[href="/blog/"]), :scope > p.author'):
                node.decompose()
            heading.decompose()
            nav = article.find_next_sibling()
            if nav and {'Article', 'prevnext'} <= set(nav.get('class', [])) and nav.select_one('a[href="/blog/all"]'):
                nav.decompose()
    if identity and identity[1] in {'theguardian.com', 'www.theguardian.com'}:
        # The RSS excerpt ends with a standalone link back to this very article.
        links = root.find_all('a', recursive=False, href=True)
        if links:
            link = links[-1]
            if (url_identity(link['href'], url) == identity and link.get_text(strip=True) in
                    {'Continue reading...', 'Continue reading…'} and not any(str(s).strip() for s in link.next_siblings)):
                link.decompose()
    if not identity or identity[1] != 'arstechnica.com':
        return
    # Ars supplies an intentional RSS excerpt. Remove only its terminal pair
    # of permalink/comment controls; never follow the full-article link.
    paragraphs = root.find_all('p')
    if len(paragraphs) < 2:
        return
    pair = paragraphs[-2:]
    for paragraph, label, fragment in zip(pair, ('Read full article', 'Comments'), ('', 'comments')):
        links = paragraph.find_all('a')
        if (paragraph.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figcaption']) or len(links) != 1 or
                paragraph.get_text(' ', strip=True) != label or links[0].get_text(' ', strip=True) != label or
                url_identity(links[0].get('href'), url) != identity):
            return
        if urlsplit(links[0]['href']).fragment != fragment:
            return
    if any(str(text).strip() and not any(parent is pair[-1] for parent in text.parents)
           for text in pair[-1].find_all_next(string=True) if text.parent.name not in ('script', 'style')):
        return
    for paragraph in pair:
        paragraph.decompose()
