import os
import sys
import re
import csv
import datetime
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO_DIR = os.getenv("HUASHU_AUTO_DIR", os.path.join(REPO_ROOT, "outputs", "auto"))
MANIFEST_PATH = os.path.join(AUTO_DIR, "manifest.csv")
INDEX_PATH = os.path.join(AUTO_DIR, "index.md")


class OutputRecord:
    def __init__(
        self,
        source_type: str,
        category: str,
        original_source: str,
        output_path: str,
        title: str | None,
        status: str,
        timestamp: str,
        short_category: str
    ):
        self.source_type = source_type
        self.category = category
        self.original_source = original_source
        self.output_path = output_path
        self.title = title
        self.status = status
        self.timestamp = timestamp
        self.short_category = short_category


def classify_source(source: str, explicit_type: str | None = None) -> tuple[str, str]:
    """
    Classifies a source URL or identifier into a (source_type, category) pair.
    Category is the subfolder path relative to outputs/auto/.
    """
    source_lower = source.lower()

    # Explicit types first
    if explicit_type:
        et = explicit_type.lower().strip("-")
        if et in ("youtube", "yt"):
            return "youtube", "youtube"
        elif et in ("x", "twitter", "x-text", "x-clipboard", "clipboard"):
            return "x_text", "x/text"
        elif et in ("x-video", "x-video-md"):
            return "x_video", "x/video"
        elif et in ("chatgpt", "chatgpt-full", "chatgpt-export"):
            return "chatgpt", "chatgpt"
        elif et in ("docs", "crawl"):
            return "docs", "docs"
        elif et in ("github", "git"):
            return "github", "github"
        elif et in ("research", "consensus", "ingest"):
            return "research", "research"
        elif et in ("web", "page"):
            return "web", "web"
        elif et == "misc":
            return "misc", "misc"

    # Auto-classify based on source content / URL
    # 1. YouTube
    if "youtube.com" in source_lower or "youtu.be" in source_lower:
        return "youtube", "youtube"

    # 2. X / Twitter
    if "x.com" in source_lower or "twitter.com" in source_lower:
        if "/video/" in source_lower:
            return "x_video", "x/video"
        else:
            return "x_text", "x/text"

    # 3. ChatGPT
    if "chatgpt.com" in source_lower or "chat.openai.com" in source_lower:
        return "chatgpt", "chatgpt"

    # 4. GitHub
    if "github.com" in source_lower:
        return "github", "github"

    # 5. Generic URL
    if source_lower.startswith(("http://", "https://")):
        return "web", "web"

    # 6. Fallback
    return "misc", "misc"


def route_output(source: str, filename: str, explicit_type: str | None = None) -> str:
    """
    Routes an output filename to its categorized subdirectory under outputs/auto/.
    Creates the directory if it doesn't exist.
    """
    _, category = classify_source(source, explicit_type)
    target_dir = os.path.join(AUTO_DIR, category)
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, filename)


