from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import re
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1]
USER_DATA_DIR = Path(sys.argv[2])
PROFILE_NAME = sys.argv[3]

repo = Path.home() / "huashu-md-html"
outdir = repo / "outputs" / "auto"
outdir.mkdir(parents=True, exist_ok=True)

def slug(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    handle = parts[0] if parts else "x"
    content_id = next((p for p in parts if p.isdigit()), datetime.now().strftime("%H%M%S"))
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", f"{handle}-{content_id}")

def clean(text: str) -> str:
    lines = []
    seen = set()
    junk = {
        "Post", "Reply", "Share", "Like", "Repost", "Quote",
        "Log in", "Sign up", "For you", "Following", "Subscribe",
        "What’s happening", "Who to follow", "Relevant people"
    }
    for line in text.splitlines():
        line = line.strip()
        if not line or line in junk or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines).strip()

with sync_playwright() as p:
    print(f"Using cloned Chrome user data dir: {USER_DATA_DIR}")
    print(f"Using profile directory: {PROFILE_NAME}")

    context = p.chromium.launch_persistent_context(
        str(USER_DATA_DIR),
        channel="chrome",
        headless=False,
        viewport={"width": 1280, "height": 950},
        ignore_default_args=[
            "--password-store=basic",
            "--use-mock-keychain",
        ],
        args=[
            f"--profile-directory={PROFILE_NAME}",
            "--disable-blink-features=AutomationControlled",
        ],
        timeout=60000,
    )

    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    print("\nเปิด Chrome clone profile แล้ว")
    print("ถ้าเห็น X article จริงแล้ว กลับมา Terminal แล้วกด Enter")
    input("\nPress Enter to extract... ")

    page.wait_for_timeout(2500)

    data = page.evaluate("""() => {
        const chunks = [];

        for (const el of Array.from(document.querySelectorAll('article'))) {
            const t = el.innerText || '';
            if (t.trim().length > 30) chunks.push(t);
        }

        for (const el of Array.from(document.querySelectorAll('[data-testid="tweetText"]'))) {
            const t = el.innerText || '';
            if (t.trim().length > 30) chunks.push(t);
        }

        if (chunks.length === 0) {
            const main = document.querySelector('main');
            if (main && main.innerText.trim().length > 30) chunks.push(main.innerText);
        }

        return {
            title: document.title || 'X Content',
            url: location.href,
            text: chunks.join('\\n\\n---\\n\\n')
        };
    }""")

    title = data.get("title") or "X Content"
    final_url = data.get("url") or URL
    text = clean(data.get("text") or "")
    word_count = len(text.split())
    status = "success" if word_count >= 50 else "partial"

    out = outdir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-x-chrome-clone-{slug(URL)}.md"

    out.write_text(f"""---
source: huashu
type: x-content
extraction_mode: chrome-profile-clone-playwright
chrome_profile: {PROFILE_NAME}
url: {final_url}
status: {status}
word_count: {word_count}
---

# {title}

Source: {final_url}

## Content

{text if text else "[No meaningful X content extracted. Make sure the article is visible, then run again.]"}

## Extraction Notes

Extracted using a cloned Chrome profile through Playwright.

Cloned user data dir:
{USER_DATA_DIR}

Chrome profile:
{PROFILE_NAME}
""", encoding="utf-8")

    print(f"\nSaved Markdown: {out}")
    print(f"Status: {status}")
    print(f"Word count: {word_count}")

    context.close()
