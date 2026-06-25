#!/usr/bin/env python3
"""
huashu_cli.py — Top-level interactive and non-interactive command-line interface
for the Local Research Ingestion Pipeline.
"""

import os
import sys
import subprocess
import csv
import json
import re
import shutil
import tempfile
import urllib.parse

# Find repository root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR_FALLBACK_NONSPACE_THRESHOLD = 200


def should_fallback_to_ocr(markdown_text: str) -> bool:
    """
    Returns True when standard extraction produced too little usable text.
    The heuristic deliberately counts non-whitespace characters so blank or
    formatting-only Markdown triggers OCR, while normal text PDFs do not.
    """
    return len(re.sub(r"\s+", "", markdown_text or "")) < OCR_FALLBACK_NONSPACE_THRESHOLD


def slugify_output_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9ก-๙._-]+", "-", value).strip("-")
    return slug[:90] or "content"


def is_github_repo_url(url: str) -> bool:
    """
    Detects GitHub repository root/tree URLs without capturing issue, blob,
    pull request, or other non-repository pages.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if parsed.scheme not in ("http", "https") or netloc != "github.com":
        return False

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return False
    if len(parts) == 2:
        return True
    return len(parts) >= 4 and parts[2] == "tree"

def find_input_file(filename: str) -> str | None:
    """
    Finds the input file from:
      1. exact path
      2. current working directory
      3. inputs/consensus/ relative to repo
      4. ~/Downloads/
    """
    # 1. Exact path
    if os.path.exists(filename):
        return os.path.abspath(filename)

    # 2. CWD relative path
    cwd_path = os.path.join(os.getcwd(), filename)
    if os.path.exists(cwd_path):
        return os.path.abspath(cwd_path)

    # 3. inputs/consensus/ in the repo
    repo_inputs = os.path.join(REPO_ROOT, "inputs", "consensus", filename)
    if os.path.exists(repo_inputs):
        return os.path.abspath(repo_inputs)

    # 4. ~/Downloads/
    downloads = os.path.expanduser("~/Downloads")
    downloads_path = os.path.join(downloads, filename)
    if os.path.exists(downloads_path):
        return os.path.abspath(downloads_path)

    return None


def get_latest_run_dir() -> str | None:
    """
    Finds the latest run directory by reading outputs/latest_ingest.txt
    or scanning outputs/consensus/.
    """
    latest_file_path = os.path.join(REPO_ROOT, "outputs", "latest_ingest.txt")
    if os.path.exists(latest_file_path):
        with open(latest_file_path, "r", encoding="utf-8") as f:
            path = f.read().strip()
            if os.path.exists(path):
                return path

    consensus_dir = os.path.join(REPO_ROOT, "outputs", "consensus")
    if os.path.exists(consensus_dir):
        subdirs = [os.path.join(consensus_dir, d) for d in os.listdir(consensus_dir)]
        subdirs = [d for d in subdirs if os.path.isdir(d) and os.path.exists(os.path.join(d, "metadata", "papers.jsonl"))]
        if subdirs:
            # Sort by directory name (format is YYYYMMDD-HHMMSS-...)
            subdirs.sort(key=lambda x: os.path.basename(x))
            return subdirs[-1]

    return None


def get_latest_research_run() -> tuple[str, str] | tuple[None, None]:
    """
    Finds the latest research run folder under outputs/research-runs/
    and returns (run_folder, note_path).
    """
    runs_dir = os.path.join(REPO_ROOT, "outputs", "research-runs")
    if os.path.exists(runs_dir):
        subdirs = [os.path.join(runs_dir, d) for d in os.listdir(runs_dir)]
        subdirs = [d for d in subdirs if os.path.isdir(d) and os.path.exists(os.path.join(d, "research_note.md"))]
        if subdirs:
            subdirs.sort(key=lambda x: os.path.basename(x))
            latest_run = subdirs[-1]
            return latest_run, os.path.join(latest_run, "research_note.md")
    return None, None


def write_latest_run_dir(run_dir: str):
    """
    Saves the latest run directory pointer.
    """
    outputs_dir = os.path.join(REPO_ROOT, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    latest_file_path = os.path.join(outputs_dir, "latest_ingest.txt")
    with open(latest_file_path, "w", encoding="utf-8") as f:
        f.write(run_dir)


def print_ingest_summary(run_dir: str):
    """
    Reads manifest.csv and index_manifest.json to print a formatted count summary.
    """
    manifest_path = os.path.join(run_dir, "metadata", "manifest.csv")
    if not os.path.exists(manifest_path):
        print(f"[warn] manifest.csv not found under {run_dir}")
        return

    total = 0
    resolved_doi = 0
    oa_pdf_found = 0
    pdf_downloaded = 0
    html_fallback = 0
    md_converted = 0
    quality_passed = 0
    manual_needed = 0
    failed_forbidden = 0

    with open(manifest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            if row.get("doi"):
                resolved_doi += 1
            if row.get("oa_pdf_url"):
                oa_pdf_found += 1
            if row.get("real_download_performed") == "True":
                pdf_downloaded += 1
            if row.get("html_to_md_performed") == "True":
                html_fallback += 1
            if row.get("markdown_path"):
                md_converted += 1
            if row.get("extraction_quality_status") == "passed":
                quality_passed += 1
            if row.get("status") == "manual_needed":
                manual_needed += 1
            if row.get("status") == "failed":
                failed_forbidden += 1

    total_chunks = 0
    manifest_json_path = os.path.join(run_dir, "memory", "index_manifest.json")
    if os.path.exists(manifest_json_path):
        try:
            with open(manifest_json_path, "r", encoding="utf-8") as jf:
                manifest_data = json.load(jf)
                total_chunks = manifest_data.get("total_chunks", 0)
        except Exception:
            pass

    print("\n" + "="*50)
    print("INGESTION SUMMARY")
    print("="*50)
    print(f"Total Records:             {total}")
    print(f"Parsed Records:            {total}")
    print(f"Resolved DOI:              {resolved_doi}")
    print(f"OA PDF Found:              {oa_pdf_found}")
    print(f"PDF Downloaded:            {pdf_downloaded}")
    print(f"HTML Fallback Success:     {html_fallback}")
    print(f"Markdown Converted:        {md_converted}")
    print(f"Quality Passed:            {quality_passed}")
    print(f"Memory Chunks Indexed:     {total_chunks}")
    print(f"Manual Needed:             {manual_needed}")
    print(f"Failed/Forbidden:          {failed_forbidden}")
    print("="*50)
    print(f"Ingestion Output Path:     {run_dir}")
    print(f"Markdown Folder:           {os.path.join(run_dir, 'md')}")
    print(f"Memory Index Folder:       {os.path.join(run_dir, 'memory')}")
    print(f"Manifest Path:             {manifest_path}")
    print("="*50 + "\n")


def run_ingest(filename: str, limit: str | None = None) -> bool:
    """
    Executes raw parsing, DOI resolution, PDF/HTML fetching, Markdown conversion,
    and automatic memory indexing.
    """
    resolved_file = find_input_file(filename)
    if not resolved_file:
        print(f"[error] Could not locate input file: '{filename}'")
        print("Tried: exact path, CWD, inputs/consensus/ in repo, and ~/Downloads/.")
        return False

    print(f"Resolved input file to: {resolved_file}")

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = "python3"

    ingest_script = os.path.join(REPO_ROOT, "scripts", "consensus_ingest.py")

    # Build consensus_ingest command args
    cmd = [
        python_exe,
        ingest_script,
        "--resolve-doi",
        "--download-pdf",
        "--html-fallback",
        "--convert-md",
        "--output-dir",
        os.path.join(REPO_ROOT, "outputs", "consensus")
    ]
    if limit:
        cmd.extend(["--limit", limit])
    cmd.append(resolved_file)

    print(f"Running Ingestion: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        # Scan stdout to find the output folder
        run_dir = None
        for line in result.stdout.splitlines():
            print(line)
            if "Output folder path:" in line:
                run_dir = line.split("Output folder path:", 1)[1].strip()

        # If output folder path wasn't captured, check stderr or try finding the latest run dir
        if not run_dir:
            # Fallback
            run_dir = get_latest_run_dir()

        if not run_dir or not os.path.exists(run_dir):
            print("[error] Ingestion completed but output run directory could not be resolved.")
            return False

        # Save pointer
        write_latest_run_dir(run_dir)

        # Build memory index automatically
        print("\n[info] Ingestion complete. Building memory index automatically...")
        index_script = os.path.join(REPO_ROOT, "scripts", "research_memory_index.py")
        build_cmd = [python_exe, index_script, "build", run_dir]
        print(f"Running Memory Indexer: {' '.join(build_cmd)}")
        subprocess.run(build_cmd, check=True)

        # Print summary
        print_ingest_summary(run_dir)
        return True

    except subprocess.CalledProcessError as e:
        print(f"\n[error] Ingestion command failed with exit status {e.returncode}.")
        print("Stderr:\n", e.stderr)
        return False


def run_search(query: str) -> bool:
    """
    Performs vector similarity search on the latest indexed memory directory.
    """
    run_dir = get_latest_run_dir()
    if not run_dir:
        print("No memory index found. Run huashu -ingest <file> first.")
        return False

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = "python3"

    index_script = os.path.join(REPO_ROOT, "scripts", "research_memory_index.py")
    cmd = [python_exe, index_script, "query", run_dir, query]

    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[error] Query failed: {e}")
        return False


def run_note(question: str) -> bool:
    """
    Runs the automated Research Council loop to synthesize findings into a markdown note.
    """
    run_dir = get_latest_run_dir()
    if not run_dir:
        print("No memory index found. Run huashu -ingest <file> first.")
        return False

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = "python3"

    loop_script = os.path.join(REPO_ROOT, "scripts", "research_loop.py")
    cmd = [python_exe, loop_script, run_dir, question]

    print(f"Running Research Council Loop: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        print(result.stdout)

        # Parse run output dir from output
        note_dir = None
        for line in result.stdout.splitlines():
            if "Research Run Folder:" in line:
                note_dir = line.split("Research Run Folder:", 1)[1].strip()

        if not note_dir:
            # Fallback
            runs_dir = os.path.join(REPO_ROOT, "outputs", "research-runs")
            if os.path.exists(runs_dir):
                subdirs = [os.path.join(runs_dir, d) for d in os.listdir(runs_dir)]
                if subdirs:
                    subdirs.sort(key=lambda x: os.path.basename(x))
                    note_dir = subdirs[-1]

        if note_dir:
            print("\n" + "="*50)
            print("RESEARCH NOTES GENERATED")
            print("="*50)
            print(f"Research Note Path:        {os.path.join(note_dir, 'research_note.md')}")
            print(f"Evidence Table Path:       {os.path.join(note_dir, 'evidence_table.csv')}")
            print(f"Next Questions Path:       {os.path.join(note_dir, 'next_questions.md')}")
            print(f"Run Log Path:              {os.path.join(note_dir, 'run_log.md')}")
            print("="*50 + "\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[error] Research loop failed: {e}")
        print("Stderr:\n", e.stderr)
        return False


def run_latest():
    """
    Displays metadata of the latest ingestion and note runs.
    """
    run_dir = get_latest_run_dir()
    if not run_dir:
        print("No ingestion runs found yet. Use -ingest to import research papers.")
        return

    print("\n" + "="*50)
    print("LATEST PIPELINE STATE")
    print("="*50)
    print(f"Latest Ingestion Run:      {run_dir}")
    print(f"Markdown Files Folder:     {os.path.join(run_dir, 'md')}")
    print(f"Memory Index Folder:       {os.path.join(run_dir, 'memory')}")

    latest_run_dir, note_path = get_latest_research_run()
    if latest_run_dir:
        print(f"Latest Research Run:       {latest_run_dir}")
        print(f"Latest Research Note:      {note_path}")
    else:
        print("Latest Research Run:       None (Run huashu -note first)")
    print("="*50 + "\n")


def parse_topics_args(args: list[str]) -> tuple[str | None, list[str]]:
    """
    Parses CLI arguments for topic builder.
    If the first argument is an option (starts with '-'), uses the latest Consensus run directory.
    Otherwise, treats it as the run directory.
    """
    if not args:
        return get_latest_run_dir(), []

    first_arg = args[0]
    if first_arg.startswith("-"):
        return get_latest_run_dir(), args
    else:
        return first_arg, args[1:]


def run_topics(run_dir: str, extra_args: list[str] = None) -> bool:
    """
    Groups related papers into concept/objective-aligned topic packs.
    """
    if not os.path.exists(run_dir):
        print(f"[error] Run directory does not exist: {run_dir}")
        return False

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable or "python3"

    topics_script = os.path.join(REPO_ROOT, "scripts", "research_topic_packs.py")
    cmd = [python_exe, topics_script, run_dir]
    if extra_args:
        cmd.extend(extra_args)

    print(f"Running Topic Pack Builder: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[error] Topic pack builder failed: {e}")
        return False


def run_local_file_conversion(filename: str) -> int:
    """
    Converts a local file via MarkItDown first, then falls back to OCR when
    the resulting Markdown has too little usable text.
    """
    resolved_file = find_input_file(filename)
    if not resolved_file:
        return -1

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable or "python3"

    print("[web/file] Converting to clean Markdown...")

    any_to_md_script = os.path.join(REPO_ROOT, "scripts", "any_to_md.py")
    with tempfile.TemporaryDirectory(prefix="huashu-extract-") as tmp_dir:
        temp_md = os.path.join(tmp_dir, "standard.md")
        res = subprocess.run([python_exe, any_to_md_script, resolved_file, "-o", temp_md, "--quiet"])
        if res.returncode != 0:
            return res.returncode

        try:
            with open(temp_md, "r", encoding="utf-8", errors="replace") as f:
                markdown_text = f.read()
        except OSError as exc:
            print(f"[error] Failed to read standard extraction output: {exc}")
            return 1

        if should_fallback_to_ocr(markdown_text):
            print("[ocr] No usable text detected. Falling back to OCR...")
            ocr_script = os.path.join(REPO_ROOT, "scripts", "ocr_extract.py")
            ocr_res = subprocess.run([python_exe, ocr_script, resolved_file])
            return ocr_res.returncode

        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router

        import datetime

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = slugify_output_name(os.path.splitext(os.path.basename(resolved_file))[0])
        md_filename = f"{stamp}-{slug}.md"
        md_filepath = output_router.route_output(resolved_file, md_filename, "misc")
        os.makedirs(os.path.dirname(md_filepath), exist_ok=True)
        shutil.copyfile(temp_md, md_filepath)

    try:
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router

        output_router.register_output(
            output_path=md_filepath,
            source=resolved_file,
            explicit_type="misc",
            title=os.path.basename(resolved_file),
            status="success",
        )
    except Exception as e:
        print(f"[warn] Failed to register output in manifest/index: {e}")

    print("")
    print("Done.")
    print("Markdown:")
    print(md_filepath)

    try:
        subprocess.run(["open", "-R", md_filepath])
    except Exception:
        pass
    return 0


def print_help():
    """
    Prints human-friendly CLI usage guidance.
    """
    print("""
