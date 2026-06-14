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


def generate_filename(url: str, output_dir: str | None = None, mode: str = "active") -> str:
    """Generates standard filename YYYYMMDD-x-[mode]-username-id.md."""
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

    mode_part = f"-{mode}" if mode else ""
    filename = f"{stamp}-x{mode_part}-{username}-{post_id}.md"
    if output_dir:
        return os.path.join(output_dir, filename)
    else:
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router
        return output_router.route_output(url, filename, "x-text")


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


def import_from_clipboard(output_dir: str | None = None) -> int:
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
    filename = f"{stamp}-x-clipboard-{username}-{post_id}.md"
    if output_dir:
        filepath = os.path.join(output_dir, filename)
    else:
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router
        filepath = output_router.route_output(url, filename, "x-text")

    md_content = f"""---
source: huashu
type: x-content
extraction_mode: clipboard
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

    try:
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router
        output_router.register_output(
            output_path=filepath,
            source=url,
            explicit_type="x-text",
            title=f"X Clipboard {username}",
            status="success"
        )
    except Exception as e:
        print(f"[warn] Failed to register output in manifest/index: {e}")

    print(f"\n[ok] Clipboard X content saved to: {filepath}")
    print("\nDone.")

    try:
        subprocess.run(["open", "-R", filepath])
    except Exception:
        pass

    return 0


def extract_x(url: str, output_dir: str) -> int:
    """Uses AppleScript to extract the rendered content from the active Chrome tab."""
    return extract_x_active_chrome(url, output_dir)


def strip_query_and_normalize(u: str) -> str:
    if not u:
        return ""
    p = urllib.parse.urlparse(normalize_url(u))
    path = p.path.rstrip('/')
    path = path.replace("/status/", "/article/")
    return urllib.parse.urlunparse((p.scheme, p.netloc, path, '', '', ''))

def extract_x_id(url: str) -> str:
    parsed = urllib.parse.urlparse(normalize_url(url))
    path_parts = [p for p in parsed.path.split('/') if p]
    if len(path_parts) >= 3 and path_parts[1] in ("status", "article"):
        return path_parts[2]
    return ""

def match_x_urls(requested: str, active: str) -> bool:
    if not requested or not active:
        return False
        
    req_id = extract_x_id(requested)
    if req_id and req_id in active:
        return True
        
    req_norm = strip_query_and_normalize(requested)
    act_norm = strip_query_and_normalize(active)
    return req_norm == act_norm

def get_active_chrome_tab_info() -> tuple[str, str]:
    script = """
    if application "Google Chrome" is running then
        tell application "Google Chrome"
            if exists window 1 then
                set tabUrl to URL of active tab of window 1
                set tabTitle to title of active tab of window 1
                return tabUrl & "|||" & tabTitle
            end if
        end tell
    end if
    return ""
    """
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        out = res.stdout.strip()
        if "|||" in out:
            parts = out.split("|||", 1)
            return parts[0], parts[1]
        return out, ""
    except Exception:
        return "", ""

def extract_chrome_content() -> tuple[str, str, str]:
    script = """
    tell application "Google Chrome"
        set activeTab to active tab of window 1
        set tabTitle to title of activeTab

        try
            set js to "(() => {
                let text = '';
                let articles = document.querySelectorAll('article');
                if (articles.length > 0) {
                    for (let a of articles) {
                        text += a.innerText + '\\n\\n---\\n\\n';
                    }
                } else {
                    text = document.body.innerText;
                }
                return text;
            })();"
            set tabContent to execute activeTab javascript js
            return "SUCCESS|||" & tabTitle & "|||" & tabContent
        on error errMsg
            return "BLOCKED|||" & errMsg
        end try
    end tell
    """
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        out = res.stdout.strip()
        if out.startswith("SUCCESS|||"):
            parts = out.split("|||", 2)
            title = parts[1] if len(parts) > 1 else ""
            content = parts[2] if len(parts) > 2 else ""

            # Quality check for clipboard poison/test data
            if "This is a clipboard test" in content or "CLIPBOARD_POISON_SHOULD_NOT_APPEAR" in content:
                return "failed", title, "Clipboard poison detected in active Chrome extraction."

            if not content or len(content.split()) < 5:
                return "failed", title, content
            return "success", title, content
        elif out.startswith("BLOCKED|||"):
            return "blocked", "", out.split("|||", 1)[1]
        else:
            return "failed", "", out
    except Exception as e:
        return "failed", "", str(e)


def extract_x_active_chrome(url: str, output_dir: str) -> int:
    """Uses AppleScript to extract content from the already-open active Chrome tab."""
    url = normalize_url(url)

    active_url, active_title = get_active_chrome_tab_info()

    if not match_x_urls(url, active_url):
        print(f"Please open this X URL in your logged-in Chrome active tab, then run the same huashu command again:\n{url}")
        print(f"Requested URL: {url}")
        print(f"Active Chrome URL: {active_url}")
        print(f"Active Chrome title: {active_title}")
        return 0

    print("Extracting content from active Chrome tab...")
    status, title, content = extract_chrome_content()

    if status == "blocked":
        filepath = generate_filename(url, output_dir, "blocked")
        print("Enable Chrome > View > Developer > Allow JavaScript from Apple Events,")
        print("or use:")
        print("huashu -x-clipboard")

        diagnostic_content = f"""---
