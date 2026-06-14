#!/usr/bin/env python3
"""
x_video_download.py — X/Twitter video downloader and transcriber for local archival.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def extract_status_id(url: str) -> str | None:
    """Extracts the status ID from an X/Twitter URL."""
    match = re.search(r"/status/(\d+)", url)
    if match:
        return match.group(1)
    return None


def write_markdown(
    url: str,
    status_id: str,
    author: str,
    title: str,
    duration: str,
    work_dir: str,
    audio_file: str,
    transcript_source: str,
    transcript_engine: str,
    status: str,
    description: str,
    transcript: str,
    notes_list: list[str],
    md_filepath: str,
    metadata_filepath: str
):
    """Writes or updates the final output markdown files (both user-facing and work_dir cache)."""
    notes_section = "\n".join([f"- {note}" for note in notes_list]) if notes_list else "- None"
    clean_title = " ".join(title.split()) if title else f"X Video: {status_id}"

    markdown_content = f"""source_type: x_video
url: {url}
status_id: {status_id}
author: {author}
title: {clean_title}
duration: {duration}
work_dir: {work_dir}
audio_file: {audio_file}
transcript_source: {transcript_source}
transcript_engine: {transcript_engine}
status: {status}
------------------------------------

# X Video: {clean_title}

## Metadata

- **Uploader/Account**: {author}
- **Duration**: {duration} seconds
- **URL**: {url}
- **Status ID**: {status_id}
- **Work Directory**: {work_dir}
- **Audio File**: {audio_file}
- **Transcript Source**: {transcript_source}
- **Transcript Engine**: {transcript_engine}
- **Status**: {status}

## Post Text

{description}

## Transcript

{transcript if transcript else "Transcript unavailable."}

## Notes