Huashu Ingestion & Auto-Research CLI

Usage (Command Line):
  python3 scripts/huashu_cli.py -topics [<run-dir>]                 Build concept-aligned topic packs (uses latest run by default).
  python3 scripts/huashu_cli.py -upload-ready [<run-dir>]           Regenerate upload-ready exports for a run.
  python3 scripts/huashu_cli.py -ingest <filename> [--limit <num>]  Ingest, clean, convert, and index research papers.
  python3 scripts/huashu_cli.py -search "<query>"                   Query similarity search over local paper vectors.
  python3 scripts/huashu_cli.py -note "<question>"                  Run the Research Council to write a markdown note.
  python3 scripts/huashu_cli.py -latest                             Show directories and details of the latest runs.
  python3 scripts/huashu_cli.py -docs <url>                         Force docs crawl of a site.
  python3 scripts/huashu_cli.py -page <url>                         Force single-page web conversion.
  python3 scripts/huashu_cli.py -repo <github_repo_url>              Extract text source files from a GitHub repository.
  python3 scripts/huashu_cli.py -repo-search "<query>"               Search the latest extracted repository semantic index.
  python3 scripts/huashu_cli.py -ocr <file>                         Optional OCR for images and scanned PDFs.
  python3 scripts/huashu_cli.py -x <url>                            Force X/Twitter post extraction.
  python3 scripts/huashu_cli.py -x-browser <url>                    Force browser-assisted X/Twitter post extraction.
  python3 scripts/huashu_cli.py -clipboard                          Import X/Twitter content from clipboard.
  python3 scripts/huashu_cli.py -organize-auto [--apply]            Organize legacy auto outputs into categorized folders.
  python3 scripts/huashu_cli.py <url>                               Smart docs-site crawl or single-page conversion.
  python3 scripts/huashu_cli.py -help                               Show this help message.

