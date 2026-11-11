"""Recognize publisher credits and feed widgets using only supplied content."""
import re
from urllib.parse import urlsplit

from article_scope import DATE, belongs_to_scope, editorial, url_identity


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


def clean_imported_widgets(root, url):
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
