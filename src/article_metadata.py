"""Read article attribution from public HTML, without fetching more resources."""
from html import unescape
import json
import re
from urllib.parse import urljoin, urlparse

from tts import speech_text
from imported_content import GUARDIAN_HOSTS, OPEN_CULTURE_HOSTS, QUILLETTE_HOSTS, WYOFILE_HOSTS, earth_observatory_writer, freebsd_report_writer, guardian_author_label, open_culture_writer, universal_hub_writer, wyofile_feature
from article_scope import DATE, STRONG_TOWNS_HOSTS, abseil_tip_byline, article_labels, article_scope, belongs_to_scope, editorial, explicitly_hidden, heading_matches, heading_text, opening_writer_credits, plover_story_title, react_blog_credit, url_identity


def clean(value, limit=160):
    return ' '.join(speech_text(value).split())[:limit].strip() if isinstance(value, str) else ''


def visible_text(node):
    return ' '.join(str(value) for value in node.strings if editorial(value.parent))


def reference_id(value, base_url):
    if not isinstance(value, str):
        return None
    try:
        return urljoin(base_url, value)
    except ValueError:
        return None


def linked_byline_names(byline):
    """Read distinct author names inside attribution, excluding its controls."""
    members = byline.select('[rel~="author"], [itemprop~="author"], [itemprop~="name"], '
                            'a[href*="/authors/"], a[href*="/author/"], a[href*="/by/"]')
    if byline.name == 'a' and (byline.get('rel') and 'author' in byline['rel'] or
                              any(part in byline.get('href', '') for part in ('/authors/', '/author/', '/by/'))):
        members = [byline]
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
        if (not editorial(node) or node.find_parent(['time', 'template', 'script', 'style', 'noscript']) or
                any(id(parent) in identities for parent in node.parents)):
            continue
        value = node.select_one('[itemprop~="name"]') or node
        name = re.sub(r'^by(?:\s*:\s*|\s+)', '', clean(visible_text(value), 100), flags=re.I)
        if not explicit and (node.get('href', '').startswith('#') or 'tag' in node.get('rel', []) or
                             name.casefold() in {'follow', 'subscribe', 'share', 'email', 'comments'}):
            continue
        if name and name not in values:
            values.append(name)
            if len(values) == 5:
                break
    return values