Usage (Interactive Mode):
  Simply run 'python3 scripts/huashu_cli.py' with no arguments to enter interactive mode:
  huashu> ingest Research.ris --limit 3
  huashu> search financial time series denoising
  huashu> note regime switching and noise control
  huashu> latest
  huashu> help
  huashu> exit
""")


def parse_interactive_command(cmd_line: str) -> tuple[str, str]:
    """
    Parses interactive command line input into command and arguments.
    """
    cmd_line = cmd_line.strip()
    if not cmd_line:
        return "", ""
    parts = cmd_line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    return cmd, arg


def interactive_loop():
    """
    Starts the interactive command-line loop.
    """
    print("="*60)
    print(" Huashu Local Ingestion & Auto-Research Council CLI Tool")
    print(" Type 'help' for commands, 'exit' or 'quit' to exit.")
    print("="*60 + "\n")

    while True:
        try:
            cmd_line = input("huashu> ")
            cmd, arg = parse_interactive_command(cmd_line)
            if not cmd:
                continue

            if cmd in ("exit", "quit", "q"):
                print("Exiting. Goodbye!")
                break
            elif cmd == "help":
                print_help()
            elif cmd == "ingest":
                if not arg:
                    print("[error] Command 'ingest' requires an input filename.")
                    continue
                # Split options like --limit
                arg_parts = arg.split()
                filename = arg_parts[0]
                limit = None
                if len(arg_parts) > 2 and arg_parts[1] == "--limit":
                    limit = arg_parts[2]
                run_ingest(filename, limit)
            elif cmd == "search":
                if not arg:
                    print("[error] Command 'search' requires a search query.")
                    continue
                # Strip quotes if the user typed them in interactive mode
                arg = arg.strip('\'"')
                run_search(arg)
            elif cmd == "note":
                if not arg:
                    print("[error] Command 'note' requires a question or topic.")
                    continue
                arg = arg.strip('\'"')
                run_note(arg)
            elif cmd == "latest":
                run_latest()
            elif cmd == "topics":
                run_dir, extra_args = parse_topics_args(arg.split() if arg else [])
                if not run_dir:
                    print("[error] No consensus run found.")
                    continue
                run_topics(run_dir, extra_args)
            elif cmd == "topics-latest":
                run_dir = get_latest_run_dir()
                if run_dir:
                    print(f"Using latest consensus run directory: {run_dir}")
                    run_topics(run_dir)
                else:
                    print("[error] No consensus run found.")
            elif cmd == "upload-ready":
                run_dir, extra_args = parse_topics_args(arg.split() if arg else [])
                if not run_dir:
                    print("[error] No consensus run found.")
                    continue
                extra_args.append("--upload-ready-only")
                run_topics(run_dir, extra_args)
            else:
                print(f"[error] Unknown command: '{cmd}'. Type 'help' for usage examples.")
        except KeyboardInterrupt:
            print("\nExiting. Goodbye!")
            break
        except Exception as e:
            print(f"[error] An unexpected error occurred: {e}")


def run_single_page_conversion(url: str, output_dir: str | None = None) -> bool:
    """Runs legacy single-page conversion to Markdown using html_to_md.py / any_to_md.py."""
    import datetime
    import subprocess
    import sys
    import urllib.parse

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    u = urllib.parse.urlparse(url)
    if "youtube.com" in u.netloc:
        q = urllib.parse.parse_qs(u.query)
        slug_text = "youtube-" + q.get("v", ["video"])[0]
    elif "youtu.be" in u.netloc:
        slug_text = "youtube-" + u.path.strip("/")
    elif u.netloc:
        slug_text = (u.netloc + u.path).strip("/")
    else:
        slug_text = url

    slug_text = re.sub(r"[^A-Za-z0-9ก-๙._-]+", "-", slug_text).strip("-")
    slug = slug_text[:90] or "content"

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    md_filename = f"{stamp}-{slug}.md"
    if output_dir:
        md_filepath = os.path.join(output_dir, md_filename)
    else:
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router
        md_filepath = output_router.route_output(url, md_filename, "web")

    print("[web/file] Converting to clean Markdown...")

    python_exe = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    html_to_md_script = os.path.join(REPO_ROOT, "scripts", "html_to_md.py")
    any_to_md_script = os.path.join(REPO_ROOT, "scripts", "any_to_md.py")

    # Run html_to_md.py
    cmd = [python_exe, html_to_md_script, url, "-o", md_filepath]
    res = subprocess.run(cmd)

    if res.returncode != 0:
        # Fallback to any_to_md.py
        cmd = [python_exe, any_to_md_script, url, "-o", md_filepath]
        res = subprocess.run(cmd)

    if res.returncode == 0 and os.path.exists(md_filepath):
        try:
            sys.path.append(os.path.join(REPO_ROOT, "scripts"))
            import output_router
            output_router.register_output(
                output_path=md_filepath,
                source=url,
                explicit_type="web",
                title=slug,
                status="success"
            )
        except Exception as e:
            print(f"[warn] Failed to register output in manifest/index: {e}")
        print(f"\n[ok] {url} → {md_filepath} (engine: html-to-markdown)")
        print("\nDone.")
        print("Markdown:")
        print(md_filepath)

        try:
            subprocess.run(["open", "-R", md_filepath])
        except Exception:
            pass
        return True
    else:
        print(f"[error] Failed to convert page: {url}")
        return False


def main() -> int:
    if len(sys.argv) < 2:
        # No arguments -> start interactive mode
        interactive_loop()
        return 0

    arg1 = sys.argv[1].lower()

    if arg1 in ("-organize-auto", "--organize-auto"):
        python_exe = sys.executable or "python3"
        organize_script = os.path.join(REPO_ROOT, "scripts", "organize_auto_outputs.py")
        cmd = [python_exe, organize_script]
        cmd.extend(sys.argv[2:])
        res = subprocess.run(cmd)
        return res.returncode

    if arg1 in ("-ocr", "--ocr", "ocr"):
        if len(sys.argv) < 3:
            print("[error] Please specify an image or PDF file.")
            print(f"Usage: python3 scripts/huashu_cli.py {sys.argv[1]} <file> [--engine paddleocr]")
            return 1
        python_exe = sys.executable or "python3"
        ocr_script = os.path.join(REPO_ROOT, "scripts", "ocr_extract.py")
        cmd = [python_exe, ocr_script]
        cmd.extend(sys.argv[2:])
        res = subprocess.run(cmd)
        return res.returncode

    if arg1 in ("-repo", "--repo", "repo"):
        if len(sys.argv) < 3:
            print("[error] Please specify a GitHub repository URL.")
            print(f"Usage: python3 scripts/huashu_cli.py {sys.argv[1]} <github_repo_url> [--max-files N] [--max-file-size-kb N]")
            return 1
        url = sys.argv[2]
        if not is_github_repo_url(url):
            print(f"[error] Not a supported GitHub repository URL: {url}")
            return 1
        python_exe = sys.executable or "python3"
        repo_script = os.path.join(REPO_ROOT, "scripts", "github_repo_extract.py")
        cmd = [python_exe, repo_script, url]
        cmd.extend(sys.argv[3:])
        res = subprocess.run(cmd)
        return res.returncode

    if arg1 in ("-repo-search", "--repo-search", "repo-search"):
        if len(sys.argv) < 3:
            print("[error] Please specify a repository search query.")
            print(f"Usage: python3 scripts/huashu_cli.py {sys.argv[1]} \"<query>\" [--repo-dir DIR] [-k N]")
            return 1
        query = sys.argv[2]
        import argparse

        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--repo-dir", default=None)
        parser.add_argument("-k", "--top-k", type=int, default=5)
        opts, _ = parser.parse_known_args(sys.argv[3:])
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import github_repo_extract

        return github_repo_extract.repo_search(query, run_dir=opts.repo_dir, top_k=opts.top_k)

    # Route X-specific commands or clipboard fallbacks first
    is_x_command = arg1 in ("-x", "--x", "-x-browser", "--x-browser")
    is_clipboard_command = arg1 in ("-clipboard", "--clipboard", "-x-clipboard", "--x-clipboard")

    if is_x_command or is_clipboard_command:
        python_exe = sys.executable or "python3"
        x_extract_script = os.path.join(REPO_ROOT, "scripts", "x_extract.py")
        cmd = [python_exe, x_extract_script]

        if is_clipboard_command:
            cmd.append("--clipboard")
            cmd.extend(sys.argv[2:])
        else:
            if len(sys.argv) < 3:
                print("[error] Please specify a target URL.")
                print(f"Usage: python3 scripts/huashu_cli.py {sys.argv[1]} <url> [options]")
                return 1
            url = sys.argv[2]
            if not url.startswith(("http://", "https://")):
                print(f"[error] Invalid URL: {url}")
                return 1
            if arg1 in ("-x-browser", "--x-browser"):
                cmd.append("--browser")
            cmd.append(url)
            cmd.extend(sys.argv[3:])

        res = subprocess.run(cmd)
        return res.returncode

    is_x_video_command = arg1 in ("-x-video", "--x-video", "-x-video-md", "--x-video-md")

    if is_x_video_command:
        if len(sys.argv) < 3:
            print("[error] Please specify a target X URL.")
            print(f"Usage: python3 scripts/huashu_cli.py {sys.argv[1]} <url> [options]")
            return 1
        url = sys.argv[2]
        extra_args = sys.argv[3:]
        if not url.startswith(("http://", "https://")):
            print(f"[error] Invalid URL: {url}")
            return 1
        python_exe = sys.executable or "python3"
        x_video_download_script = os.path.join(REPO_ROOT, "scripts", "x_video_download.py")
        cmd = [python_exe, x_video_download_script, url]
        cmd.extend(extra_args)
        res = subprocess.run(cmd)
        return res.returncode

    is_chatgpt_command = arg1 in ("-chatgpt", "--chatgpt", "-chatgpt-full", "--chatgpt-full")
    is_chatgpt_export_command = arg1 in ("-chatgpt-export", "--chatgpt-export")

    if is_chatgpt_command or is_chatgpt_export_command:
        if len(sys.argv) < 3:
            print(f"[error] Please specify a target ChatGPT URL or conversations.json export file.")
            print(f"Usage: python3 scripts/huashu_cli.py {sys.argv[1]} <url_or_file> [options]")
            return 1
        python_exe = sys.executable or "python3"
        chatgpt_script = os.path.join(REPO_ROOT, "scripts", "chatgpt_extract.py")
        cmd = [python_exe, chatgpt_script]
        if is_chatgpt_export_command:
            cmd.append("-chatgpt-export")
        elif arg1 in ("-chatgpt-full", "--chatgpt-full"):
            cmd.append("--full")
        cmd.extend(sys.argv[2:])
        res = subprocess.run(cmd)
        return res.returncode

    is_youtube_playlist_command = arg1 in ("-youtube-playlist", "--youtube-playlist")

    if is_youtube_playlist_command:
        if len(sys.argv) < 3:
            print("[error] Please specify a target YouTube playlist URL.")
            print(f"Usage: python3 scripts/huashu_cli.py {sys.argv[1]} <url> [--limit <num>]")
            return 1
        url = sys.argv[2]
        extra_args = sys.argv[3:]
        if not url.startswith(("http://", "https://")):
            print(f"[error] Invalid URL: {url}")
            return 1
        python_exe = sys.executable or "python3"
        playlist_extract_script = os.path.join(REPO_ROOT, "scripts", "youtube_playlist_extract.py")
        cmd = [python_exe, playlist_extract_script, url]
        cmd.extend(extra_args)
        res = subprocess.run(cmd)
        return res.returncode

    is_youtube_command = arg1 in ("-youtube", "--youtube")

    if is_youtube_command:
        if len(sys.argv) < 3:
            print("[error] Please specify a target YouTube URL.")
            print(f"Usage: python3 scripts/huashu_cli.py {sys.argv[1]} <url> [options]")
            return 1
        url = sys.argv[2]
        extra_args = sys.argv[3:]
        if not url.startswith(("http://", "https://")):
            print(f"[error] Invalid URL: {url}")
            return 1
        python_exe = sys.executable or "python3"
        youtube_extract_script = os.path.join(REPO_ROOT, "scripts", "youtube_extract.py")
        cmd = [python_exe, youtube_extract_script, url]
        cmd.extend(extra_args)
        res = subprocess.run(cmd)
        return res.returncode

    # Check if first argument is a URL, or -docs / -page command
    is_url_arg = arg1.startswith(("http://", "https://"))
    is_docs_command = arg1 in ("-docs", "--docs", "docs")
    is_page_command = arg1 in ("-page", "--page", "page")

    if is_docs_command or is_page_command or is_url_arg:
        # Resolve target URL and extra args
        if is_docs_command or is_page_command:
            if len(sys.argv) < 3:
                print(f"[error] Please specify a target URL.")
                print(f"Usage: python3 scripts/huashu_cli.py {arg1} <url> [options]")
                return 1
            url = sys.argv[2]
            extra_args = sys.argv[3:]
        else:
            url = sys.argv[1]
            extra_args = sys.argv[2:]

        # Ensure it's a valid URL
        if not url.startswith(("http://", "https://")):
            print(f"[error] Invalid URL: {url}")
            return 1

        if is_github_repo_url(url):
            python_exe = sys.executable or "python3"
            repo_script = os.path.join(REPO_ROOT, "scripts", "github_repo_extract.py")
            cmd = [python_exe, repo_script, url]
            cmd.extend(extra_args)
            res = subprocess.run(cmd)
            return res.returncode

        # Check if URL is a YouTube URL to route to youtube_extract.py or playlist
        is_youtube = False
        is_youtube_playlist = False
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            if ":" in netloc:
                netloc = netloc.split(":")[0]
            if netloc in ("youtube.com", "www.youtube.com", "youtu.be") or netloc.endswith((".youtube.com", ".youtu.be")):
                if "/playlist" in parsed.path:
                    is_youtube_playlist = True
                else:
                    is_youtube = True
        except Exception:
            pass

        if is_youtube_playlist:
            python_exe = sys.executable or "python3"
            playlist_extract_script = os.path.join(REPO_ROOT, "scripts", "youtube_playlist_extract.py")
            cmd = [python_exe, playlist_extract_script, url]
            cmd.extend(extra_args)
            res = subprocess.run(cmd)
            return res.returncode

        if is_youtube:
            python_exe = sys.executable or "python3"
            youtube_extract_script = os.path.join(REPO_ROOT, "scripts", "youtube_extract.py")
            cmd = [python_exe, youtube_extract_script, url]
            cmd.extend(extra_args)
            res = subprocess.run(cmd)
            return res.returncode

        # Check if URL is a ChatGPT conversation URL to route to chatgpt_extract.py
        is_chatgpt = False
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            if ":" in netloc:
                netloc = netloc.split(":")[0]
            if netloc in ("chatgpt.com", "chat.openai.com") or netloc.endswith((".chatgpt.com", ".chat.openai.com")):
                if "/c/" in parsed.path.lower():
                    is_chatgpt = True
        except Exception:
            pass

        if is_chatgpt:
            python_exe = sys.executable or "python3"
            chatgpt_script = os.path.join(REPO_ROOT, "scripts", "chatgpt_extract.py")
            cmd = [python_exe, chatgpt_script, url]
            cmd.extend(extra_args)
            res = subprocess.run(cmd)
            return res.returncode

        # Check if URL is an X video URL to route to x_video_download.py
        is_x_video = False
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            if ":" in netloc:
                netloc = netloc.split(":")[0]
            if netloc in ("x.com", "twitter.com", "mobile.twitter.com") or netloc.endswith((".x.com", ".twitter.com")):
                if "/video/" in parsed.path.lower():
                    is_x_video = True
        except Exception:
            pass

        if is_x_video:
            python_exe = sys.executable or "python3"
            x_video_download_script = os.path.join(REPO_ROOT, "scripts", "x_video_download.py")
            cmd = [python_exe, x_video_download_script, url]
            cmd.extend(extra_args)
            res = subprocess.run(cmd)
            return res.returncode

        # Check if URL is an X/Twitter URL to route to x_extract.py
        is_x = False
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            if ":" in netloc:
                netloc = netloc.split(":")[0]
            if netloc in ("x.com", "twitter.com", "mobile.twitter.com") or netloc.endswith((".x.com", ".twitter.com")):
                is_x = True
        except Exception:
            pass

        if is_x:
            python_exe = sys.executable or "python3"
            x_extract_script = os.path.join(REPO_ROOT, "scripts", "x_extract.py")
            cmd = [python_exe, x_extract_script, url]
            cmd.extend(extra_args)
            res = subprocess.run(cmd)
            return res.returncode

        # Parse extra options
        import argparse
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--max-pages", type=int, default=100)
        parser.add_argument("--delay", type=float, default=0.5)
        parser.add_argument("--output-dir", default=None)
        opts, _ = parser.parse_known_args(extra_args)

        # Route
        if is_docs_command:
            print(f"Forced docs crawl requested for: {url}")
            sys.path.append(os.path.join(REPO_ROOT, "scripts"))
            import docs_crawl
            out_dir = opts.output_dir
            return docs_crawl.crawl_docs(url, opts.max_pages, opts.delay, out_dir)

        elif is_page_command:
            print(f"Forced single page conversion requested for: {url}")
            success = run_single_page_conversion(url, opts.output_dir)
            return 0 if success else 1

        else:
            # Plain URL: auto-classify
            sys.path.append(os.path.join(REPO_ROOT, "scripts"))
            import docs_crawl
            print(f"Running smart classification on URL: {url}")
            is_docs, signals = docs_crawl.classify_url(url)

            if is_docs:
                print(f"Detected docs site. Crawling up to {opts.max_pages} pages...")
                print("Signals matched:")
                for sig in signals:
                    print(f" - {sig}")
                out_dir = opts.output_dir
                return docs_crawl.crawl_docs(url, opts.max_pages, opts.delay, out_dir)
            else:
                print("Detected single page. Converting one page...")
                success = run_single_page_conversion(url, opts.output_dir)
                return 0 if success else 1

    if arg1 in ("-help", "--help", "-h", "help"):
        print_help()
        return 0
    elif arg1 in ("-ingest", "--ingest", "ingest"):
        if len(sys.argv) < 3:
            print("[error] Please specify a Consensus CSV/RIS filename.")
            print("Usage: python3 scripts/huashu_cli.py -ingest <filename> [--limit <num>]")
            return 1
        filename = sys.argv[2]
        limit = None
        if len(sys.argv) > 4 and sys.argv[3] == "--limit":
            limit = sys.argv[4]
        success = run_ingest(filename, limit)
        return 0 if success else 1
    elif arg1 in ("-search", "--search", "search"):
        if len(sys.argv) < 3:
            print("[error] Please specify a search query.")
            print("Usage: python3 scripts/huashu_cli.py -search \"<query>\"")
            return 1
        query = sys.argv[2]
        success = run_search(query)
        return 0 if success else 1
    elif arg1 in ("-note", "--note", "note"):
        if len(sys.argv) < 3:
            print("[error] Please specify a research question or topic.")
            print("Usage: python3 scripts/huashu_cli.py -note \"<question>\"")
            return 1
        question = sys.argv[2]
        success = run_note(question)
        return 0 if success else 1
    elif arg1 in ("-latest", "--latest", "latest"):
        run_latest()
        return 0
    elif arg1 in ("-topics", "--topics", "topics"):
        run_dir, extra_args = parse_topics_args(sys.argv[2:])
        if not run_dir:
            print("[error] No consensus run found. Run -ingest first.")
            return 1
        success = run_topics(run_dir, extra_args)
        return 0 if success else 1
    elif arg1 in ("-topics-latest", "--topics-latest", "topics-latest"):
        run_dir = get_latest_run_dir()
        if not run_dir:
            print("[error] No consensus run found. Run -ingest first.")
            return 1
        print(f"Using latest consensus run directory: {run_dir}")
        extra_args = sys.argv[2:]
        success = run_topics(run_dir, extra_args)
        return 0 if success else 1
    elif arg1 in ("-upload-ready", "--upload-ready", "upload-ready"):
        run_dir, extra_args = parse_topics_args(sys.argv[2:])
        if not run_dir:
            print("[error] No consensus run found. Run -ingest first.")
            return 1
        extra_args.append("--upload-ready-only")
        success = run_topics(run_dir, extra_args)
        return 0 if success else 1
    else:
        local_file_result = run_local_file_conversion(sys.argv[1])
        if local_file_result >= 0:
            return local_file_result

        # Route to legacy any-to-markdown/clean Markdown script
        legacy_script = "/Users/AnundaB/bin/huashu"
        if os.path.exists(legacy_script):
            cmd = ["bash", legacy_script] + sys.argv[1:]
            res = subprocess.run(cmd)
            return res.returncode
        else:
            print(f"[error] Unknown argument: '{sys.argv[1]}'. Legacy script not found at {legacy_script}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