source: huashu
type: x-content
url: {url}
status: blocked
---

# X Extraction Blocked

Source: {url}

## Content

AppleScript JavaScript execution is blocked.

## Extraction Notes

Error: {content}
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(diagnostic_content)

        try:
            sys.path.append(os.path.join(REPO_ROOT, "scripts"))
            import output_router
            output_router.register_output(
                output_path=filepath,
                source=url,
                explicit_type="x-text",
                title=f"X Extract Blocked",
                status="blocked"
            )
        except Exception as e:
            print(f"[warn] Failed to register output in manifest/index: {e}")
        return 1

    if status == "failed":
        filepath = generate_filename(url, output_dir, "failed")
        print("Active Chrome extraction failed. Use huashu -x-clipboard if you want clipboard fallback.")

        diagnostic_content = f"""---
source: huashu
type: x-content
url: {url}
status: failed
---

# X Extraction Failed

Source: {url}

## Content

Quality check failed. Content extracted:
{content}
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(diagnostic_content)

        try:
            sys.path.append(os.path.join(REPO_ROOT, "scripts"))
            import output_router
            output_router.register_output(
                output_path=filepath,
                source=url,
                explicit_type="x-text",
                title=f"X Extract Failed",
                status="failed"
            )
        except Exception as e:
            print(f"[warn] Failed to register output in manifest/index: {e}")
        return 1

    # Success
    filepath = generate_filename(url, output_dir, "active")
    md_content = f"""---
source: huashu
type: x-content
extraction_mode: active-chrome
url: {url}
status: success
---

# {title}

Source: {url}

## Content

{content}

## Extraction Notes

Extracted via active Chrome tab using AppleScript.
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)

    try:
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router
        output_router.register_output(
            output_path=filepath,
            source=url,
            explicit_type="x-text",
            title=title,
            status="success"
        )
    except Exception as e:
        print(f"[warn] Failed to register output in manifest/index: {e}")

    print(f"\n[ok] Active Chrome X content saved to: {filepath}")

    try:
        subprocess.run(["open", "-R", filepath])
    except Exception:
        pass

    return 0


def extract_x_browser(url: str, output_dir: str | None = None) -> int:
    """Deprecated Playwright browser mode. Routes to active Chrome mode."""
    print("Warning: -x-browser mode is deprecated. Using active Chrome mode instead.")
    print(f"Please use plain `huashu \"{url}\"` with the X page already open in logged-in Chrome.")
    return extract_x_active_chrome(url, output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="X/Twitter post extractor for huashu")
    parser.add_argument("url", nargs="?", help="URL of the X/Twitter post")
    parser.add_argument("--clipboard", action="store_true", help="Import from clipboard instead")
    parser.add_argument("--browser", action="store_true", help="Use browser-assisted extraction")
    parser.add_argument("--output-dir", help="Output directory")

    args, _ = parser.parse_known_args()

    output_dir = args.output_dir
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    if args.clipboard:
        return import_from_clipboard(output_dir)

    if not args.url:
        sys.stderr.write("[error] Must specify a URL or --clipboard.\n")
        return 1

    if args.browser:
        return extract_x_browser(args.url, output_dir)

    return extract_x(args.url, output_dir)


if __name__ == "__main__":
    sys.exit(main())
