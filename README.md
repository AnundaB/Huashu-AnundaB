# Huashu-AnundaB

One command to turn scattered online research into organized local Markdown knowledge.

> **Note:** This repository is a modified fork/adaptation of [alchaincyf/huashu-md-html](https://github.com/alchaincyf/huashu-md-html) by Huashu (花叔), originally released under the MIT License. This is not the official Huashu distribution. Please see [PROVENANCE.md](PROVENANCE.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and [LICENSE](LICENSE) for details.

## The Problem

Online research is often scattered across multiple platforms:
- YouTube videos and playlists
- ChatGPT shared conversations
- X/Twitter posts
- Web pages
- Documentation
- Local notes

Keeping track of this information in a usable, unified format is difficult and time-consuming.

## The Solution

Huashu-AnundaB turns your scattered online research into clean, organized local Markdown files with a single command. It acts as a bridge between the web and your local knowledge base.

## Features

- Smart URL capture with `huashu "<url>"`
- YouTube video transcript extraction
- YouTube playlist transcript extraction
  - Creates `playlist_index.md`
  - Creates `combined.md`
  - Creates per-video `videos/*.md`
- ChatGPT share/conversation extraction
- X/Twitter text extraction
- X video transcript extraction
- Categorized auto output routing
- Safe output organization with `huashu -organize-auto --dry-run` and `--apply`
- Local semantic index and benchmark tooling
- Markdown/HTML/DOCX inherited conversion scripts where applicable

## Installation

### macOS/Linux

```bash
git clone https://github.com/AnundaB/Huashu-AnundaB.git
cd Huashu-AnundaB

python3 -m venv .venv
. .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

python -m pytest
huashu -latest
```

### Windows (via WSL2)

Open PowerShell as Administrator:

```powershell
wsl --install -d Ubuntu
```

Then, in your Ubuntu terminal:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg

git clone https://github.com/AnundaB/Huashu-AnundaB.git
cd Huashu-AnundaB

python3 -m venv .venv
. .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

python -m pytest
huashu -latest
```

## Quickstart

```bash
# General web page capture
huashu "https://example.com"

# YouTube video
huashu -youtube "https://www.youtube.com/watch?v=VIDEO_ID"

# YouTube playlist (limit to 5 videos)
huashu -youtube-playlist "https://youtube.com/playlist?list=PLAYLIST_ID" --limit 5

# X/Twitter post
huashu -x "https://x.com/..."

# ChatGPT shared conversation
huashu -chatgpt "https://chatgpt.com/share/..."

# GitHub repository source extraction
huashu -repo "https://github.com/owner/repo" --max-files 500 --max-file-size-kb 512

# Search latest extracted repository
huashu -repo-search "risk kernel"

# Optional OCR for an image or scanned PDF
huashu -ocr path/to/file.png

# Organize outputs (preview)
huashu -organize-auto --dry-run

# Organize outputs (apply)
huashu -organize-auto --apply
```

## Optional OCR

Optional OCR can improve extraction for screenshots, scanned PDFs, and image-heavy documents. OCR support is dependency-heavy, so Huashu keeps it optional and fallback-oriented.

```bash
huashu -ocr path/to/image-or-pdf
huashu -ocr path/to/image-or-pdf --engine paddleocr
```

The initial OCR adapter uses PaddleOCR when it is installed in your environment. If it is missing, Huashu prints install guidance instead of failing with a stack trace. PDF OCR also needs a local page renderer such as PyMuPDF.

OCR accuracy depends on the source image quality, language, layout complexity, and installed OCR models. Huashu does not claim perfect OCR output.

## Output Structure

When using the organization features, your outputs are routed into structured directories:

```text
outputs/auto/
  web/
  docs/
  youtube/
    playlists/
      <playlist-id>/
        playlist_index.md
        combined.md
        videos/
          001-<video-id>-<slug>.md
  x/
    text/
    video/
  chatgpt/
  github/
    <timestamp>-<owner>-<repo>/
      repository_index.md
      architecture.md
      dependency_graph.md
      imports.csv
      combined.md
      tree.txt
      repo_metadata.md
      semantic_index/
      files/
  research/
  misc/
```

## Privacy and Safety

- **Local First**: Outputs are saved locally by default.
- **Git Ignore**: Do not commit `outputs/`, `.venv/`, `.env`, secrets, cookies, or personal transcripts. These are ignored by default.
- **Respectful Scraping**: The tool should not bypass paywalls, login screens, or restricted content.
- **YouTube Transcripts**: YouTube mode extracts captions/transcripts; it should not download full videos by default.

## Development

To run tests and check for issues:

```bash
python -m pytest
git diff --check
```

## License and Attribution

- **Original Project**: [Huashu (花叔)](https://github.com/alchaincyf/huashu-md-html), released under the MIT License.
- **This Adaptation**: AnundaB modifications are under the MIT License unless otherwise stated.
- Please see [`PROVENANCE.md`](PROVENANCE.md) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for full licensing and attribution details.
