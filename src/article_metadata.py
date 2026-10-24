"""Read article attribution from public HTML, without fetching more resources."""
import json
import re
from urllib.parse import urljoin, urlparse

from tts import speech_text
from article_scope import article_scope, belongs_to_scope, editorial, explicitly_hidden, heading_matches, heading_text, url_identity


def clean(value, limit=160):
    return ' '.join(speech_text(value).split())[:limit].strip() if isinstance(value, str) else ''


def linked_byline_names(byline):
    """Read distinct author names inside attribution, excluding its controls."""
    members = byline.select('[rel~="author"], [itemprop~="author"], [itemprop~="name"], '
                            'a[href*="/authors/"], a[href*="/author/"]')
    explicit = bool(members)
    if ('author' in byline.get('rel', []) or 'author' in byline.get('itemprop', '').split()
            or 'author' in byline.get('class', [])) and byline.parent:
        siblings = byline.parent.select(':scope > [rel~="author"], :scope > [itemprop~="author"], :scope > .author')
        if len(siblings) > 1:
            members, explicit = siblings, True
    if not members:
        members = byline.select('a')
    identities = {id(node) for node in members}
    values = []
    for node in members[:100]:
        if (not editorial(node) or node.find_parent('time') or
                any(id(parent) in identities for parent in node.parents)):
            continue
        value = node.select_one('[itemprop~="name"]') or node
        name = re.sub(r'^by(?:\s*:\s*|\s+)', '', clean(value.get_text(' ', strip=True), 100), flags=re.I)
        if not explicit and (node.get('href', '').startswith('#') or 'tag' in node.get('rel', []) or
                             name.casefold() in {'follow', 'subscribe', 'share', 'email', 'comments'}):
            continue
        if name and name not in values:
            values.append(name)
            if len(values) == 5:
                break
    return values


def public_structured_article(node, references, depth=0):
    """Do not use schema bodies explicitly marked as containing paid sections."""
    if depth > 3:
        return False
    if isinstance(node, str):
        node = references.get(node)
    if not isinstance(node, dict):
        return True
    access = node.get('isAccessibleForFree')
    if access is False or isinstance(access, str) and access.strip().casefold() == 'false':
        return False
    ref = references.get(node.get('@id')) if isinstance(node.get('@id'), str) else None
    if ref is not None and ref is not node and not public_structured_article(ref, references, depth + 1):
        return False
    parts = node.get('hasPart', [])
    parts = parts if isinstance(parts, list) else [parts]
    return len(parts) <= 100 and all(public_structured_article(part, references, depth + 1) for part in parts)


def article_details(soup, url):
    """Return attribution and an eligible structured-body fallback for this page."""
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
    page_label = clean(soup.title.get_text(' ', strip=True) if soup.title else '')
    identity_scope = article_scope(soup, social_title or page_label, url)
    title_hints = [social_title, page_label] + [
        clean(heading_text(node)) for node in
        identity_scope.select('.PostsPageTitle-root, h1, .entry-title')
        if belongs_to_scope(node, identity_scope)]
    title_hints = list(filter(None, title_hints))
    def article_score(node):
        identities = article_urls(node)
        return (requested in identities, canonical_url is not None and canonical_url in identities,
                any(heading_matches(clean(node.get('headline')), hint) for hint in title_hints))
    def eligible_article(node):
        score = article_score(node)
        if article_urls(node):
            return any(score[:2])  # A matching headline cannot excuse another article's URL.
        # Identity-free singleton schemas are common. Retain them only when
        # their headline does not conflict with the page's own title evidence.
        return score[2] or len(articles) == 1 and (not clean(node.get('headline')) or not title_hints)
    eligible = [node for node in articles if eligible_article(node)]
    article = max(eligible, key=article_score) if eligible else {}
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
        if (not same_host or parsed.path not in ('', '/') or parsed.query or parsed.fragment or
                link.find_parent(['p', 'li', 'blockquote', 'pre', 'code']) or
                any(explicitly_hidden(parent) for parent in (link, *link.parents))):
            continue
        label = clean(link.get('title') or link.get_text(' ', strip=True), 80)
        if not label:
            image = link.find('img', alt=True)
            label = clean(image.get('alt') if image else '', 80)
        label = re.sub(r'(?:\s+logo|:\s*Home)$', '', label, flags=re.I)
        if label and label.casefold() not in ('home', 'homepage', 'go', 'skip to content', 'archive', 'archives', 'index'):
            home_name = label
            break
    feed = soup.select_one('link[rel="alternate"][type="application/atom+xml"][title], '
                           'link[rel="alternate"][type="application/rss+xml"][title]')
    feed_name = re.sub(r'\s+[-|–—]\s+(?:Atom|RSS)(?:\s+Feed)?$', '',
                       feed.get('title', '').split(' » ')[0] if feed else '', flags=re.I)
    publication = clean(meta('og:site_name') or names(article.get('publisher')) or
                        names(site) or names(article.get('isPartOf')) or meta('application-name') or
                        feed_name or home_name, 80)
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
        value = clean(heading_text(node))
        # Some sites put Markdown emphasis into social/SEO metadata. Compare
        # without those markers, then read the visible heading as plain text.
        return any(heading_matches(value, raw) for raw in (structured, social, page_title))
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
    title = clean(heading_text(heading) if heading else '') or structured or social or page_title
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
    if byline is not None and re.fullmatch(r'by\s*:?', clean(byline.get_text(' ', strip=True)), re.I):
        byline = next((node for node in byline.parent.select(
            ':scope > .author, :scope > [rel~="author"], :scope > [itemprop~="author"]')
            if belongs_to_scope(node, scope)), None)
    if byline is None and scope.parent is not None and scope.parent.name == 'topcomment':
        byline = next((node for node in scope.select('.info > .username') if belongs_to_scope(node, scope)), None)
    byline_name = byline_authors = ''
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
        members = linked_byline_names(byline)
        if members:
            byline_name = ', '.join(members)
            if len(members) > 1:
                byline_authors = byline_name
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
    author = visible_authors or byline_authors or names(article.get('author')) or meta('author', 'parsely-author', 'citation_author') or byline_name
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
    author = re.sub(r'^by(?:\s*:\s*|\s+|$)', '', author, flags=re.I)
    body = article.get('articleBody')
    identified = (any(article_score(article)[:2]) or not article_urls(article) and
                  heading_matches(title, clean(article.get('headline'))))
    if not isinstance(body, str) or not identified or not public_structured_article(article, references):
        body = ''
    return publication, title, author, body


def article_metadata(soup, url):
    return article_details(soup, url)[:3]
