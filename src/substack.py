"""Reads the user's Substack subscriptions through Substack's (unofficial) web API."""
import time
from urllib.parse import urljoin

from curl_cffi import requests
from bs4 import BeautifulSoup

# Substack sits behind Cloudflare, which challenges non-browser TLS fingerprints;
# curl_cffi impersonates Chrome (including its user agent).
HEADERS = {"Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}

# Fields that indicate a post already ships with audio (podcast upload or voiceover).
AUDIO_FIELDS = ("podcast_url", "podcast_upload_id", "podcast_duration", "voiceover_upload_id", "audio_items")


class Substack:
    def __init__(self, sid: str):
        sid = sid.strip().strip('"')
        if sid.startswith("substack.sid="):  # tolerate pasting the whole cookie pair
            sid = sid[len("substack.sid="):]
        self.cookie = f"substack.sid={sid}"

    def get(self, url, **params):
        # Follow redirects by hand so the cookie survives the hop to a custom domain.
        for _ in range(5):
            r = requests.get(url, params=params, headers={**HEADERS, "Cookie": self.cookie},
                             allow_redirects=False, timeout=30, impersonate="chrome")
            if r.is_redirect:
                url, params = urljoin(url, r.headers["Location"]), None
                continue
            if r.status_code == 429:
                time.sleep(5)
                continue
            if r.status_code >= 400:
                # Show enough of the response to tell a bad cookie from a bot-protection block.
                snippet = " ".join(r.text[:300].split())
                raise RuntimeError(f"{r.status_code} from {url} (server={r.headers.get('server')}, "
                                   f"cf-mitigated={r.headers.get('cf-mitigated')}): {snippet}")
            return r.json()
        raise RuntimeError(f"Too many redirects or retries for {url}")

    def publications(self, fallback_file="publications.txt"):
        try:
            data = self.get("https://substack.com/api/v1/subscriptions")
        except RuntimeError as e:
            # substack.com is behind a Cloudflare challenge for datacenter IPs (GitHub runners).
            print(f"Subscription list unavailable ({str(e)[:60]}...); using {fallback_file}")
            return self.publications_from_file(fallback_file)
        pubs = []
        for p in data.get("publications", []):
            base = f"https://{p['custom_domain']}" if p.get("custom_domain") else f"https://{p['subdomain']}.substack.com"
            pubs.append({"id": p["id"], "name": p.get("name") or p["subdomain"], "base": base})
        return pubs

    @staticmethod
    def publications_from_file(path):
        pubs = []
        for line in open(path):
            parts = line.split("#")[0].split(maxsplit=1)  # "<url> [display name]"
            if parts:
                url = parts[0].rstrip("/")
                host = url.split("//")[-1]
                pubs.append({"id": host, "name": parts[1].strip() if len(parts) > 1 else host, "base": url})
        return pubs

    def recent_posts(self, pub, limit=12):
        return self.get(f"{pub['base']}/api/v1/archive", sort="new", limit=limit)

    def post_text(self, pub, slug):
        post = self.get(f"{pub['base']}/api/v1/posts/{slug}")
        html = post.get("body_html") or ""
        text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        return post, text


def has_audio(post) -> bool:
    """True only when there is audio the reader can actually play.

    Substack attaches a TTS voiceover entry to most posts, but on paywalled posts it has
    status "paywalled" and no audio_url, so for a non-paying reader there's no audio.
    """
    if post.get("type") == "podcast" or post.get("podcast_url") or post.get("podcast_upload_id"):
        return True
    return any(item.get("audio_url") for item in post.get("audio_items") or [])
