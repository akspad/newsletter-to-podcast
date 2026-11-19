"""Recognize publisher credits and feed widgets using only supplied content."""
import re
from urllib.parse import urlsplit

from tts import speech_text

from article_scope import DATE, belongs_to_scope, editorial, heading_matches, heading_text, url_identity


HARVARD_HOSTS = {'harvardmagazine.com', 'www.harvardmagazine.com'}
OUTSIDE_HOSTS = {'outsideonline.com', 'www.outsideonline.com'}
COLOSSAL_HOSTS = {'thisiscolossal.com', 'www.thisiscolossal.com'}
WYOFILE_HOSTS = {'wyofile.com', 'www.wyofile.com'}


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
        if (person and person[1] in HARVARD_HOSTS and re.fullmatch(r'/writer/[^/]+', person[2])
                and '@' not in name and 0 < len(name) <= 100):
            return link, name
    return None


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
            if (not target or target[1] != identity[1] or not target[2].endswith('.html') or target == identity
                    or ('bookmark' not in link.get('rel', []) and
                        (text != 'Related Content:' or not re.fullmatch(r'/\d{4}/\d{2}/[^/]+\.html', target[2])))
                    or len(sibling.find_all('a')) != 1 or sibling.get_text(strip=True) != link.get_text(strip=True)):
                break
            cards.append(sibling)
        if cards and ('bookmark' in cards[0].a.get('rel', []) or len(cards) >= 2):
            paragraph.decompose()
            for card in cards:
                card.decompose()


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
                          'field--name-field-slug', 'field--name-field-hero-image'} and not widget.find('figcaption'):
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
    if identity and identity[1] in {'openculture.com', 'www.openculture.com'}:
        remove_openculture_endmatter(root, url)
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
    if identity and identity[1] == 'simonwillison.net':
        # The Atom feed appends a paragraph of category links after the story.
        paragraph = next((node for node in reversed(root.contents) if str(node).strip()), None)
        if getattr(paragraph, 'name', None) == 'p':
            links = paragraph.find_all('a', recursive=False, href=True)
            tags = [link.get_text(strip=True) for link in links]
            if (tags and ' '.join(paragraph.get_text().split()) == 'Tags: ' + ', '.join(tags)
                    and all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', tag)
                            and url_identity(link['href'], url) == url_identity('/tags/' + tag, url)
                            for tag, link in zip(tags, links))):
                paragraph.decompose()
    if identity and identity[1] in {'eff.org', 'www.eff.org'}:
        for notice in root.select('.mytube > .mytubetext'):
            if notice.find_parent(['blockquote', 'pre', 'code']) or not notice.parent.select_one(':scope > .mytubetrigger'):
                continue
            links = notice.select('a[href]')
            if (len(links) == 2 and links[0].get_text(strip=True) == 'Privacy info.'
                    and url_identity(links[0]['href'], url) == url_identity('/deeplinks/2008/02/embedded-video-and-your-privacy', url)
                    and notice.get_text(' ', strip=True) == 'Privacy info. This embed will serve content from ' + links[1].get_text(strip=True)):
                notice.decompose()
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
