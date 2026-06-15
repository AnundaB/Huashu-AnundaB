#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def extract_playlist_id(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        list_ids = query.get("list")
        if list_ids:
            return list_ids[0]
    except Exception:
        pass
    return None

def slugify(text: str) -> str:
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)

def run_playlist_extraction(url: str, limit: int | None = None) -> int:
    playlist_id = extract_playlist_id(url)
    if not playlist_id:
        sys.stderr.write(f"[error] Could not extract playlist ID from URL: {url}\n")
        return 1

    auto_dir = os.getenv("HUASHU_AUTO_DIR", os.path.join(REPO_ROOT, "outputs", "auto"))
    playlist_dir = os.path.join(auto_dir, "youtube", "playlists", playlist_id)
    videos_dir = os.path.join(playlist_dir, "videos")
    os.makedirs(videos_dir, exist_ok=True)

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable or "python3"

    print(f"[youtube-playlist] Fetching metadata for playlist ID {playlist_id}...")

    cmd = [python_exe, "-m", "yt_dlp", "--dump-json", "--flat-playlist"]
    if limit:
        cmd.extend(["--playlist-end", str(limit)])
    cmd.append(url)

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", check=True, timeout=120)
    except subprocess.TimeoutExpired:
        sys.stderr.write("[error] yt-dlp timed out while fetching playlist metadata.\n")
        return 1
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"[error] Failed to fetch playlist using yt-dlp: {e.stderr}\n")
        return 1

    videos = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            v_data = json.loads(line)
            v_id = v_data.get("id")
            if v_id:
                videos.append(v_data)
        except json.JSONDecodeError:
            pass

    if not videos:
        print("[warn] No videos found in playlist.")
        return 1

    print(f"[youtube-playlist] Found {len(videos)} videos. Extracting individual transcripts...")

    success_count = 0
    fail_count = 0
    youtube_extract_script = os.path.join(REPO_ROOT, "scripts", "youtube_extract.py")

    index_md_path = os.path.join(playlist_dir, "playlist_index.md")
    combined_md_path = os.path.join(playlist_dir, "combined.md")

    index_lines = []
    combined_content = []

    for i, v in enumerate(videos, 1):
        v_id = v.get("id")
        v_title = v.get("title", f"Video {v_id}")
        v_url = f"https://www.youtube.com/watch?v={v_id}"
        v_slug = slugify(v_title)

        # 001-<video-id>-<slug>.md
        padded_i = f"{i:03d}"
        filename = f"{padded_i}-{v_id}-{v_slug}.md"
        output_file = os.path.join(videos_dir, filename)

        print(f"[{i}/{len(videos)}] Extracting video {v_id} ({v_title})...")

        ext_cmd = [python_exe, youtube_extract_script, v_url, "--output-file", output_file]
        ext_res = subprocess.run(ext_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")

        if ext_res.returncode == 0 and os.path.exists(output_file):
            success_count += 1
            status_mark = "✅"
            rel_path = f"videos/{filename}"
            index_lines.append(f"{padded_i}. {status_mark} [{v_title}]({rel_path}) - URL: {v_url}")

            # Read transcript content and append to combined.md
            with open(output_file, "r", encoding="utf-8") as f:
                content = f.read()
                # strip frontmatter
                if content.startswith("source_type:"):
                    parts = content.split("---------------", 1)
                    if len(parts) > 1:
                        content = parts[1].strip()
                combined_content.append(content)
        else:
            fail_count += 1
            status_mark = "❌"
            err_msg = ext_res.stderr.strip() or "Unknown error"
            err_msg = err_msg.replace('\n', ' ')
            index_lines.append(f"{padded_i}. {status_mark} {v_title} - URL: {v_url} - Error: {err_msg}")

    # Determine status
    if success_count == len(videos):
        status = "success"
    elif success_count == 0:
        status = "failed"
    else:
        status = "partial_success"

    # Write playlist_index.md
    frontmatter = [
        f"source_type: youtube_playlist",
        f"url: {url}",
        f"playlist_id: {playlist_id}",
        f"video_count: {len(videos)}",
        f"success_count: {success_count}",
        f"failed_count: {fail_count}",
        f"status: {status}",
        "---------------",
        f"# YouTube Playlist: {playlist_id}",
        "",
        "## Videos",
        ""
    ]

    with open(index_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(frontmatter + index_lines) + "\n")

    # Write combined.md
    if combined_content:
        with open(combined_md_path, "w", encoding="utf-8") as f:
            f.write(f"# YouTube Playlist Combined Transcript: {playlist_id}\n\n")
            f.write("\n\n---\n\n".join(combined_content))
            f.write("\n")

    print(f"\n[ok] Playlist extraction complete: {success_count}/{len(videos)} videos successful.")
    print(f"Index saved to: {index_md_path}")
    if combined_content:
        print(f"Combined saved to: {combined_md_path}")

    if status == "failed":
        return 1
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(description="Extract YouTube playlist videos to Markdown.")
    parser.add_argument("url", help="YouTube playlist URL to extract.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of videos to extract.")
    args = parser.parse_args()

    return run_playlist_extraction(args.url, args.limit)

if __name__ == "__main__":
    sys.exit(main())
