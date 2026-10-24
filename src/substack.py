"""Reads posts from Substack publications (their unofficial web API), plain RSS feeds and plain web pages."""
import json
import codecs
import hashlib
import os
import re
import time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

from pathlib import Path
import security

# Substack sits behind Cloudflare, which challenges non-browser TLS fingerprints;
# curl_cffi impersonates Chrome (including its user agent).
HEADERS = {"Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}

# Fields that indicate a post already ships with audio (podcast upload or voiceover).
AUDIO_FIELDS = ("podcast_url", "podcast_upload_id", "podcast_duration", "voiceover_upload_id", "audio_items")


def feed_date(value, *, rss=False):
    """Return a usable timestamp, or skip an entry whose date cannot be parsed."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        if rss:
            try:
                published = parsedate_to_datetime(value)
            except (ValueError, TypeError, OverflowError):
                published = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        else:
            published = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except (ValueError, TypeError, OverflowError):
        return None
    return published.replace(tzinfo=timezone.utc) if published.tzinfo is None else published


def decode_source(body, headers):
    """Decode bounded raw HTML/XML using a BOM, HTTP charset or page declaration."""
    from bs4 import UnicodeDammit

    content_type = next((value for key, value in headers.items() if key.lower() == 'content-type'), '')
    charset = re.search(r'\bcharset\s*=\s*[\"\']?([^\s;\"\']+)', content_type, re.I)
    encodings = []
    if charset:
        try:
            encodings.append(codecs.lookup(charset[1]).name)
        except LookupError:
            pass  # A bad header must not mask a valid page-level declaration.
    data = bytes(body)
    if data.startswith((codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE,
                        codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encodings = []  # Let the detector's BOM take precedence over headers.
    decoded = UnicodeDammit(data, known_definite_encodings=encodings, is_html=True)
    return decoded.unicode_markup if decoded.unicode_markup is not None else data.decode('utf-8', errors='replace')


class SourceDownloadError(RuntimeError):
    def __init__(self, message, status_code, *, headers=None, body=b""):
        super().__init__(message)
        self.status_code = status_code
        # Only fixed labels and numeric delays can leave the download worker.
        # Never retain response bodies, cookies, challenge tokens, or URLs.
        headers = {key.lower(): str(value) for key, value in (headers or {}).items()}
        server = headers.get("server", "").lower()
        server = next((name for name in ("vercel", "cloudflare", "cloudfront", "fastly", "nginx")
                       if name in server), "other" if server else "unknown")
        text = bytes(body[:128_000]).lower()
        protection = "none"
        html_page = ('text/html' in headers.get('content-type', '').lower() or
                     'application/xhtml+xml' in headers.get('content-type', '').lower() or
                     text.lstrip().startswith((b'<!doctype html', b'<html', b'<head', b'<title')))
        vercel_page = html_page and re.search(rb'<title\b[^>]*>\s*vercel security checkpoint\s*</title\s*>', text)
        cloudflare_page = (html_page and re.search(rb'<title\b[^>]*>\s*just a moment[^<]*</title\s*>', text) and
                           (b'/cdn-cgi/challenge-platform/' in text or b'_cf_chl_opt' in text))
        if (headers.get("x-vercel-mitigated", "").lower() == "challenge" or vercel_page or
                status_code >= 400 and b"vercel security checkpoint" in text):
            protection = "vercel_challenge"
        elif headers.get("cf-mitigated", "").lower() == "challenge" or cloudflare_page:
            protection = "cloudflare_challenge"
        self.protection = protection
        delay = headers.get("retry-after", "")
        delay = delay if re.fullmatch(r"[0-9]{1,6}", delay) else "present" if delay else "none"
        self.diagnostics = f"server={server} protection={protection} retry_after={delay}"


class Substack:
    def __init__(self, sid: str, *, request_timeout=30):
        sid = sid.strip().strip('"')
        if sid.startswith("substack.sid="):  # tolerate pasting the whole cookie pair
            sid = sid[len("substack.sid="):]
        self.download_bytes = 0
        self.request_timeout = request_timeout
        self.last_url = None
        self.cookie = f"substack.sid={sid}" if sid else None
        self.auth_hosts = {h.strip().lower() for h in os.environ.get("SUBSTACK_AUTH_HOSTS", "").split(",") if h.strip()}

    def auth_headers(self, url):
        parsed = urlparse(url)
        if (self.cookie and parsed.scheme == "https" and parsed.hostname in self.auth_hosts
                and parsed.port in (None, 443) and not parsed.username):
            return {"Cookie": self.cookie}
        return {}

    def get(self, url, raw=False, **params):
        from curl_cffi import CurlOpt, requests

        self.last_url = None  # Failed requests must not retain a previous destination.
        # Pin an authorized address: a second DNS lookup must not enable rebinding.
        for _ in range(5):
            host, port, address = security.public_destination(url)
            target = f"[{address}]" if ":" in address else address
            body = bytearray()
            exceeded = False

            def receive(data):
                nonlocal exceeded
                self.download_bytes += len(data)
                if (len(body) + len(data) > security.MAX_RESPONSE_BYTES
                        or self.download_bytes > security.MAX_DOWNLOAD_BYTES):
                    exceeded = True
                    return 0xFFFFFFFF  # CURL_WRITEFUNC_ERROR; 0 is ignored by older curl_cffi callbacks
                body.extend(data)
                return len(data)

            try:
                r = requests.get(
                    url, params=params,
                    headers={**HEADERS, "Accept-Encoding": "identity", **self.auth_headers(url)},
                    allow_redirects=False, timeout=self.request_timeout, impersonate="chrome",
                    accept_encoding="identity", content_callback=receive,
                    curl_options={CurlOpt.RESOLVE: [f"{host}:{port}:{target}".encode()],
                                  CurlOpt.PROXY: b"", CurlOpt.MAXFILESIZE_LARGE: security.MAX_RESPONSE_BYTES})
            except Exception as error:
                if exceeded or getattr(error, "code", None) == 63:  # CURLE_FILESIZE_EXCEEDED
                    raise security.BudgetExceeded("Source download budget exceeded") from None
                raise
            if exceeded:
                raise security.BudgetExceeded("Source download budget exceeded")
            if r.is_redirect:
                destination = urljoin(url, r.headers["Location"])
                if urlparse(url).scheme == "https" and urlparse(destination).scheme != "https":
                    raise ValueError("Source redirect cannot downgrade HTTPS")
                url, params = destination, None
                continue
            error = SourceDownloadError(f"Source returned HTTP {r.status_code}", r.status_code,
                                        headers=getattr(r, "headers", {}), body=body)
            if r.status_code >= 400 or error.protection != "none":
                # A browser challenge cannot be completed by repeating this request.
                if r.status_code == 429 and error.protection == "none":
                    time.sleep(5)
                    continue
                raise error
            # libcurl's write callback receives decoded bytes; no whole-response buffer is used.
            if raw:
                result = decode_source(body, getattr(r, "headers", {}))
            else:
                result = json.loads(body.decode(getattr(r, "encoding", None) or "utf-8", errors="replace"))
            self.last_url = url
            return result
        raise SourceDownloadError("Source exceeded redirect/retry limit", r.status_code,
                                  headers=getattr(r, "headers", {}), body=body)

    def publications(self):
        # An explicit list prevents silently importing an account's subscriptions.
        if os.environ.get("PUBLICATIONS", "").strip():
            return self.publications_from_text(os.environ["PUBLICATIONS"])
        return self.publications_from_file(os.environ.get("PUBLICATIONS_FILE") or "publications.txt")

    @staticmethod
    def publications_from_file(path):
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ValueError("No publication list: copy publications.example.txt to publications.txt or set PUBLICATIONS") from None
        return Substack.publications_from_text(text)

    @staticmethod
    def publications_from_text(text):
        pubs = []
        for number, line in enumerate(text.splitlines(), 1):
            # "<url> [display name] [| only: <title text>] [| full] [| rss] [| page: <article path>] [| any length]"
            main, *opts = [part.strip() for part in line.split("#")[0].split("|")]
            parts = main.split(maxsplit=1)
            if parts:
                url = parts[0].rstrip("/")
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
                    raise ValueError(f"Publication line {number}: expected an HTTP(S) URL without credentials")
                host = parsed.hostname
                unknown = [o for o in opts if o not in ("full", "summary", "rss", "any length")
                           and not o.startswith(("only:", "page:"))]
                if unknown or ("full" in opts and "summary" in opts):
                    raise ValueError(f"Publication line {number}: unknown or conflicting options")
                only = next((o.removeprefix("only:").strip() for o in opts if o.startswith("only:")), None)
                page = next((o.removeprefix("page:").strip() for o in opts if o.startswith("page:")), None)
                rss = not page and ("rss" in opts or url.endswith(("/feed", ".xml", "/rss")))
                pubs.append({"id": host, "name": parts[1].strip() if len(parts) > 1 else host, "base": url,
                             "only": only, "mode": "full" if "full" in opts else "summary" if "summary" in opts else None,
                             "rss": rss, "page": page,
                             "any_length": "any length" in opts})
        if not pubs:
            raise ValueError("Publication list is empty")
        return pubs

    def recent_posts(self, pub, limit=50):
        if pub.get("rss"):
            return self.rss_posts(pub, security.MAX_SOURCE_ENTRIES)
        if pub.get("page"):
            return self.page_posts(pub, 30)
        return self.get(f"{pub['base']}/api/v1/archive", sort="new", limit=limit)[:min(limit, security.MAX_SOURCE_ENTRIES)]

    def rss_posts(self, pub, limit):
        """Reads an RSS feed into the same shape as Substack's archive entries."""
        ns = {"content": "http://purl.org/rss/1.0/modules/content/", "dc": "http://purl.org/dc/elements/1.1/"}
        posts = []
        root = ET.fromstring(self.get(pub["base"], raw=True))
        if root.tag == "{http://www.w3.org/2005/Atom}feed":
            return self.atom_posts(pub, root, limit, base_url=self.last_url or pub['base'])
        for index, item in enumerate(root.iter("item")):
            if index >= min(limit or security.MAX_SOURCE_ENTRIES, security.MAX_SOURCE_ENTRIES):
                break
            link = item.findtext("link") or ""
            guid = item.findtext("guid") or link
            html = item.findtext("content:encoded", namespaces=ns) or item.findtext("description") or ""
            text = html_to_text(html)
            published = feed_date(item.findtext("pubDate") or item.findtext("dc:date", namespaces=ns), rss=True)
            if published is None:
                continue  # undated entries cannot be filtered reliably by lookback
            enclosure = item.find("enclosure")
            posts.append({
                "id": int(hashlib.sha1(guid.encode()).hexdigest()[:10], 16),
                "slug": urlparse(link).path.strip("/").split("/")[-1] or "post",
                "title": item.findtext("title") or "",
                "post_date": published.isoformat(),
                "podcast_url": enclosure.get("url") if enclosure is not None and enclosure.get("type", "").startswith("audio/") else None,
                "canonical_url": link,
                "audience": "everyone",
                "wordcount": len(text.split()),
                "body_html": html,
                "publishedBylines": [{"name": n} for n in [item.findtext("dc:creator", namespaces=ns)] if n],
            })
        return posts[:limit]

    @staticmethod
    def atom_posts(pub, root, limit, *, base_url=None):
        ns = {"a": "http://www.w3.org/2005/Atom"}
        xml_base = '{http://www.w3.org/XML/1998/namespace}base'
        root_base = urljoin(base_url or pub['base'], root.get(xml_base, ''))
        posts = []
        for index, entry in enumerate(root.findall("a:entry", ns)):
            if index >= min(limit or security.MAX_SOURCE_ENTRIES, security.MAX_SOURCE_ENTRIES):
                break
            published = feed_date(entry.findtext("a:published", namespaces=ns) or entry.findtext("a:updated", namespaces=ns))
            if published is None:
                continue
            links = entry.findall("a:link", ns)
            entry_base = urljoin(root_base, entry.get(xml_base, ''))
            def link_url(node):
                return urljoin(urljoin(entry_base, node.get(xml_base, '')), node.get('href', ''))
            link = next((link_url(e) for e in links if e.get('href') and e.get("rel", "alternate") == "alternate"), "")
            content = entry.find("a:content", ns)
            if content is None:
                content = entry.find("a:summary", ns)
            body = "" if content is None else (content.text or "") + "".join(ET.tostring(c, encoding="unicode") for c in content)
            guid = entry.findtext("a:id", namespaces=ns) or link
            posts.append({"id": int(hashlib.sha1(guid.encode()).hexdigest()[:10], 16),
                          "slug": urlparse(link).path.strip("/").split("/")[-1] or "post",
                          "title": entry.findtext("a:title", namespaces=ns) or "Untitled",
                          "post_date": published.isoformat(), "canonical_url": link, "audience": "everyone",
                          "wordcount": len(html_to_text(body).split()), "body_html": body,
                          "publishedBylines": [{"name": e.text or ""} for e in entry.findall("a:author/a:name", ns)],
                          "podcast_url": next((link_url(e) for e in links if e.get('href') and e.get("rel") == "enclosure" and e.get("type", "").startswith("audio/")), None)})
        return posts[:limit]

    def page_posts(self, pub, limit):
        """Reads a site with no feed: its listing page links to articles under pub["page"] (e.g. /stories/),
        and each article page carries its title, a "Month D, YYYY" date and a rich-text body (Webflow)."""
        from bs4 import BeautifulSoup

        listing = self.get(pub["base"], raw=True)
        links = []
        for path in re.findall(r'href="(%s[^"#?]+)"' % re.escape(pub["page"]), listing):
            if path not in links:
                links.append(path)
        posts, titles = [], set()
        for path in links[:limit]:
            url = urljoin(pub["base"], path)
            try:
                soup = BeautifulSoup(self.get(url, raw=True), "html.parser")
            except RuntimeError:
                print("An article page was unavailable; skipping it.")
                continue
            og = soup.find("meta", property="og:title")
            title = (og and og.get("content")) or (soup.title.string if soup.title else path)
            date = re.search(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b", soup.get_text(" "))
            body = soup.select_one(".w-richtext, article, main")
            title = title.strip()
            # Undated pages aren't articles; Webflow's duplicated drafts ("... Copy") repeat one that is.
            if not date or not body or title in titles or re.search(r"\bcopy$", title, re.I) or path.endswith("-copy"):
                continue
            titles.add(title)
            html = str(body)
            desc = soup.find("meta", attrs={"name": "description"})
            posts.append({
                "subtitle": (desc and desc.get("content")) or "",
                "id": int(hashlib.sha1(url.encode()).hexdigest()[:10], 16),
                "slug": path.strip("/").split("/")[-1] or "post",
                "title": title,
                "post_date": datetime.strptime(date.group(1), "%B %d, %Y").replace(hour=12, tzinfo=timezone.utc).isoformat(),
                "canonical_url": url,
                "audience": "everyone",
                "wordcount": len(html_to_text(html).split()),
                "body_html": html,
            })
        return sorted(posts, key=lambda p: p["post_date"], reverse=True)

    def post_text(self, pub, post):
        if pub.get("rss") or pub.get("page"):
            return post, html_to_text(post["body_html"])
        full = self.get(f"{pub['base']}/api/v1/posts/{post['slug']}")
        return full, html_to_text(full.get("body_html") or "")


def html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    # Drop Substack's subscribe/share widgets and embedded buttons; they aren't article text.
    for el in soup.select("script, style, nav, .subscription-widget-wrap, .button-wrapper, .captioned-button-wrap, .share-dialog"):
        el.decompose()
    # One line per block element, so link text stays inside its sentence.
    blocks = soup.find_all(["p", "h1", "h2", "h3", "h4", "li", "blockquote", "figcaption"])
    lines = [re.sub(r"\s+([,.;:!?)])", r"\1", b.get_text(" ", strip=True))
             for b in blocks if not b.find_parent(["li", "blockquote"])]
    return "\n".join(l for l in lines if l) or soup.get_text("\n", strip=True)


def has_audio(post) -> bool:
    """True only when there is audio the reader can actually play.

    Substack attaches a TTS voiceover entry to most posts, but on paywalled posts it has
    status "paywalled" and no audio_url, so for a non-paying reader there's no audio.
    """
    if post.get("type") == "podcast" or post.get("podcast_url") or post.get("podcast_upload_id"):
        return True
    return any(item.get("audio_url") for item in post.get("audio_items") or [])