{notes_section}
"""

    with open(md_filepath, "w", encoding="utf-8") as out_f:
        out_f.write(markdown_content)
    with open(metadata_filepath, "w", encoding="utf-8") as mf:
        mf.write(markdown_content)

    try:
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router
        output_router.register_output(
            output_path=md_filepath,
            source=url,
            explicit_type="x-video",
            title=clean_title,
            status=status
        )
    except Exception as e:
        print(f"[warn] Failed to register output in manifest/index: {e}")


def run_download(url: str, output_dir: str | None = None) -> int:
    """Downloads X video metadata and audio, then transcribes locally."""
    status_id = extract_status_id(url)
    if not status_id:
        sys.stderr.write(f"[error] Could not extract status ID from URL: {url}\n")
        return 1

    if not output_dir:
        output_dir = os.path.join(REPO_ROOT, "outputs", "media", "x")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir_name = f"{stamp}-x-{status_id}"
    work_dir = os.path.join(output_dir, out_dir_name)
    os.makedirs(work_dir, exist_ok=True)

    filename = f"{stamp}-x-video-{status_id}.md"
    sys.path.append(os.path.join(REPO_ROOT, "scripts"))
    import output_router
    md_filepath = output_router.route_output(url, filename, "x-video")
    metadata_filepath = os.path.join(work_dir, "metadata.md")

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable or "python3"

    print(f"[x_video] Fetching metadata for status ID {status_id}...")

    # Step 1: Dump JSON
    cmd_meta = [python_exe, "-m", "yt_dlp", "--skip-download", "--dump-json", url]
    metadata = {}
    try:
        res_meta = subprocess.run(cmd_meta, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=60)
        if res_meta.returncode == 0:
            metadata = json.loads(res_meta.stdout)
        else:
            sys.stderr.write(f"[error] yt-dlp metadata failed: {res_meta.stderr}\n")
            return 1
    except subprocess.TimeoutExpired:
        sys.stderr.write("[error] yt-dlp metadata command timed out after 60 seconds.\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"[error] Failed to fetch metadata using yt-dlp: {e}\n")
        return 1

    title = metadata.get("title") or metadata.get("description") or f"X Video {status_id}"
    author = metadata.get("uploader") or metadata.get("uploader_id") or metadata.get("channel") or "unknown"
    duration = metadata.get("duration") or "N/A"
    description = metadata.get("description") or ""

    # Step 2: Write initial Markdown file early
    print("[x_video] Writing initial metadata-only Markdown files...")
    write_markdown(
        url=url,
        status_id=status_id,
        author=author,
        title=title,
        duration=str(duration),
        work_dir=work_dir,
        audio_file="none",
        transcript_source="none",
        transcript_engine="none",
        status="metadata_only",
        description=description,
        transcript="",
        notes_list=["Transcript not started yet."],
        md_filepath=md_filepath,
        metadata_filepath=metadata_filepath
    )

    # Print first-step details to terminal
    print(f"saved Markdown path: {md_filepath}")
    print(f"saved directory: {work_dir}")
    print(f"saved video path: none")
    print(f"metadata path: {metadata_filepath}")
    print(f"status: metadata_only")

    # Step 3: Download Audio
    out_template = os.path.join(work_dir, "audio.%(ext)s")
    cmd_dl = [
        python_exe, "-m", "yt_dlp",
        "-f", "ba[abr<=128]/ba/bestaudio/best[height<=360]",
        "--no-playlist",
        "--write-info-json",
        "--socket-timeout", "30",
        "--retries", "3",
        "--fragment-retries", "3",
        "--retry-sleep", "2",
        "--output", out_template,
        url
    ]

    print(f"[x_video] Downloading audio for status ID {status_id}...")
    try:
        res_dl = subprocess.run(cmd_dl, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=180)
        if res_dl.returncode != 0:
            sys.stderr.write(f"[warn] yt-dlp audio download failed: {res_dl.stderr}\n")
            write_markdown(
                url=url, status_id=status_id, author=author, title=title, duration=str(duration),
                work_dir=work_dir, audio_file="none", transcript_source="none", transcript_engine="none",
                status="metadata_only", description=description, transcript="",
                notes_list=[f"Transcript unavailable: Audio download failed (exit {res_dl.returncode})."],
                md_filepath=md_filepath, metadata_filepath=metadata_filepath
            )
            return 0
    except subprocess.TimeoutExpired:
        sys.stderr.write("[error] yt-dlp audio download timed out after 180 seconds.\n")
        write_markdown(
            url=url, status_id=status_id, author=author, title=title, duration=str(duration),
            work_dir=work_dir, audio_file="none", transcript_source="none", transcript_engine="none",
            status="metadata_only", description=description, transcript="",
            notes_list=["Transcript unavailable: Audio download timed out."],
            md_filepath=md_filepath, metadata_filepath=metadata_filepath
        )
        return 0
    except Exception as e:
        sys.stderr.write(f"[error] Failed to download audio: {e}\n")
        write_markdown(
            url=url, status_id=status_id, author=author, title=title, duration=str(duration),
            work_dir=work_dir, audio_file="none", transcript_source="none", transcript_engine="none",
            status="metadata_only", description=description, transcript="",
            notes_list=[f"Transcript unavailable: Audio download exception ({e})."],
            md_filepath=md_filepath, metadata_filepath=metadata_filepath
        )
        return 0

    # Locate and rename info JSON
    info_json_path = os.path.join(work_dir, "info.json")
    found_info_json = None
    for f in os.listdir(work_dir):
        if f.endswith(".info.json"):
            found_info_json = os.path.join(work_dir, f)
            break
    if found_info_json and found_info_json != info_json_path:
        if os.path.exists(info_json_path):
            os.remove(info_json_path)
        os.rename(found_info_json, info_json_path)

    # Locate raw downloaded audio file
    raw_audio_path = None
    for f in os.listdir(work_dir):
        ext = os.path.splitext(f)[1].lower()
        if ext in (".m4a", ".mp3", ".webm", ".aac", ".wav", ".opus", ".ogg", ".mp4", ".mkv") and not f.endswith(".info.json"):
            raw_audio_path = os.path.join(work_dir, f)
            break

    if not raw_audio_path or not os.path.exists(raw_audio_path):
        write_markdown(
            url=url, status_id=status_id, author=author, title=title, duration=str(duration),
            work_dir=work_dir, audio_file="none", transcript_source="none", transcript_engine="none",
            status="metadata_only", description=description, transcript="",
            notes_list=["Transcript unavailable: Downloaded raw audio file could not be found."],
            md_filepath=md_filepath, metadata_filepath=metadata_filepath
        )
        return 0

    # Step 4: Extract/Convert to audio.wav using ffmpeg
    ffmpeg_available = shutil.which("ffmpeg") is not None
    audio_wav_path = os.path.join(work_dir, "audio.wav")

    if ffmpeg_available:
        cmd_ffmpeg = [
            "ffmpeg", "-y", "-i", raw_audio_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_wav_path
        ]
        print("[x_video] Converting audio to WAV using ffmpeg...")
        try:
            res_ff = subprocess.run(cmd_ffmpeg, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            if res_ff.returncode == 0 and os.path.exists(audio_wav_path):
                # Delete raw audio to save space if it's not the WAV file itself
                if raw_audio_path != audio_wav_path:
                    try:
                        os.remove(raw_audio_path)
                    except Exception:
                        pass
            else:
                write_markdown(
                    url=url, status_id=status_id, author=author, title=title, duration=str(duration),
                    work_dir=work_dir, audio_file="none", transcript_source="none", transcript_engine="none",
                    status="metadata_only", description=description, transcript="",
                    notes_list=[f"Transcript unavailable: ffmpeg conversion failed (exit {res_ff.returncode})."],
                    md_filepath=md_filepath, metadata_filepath=metadata_filepath
                )
                return 0
        except subprocess.TimeoutExpired:
            sys.stderr.write("[error] ffmpeg conversion timed out after 120 seconds.\n")
            write_markdown(
                url=url, status_id=status_id, author=author, title=title, duration=str(duration),
                work_dir=work_dir, audio_file="none", transcript_source="none", transcript_engine="none",
                status="metadata_only", description=description, transcript="",
                notes_list=["Transcript unavailable: ffmpeg conversion timed out."],
                md_filepath=md_filepath, metadata_filepath=metadata_filepath
            )
            return 0
        except Exception as e:
            write_markdown(
                url=url, status_id=status_id, author=author, title=title, duration=str(duration),
                work_dir=work_dir, audio_file="none", transcript_source="none", transcript_engine="none",
                status="metadata_only", description=description, transcript="",
                notes_list=[f"Transcript unavailable: ffmpeg extraction failed ({e})."],
                md_filepath=md_filepath, metadata_filepath=metadata_filepath
            )
            return 0
    else:
        sys.stderr.write("[warn] ffmpeg is missing. Cannot transcribe audio.\n")
        write_markdown(
            url=url, status_id=status_id, author=author, title=title, duration=str(duration),
            work_dir=work_dir, audio_file="none", transcript_source="none", transcript_engine="none",
            status="metadata_only", description=description, transcript="",
            notes_list=["Transcript unavailable: ffmpeg is missing."],
            md_filepath=md_filepath, metadata_filepath=metadata_filepath
        )
        return 0

    # Step 5: Perform Transcription
    transcribed_text = None
    engine_used = "none"

    # 1. Try faster-whisper
    print("[x_video] Trying transcription with faster-whisper...")
    faster_cmd = [
        python_exe, "-c",
        "from faster_whisper import WhisperModel; import sys; "
        "model = WhisperModel('base', device='cpu', compute_type='int8'); "
        "segments, info = model.transcribe(sys.argv[1], beam_size=5); "
        "print(' '.join([s.text for s in segments]).strip())",
        audio_wav_path
    ]
    try:
        res = subprocess.run(faster_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=180)
        if res.returncode == 0 and res.stdout.strip():
            transcribed_text = res.stdout.strip()
            engine_used = "faster-whisper"
    except subprocess.TimeoutExpired:
        print("[x_video] faster-whisper transcription timed out.")
    except Exception:
        pass

    # 2. Try openai-whisper
    if not transcribed_text:
        print("[x_video] Trying transcription with openai-whisper...")
        openai_cmd = [
            python_exe, "-c",
            "import whisper; import sys; "
            "model = whisper.load_model('base'); "
            "result = model.transcribe(sys.argv[1], fp16=False); "
            "print((result.get('text') or '').strip())",
            audio_wav_path
        ]
        try:
            res = subprocess.run(openai_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=180)
            if res.returncode == 0 and res.stdout.strip():
                transcribed_text = res.stdout.strip()
                engine_used = "openai-whisper"
        except subprocess.TimeoutExpired:
            print("[x_video] openai-whisper transcription timed out.")
        except Exception:
            pass

    # 3. Try whisper CLI
    if not transcribed_text and shutil.which("whisper"):
        print("[x_video] Trying transcription with whisper CLI...")
        cli_cmd = ["whisper", audio_wav_path, "--model", "base", "--output_dir", work_dir, "--output_format", "txt"]
        try:
            res = subprocess.run(cli_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
            txt_path = os.path.join(work_dir, "audio.txt")
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    transcribed_text = f.read().strip()
                engine_used = "whisper-cli"
        except subprocess.TimeoutExpired:
            print("[x_video] whisper CLI transcription timed out.")
        except Exception:
            pass

    # Step 6: Finalize Markdown
    if transcribed_text:
        print(f"[x_video] Transcription successful using {engine_used}.")
        write_markdown(
            url=url, status_id=status_id, author=author, title=title, duration=str(duration),
            work_dir=work_dir, audio_file=audio_wav_path, transcript_source="audio", transcript_engine=engine_used,
            status="success", description=description, transcript=transcribed_text,
            notes_list=[], md_filepath=md_filepath, metadata_filepath=metadata_filepath
        )
    else:
        print("[warn] All transcription engines failed or timed out.")
        write_markdown(
            url=url, status_id=status_id, author=author, title=title, duration=str(duration),
            work_dir=work_dir, audio_file=audio_wav_path, transcript_source="none", transcript_engine="none",
            status="metadata_only", description=description, transcript="",
            notes_list=["Transcript unavailable: Speech-to-text transcription failed or timed out."],
            md_filepath=md_filepath, metadata_filepath=metadata_filepath
        )

    # Print final steps
    print(f"saved Markdown path: {md_filepath}")
    print(f"saved directory: {work_dir}")
    print(f"saved video path: none")
    print(f"metadata path: {metadata_filepath}")
    print(f"status: {'success' if transcribed_text else 'metadata_only'}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract X/Twitter video details and transcribe to Markdown.")
    parser.add_argument("url", help="X/Twitter status/video URL.")
    parser.add_argument("-o", "--output-dir", default=None, help="Output directory.")
    args = parser.parse_args()

    return run_download(args.url, args.output_dir)


if __name__ == "__main__":
    sys.exit(main())