def public_structured_article(node, references, depth=0, base_url=''):
    """Do not use schema bodies explicitly marked as containing paid sections."""
    if depth > 3:
        return False
    if isinstance(node, str):
        node = references.get(reference_id(node, base_url))
    if not isinstance(node, dict):
        return True
    access = node.get('isAccessibleForFree')
    if access is False or isinstance(access, str) and access.strip().casefold() == 'false':
        return False
    ref = references.get(reference_id(node.get('@id'), base_url))
    if ref is not None and ref is not node and not public_structured_article(ref, references, depth + 1, base_url):
        return False
    parts = node.get('hasPart', [])
    parts = parts if isinstance(parts, list) else [parts]
    return len(parts) <= 100 and all(public_structured_article(part, references, depth + 1, base_url) for part in parts)


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
    references = {identity: node for node in nodes if (identity := reference_id(node.get('@id'), url)) is not None}

    def names(value, depth=0):
        if depth > 3:
            return ''
        values = value[:5] if isinstance(value, list) else [value]
        found = []
        for item in values:
            if isinstance(item, dict):
                name = clean(item.get('name'), 100)
                if not name and isinstance(item.get('@id'), str):
                    name = names(references.get(reference_id(item['@id'], url)), depth + 1)
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
    visible_titles = [
        clean(heading_text(node)) for node in
        identity_scope.select('.PostsPageTitle-root, h1, .entry-title')
        if belongs_to_scope(node, identity_scope)]
    title_hints = [social_title, page_label] + visible_titles
    title_hints = list(filter(None, title_hints))
    def article_score(node):
        identities = article_urls(node)
        return (requested in identities, canonical_url is not None and canonical_url in identities,
                any(heading_matches(clean(node.get('headline')), hint) for hint in title_hints),
                # Publishing plugins can emit a second record for the same
                # URL with an SEO suffix and the posting account as author.
                # Break otherwise equal identity scores using the article's
                # visible headline, independently of schema type or order.
                any(clean(node.get('headline')).casefold() == hint.casefold()
                    for hint in visible_titles if hint))
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
    feed_name = re.sub(r'\s+(?:[-|–—]\s+)?(?:Atom|RSS)\s+Feed$|\s+[-|–—]\s+(?:Atom|RSS)$', '',
                       feed.get('title', '').split(' » ')[0] if feed else '', flags=re.I)
    if clean(feed_name).casefold() in {'rss', 'atom', 'feed', 'rss feed', 'atom feed',
                                      'recent entries', 'recent posts', 'latest posts',
                                      'rss: xml feed', 'rss: json feed'}:
        feed_name = ''
    if requested and requested[1] == 'blog.jim-nielsen.com' and not feed_name:
        headline, _, site_label = page_label.rpartition(' - ')
        if headline in visible_titles and site_label:
            home_name = site_label
    pypi_post = requested and requested[1] == 'blog.pypi.org' and requested[2].startswith('/posts/')
    if pypi_post:
        logo = soup.select_one('header .md-logo[data-md-component="logo"][title]')
        if logo:
            home_name = logo['title']
    inkscape_news = requested and requested[1] == 'inkscape.org' and requested[2].startswith('/news/')
    if inkscape_news:
        logo = soup.select_one('#logo a > img[alt]')
        if logo and editorial(logo):
            home_name = logo['alt']
            if clean(feed_name).casefold() == 'news feed':
                feed_name = ''
    publication = clean(meta('og:site_name') or names(article.get('publisher')) or
                        names(site) or names(article.get('isPartOf')) or meta('application-name') or
                        feed_name or home_name, 80)
    publication = publication.split(' | ')[0].strip()
    publication = publication or clean((urlparse(url).hostname or '').removeprefix('www.'), 80)
    react_post = requested and requested[1] == 'react.dev' and requested[2].startswith('/blog/')
    if react_post and page_label.endswith(' – React'):
        publication = 'React'
    if (requested and requested[1] in STRONG_TOWNS_HOSTS and requested[2].startswith('/journal/')
            and publication == 'strongtowns.org' and page_label.endswith(' | Strong Towns')):
        publication = 'Strong Towns'
    if requested and requested[1] == 'blog.archive.org':
        masthead = soup.select_one('header .site-title > a[rel~="home"][href]')
        if masthead and editorial(masthead) and url_identity(masthead['href'], url) == requested[:2] + ('', ()):
            publication = clean(masthead.get_text(), 80) or publication

    def strip_suffix(value):
        for separator in (' — ', ' - ', ' | ', ' – ', ' –\u00a0'):
            suffix = separator + publication
            if value.casefold().endswith(suffix.casefold()):
                return value[:-len(suffix)].strip()
        return value

    structured = clean(article.get('headline'))
    social = clean(meta('og:title', 'twitter:title'))
    page_title = clean(soup.title.get_text(' ', strip=True) if soup.title else '')
    headings = [node for node in soup.select('.PostsPageTitle-root, article h1, main h1, .entry-title, .post-title')
                if editorial(node)]
    def matches_heading(node):
        value = clean(heading_text(node))
        # Some sites put Markdown emphasis into social/SEO metadata. Compare
        # without those markers, then read the visible heading as plain text.
        return any(heading_matches(value, raw) or heading_matches(value, unescape(raw))
                   for raw in (structured, social, page_title))
    if not headings:
        # Nonsemantic collection layouts can place h1 outside article/main.
        # Require a metadata match so unrelated site branding cannot win.
        headings = [node for node in soup.select('h1') if editorial(node) and not node.find_parent(['header', 'nav', 'aside'])
                    and matches_heading(node)]
    # Match metadata to distinguish an article heading from blog branding (Go
    # has both as h1). Otherwise prefer the visible headline over its SEO variant.
    preliminary_scope = article_scope(soup, structured or social or page_title, url)
    labels = next((fields for raw in (structured, social, page_title)
                   for block, fields in article_labels(soup, raw)
                   if belongs_to_scope(block, preliminary_scope)), {})
    preferred_headings = [node for node in headings if any(parent is preliminary_scope for parent in node.parents)]
    heading = next((node for node in headings if matches_heading(node)),
                   labels.get('title') or next(iter(preferred_headings or headings), None))
    if requested and requested[1] in {'reason.com', 'www.reason.com'} and requested[2].startswith('/volokh/'):
        permalink = preliminary_scope.select_one(':scope > header > h2.entry-title > a[href]')
        if permalink and editorial(permalink) and url_identity(permalink['href'], url) == requested:
            heading = permalink
    if (requested and requested[1] in {'theparisreview.org', 'www.theparisreview.org'}
            and requested[2].startswith('/blog/')):
        # The article headline is a sibling of main, and the schema can
        # contain HTML entities even when the visible text is correct.
        headline = soup.select_one('section#content > header.titles > h1')
        raw_headline = article.get('headline')
        if headline and editorial(headline) and isinstance(raw_headline, str):
            visible = clean(heading_text(headline))
            if visible and visible in (structured, clean(unescape(raw_headline))):
                heading = headline
    abseil_tip = requested and requested[1] == 'abseil.io' and re.fullmatch(r'/(tips|fast)/(\d+)', requested[2])
    if abseil_tip:
        tip = soup.select_one('div.col-sm-8.markdown > h1')
        prefix = 'Performance ' if abseil_tip[1] == 'fast' else ''
        if tip and editorial(tip) and heading_text(tip).startswith(f'{prefix}Tip of the Week #{abseil_tip[2]}: '):
            heading = tip
    title = clean(heading_text(heading) if heading else '') or structured or social or page_title
    if (requested and requested[1] == 'devblogs.microsoft.com' and requested[2].startswith('/oldnewthing/')
            and heading and heading.find('code') and all(child.name in {'code', 'em', 'strong'} for child in heading.find_all())):
        title = clean(heading.get_text()) or title
    title = strip_suffix(title)
    plover_title = plover_story_title(soup, url)
    if plover_title:
        title = clean(heading_text(plover_title)) or title
        masthead = soup.select_one('h1.pagetitle')
        if masthead and editorial(masthead):
            publication = clean(heading_text(masthead), 80) or publication

    scope = article_scope(soup, title, url)
    diary_author = ''
    if (requested and requested[1] in {'openstreetmap.org', 'www.openstreetmap.org'}
            and 'diary_post' in scope.get('class', [])):
        entry = re.fullmatch(r'(/user/[^/]+)/diary/\d+', requested[2])
        if entry:
            for permalink in scope.select(':scope > div > h2 > a[href]'):
                if url_identity(permalink['href'], url) != requested or not belongs_to_scope(permalink, scope):
                    continue
                title = clean(heading_text(permalink)) or title
                profile = url_identity(entry[1], url)
                diary_author = next((clean(visible_text(link)) for link in permalink.parent.parent.select(
                    ':scope > small a[href]')
                    if url_identity(link['href'], url) == profile and belongs_to_scope(link, scope)), '')
                break
    byline = next((node for node in scope.select('[rel~="author"], [itemprop~="author"], '
                  '.PostsAuthors-root, .byline, .news-article--authored-by, p.author, .c-article__author__name')
                   if belongs_to_scope(node, scope) and not node.find_parent(['blockquote', 'pre', 'code'])), None)
    if byline is None:
        # An ordinary link to somebody's author page in the prose isn't a
        # byline. Accept these links only inside article attribution markup.
        byline = next((node for node in scope.select(
            'header a[href*="/authors/"], header a[href*="/author/"], .blog-post-meta a[href*="/author/"]')
            if belongs_to_scope(node, scope) and
            not node.find_parent(['blockquote', 'pre', 'code', 'template', 'script', 'style', 'noscript'])), None)
    if byline is None:
        byline = next((node for node in soup.select('.PostsAuthors-root, .byline, .news-article--authored-by, .c-article__author__name')
                       if belongs_to_scope(node, scope) and not node.find_parent(['blockquote', 'pre', 'code'])), None)
    if byline is not None and re.fullmatch(r'by\s*:?', clean(byline.get_text(' ', strip=True)), re.I):
        byline = next((node for node in byline.parent.select(
            ':scope > .author, :scope > [rel~="author"], :scope > [itemprop~="author"]')
            if belongs_to_scope(node, scope)), None)
    if byline is None and scope.parent is not None and scope.parent.name == 'topcomment':
        byline = next((node for node in scope.select('.info > .username') if belongs_to_scope(node, scope)), None)
    if requested and requested[1] == 'webkit.org' and byline is not None:
        writer = byline.select_one(':scope > p.author')
        if writer and editorial(writer):
            byline = writer
    if (requested and requested[1] in QUILLETTE_HOSTS and byline is not None and byline.name == 'a'
            and byline.select_one('figcaption.sr-only')):
        profile = url_identity(byline.get('href'), url)
        if profile and profile[1] in QUILLETTE_HOSTS and profile[2].startswith('/author/'):
            byline = next((link for link in scope.select('header a[href]')
                           if url_identity(link['href'], url) == profile and editorial(link)
                           and not link.find('figure') and visible_text(link).strip()), None)
    if byline is None and requested and requested[1] == 'blogs.kde.org' and scope.name == 'article':
        byline = next((node for node in scope.select(
            ':scope > .jumbotron > .content-width > p.meta:has(a[href*="/authors/"])')
            if belongs_to_scope(node, scope)), None)
    if requested and requested[1] in {'openculture.com', 'www.openculture.com'}:
        for credit in scope.select('.recent_post > .alignleft > p.author'):
            permalink = credit.select_one('a[title="Permalink"][href]')
            if (permalink and url_identity(permalink['href'], url) == requested
                    and belongs_to_scope(credit, scope) and credit.select_one('a[rel~="author"]')):
                byline = credit
                break
        else:
            if byline is not None and byline.select_one('a[href$="#respond"]'):
                byline = None
    byline_name = byline_authors = ''
    if byline is not None:
        # Prefer an author link/name to a wrapper containing roles and dates.
        name_node = next((node for node in byline.select('[itemprop~="name"], a') if editorial(node)), byline)
        byline_name = visible_text(name_node).split(' | ')[0]
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
            # A visible single name may be a collapsed view of a complete
            # structured coauthor list. Keep that list when it agrees.
            structured_authors = article.get('author')
            if (len(members) > 1 or not isinstance(structured_authors, list) or
                    not any(names(value) == byline_name for value in structured_authors)):
                byline_authors = byline_name
    # An explicit visible author list is stronger evidence than a generic
    # publisher account in JSON-LD (for example "The Editors"). Read the whole
    # group so a multi-author byline isn't reduced to its first link.
    groups = [node for node in soup.select('.article-authors, .c-article-author, .single-article-meta .bylines')
              if belongs_to_scope(node, scope) and not node.find_parent(['blockquote', 'pre', 'code'])]
    if urlparse(url).hostname == 'blog.cloudflare.com':
        groups.extend(node for node in scope.select('header p')
                      if node.select_one('a[href^="/author/"] > bdi') and belongs_to_scope(node, scope) and not node.find_parent(['blockquote', 'pre', 'code']))
    if labels.get('author') is not None:
        groups.append(labels['author'])
    group = next((node for node in groups if any(parent is scope for parent in node.parents)),
                 next(iter(groups), None))
    visible_authors = ''
    if group is not None:
        visible_authors = ', '.join(linked_byline_names(group))
        if not visible_authors and not group.select('a, [itemprop~="name"]'):
            visible_authors = clean(visible_text(group), 100)
    if (requested and requested[1] == 'www.internetsociety.org' and requested[2].startswith('/blog/')
            and scope.name == 'article' and 'content-wrapper' in scope.parent.get('class', [])):
        header = scope.find_previous_sibling()
        headline = header.find('h1') if header and header.name == 'header' else None
        if headline and editorial(headline) and heading_matches(heading_text(headline), title):
            names_in_header = [clean(visible_text(link)) for link in header.select(
                '.author-box .author-meta .author-name > a[href]') if editorial(link)]
            visible_authors = ', '.join(dict.fromkeys(filter(None, names_in_header))) or visible_authors
    if requested and requested[1] == 'gds.blog.gov.uk' and scope.name == 'article':
        attribution = scope.select_one(':scope > header .govuk-body-s:has(a[rel~="author"])')
        if attribution and editorial(attribution):
            authors = [re.split(r',\s+Head of\s+', name, maxsplit=1, flags=re.I)[0]
                       for name in linked_byline_names(attribution)]
            visible_authors = ', '.join(dict.fromkeys(authors)) or visible_authors
    if requested and requested[1] == 'web.dev' and requested[2].startswith('/blog/'):
        author_names = [clean(visible_text(node), 100) for node in scope.select(
            '.devsite-article-body > p > .wd-authors > .wd-author > div > span:first-child')
            if belongs_to_scope(node, scope)]
        visible_authors = ', '.join(dict.fromkeys(filter(None, author_names))) or visible_authors
    if requested and requested[1] == 'zed.dev' and requested[2].startswith('/blog/'):
        for header in soup.select('main header:has(h1)'):
            if not editorial(header) or not heading_matches(heading_text(header.h1), title):
                continue
            authors = []
            for link in header.select('.flex.flex-wrap > a[href]:has(img[alt])'):
                label = link.select_one('p.text-sm')
                name = clean(visible_text(label), 100) if label and editorial(label) else ''
                if name and any(clean(img['alt'], 100) == name for img in link.select('img[alt]')):
                    authors.append(name)
            authors = list(dict.fromkeys(authors))
            if len(authors) > 1:
                visible_authors = ', '.join(authors)
            break
    if requested and requested[1] in GUARDIAN_HOSTS:
        credit = scope.select_one('address[data-component="meta-byline"][data-gu-name="byline"]')
        if credit and credit.find_parent('article') is scope:
            # The publisher puts its article byline inside the metadata aside.
            visible_credit = ' '.join(str(text) for text in credit.strings
                                      if not any(explicitly_hidden(node) for node in text.parents))
            visible_authors = guardian_author_label(clean(visible_credit)) or visible_authors
    if (requested and requested[1] in {'theconversation.com', 'www.theconversation.com'}
            and scope.name == 'article' and scope.get('id') == 'article'):
        authors = [clean(node.get_text()) for node in scope.select(
            'aside.content-sidebar section.content-authors .content-authors-synopsis > '
            'button.content-authors-toggle > span.nobr')
            if not any(explicitly_hidden(parent) for parent in (node, *node.parents))]
        # The collapsed byline can show just the first author.
        listed = [clean(node.get_text()) for node in scope.select(
            'aside.content-sidebar section.content-authors #article-authors-list '
            'li.vcard[itemprop~="author"] > a[rel~="author"] > .author-name')
            if not any(explicitly_hidden(parent) for parent in (node, *node.parents))]
        if listed and set(filter(None, authors)).issubset(listed):
            authors = listed
        visible_authors = ', '.join(dict.fromkeys(filter(None, authors))) or visible_authors
    if requested and requested[1] == 'projects.propublica.org' and scope.name == 'article':
        credit = scope.select_one(':scope > header.opener .opener__text > .opener__meta > p.opener__byline')
        if credit and editorial(credit) and clean(visible_text(credit)).casefold().startswith('by '):
            authors = []
            for link in credit.select(':scope > a[href]'):
                profile = url_identity(link['href'], url)
                if profile and profile[1] == 'www.propublica.org' and profile[2].startswith('/people/'):
                    authors.append(clean(visible_text(link)))
            visible_authors = ', '.join(dict.fromkeys(filter(None, authors))) or visible_authors
    if requested and requested[1] in {'hakaimagazine.com', 'www.hakaimagazine.com'}:
        writers = [clean(visible_text(link)) for link in scope.select(
            'header > .singlebyline > a[id="author_link_top"][href*="/profiles/"]')
            if belongs_to_scope(link, scope)]
        visible_authors = ', '.join(dict.fromkeys(filter(None, writers))) or visible_authors
    if requested and requested[1] in STRONG_TOWNS_HOSTS and requested[2].startswith('/journal/'):
        for headline in soup.select('.thought-leadership_wrap > section .mast-col > .heading-component > h1, '
                                    '.action-content_wrap > section.cc-action-content .mast-col > .heading-component > h1'):
            if not editorial(headline) or not heading_matches(heading_text(headline), title):
                continue
            writers = [clean(visible_text(node), 100) for node in headline.parent.parent.select(
                ':scope > .w-dyn-list > .w-dyn-items > .w-dyn-item .mast-paragraph > div')
                if editorial(node)]
            visible_authors = ', '.join(dict.fromkeys(filter(None, writers))) or visible_authors
            break
    author = diary_author or visible_authors or byline_authors or names(article.get('author')) or meta('author', 'parsely-author', 'citation_author') or byline_name
    if abseil_tip and heading is not None:
        _, credited = abseil_tip_byline(heading)
        author = clean(credited) or author
    if react_post:
        _, react_author = react_blog_credit(soup, title)
        author = react_author or author
    host = urlparse(url).hostname
    if (not author and requested and host == 'www.bicycleretailer.com'
            and url_identity(scope.get('about'), url) == requested):
        credit = soup.select_one('#block-views-author-block .view-author .authname > a')
        if credit and editorial(credit):
            author = clean(visible_text(credit))
    if host in {'universalhub.com', 'www.universalhub.com'}:
        _, writer = universal_hub_writer(scope, url)
        if not writer and not author and 'node-story' in scope.get('class', []):
            link = scope.select_one(':scope > .content > .submitted-by > a.username[href^="/users/"]')
            if link and editorial(link):
                name = clean(visible_text(link))
                if name and clean(visible_text(link.parent)).startswith(f'By {name} on '):
                    writer = name
        author = writer or author
    if host == 'freebsdfoundation.org':
        author = freebsd_report_writer(scope, url, title) or author
    if (not author and requested and host in {'publicdomainreview.org', 'www.publicdomainreview.org'}
            and requested[2].startswith('/collection/')):
        credit = scope.select_one('.collection-view > .collection-byline > .attribution:has(> a[href])')
        if credit and editorial(credit):
            link = credit.find('a', recursive=False)
            profile = url_identity(link.get('href'), url)
            name = clean(visible_text(link))
            if (profile and profile[:2] == requested[:2] and profile[2].startswith('/contributor/')
                    and clean(visible_text(credit)) == f'Text by {name}'):
                author = name
    if host in OPEN_CULTURE_HOSTS and author.casefold() in {'', 'oc', 'open culture'}:
        section = scope.select_one('.recent_post > .colorcontrast > .entry')
        if section and belongs_to_scope(section, scope):
            author = open_culture_writer(section, url) or author
    if not author and scope.name == 'article' and host == 'pluralistic.net':
        credit = scope.select_one(':scope > footer.entry-footer .byline .author.vcard a[href*="/author/"]')
        if credit and not any(explicitly_hidden(node) for node in (credit, *credit.parents)):
            author = clean(credit.get_text(), 100)
    if not author and pypi_post:
        profiles = soup.select('.md-sidebar--post .md-post__authors .md-profile__description > strong > a[href]')
        names_in_sidebar = []
        for link in profiles:
            name = clean(' '.join(str(t) for t in link.strings
                                  if not any(explicitly_hidden(node) for node in t.parents)))
            if name and name not in names_in_sidebar:
                names_in_sidebar.append(name)
        author = ', '.join(names_in_sidebar)
    if not author and scope.name == 'article' and host == 'blog.openstreetmap.org':
        # The selected article's own footer carries the WordPress author credit.
        authors = []
        for link in scope.select(':scope > footer.entry-meta .by-author .vcard a[rel~="author"]'):
            if any(explicitly_hidden(node) for node in (link, *link.parents)):
                continue
            name = clean(' '.join(str(t) for t in link.strings
                                  if not any(explicitly_hidden(p) for p in t.parents)))
            if name and name not in authors:
                authors.append(name)
        author = ', '.join(authors)
    if not author and scope.name == 'article' and host in {'www.w3.org', 'w3.org'}:
        for label in scope.select(':scope > section.meta dl > dt'):
            if visible_text(label).strip().casefold().rstrip(':') != 'by':
                continue
            value = label.find_next_sibling()
            if value and value.name == 'dd' and editorial(value):
                authors = [clean(visible_text(li)) for li in value.select(':scope > ul > li') if editorial(li)]
                author = ', '.join(filter(None, authors))
                if author:
                    break
    if not author or author.casefold() in {'nasa earth observatory', 'nasa science', 'nasa'}:
        author = earth_observatory_writer(scope, url) or author
    if author.casefold() in {'plos one editors', 'plos editors'}:
        author = next((name for node, name in opening_writer_credits(scope)
                       if belongs_to_scope(node, scope)), author)
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
    author = clean(author or meta('article:author', 'og:article:author'), 240)
    if host in {'calnewport.com', 'www.calnewport.com'} and publication == 'Cal Newport' and author == 'Study Hacks':
        author = ''
    if host in WYOFILE_HOSTS and (feature := wyofile_feature(soup, title)):
        credit = feature.select_one('header.entry-header .entry-meta > span.byline')
        if credit and editorial(credit):
            signed = clean(visible_text(credit), 241)
            if re.match(r'^by\s+\S', signed, re.I) and len(signed) <= 240:
                author = signed
    if author.startswith(('http://', 'https://')):
        author = ''
    author = re.sub(r'^by(?:\s*:\s*|\s+|$)', '', author, flags=re.I)
    if DATE.fullmatch(author) or (inkscape_news and author.casefold() == 'none'):
        author = ''
    body = article.get('articleBody')
    identified = (any(article_score(article)[:2]) or not article_urls(article) and
                  heading_matches(title, clean(article.get('headline'))))
    if not isinstance(body, str) or not identified or not public_structured_article(article, references, base_url=url):
        body = ''
    if (host == 'kottke.org' and requested == canonical_url and scope.name == 'div'
            and 'post' in scope.get('class', []) and title
            and not any(editorial(node) for node in scope.select('h1, h2, h3, .post-title'))):
        # Untitled link posts can use a clipped copy of their opening as SEO
        # metadata. Let the opening itself supply those words once.
        first = scope.find('p', recursive=False)
        clipped = re.sub(r'(?:\.{3}|…)\s*$', '', page_title).rstrip()
        if first and editorial(first) and clipped and clipped != page_title:
            opening = ' '.join(speech_text(first.get_text()).split())
            if opening.startswith(clipped) and opening.startswith(title.rstrip('.…')):
                title = ''
    return publication, title, author, body


def article_metadata(soup, url):
    return article_details(soup, url)[:3]
