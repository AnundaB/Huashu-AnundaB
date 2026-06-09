#!/usr/bin/env python3
"""
x_extract.py — Specific extractor for X/Twitter links and articles with quality gating.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def normalize_url(url: str) -> str:
    """Normalizes x.com/twitter.com/mobile.twitter.com URLs."""
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc in ("twitter.com", "mobile.twitter.com", "x.com"):
        netloc = "x.com"
    return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def generate_filename(url: str, output_dir: str) -> str:
    """Generates standard filename YYYYMMDD-x-username-id.md."""
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    parsed = urllib.parse.urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]

    username = "x"
    post_id = "post"
    if len(path_parts) >= 3:
        username = path_parts[0]
        post_id = path_parts[2]
    elif len(path_parts) >= 1:
        username = path_parts[0]

    username = re.sub(r'[^a-zA-Z0-9_-]', '', username)
    post_id = re.sub(r'[^a-zA-Z0-9_-]', '', post_id)

    return os.path.join(output_dir, f"{stamp}-x-{username}-{post_id}.md")


def check_quality(html: str, soup: BeautifulSoup) -> tuple[str, str]:
    """
    Applies a quality gate. Checks if page is a generic web/app shell or if
    actual tweet/article content is present.
    """
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    title_lower = title.lower()

    # Generic titles indicative of an empty shell
    if title_lower in ("", "x", "twitter", "x (formerly twitter)", "unsupported browser", "checking your browser"):
        return "blocked", "Page title is generic/unsupported app shell"

    # Search for actual tweet text container markers
    if 'data-testid="tweetText"' not in html and 'class="tweet-text"' not in html:
        # Check if text length is small
        text = soup.get_text()
        words = text.split()
        if len(words) < 50:
            return "blocked", "No tweet or article content found in static HTML"

    return "success", "Quality checks passed"


def import_from_clipboard(output_dir: str) -> int:
    """Reads content from clipboard, cleans/formats it, and saves it to outputs/auto/."""
    res = subprocess.run(["pbpaste"], capture_output=True, text=True)
    text = res.stdout.strip()

    if not text:
        sys.stderr.write("[error] Clipboard is empty. Copy the X content first.\n")
        return 1

    lines = [line.strip() for line in text.split("\n")]
    first_line = lines[0] if lines else ""

    url = "clipboard"
    username = "manual"
    post_id = "clipboard"

    if first_line.startswith(("http://", "https://")) and ("x.com" in first_line or "twitter.com" in first_line):
        url = first_line
        parsed = urllib.parse.urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 3:
            username = path_parts[0]
            post_id = path_parts[2]
        content_text = "\n".join(lines[1:]).strip()
    else:
        content_text = text

    stamp = datetime.datetime.now().strftime("%Y%m%d")
    filename = f"{stamp}-x-{username}-{post_id}.md"
    filepath = os.path.join(output_dir, filename)

    md_content = f"""---
source: huashu
type: x-content
url: {url}
status: success
---

# X Content from Clipboard

Source: {url}

## Content

{content_text}

## Extraction Notes

Manually imported from clipboard.
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\n[ok] Clipboard X content saved to: {filepath}")
    print("\nDone.")

    try:
        subprocess.run(["open", "-R", filepath])
    except Exception:
        pass

    return 0


def extract_x(url: str, output_dir: str) -> int:
    """Attempts public extraction. Writes diagnostic fallback MD if blocked."""
    url = normalize_url(url)
    filepath = generate_filename(url, output_dir)

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    html = ""
    fetch_err = None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
    except Exception as e:
        fetch_err = str(e)

    soup = None
    if html:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            pass

    # Check Quality
    status = "failed"
    note = "Failed to fetch page"
    if fetch_err:
        note = f"Fetch exception: {fetch_err}"
    elif soup:
        status, note = check_quality(html, soup)

    if status == "success":
        # Extract title and description
        title = soup.title.string.strip() if soup.title and soup.title.string else "X Post"
        desc = ""
        meta_desc = soup.find("meta", property="og:description") or soup.find("meta", name="description")
        if meta_desc:
            desc = meta_desc.get("content", "").strip()

        md_content = f"""---
source: huashu
type: x-content
url: {url}
status: success
---

# {title}

Source: {url}

## Content

{desc or "Public static content extracted."}

## Extraction Notes

Extracted via public static tags.
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"\n[ok] Extracted X content to: {filepath}")
        return 0
    else:
        # Blocked/Failed fallback: save diagnostic MD and print error
        sys.stderr.write("X content could not be extracted publicly. Try browser/manual clipboard fallback.\n")

        # Diagnostic Markdown file creation
        diagnostic_content = f"""---
source: huashu
type: x-content
url: {url}
status: blocked
---

# X Extraction Blocked

Source: {url}

## Content

X content could not be extracted publicly. Try browser/manual clipboard fallback.

## Extraction Notes

Extraction failed: {note}
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(diagnostic_content)

        # Print diagnostic path to stdout for user visibility
        print(f"Saved diagnostic state to: {filepath}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="X/Twitter post extractor for huashu")
    parser.add_argument("url", nargs="?", help="URL of the X/Twitter post")
    parser.add_argument("--clipboard", action="store_true", help="Import from clipboard instead")
    parser.add_argument("--output-dir", help="Output directory")

    args, _ = parser.parse_known_args()

    output_dir = args.output_dir
    if not output_dir:
        output_dir = os.path.join(REPO_ROOT, "outputs", "auto")
    os.makedirs(output_dir, exist_ok=True)

    if args.clipboard:
        return import_from_clipboard(output_dir)

    if not args.url:
        sys.stderr.write("[error] Must specify a URL or --clipboard.\n")
        return 1

    return extract_x(args.url, output_dir)


if __name__ == "__main__":
    sys.exit(main())