def register_output(
    output_path: str,
    source: str,
    explicit_type: str | None = None,
    title: str | None = None,
    status: str = "success"
):
    """
    Appends a record to outputs/auto/manifest.csv and rebuilds outputs/auto/index.md.
    Also performs semantic content classification if the output is a Markdown file.
    """
    # 1. Normalize paths to make them relative to outputs/auto/ or absolute if outside
    output_path_abs = os.path.abspath(output_path)
    if output_path_abs.startswith(AUTO_DIR + os.sep):
        rel_path = os.path.relpath(output_path_abs, AUTO_DIR)
    else:
        rel_path = output_path_abs

    # 2. Classify
    source_type, category = classify_source(source, explicit_type)
    short_category = category.split("/")[0]

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Semantic Metadata defaults
    content_category = "unknown"
    topics = "general"
    confidence = 0.0
    classifier_engine = "none"
    classifier_version = "none"
    semantic_neighbors = ""
    embedding_model = "none"
    vector_backend = "none"

    # Try classifying content if the file exists and is markdown
    if output_path_abs.endswith(".md") and os.path.exists(output_path_abs):
        try:
            with open(output_path_abs, "r", encoding="utf-8", errors="replace") as mdf:
                text = mdf.read()
            sys.path.append(os.path.join(REPO_ROOT, "scripts"))
            import content_classifier
            res = content_classifier.classify_content(text, doc_path=output_path_abs)
            content_category = res.get("content_category", "unknown")
            topics = res.get("topics", "general")
            confidence = res.get("confidence", 0.0)
            classifier_engine = res.get("classifier_engine", "none")
            classifier_version = res.get("classifier_version", "1.0.0")
            semantic_neighbors = res.get("semantic_neighbors", "")
            embedding_model = res.get("embedding_model", "local_projected_hash_128")
            vector_backend = res.get("vector_backend", "numpy_fallback")
        except Exception as e:
            print(f"[warn] Failed to classify document: {e}")

    # 3. Read existing manifest entries or create new manifest
    existing_entries = []
    os.makedirs(AUTO_DIR, exist_ok=True)

    if os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    for row in reader:
                        existing_entries.append(row)
        except Exception as e:
            print(f"[warn] Failed to read existing manifest: {e}")

    # 4. Check if this output_path is already registered to avoid duplicates
    updated = False
    for entry in existing_entries:
        if entry.get("output_path") == rel_path:
            entry["timestamp"] = timestamp
            entry["source_type"] = source_type
            entry["category"] = category
            entry["short_category"] = short_category
            entry["original_source"] = source
            entry["title"] = title or entry.get("title") or ""
            entry["status"] = status
            entry["content_category"] = content_category
            entry["topics"] = topics
            entry["confidence"] = str(confidence)
            entry["classifier_engine"] = classifier_engine
            entry["classifier_version"] = classifier_version
            entry["semantic_neighbors"] = semantic_neighbors
            entry["embedding_model"] = embedding_model
            entry["vector_backend"] = vector_backend
            updated = True
            break

    if not updated:
        existing_entries.append({
            "timestamp": timestamp,
            "source_type": source_type,
            "category": category,
            "short_category": short_category,
            "original_source": source,
            "output_path": rel_path,
            "title": title or "",
            "status": status,
            "content_category": content_category,
            "topics": topics,
            "confidence": str(confidence),
            "classifier_engine": classifier_engine,
            "classifier_version": classifier_version,
            "semantic_neighbors": semantic_neighbors,
            "embedding_model": embedding_model,
            "vector_backend": vector_backend
        })

    # 5. Write back to manifest.csv
    fieldnames = [
        "timestamp", "source_type", "category", "short_category", "original_source",
        "output_path", "title", "status", "content_category", "topics", "confidence",
        "classifier_engine", "classifier_version", "semantic_neighbors", "embedding_model", "vector_backend"
    ]
    try:
        with open(MANIFEST_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in existing_entries:
                # Fill missing keys in case of old manifest rows
                for fn in fieldnames:
                    if fn not in entry:
                        entry[fn] = ""
                writer.writerow(entry)
    except Exception as e:
        print(f"[error] Failed to write manifest: {e}")

    # 6. Rebuild index.md
    rebuild_index(existing_entries)


def rebuild_index(entries: list[dict]):
    """
    Rebuilds outputs/auto/index.md from the list of manifest entries.
    """
    groups = {}
    for entry in entries:
        cat = entry.get("category", "misc")
        if cat not in groups:
            groups[cat] = []
        groups[cat].append(entry)

    pretty_names = {
        "youtube": "YouTube Transcripts",
        "x/text": "X (Twitter) Posts",
        "x/video": "X (Twitter) Videos",
        "chatgpt": "ChatGPT Conversations",
        "docs": "Documentation Crawls",
        "github": "GitHub Repositories",
        "research": "Consensus & Research Imports",
        "web": "Web Pages",
        "misc": "Miscellaneous Extracts"
    }

    lines = []
    lines.append("# Huashu Auto-Research Extract Index")
    lines.append("")
    lines.append("This is an automatically updated index of all extracted research and content.")
    lines.append("")
    lines.append("## Categories")
    lines.append("")

    sorted_cats = sorted(groups.keys(), key=lambda c: pretty_names.get(c, c))

    for cat in sorted_cats:
        pretty_name = pretty_names.get(cat, cat.capitalize())
        lines.append(f"### {pretty_name}")
        lines.append("")
        for entry in sorted(groups[cat], key=lambda e: e.get("timestamp", ""), reverse=True):
            title = entry.get("title") or entry.get("output_path")
            out_path = entry.get("output_path")
            source = entry.get("original_source")
            status = entry.get("status")
            ts = entry.get("timestamp")

            status_indicator = ""
            if status != "success":
                status_indicator = f" ({status})"

            lines.append(f"- **[{title}]({out_path})**{status_indicator}")

            meta_parts = [f"Source: `{source}`", f"Extracted: {ts}"]

            content_category = entry.get("content_category")
            if content_category and content_category != "unknown":
                meta_parts.append(f"Category: `{content_category}`")

            topics = entry.get("topics")
            if topics and topics != "general":
                meta_parts.append(f"Topics: `{topics}`")

            lines.append("  - " + " | ".join(meta_parts))
        lines.append("")

    try:
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[error] Failed to write index: {e}")
