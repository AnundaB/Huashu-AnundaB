#!/usr/bin/env python3
"""
docs_crawl.py — Crawl documentation site under same prefix and convert pages to Markdown.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def generate_slug(url: str) -> str:
    """Generates a clean slug from URL netloc and path."""
    parsed = urllib.parse.urlparse(url)
    combined = (parsed.netloc + parsed.path).strip("/")
    slug = re.sub(r'[^a-zA-Z0-9]', '-', combined)
    slug = re.sub(r'-+', '-', slug).strip("-")
    if slug.startswith("www-"):
        slug = slug[4:]
    return slug[:60] or "docs"


def classify_url(url: str) -> tuple[bool, list[str]]:
    """
    Classifies if a URL belongs to a documentation site based on path, title,
    sidebar elements, and internal links.
    Returns: (is_docs, list_of_matched_signals)
    """
    signals = []

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, ["Invalid URL"]

    path_lower = parsed.path.lower()
    path_keywords = ["/docs/", "/documentation/", "/guide/", "/manual/", "/learn/", "/reference/"]
    if any(kw in path_lower for kw in path_keywords):
        signals.append("URL path contains docs/guide keywords")

    # Fetch start page raw HTML
    html = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (huashu-md-html/0.1)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
    except Exception as e:
        return False, [f"Failed to fetch start URL: {e}"]

    # Parse HTML using BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        return False, [f"Failed to parse HTML: {e}"]

    # Check for sidebar/nav elements or classes
    has_sidebar = False
    sidebar_el = soup.find(["aside", "nav"])
    if sidebar_el:
        has_sidebar = True
    else:
        for el in soup.find_all(True):
            cls = el.get("class", [])
            if isinstance(cls, list):
                cls_str = " ".join(cls).lower()
            else:
                cls_str = str(cls).lower()
            el_id = str(el.get("id", "")).lower()
            if any(kw in cls_str or kw in el_id for kw in ["sidebar", "navigation", "nav-list", "docs-menu", "aside-menu"]):
                has_sidebar = True
                break
    if has_sidebar:
        signals.append("Page has sidebar/nav elements or classes")

    # Check title suggestions
    title = soup.title.string.lower() if soup.title and soup.title.string else ""
    title_keywords = ["documentation", "docs", "user guide", "reference manual", "handbook", "tutorial"]
    if any(kw in title for kw in title_keywords):
        signals.append("Page title suggests documentation")

    # Count internal same-prefix links
    prefix = url
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        try:
            absolute_url = urllib.parse.urljoin(url, href)
            # Remove fragment/query
            url_parsed = urllib.parse.urlparse(absolute_url)
            clean_url = urllib.parse.urlunparse((url_parsed.scheme, url_parsed.netloc, url_parsed.path, "", "", ""))
            if clean_url.startswith(prefix) and clean_url != url:
                links.append(clean_url)
        except Exception:
            continue
    same_prefix_links = list(set(links))
    if len(same_prefix_links) >= 5:
        signals.append(f"Found {len(same_prefix_links)} internal links under prefix '{prefix}'")

    is_docs = len(signals) > 0
    return is_docs, signals


def write_combined_markdown(filepath: str, pages: list[dict]):
    """Generates a combined markdown file with Table of Contents."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Combined Documentation\n\n")
        f.write("## Table of Contents\n")
        for i, page in enumerate(pages):
            f.write(f"{i+1}. [{page['title']}](#{page['anchor']})\n")
        f.write("\n")

        for i, page in enumerate(pages):
            f.write(f"\n\n---\n\n## {i+1}. {page['title']}\n")
            f.write(f"Source: {page['url']}\n\n")

            try:
                with open(page["filepath"], "r", encoding="utf-8") as pf:
                    content = pf.read().strip()
                f.write(content)
            except Exception as e:
                f.write(f"[Error reading page content: {e}]")
            f.write("\n")


