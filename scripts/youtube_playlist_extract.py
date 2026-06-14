#!/usr/bin/env python3
import argparse
import datetime
import json
import os
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

def run_playlist_extraction(url: str, limit: int | None = None) -> int:
    playlist_id = extract_playlist_id(url)
    if not playlist_id:
        sys.stderr.write(f"[error] Could not extract playlist ID from URL: {url}\n")
        return 1

    auto_dir = os.getenv("HUASHU_AUTO_DIR", os.path.join(REPO_ROOT, "outputs", "auto"))
    output_dir = os.path.join(auto_dir, "youtube", "playlists", playlist_id)
    os.makedirs(output_dir, exist_ok=True)

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
    youtube_extract_script = os.path.join(REPO_ROOT, "scripts", "youtube_extract.py")
    
    # Write playlist_index.md
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    index_md_path = os.path.join(output_dir, "playlist_index.md")
    
    lines = [
        f"source_type: youtube_playlist",
        f"url: {url}",
        f"playlist_id: {playlist_id}",
        f"video_count: {len(videos)}",
        f"status: success",
        "---------------",
        f"# YouTube Playlist: {playlist_id}",
        "",
        "## Videos",
        ""
    ]

    for i, v in enumerate(videos, 1):
        v_id = v.get("id")
        v_title = v.get("title", f"Video {v_id}")
        v_url = f"https://www.youtube.com/watch?v={v_id}"
        
        print(f"[{i}/{len(videos)}] Extracting video {v_id} ({v_title})...")
        
        # We call the single-video extractor with the clean URL and a specific output directory
        ext_cmd = [python_exe, youtube_extract_script, v_url, "--output-dir", output_dir]
        ext_res = subprocess.run(ext_cmd)
        
        if ext_res.returncode == 0:
            success_count += 1
            status_mark = "✅"
        else:
            status_mark = "❌"
            
        lines.append(f"{i}. {status_mark} [{v_title}]({v_url})")

    with open(index_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n[ok] Playlist extraction complete: {success_count}/{len(videos)} videos successful.")
    print(f"Index saved to: {index_md_path}")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(description="Extract YouTube playlist videos to Markdown.")
    parser.add_argument("url", help="YouTube playlist URL to extract.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of videos to extract.")
    args = parser.parse_args()

    return run_playlist_extraction(args.url, args.limit)

if __name__ == "__main__":
    sys.exit(main())
