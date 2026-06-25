# Huashu-AnundaB

> **Turn Anything Into Markdown.**

Huashu-AnundaB is a local-first knowledge extraction CLI that turns websites, YouTube videos, YouTube playlists, GitHub repositories, PDFs, images, ChatGPT conversations, X/Twitter posts, and local files into clean, organized, searchable Markdown.

```bash
huashu "<anything>"
```

Everything becomes Markdown.  
Everything stays local.

> **Note**
>
> This repository is a modified fork/adaptation of [`alchaincyf/huashu-md-html`](https://github.com/alchaincyf/huashu-md-html) by Huashu (花叔), originally released under the MIT License.
>
> This is not the official Huashu distribution.
>
> Please see [`PROVENANCE.md`](PROVENANCE.md), [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md), and [`LICENSE`](LICENSE) for licensing and attribution details.

---

## Why Huashu-AnundaB?

Knowledge is scattered everywhere:

- YouTube videos and playlists
- GitHub repositories
- ChatGPT conversations
- X/Twitter posts and videos
- Web pages and documentation
- PDFs and scanned documents
- Screenshots and image-heavy files
- Research papers
- Local notes and files

Most of this knowledge gets lost inside browser tabs, bookmarks, screenshots, chat history, and random folders.

Huashu-AnundaB turns that scattered information into a local Markdown knowledge base that you can search, organize, study, and feed into AI workflows.

---

## What Huashu Can Extract

| Source | Output |
|---|---|
| Websites | Clean Markdown |
| Documentation pages | Markdown notes |
| YouTube videos | Transcript Markdown |
| YouTube playlists | `playlist_index.md`, `combined.md`, per-video Markdown |
| GitHub repositories | Full repo snapshot, file tree, combined source, architecture, dependency graph, semantic index |
| ChatGPT shared conversations | Markdown conversation archive |
| X/Twitter posts | Markdown |
| X/Twitter videos | Metadata + audio transcript when possible |
| Born-digital PDFs | Markdown via text extraction |
| Scanned PDFs, images, and screenshots | Optional OCR Markdown |
| Local files | Markdown where supported |

---

## Core Idea

```text
Anything
  ↓
Markdown
  ↓
Organized local knowledge base
  ↓
Semantic search
  ↓
AI-ready context
```

Huashu is designed for people who want to collect knowledge from the internet and turn it into durable local files.

Markdown is simple, portable, searchable, git-friendly, and easy to use with AI tools.

---

## Quickstart

## One Command Mode

```bash
huashu "<anything>"
```

Huashu detects the input type and routes automatically:

- URLs
- YouTube videos/playlists
- GitHub repositories
- ChatGPT shares
- X/Twitter posts/videos
- PDFs
- born-digital PDFs
- scanned PDFs and images when optional OCR is enabled
- code files
- JSON/YAML/text files

Explicit commands such as `huashu -repo`, `huashu -ocr`, `huashu -youtube`, and `huashu -youtube-playlist` are still available for advanced usage.

### Capture a web page

```bash
huashu "https://example.com"
```

### Extract a YouTube video transcript

```bash
huashu -youtube "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Extract a YouTube playlist

```bash
huashu -youtube-playlist "https://youtube.com/playlist?list=PLAYLIST_ID" --limit 5
```

This creates:

```text
playlist_index.md
combined.md
videos/
  001-video-title.md
  002-video-title.md
```

### Extract a GitHub repository

```bash
huashu "https://github.com/owner/repo"
```

This creates a local repository knowledge base:

```text
repository_index.md
combined.md
tree.txt
repo_metadata.md
architecture.md
dependency_graph.md
imports.csv
symbols.md
symbols.jsonl
semantic_index/
files/
```

### Search an extracted repository

```bash
huashu -repo-search "risk management"
```

Search results include:

- score
- repository
- file path
- chunk preview

### Extract OCR from a scanned PDF or image

```bash
huashu -ocr "scanned_document.pdf"
huashu -ocr "screenshot.png"
```

OCR is optional because it uses heavier model-based dependencies. The default install keeps Huashu lightweight for normal laptops. To enable OCR, run `huashu setup-ocr` or `python -m pip install -r requirements-ocr.txt`.

### Extract a ChatGPT shared conversation

```bash
huashu -chatgpt "https://chatgpt.com/share/..."
```

### Extract an X/Twitter post

```bash
huashu -x "https://x.com/..."
```

### Extract an X/Twitter video transcript

```bash
huashu "https://x.com/user/status/123/video/1"
```

### Organize outputs safely

Preview first:

```bash
huashu -organize-auto --dry-run
```

Apply:

```bash
huashu -organize-auto --apply
```

---

## GitHub Repository Intelligence

Huashu-AnundaB can turn a GitHub repository into a local code knowledge base.

```bash
huashu -repo "https://github.com/YiJia-Xiao/TradingAgents"
```

It does not just scrape the rendered GitHub page.

It recursively enumerates the repository tree, downloads text-based source files, preserves folder structure, and generates Markdown intelligence files.

### Generated files

```text
outputs/auto/github/<repo>/
  repository_index.md
  combined.md
  tree.txt
  repo_metadata.md
  architecture.md
  dependency_graph.md
  imports.csv
  symbols.md
  symbols.jsonl
  semantic_index/
    chunks.jsonl
    vectors.npy
    ids.npy
    id_map.jsonl
    index_manifest.json
  files/
    <original repo file structure>
```

### Repository analysis includes

- full file tree
- file counts by extension
- largest files
- probable entrypoints
- test directories
- config files
- dependency files
- documentation files
- top-level directory descriptions
- deterministic architecture overview
- Python dependency graph via `ast`
- local semantic search index

### Limits and safety

Huashu skips binary files by default and supports limits for large repositories:

```bash
huashu -repo "https://github.com/owner/repo" --max-files 500 --max-file-size-kb 512
```

No GitHub token is required for normal public repositories.

For heavy usage, future versions may support optional `GITHUB_TOKEN` for higher GitHub API limits.

---

## OCR Extraction

Huashu can extract text from images, screenshots, scanned PDFs, and image-heavy documents.

```bash
huashu -ocr path/to/file.png
huashu -ocr path/to/scanned.pdf
```

OCR output includes Markdown metadata:

```yaml
source: path/to/file
engine: paddleocr
page_count: 3
status: success
confidence: available_when_supported
warnings: []
```

OCR is not part of the default lightweight install. OCR commands print profile-specific install guidance instead of crashing when OCR dependencies are missing.

One-command mode does not silently launch OCR by default. If a PDF looks scanned or image-heavy, Huashu prints guidance instead of starting a model download. To allow automatic OCR fallback after installing OCR dependencies:

```bash
HUASHU_AUTO_OCR=1 huashu "scanned_document.pdf"
```

---

## YouTube Playlist Extraction

Huashu can convert playlists into structured Markdown knowledge bases.

```bash
huashu -youtube-playlist "https://youtube.com/playlist?list=PLAYLIST_ID" --limit 10
```

Output:

```text
outputs/auto/youtube/playlists/<playlist-id>/
  playlist_index.md
  combined.md
  videos/
    001-title.md
    002-title.md
```

This is useful for:

- courses
- tutorials
- lectures
- podcasts
- research playlists
- study plans

---

## X/Twitter Video Transcription

Huashu can process X/Twitter video URLs.

It fetches metadata, downloads audio when possible, converts audio locally, and attempts speech-to-text transcription.

Long audio is handled with chunking and safer transcript status reporting.

Possible statuses:

```text
success
metadata_only
transcript_failed
```

---

## Local Semantic Search

Huashu includes local semantic indexing for extracted knowledge.

Current embedding is lightweight and local by default.

Repository semantic search:

```bash
huashu -repo-search "portfolio optimization"
huashu -repo-search "risk kernel"
huashu -repo-search "IBKR"
```

The goal is to make your extracted Markdown useful not only as files, but as a searchable local memory system.

---

## Output Structure

Huashu organizes extracted files under:

```text
outputs/auto/
  web/
  docs/
  youtube/
    playlists/
  x/
    text/
    video/
  chatgpt/
  github/
  research/
  ocr/
  misc/
```

Generated media/cache files may also appear under:

```text
outputs/media/
```

Do not commit personal outputs, transcripts, media files, cookies, tokens, or `.env` files.

---

## Installation

`requirements.txt` is the default lightweight install for fast, common extraction: web pages, YouTube transcripts and playlists, GitHub repositories, ChatGPT shares, X/text workflows, local text/code/data files, and born-digital PDFs via text extraction.

OCR for scanned PDFs, screenshots, and image-heavy documents is optional because it is heavier and model-based.

### macOS / Linux

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

### Optional OCR Add-On

If you need OCR, add the OCR profile after the default install:

```bash
python -m pip install -r requirements-ocr.txt
```

or use:

```bash
huashu setup-ocr
```

OCR may download models on first use depending on the engine. On small laptops, test large PDFs with `huashu -ocr file.pdf --max-pages 1` before running the whole document.

### Windows via WSL2

Open PowerShell as Administrator:

```powershell
wsl --install -d Ubuntu
```

Then open Ubuntu:

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

---

## Install Profiles and Troubleshooting

Huashu has Python dependency profiles:

- `requirements.txt`: default lightweight install.
- `requirements-core.txt`: core dependency list used by the default install.
- `requirements-ocr.txt`: optional OCR add-on for scanned PDFs, screenshots, and image-heavy documents.

### FFmpeg

Needed for video/audio processing.

macOS:

```bash
brew install ffmpeg
```

Ubuntu:

```bash
sudo apt install -y ffmpeg
```

### OCR

OCR is optional and not included in the default install:

```bash
python -m pip install -r requirements-ocr.txt
```

or:

```bash
huashu setup-ocr
```

OCR dependencies are heavier than core dependencies. PaddleOCR may download OCR models on first OCR use.

### Doctor

`huashu doctor` is a troubleshooting command, not a required setup step. It checks the local Python executable, Python version, FFmpeg, MarkItDown, repository/search-related dependencies, and reports OCR as optional.

```bash
huashu doctor
```

If OCR dependencies are missing, `huashu setup-ocr` is available as a convenience:

```bash
huashu setup-ocr
```

---

## Development

Run tests:

```bash
python -m pytest
```

Check whitespace / patch quality:

```bash
git diff --check
```

Show current changes:

```bash
git status --short
git diff --stat
```

---

## Safety and Privacy

Huashu is local-first.

- Outputs are saved locally by default.
- Do not commit `outputs/`, `.venv/`, `.env`, cookies, secrets, private transcripts, or personal files.
- The tool should not bypass paywalls, login screens, private repositories, or restricted content.
- YouTube mode extracts captions/transcripts; it does not download full videos by default.
- GitHub repository mode is designed for public repositories unless you explicitly extend it later.

---

## What Huashu-AnundaB Is Not

Huashu-AnundaB is not:

- the official Huashu distribution
- a paywall bypass tool
- a private content scraper
- a full video downloader
- a replacement for legal/compliance review
- a perfect OCR or perfect semantic search system

It is a local knowledge extraction tool focused on turning useful public or user-owned information into Markdown.

---

## Roadmap

Planned or possible next steps:

- opt-in automatic OCR fallback for scanned PDFs
- better repository symbol extraction
- cross-repository search
- repository Q&A
- optional GitHub token support
- better table/layout reconstruction for OCR
- stronger semantic indexing
- local knowledge graph generation

---

## License and Attribution

Original project:

- [`alchaincyf/huashu-md-html`](https://github.com/alchaincyf/huashu-md-html) by Huashu (花叔)
- originally released under the MIT License

This adaptation:

- Huashu-AnundaB modifications by AnundaB
- released under the MIT License unless otherwise stated

See:

- [`LICENSE`](LICENSE)
- [`PROVENANCE.md`](PROVENANCE.md)
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)

---

## One Sentence

Huashu-AnundaB turns anything into Markdown so your scattered knowledge becomes a searchable local knowledge base.