def write_manifest(filepath: str, rows: list[dict]):
    """Writes manifest.csv."""
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "output_md_path", "status", "error"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_failed_links(filepath: str, rows: list[dict]):
    """Writes failed_links.csv."""
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "error"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def crawl_docs(start_url: str, max_pages: int, delay: float, output_dir: str) -> int:
    """Performs docs crawl, conversions, and file writing."""
    try:
        url_parsed = urllib.parse.urlparse(start_url)
    except Exception as e:
        sys.stderr.write(f"[error] Invalid start URL: {start_url}\n")
        return 1

    allowed_netloc = url_parsed.netloc
    allowed_prefix = start_url

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = generate_slug(start_url)
    run_folder_name = f"{timestamp}-{slug}"
    run_dir = os.path.join(output_dir, run_folder_name)
    pages_dir = os.path.join(run_dir, "pages")

    os.makedirs(pages_dir, exist_ok=True)

    queue = [start_url]
    visited = set()
    successful_pages = []
    manifest_rows = []
    failed_links = []

    order = 1
    private_keywords = ["/login", "/signin", "/signup", "/logout", "/account", "/profile", "/private", "/register", "/auth"]

    print(f"Starting crawl of docs site. Allowed prefix: {allowed_prefix}")
    print(f"Max pages: {max_pages}, delay: {delay}s")
    print(f"Output folder: {run_dir}")

    while queue and len(visited) < max_pages:
        current_url = queue.pop(0)
        if current_url in visited:
            continue

        visited.add(current_url)
        print(f"[{len(visited)}/{max_pages}] Fetching: {current_url}")

        if len(visited) > 1:
            time.sleep(delay)

        html = ""
        fetch_error = None
        try:
            req = urllib.request.Request(current_url, headers={"User-Agent": "Mozilla/5.0 (huashu-md-html/0.1)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                html = raw.decode(charset, errors="replace")
        except Exception as e:
            fetch_error = str(e)
            print(f"  -> [warn] Failed to fetch: {e}")
            failed_links.append({"url": current_url, "error": fetch_error})
            manifest_rows.append({
                "url": current_url,
                "title": "",
                "output_md_path": "",
                "status": "failed_fetch",
                "error": fetch_error
            })
            continue

        soup = None
        title = ""
        try:
            soup = BeautifulSoup(html, "html.parser")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
        except Exception as e:
            print(f"  -> [warn] Failed to parse HTML: {e}")

        if not title and soup:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text().strip()
        if not title:
            title = current_url

        # Add internal links to queue
        if soup:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                try:
                    absolute_url = urllib.parse.urljoin(current_url, href)
                    url_parsed = urllib.parse.urlparse(absolute_url)
                    clean_url = urllib.parse.urlunparse((url_parsed.scheme, url_parsed.netloc, url_parsed.path, "", "", ""))

                    if url_parsed.netloc == allowed_netloc and clean_url.startswith(allowed_prefix):
                        is_private = any(kw in clean_url.lower() for kw in private_keywords)
                        if not is_private and clean_url not in visited and clean_url not in queue:
                            if len(queue) + len(visited) < max_pages * 2:
                                queue.append(clean_url)
                except Exception:
                    continue

        page_slug = generate_slug(current_url)
        if not page_slug or page_slug == slug:
            parsed_curr = urllib.parse.urlparse(current_url)
            page_slug = parsed_curr.path.strip("/").replace("/", "-")
            if not page_slug:
                page_slug = "index"

        page_filename = f"{order:03d}-{page_slug}.md"
        page_md_path = os.path.join(pages_dir, page_filename)

        # Pause before conversion fetch to be polite
        time.sleep(delay)

        # Execute html_to_md.py subprocess call
        python_exe = sys.executable
        html_to_md_script = os.path.join(REPO_ROOT, "scripts", "html_to_md.py")
        conv_res = subprocess.run(
            [python_exe, html_to_md_script, current_url, "-o", page_md_path, "--quiet"],
            capture_output=True, text=True
        )

        if conv_res.returncode == 0 and os.path.exists(page_md_path):
            status = "converted"
            error_msg = ""
            print(f"  -> Converted to pages/{page_filename}")

            anchor_title = re.sub(r'[^\w\s-]', '', title.lower())
            anchor = re.sub(r'[-\s]+', '-', anchor_title).strip("-")
            anchor = f"{order}-{anchor}"

            successful_pages.append({
                "url": current_url,
                "title": title,
                "filename": page_filename,
                "filepath": page_md_path,
                "anchor": anchor
            })
            order += 1
        else:
            status = "failed_conversion"
            error_msg = conv_res.stderr.strip() or "Unknown conversion error"
            print(f"  -> [error] Conversion failed: {error_msg}")
            failed_links.append({"url": current_url, "error": error_msg})
            if os.path.exists(page_md_path):
                try:
                    os.remove(page_md_path)
                except Exception:
                    pass

        manifest_rows.append({
            "url": current_url,
            "title": title,
            "output_md_path": f"pages/{page_filename}" if status == "converted" else "",
            "status": status,
            "error": error_msg
        })

    # Write output files
    combined_md_path = os.path.join(run_dir, "combined.md")
    write_combined_markdown(combined_md_path, successful_pages)

    manifest_csv_path = os.path.join(run_dir, "manifest.csv")
    write_manifest(manifest_csv_path, manifest_rows)

    failed_csv_path = os.path.join(run_dir, "failed_links.csv")
    write_failed_links(failed_csv_path, failed_links)

    print("\n" + "="*50)
    print("CRAWL SUMMARY")
    print("="*50)
    print(f"Total Discovered:    {len(visited)}")
    print(f"Successfully Converted: {len(successful_pages)}")
    print(f"Failed Links:        {len(failed_links)}")
    print(f"Run Output Folder:   {run_dir}")
    print(f"Combined File:       {combined_md_path}")
    print(f"Manifest:            {manifest_csv_path}")
    print("="*50 + "\n")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smart Documentation Crawler for huashu")
    parser.add_argument("start_url", help="Documentation site landing URL")
    parser.add_argument("--max-pages", type=int, default=100, help="Max pages to crawl")
    parser.add_argument("--delay", type=float, default=0.5, help="Polite delay in seconds between crawls")
    parser.add_argument("--output-dir", help="Base output directory")
    parser.add_argument("--force", action="store_true", help="Force crawl and bypass classification check")

    args = parser.parse_args()

    # Determine output directory
    output_dir = args.output_dir
    if not output_dir:
        output_dir = os.path.join(REPO_ROOT, "outputs", "auto")
    os.makedirs(output_dir, exist_ok=True)

    if not args.force:
        print(f"Running smart classification on URL: {args.start_url}")
        is_docs, signals = classify_url(args.start_url)
        print("Signals matched:")
        for sig in signals:
            print(f" - {sig}")
        if not is_docs:
            print("[warn] Smart classification did not detect this as a documentation site.")
            print("Use --force or route command via -docs to force a crawl.")
            return 1
        print("Smart classification verified documentation site. Starting crawl...")

    return crawl_docs(args.start_url, args.max_pages, args.delay, output_dir)


if __name__ == "__main__":
    sys.exit(main())
