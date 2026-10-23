"""Read article attribution from public HTML, without fetching more resources."""
import json
import re
from urllib.parse import urljoin, urlparse

from tts import speech_text
from article_scope import article_scope, belongs_to_scope, editorial, heading_matches, url_identity


def clean(value, limit=160):
    return ' '.join(speech_text(value).split())[:limit].strip() if isinstance(value, str) else ''


def article_metadata(soup, url):
    def meta(*keys):
        for key in keys:
            node = soup.find('meta', attrs={'property': key}) or soup.find('meta', attrs={'name': key})
            if node and node.get('content', '').strip():
                return node['content']
        return ''

    # Resolve references within the already-downloaded JSON-LD graph. Never
    # follow @id URLs: publishers and authors often live in sibling nodes.
    nodes = []
    for script in soup.select('script[type="application/ld+json"]')[:20]:
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, RecursionError):
            continue
        pending = data[:] if isinstance(data, list) else [data]
        while pending and len(nodes) < 500:
            node = pending.pop(0)
            if not isinstance(node, dict):
                continue
            nodes.append(node)
            for key in ('@graph', 'mainEntity'):
                child = node.get(key, [])
                pending.extend(child[:100] if isinstance(child, list) else [child])
    references = {node['@id']: node for node in nodes if isinstance(node.get('@id'), str)}

    def names(value, depth=0):
        if depth > 3:
            return ''
        values = value[:5] if isinstance(value, list) else [value]
        found = []
        for item in values:
            if isinstance(item, dict):
                name = clean(item.get('name'), 100)
                if not name and isinstance(item.get('@id'), str):
                    name = names(references.get(item['@id']), depth + 1)
            else:
                name = clean(item, 100)
            if name and not name.startswith(('http://', 'https://')) and name not in found:
                found.append(name)
        return ', '.join(found)

    def kinds(node):
        value = node.get('@type', [])
        return [value] if isinstance(value, str) else value if isinstance(value, list) else []

    articles = [node for node in nodes if any(isinstance(kind, str) and
                (kind.rsplit('/', 1)[-1].endswith('Article') or kind.rsplit('/', 1)[-1] == 'BlogPosting')
                for kind in kinds(node))]
    def article_urls(node):
        values = [node.get('url'), node.get('@id')]
        page = node.get('mainEntityOfPage')
        if isinstance(page, dict):
            values.extend([page.get('url'), page.get('@id')])
        elif isinstance(page, str):
            values.append(page)
        return {identity for value in values if (identity := url_identity(value, url))}

    requested = url_identity(url)
    canonical = soup.select_one('link[rel~="canonical"][href]')
    canonical_url = url_identity(canonical.get('href'), url) if canonical else None
    social_title = clean(meta('og:title', 'twitter:title'))
    def article_score(node):
        identities = article_urls(node)
        return (requested in identities, canonical_url is not None and canonical_url in identities,
                heading_matches(clean(node.get('headline')), social_title))
    article = max(articles, key=article_score) if articles else {}
    site = next((node for node in nodes if 'WebSite' in kinds(node)), {})

    # A site's home link is an explicit identity fallback, not an inferred name
    # from the hostname. Ignore generic Home links and restrict to this host.
    home_name = ''
    for link in soup.select('a[href]'):
        try:
            parsed = urlparse(urljoin(url, link['href']))
            same_host = parsed.hostname == urlparse(url).hostname
        except ValueError:
            continue  # A malformed navigation link must not spoil an article.
        if not same_host or parsed.path not in ('', '/'):
            continue
        label = clean(link.get('title') or link.get_text(' ', strip=True), 80)
        if not label:
            image = link.find('img', alt=True)
            label = clean(image.get('alt') if image else '', 80)
        label = re.sub(r'(?:\s+logo|:\s*Home)$', '', label, flags=re.I)
        if label and label.casefold() not in ('home', 'homepage', 'go', 'skip to content'):
            home_name = label
            break
    feed = soup.select_one('link[rel="alternate"][type="application/atom+xml"][title], '
                           'link[rel="alternate"][type="application/rss+xml"][title]')
    publication = clean(meta('og:site_name') or names(article.get('publisher')) or
                        names(site) or names(article.get('isPartOf')) or meta('application-name') or
                        (feed.get('title', '').split(' » ')[0] if feed else '') or home_name, 80)
    publication = publication.split(' | ')[0].strip()
    publication = publication or clean((urlparse(url).hostname or '').removeprefix('www.'), 80)

    def strip_suffix(value):
        for separator in (' — ', ' - ', ' | ', ' – ', ' –\u00a0'):
            suffix = separator + publication
            if value.casefold().endswith(suffix.casefold()):
                return value[:-len(suffix)].strip()
        return value

    structured = clean(article.get('headline'))
    social = clean(meta('og:title', 'twitter:title'))
    page_title = clean(soup.title.get_text(' ', strip=True) if soup.title else '')
    headings = [node for node in soup.select('.PostsPageTitle-root, article h1, main h1, .entry-title')
                if editorial(node)]
    def matches_heading(node):
        value = clean(node.get_text(' ', strip=True))
        # Some sites put Markdown emphasis into social/SEO metadata. Compare
        # without those markers, then read the visible heading as plain text.
        comparable = lambda value: re.sub(r'[*_`]', '', value)
        value = comparable(value)
        return bool(value) and any(raw and (comparable(raw) == value or
                    any(comparable(raw).startswith(value + sep) for sep in (' | ', ' - ', ' — ', ' – ')))
                    for raw in (structured, social, page_title))
    if not headings:
        # Nonsemantic collection layouts can place h1 outside article/main.
        # Require a metadata match so unrelated site branding cannot win.
        headings = [node for node in soup.select('h1') if editorial(node) and not node.find_parent(['header', 'nav', 'aside'])
                    and matches_heading(node)]
    # Match metadata to distinguish an article heading from blog branding (Go
    # has both as h1). Otherwise prefer the visible headline over its SEO variant.
    preliminary_scope = article_scope(soup, structured or social or page_title, url)
    preferred_headings = [node for node in headings if any(parent is preliminary_scope for parent in node.parents)]
    heading = next((node for node in headings if matches_heading(node)),
                   next(iter(preferred_headings or headings), None))
    title = clean(heading.get_text(' ', strip=True) if heading else '') or structured or social or page_title
    title = strip_suffix(title)

    scope = article_scope(soup, title, url)
    byline = next((node for node in scope.select('[rel~="author"], [itemprop="author"], '
                  '.PostsAuthors-root, .byline, .news-article--authored-by, p.author')
                   if belongs_to_scope(node, scope)), None)
    if byline is None:
        # An ordinary link to somebody's author page in the prose isn't a
        # byline. Accept these links only inside article attribution markup.
        byline = scope.select_one('header a[href*="/authors/"], header a[href*="/author/"], '
                                  '.blog-post-meta a[href*="/author/"]')
    if byline is None:
        byline = next((node for node in soup.select('.PostsAuthors-root, .byline, .news-article--authored-by')
                       if belongs_to_scope(node, scope)), None)
    byline_name = ''
    if byline is not None:
        # Prefer an author link/name to a wrapper containing roles and dates.
        name_node = byline.select_one('[itemprop="name"], a') or byline
        byline_name = name_node.get_text(' ', strip=True).split(' | ')[0]
        if name_node is byline and byline.find('br'):
            pieces = []
            for child in byline.children:
                if getattr(child, 'name', '') == 'br':
                    break
                pieces.append(child.get_text(' ', strip=True) if hasattr(child, 'get_text') else str(child))
            byline_name = ' '.join(pieces)
        byline_name = re.split(r',\s+(?:Chief|Senior|Staff|Principal|Contributing)\b', byline_name)[0]
    # An explicit visible author list is stronger evidence than a generic
    # publisher account in JSON-LD (for example "The Editors"). Read the whole
    # group so a multi-author byline isn't reduced to its first link.
    groups = [node for node in soup.select('.article-authors') if belongs_to_scope(node, scope)]
    group = next((node for node in groups if any(parent is scope for parent in node.parents)),
                 next(iter(groups), None))
    visible_authors = ''
    if group is not None:
        members = group.select('a, [itemprop="name"]')
        values = [clean(node.get_text(' ', strip=True), 100) for node in members[:5]]
        visible_authors = ', '.join(dict.fromkeys(filter(None, values))) or clean(group.get_text(' ', strip=True), 100)
    author = visible_authors or names(article.get('author')) or meta('author', 'parsely-author', 'citation_author') or byline_name
    if not author:
        rust_byline = soup.select_one('.publish-date-author')
        google_byline = soup.select_one('.basic-hero--blog-detail__description')
        sidebar_byline = soup.select_one('#Sidebar > p')
        if rust_byline:
            author = rust_byline.get_text(' ', strip=True).partition('·')[2].split(' on behalf of ')[0]
        elif google_byline:
            paragraphs = google_byline.find_all('p')
            if len(paragraphs) > 1:
                author = ', '.join(part.split(',')[0] for part in
                                   re.split(r',\s+and\s+', paragraphs[-1].get_text(' ', strip=True)))
        elif sidebar_byline and re.match(r'^By\s+', sidebar_byline.get_text(' ', strip=True)):
            author = sidebar_byline.get_text(' ', strip=True)
    author = clean(author or meta('article:author'), 100)
    if author.startswith(('http://', 'https://')):
        author = ''
    author = re.sub(r'^by(?:\s*:\s*|\s+)', '', author, flags=re.I)
    return publication, title, author
