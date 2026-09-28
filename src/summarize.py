import os
import time

from google import genai
from google.genai import errors, types

# Free-tier Gemini; the "latest" alias tracks Google's current Flash model.
MODEL = os.environ.get("SUMMARY_MODEL", "gemini-flash-latest")
# ~150 spoken words per minute; leave headroom under the 20-minute cap.
MAX_WORDS = int(os.environ.get("MAX_SCRIPT_WORDS", "2700"))

SYSTEM = f"""You turn long newsletter articles into a script for a solo spoken-audio summary.
Write plain prose meant to be read aloud: no markdown, bullet points, headings, URLs, tables or emoji.
Spell out symbols and abbreviations the way a narrator would say them.
Open with one sentence naming the publication, author and title. Cover the key arguments, numbers and conclusions in the article's own order.
If the text is a paywalled preview that stops early, summarize only what is there and say briefly at the end that the rest is behind the paywall.
Hard limit: {MAX_WORDS} words. Shorter is fine when the article is shorter."""


def write_script(pub_name, author, title, text):
    client = genai.Client()  # reads GEMINI_API_KEY
    prompt = f"Publication: {pub_name}\nAuthor: {author}\nTitle: {title}\n\n<article>\n{text}\n</article>"
    config = types.GenerateContentConfig(system_instruction=SYSTEM, max_output_tokens=16000)
    for attempt in range(5):
        try:
            resp = client.models.generate_content(model=MODEL, contents=prompt, config=config)
            break
        except errors.APIError as e:
            # Free tier is rate-limited per minute; back off and retry.
            if e.code not in (429, 500, 503) or attempt == 4:
                raise
            time.sleep(30 * (attempt + 1))
    script = (resp.text or "").strip()
    if not script:
        raise RuntimeError(f"Gemini returned no text for {title!r}")
    words = script.split()
    if len(words) > MAX_WORDS:
        script = " ".join(words[:MAX_WORDS])
    return script
