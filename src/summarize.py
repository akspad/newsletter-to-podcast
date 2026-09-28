import os

import anthropic

MODEL = os.environ.get("SUMMARY_MODEL", "claude-sonnet-5")
# ~150 spoken words per minute; leave headroom under the 20-minute cap.
MAX_WORDS = int(os.environ.get("MAX_SCRIPT_WORDS", "2700"))

SYSTEM = f"""You turn long newsletter articles into a script for a solo spoken-audio summary.
Write plain prose meant to be read aloud: no markdown, bullet points, headings, URLs, tables or emoji.
Spell out symbols and abbreviations the way a narrator would say them.
Open with one sentence naming the publication, author and title. Cover the key arguments, numbers and conclusions in the article's own order.
If the text is a paywalled preview that stops early, summarize only what is there and say briefly at the end that the rest is behind the paywall.
Hard limit: {MAX_WORDS} words. Shorter is fine when the article is shorter."""


def write_script(pub_name, author, title, text):
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Publication: {pub_name}\nAuthor: {author}\nTitle: {title}\n\n<article>\n{text}\n</article>"}],
    )
    script = "".join(b.text for b in msg.content if b.type == "text").strip()
    words = script.split()
    if len(words) > MAX_WORDS:
        script = " ".join(words[:MAX_WORDS])
    return script
