import os
import time

from google import genai
from google.genai import errors, types

# Free-tier Gemini; "latest" aliases track Google's current models. The free tier
# sometimes returns 503 "high demand", so fall back to a lighter model before giving up.
MODELS = [os.environ.get("SUMMARY_MODEL", "gemini-flash-latest"), "gemini-flash-lite-latest"]
# ~150 spoken words per minute; leave headroom under the 5-minute cap.
MAX_WORDS = int(os.environ.get("MAX_SCRIPT_WORDS", "700"))

SYSTEM = f"""You turn long newsletter articles into a script for a solo spoken-audio summary.
Write plain prose meant to be read aloud: no markdown, bullet points, headings, URLs, tables or emoji.
Spell out symbols and abbreviations the way a narrator would say them.
Open with one sentence naming the publication, author and title. Cover the most important arguments, numbers and conclusions in the article's own order; be selective, since the whole summary must fit in about five minutes.
If the text is a paywalled preview that stops early, summarize only what is there and say briefly at the end that the rest is behind the paywall.
Hard limit: {MAX_WORDS} words. Shorter is fine when the article is shorter."""


def write_script(pub_name, author, title, text):
    client = genai.Client()  # reads GEMINI_API_KEY
    prompt = f"Publication: {pub_name}\nAuthor: {author}\nTitle: {title}\n\n<article>\n{text}\n</article>"
    config = types.GenerateContentConfig(system_instruction=SYSTEM, max_output_tokens=16000)
    resp = None
    for model in MODELS:
        for attempt in range(3):
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=config)
                break
            except errors.APIError as e:
                if e.code not in (429, 500, 503):
                    raise
                print(f"  Gemini {model} {e.code}, attempt {attempt + 1}")
                time.sleep(20 * (attempt + 1))
        if resp is not None:
            break
    if resp is None:
        raise RuntimeError("Gemini unavailable on all models")
    script = (resp.text or "").strip()
    if not script:
        raise RuntimeError(f"Gemini returned no text for {title!r}")
    words = script.split()
    if len(words) > MAX_WORDS:
        script = " ".join(words[:MAX_WORDS])
    return script
