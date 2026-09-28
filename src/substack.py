"""Reads the user's Substack subscriptions through Substack's (unofficial) web API."""
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (substack-audio; personal use)"

# Fields that indicate a post already ships with audio (podcast upload or voiceover).
AUDIO_FIELDS = ("podcast_url", "podcast_upload_id", "podcast_duration", "voiceover_upload_id", "audio_items")


class Substack:
    def __init__(self, sid: str):
        self.cookie = f"substack.sid={sid}"

    def get(self, url, **params):
        # Follow redirects by hand so the cookie survives the hop to a custom domain.
        for _ in range(5):
            r = requests.get(url, params=params, headers={"Cookie": self.cookie, "User-Agent": UA},
                             allow_redirects=False, timeout=30)
            if r.is_redirect:
                url, params = urljoin(url, r.headers["Location"]), None
                continue
            if r.status_code == 429:
                time.sleep(5)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Too many redirects or retries for {url}")

    def publications(self):
        data = self.get("https://substack.com/api/v1/subscriptions")
        pubs = []
        for p in data.get("publications", []):
            base = f"https://{p['custom_domain']}" if p.get("custom_domain") else f"https://{p['subdomain']}.substack.com"
            pubs.append({"id": p["id"], "name": p.get("name") or p["subdomain"], "base": base})
        return pubs

    def recent_posts(self, pub, limit=12):
        return self.get(f"{pub['base']}/api/v1/archive", sort="new", limit=limit)

    def post_text(self, pub, slug):
        post = self.get(f"{pub['base']}/api/v1/posts/{slug}")
        html = post.get("body_html") or ""
        text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        return post, text


def has_audio(post) -> bool:
    return post.get("type") == "podcast" or any(post.get(f) for f in AUDIO_FIELDS)
