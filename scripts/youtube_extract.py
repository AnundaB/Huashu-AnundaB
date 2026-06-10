#!/usr/bin/env python3
"""
youtube_extract.py — Specific extractor for YouTube captions and metadata.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def extract_video_id(url: str) -> str | None:
    """Extracts the 11-character YouTube video ID from a URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        if "youtu.be" in parsed.netloc.lower():
            # Path is /<video_id>
            path = parsed.path.strip("/")
            if path:
                return path.split("/")[0]
        else:
            # Check query params for 'v'
            query = urllib.parse.parse_qs(parsed.query)
            v_list = query.get("v")
            if v_list:
                return v_list[0]
            # Check path for /embed/ or /v/ or /shorts/
            path_parts = [p for p in parsed.path.split("/") if p]
            if len(path_parts) >= 2 and path_parts[0] in ("embed", "v", "shorts"):
                return path_parts[1]
            if len(path_parts) >= 1 and len(path_parts[0]) == 11:
                return path_parts[0]
    except Exception:
        pass
    return None


def clean_vtt(vtt_path: str, source: str) -> str:
    """Parses VTT file and removes captions headers, timestamps, and duplicates."""
    if not os.path.exists(vtt_path):
        return ""

    with open(vtt_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Split into blocks by double newlines or blank lines
    blocks = re.split(r"\n\s*\n", content)
    clean_lines: list[str] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")

        # Skip header/metadata blocks
        if any(lines[0].startswith(x) for x in ["WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION", "X-TIMESTAMP-MAP"]):
            continue

        # Find the timestamp line (must contain '-->')
        timestamp_idx = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                timestamp_idx = i
                break
        if timestamp_idx == -1:
            continue

        # The lines after the timestamp line are text lines
        text_lines = lines[timestamp_idx + 1:]
        cleaned_block_lines: list[str] = []
        for line in text_lines:
            # Remove in-line timestamp tags: <00:00:00.240>
            line = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", line)
            # Remove tag classes like <c> or </c>
            line = re.sub(r"<[^>]+>", "", line)
            # Decode HTML entities
            line = html.unescape(line)
            # Normalize whitespace
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                cleaned_block_lines.append(line)

        # Deduplicate based on source type
        if source == "auto":
            # For auto-captions, there's a rolling buffer.
            # We only take the last text line of the block.
            if cleaned_block_lines:
                last_line = cleaned_block_lines[-1]
                if not clean_lines or clean_lines[-1] != last_line:
                    clean_lines.append(last_line)
        else:
            # For manual captions, keep all lines from each block but avoid adjacent identical lines
            for line in cleaned_block_lines:
                if not clean_lines or clean_lines[-1] != line:
                    clean_lines.append(line)

    return "\n".join(clean_lines).strip()


def run_extraction(url: str, output_dir: str | None = None) -> int:
    """Executes YouTube caption extraction and saves metadata & transcript to markdown."""
    video_id = extract_video_id(url)
    if not video_id:
        sys.stderr.write(f"[error] Could not extract video ID from URL: {url}\n")
        return 1

    if not output_dir:
        output_dir = os.path.join(REPO_ROOT, "outputs", "auto")
    os.makedirs(output_dir, exist_ok=True)

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable or "python3"

    print(f"[youtube] Fetching metadata for video ID {video_id}...")

    # Step 1: Dump JSON
    cmd = [python_exe, "-m", "yt_dlp", "--dump-json", "--skip-download", url]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", check=True)
        metadata = json.loads(res.stdout)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"[error] Failed to fetch metadata using yt-dlp: {e.stderr}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"[error] Failed to parse yt-dlp metadata: {e}\n")
        return 1

    title = metadata.get("title") or f"YouTube video {video_id}"
    channel = metadata.get("channel") or metadata.get("uploader") or "unknown"
    duration = metadata.get("duration") or 0
    description = metadata.get("description") or ""

    subtitles = metadata.get("subtitles") or {}
    automatic_captions = metadata.get("automatic_captions") or {}

    # Build caption priority candidate list
    def get_candidates(subs_dict: dict, source_name: str) -> list[tuple[str, str]]:
        candidates = []
        for lang in ["th-orig", "th", "en"]:
            if lang in subs_dict:
                candidates.append((lang, source_name))
        for lang in sorted(subs_dict.keys()):
            if lang not in ["th-orig", "th", "en"]:
                candidates.append((lang, source_name))
        return candidates

    candidates = get_candidates(subtitles, "manual") + get_candidates(automatic_captions, "auto")

    if not candidates:
        sys.stderr.write("[error] No subtitles or automatic captions available for this video.\n")
        return 1

    # Temporary directory for downloading subtitles
    tmp_dir = os.path.join(output_dir, "tmp_yt")
    os.makedirs(tmp_dir, exist_ok=True)
    output_template = os.path.join(tmp_dir, "%(id)s")

    selected_lang = None
    selected_source = None
    vtt_file = None

    for lang, source in candidates:
        print(f"[youtube] Attempting to download {source} caption in '{lang}'...")
        # Clear existing vtt files for this video in tmp_dir to avoid confusion
        for f in os.listdir(tmp_dir):
            if f.startswith(f"{video_id}.") and f.endswith(".vtt"):
                try:
                    os.remove(os.path.join(tmp_dir, f))
                except Exception:
                    pass

        cmd_dl = [
            python_exe, "-m", "yt_dlp",
            "--skip-download",
            "--sub-format", "vtt",
            "--no-playlist",
            "--output", output_template
        ]
        if source == "manual":
            cmd_dl.extend(["--write-subs", "--sub-langs", lang])
        else:
            cmd_dl.extend(["--write-auto-subs", "--sub-langs", lang])
        cmd_dl.append(url)

        dl_res = subprocess.run(cmd_dl, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")

        # Verify if downloaded successfully
        expected_path = os.path.join(tmp_dir, f"{video_id}.{lang}.vtt")
        if os.path.exists(expected_path):
            vtt_file = expected_path
        else:
            # Check if any file matching ID and ending in .vtt was created
            for f in os.listdir(tmp_dir):
                if f.startswith(f"{video_id}.") and f.endswith(".vtt"):
                    vtt_file = os.path.join(tmp_dir, f)
                    break

        if vtt_file and os.path.exists(vtt_file):
            selected_lang = lang
            selected_source = source
            print(f"[youtube] Successfully downloaded {source} caption '{lang}'.")
            break
        else:
            print(f"[warn] Failed to download {source} caption '{lang}'. Trying next option...")

    if not vtt_file or not os.path.exists(vtt_file):
        sys.stderr.write("[error] Failed to download any caption candidate.\n")
        return 1

    # Clean VTT file to extract transcript text
    print("[youtube] Parsing and cleaning VTT transcript...")
    transcript = clean_vtt(vtt_file, selected_source)

    # Generate filename: YYYYMMDD-HHMMSS-youtube-<video_id>.md
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    md_filename = f"{stamp}-youtube-{video_id}.md"
    md_filepath = os.path.join(output_dir, md_filename)

    # Write output markdown content
    markdown_content = f"""source_type: youtube
url: {url}
video_id: {video_id}
title: {title}
channel: {channel}
duration: {duration}
caption_language: {selected_lang}
caption_source: {selected_source}
status: success
---------------

# {title}

## Metadata

- **Channel**: {channel}
- **Duration**: {duration} seconds
- **URL**: {url}
- **Video ID**: {video_id}
- **Caption Language**: {selected_lang}
- **Caption Source**: {selected_source}

## Description

{description}

## Transcript

{transcript}
"""

    with open(md_filepath, "w", encoding="utf-8") as out_f:
        out_f.write(markdown_content)

    print(f"\n[ok] YouTube extraction success: {url} \u2192 {md_filepath}")
    print(f"saved Markdown path: {md_filepath}")
    print(f"title: {title}")
    print(f"caption_language: {selected_lang}")
    print(f"caption_source: {selected_source}")
    print(f"status: success")

    # Cleanup downloaded VTT file
    try:
        if os.path.exists(vtt_file):
            os.remove(vtt_file)
    except Exception:
        pass

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract YouTube captions and metadata to Markdown.")
    parser.add_argument("url", help="YouTube URL to extract.")
    parser.add_argument("-o", "--output-dir", default=None, help="Output directory.")
    args = parser.parse_args()

    return run_extraction(args.url, args.output_dir)


if __name__ == "__main__":
    sys.exit(main())
