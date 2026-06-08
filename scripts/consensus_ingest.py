#!/usr/bin/env python3
"""
consensus_ingest.py — Local Consensus research ingestion Phase 1 (Parser-Only Slice).

This script parses paper records from CSV or RIS files, generates stable record IDs,
and saves the normalized metadata output in a timestamped run folder.
No network requests or download operations are executed in this phase.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Local Consensus research ingestion Phase 1 (Parser-Only).",
    )
    p.add_argument(
        "input_file",
        help="Path to the input CSV or RIS file.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of records to process.",
    )
    p.add_argument(
        "--output-dir",
        default="outputs/consensus",
        help="Base directory for writing outputs. Default: outputs/consensus",
    )
    # The following options are parsed to maintain interface parity with PRD, but are unused in Phase 1
    p.add_argument(
        "--email",
        default="consensus-ingest@example.com",
        help="Email address for Unpaywall requests (unused in offline mode).",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between Unpaywall queries (unused in offline mode).",
    )
    return p.parse_args()


def clean_slug(text: str) -> str:
    """Helper to lowercase, remove non-alphanumeric chars, and squeeze whitespace to hyphens."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text.strip('-')


def generate_record_id(record: dict, existing_ids: set[str]) -> str:
    """Generates a stable, unique ID for a record in the form author-year-title_slug."""
    authors = record.get("authors") or []
    if authors:
        first_author = authors[0].strip()
        if ',' in first_author:
            # "Last, First" -> "Last"
            last_name = first_author.split(',')[0].strip()
        else:
            # "First Last" -> "Last"
            last_name = first_author.split()[-1].strip() if first_author.split() else "anon"
    else:
        last_name = "anon"

    author_slug = clean_slug(last_name)
    if not author_slug:
        author_slug = "anon"

    year = str(record.get("year") or "").strip()
    year_match = re.search(r'\b\d{4}\b', year)
    year_str = year_match.group(0) if year_match else "0000"

    title = record.get("title") or ""
    stop_words = {
        'a', 'an', 'the', 'of', 'in', 'on', 'at', 'by', 'for', 'with', 'and', 'or', 'but', 'to',
        'is', 'are', 'was', 'were', 'it', 'this', 'that', 'from', 'as', 'into', 'using'
    }
    title_words = [w for w in clean_slug(title).split('-') if w and w not in stop_words]
    title_slug = "-".join(title_words[:3]) if title_words else "paper"

    base_id = f"{author_slug}-{year_str}-{title_slug}"
    candidate = base_id
    counter = 1
    while candidate in existing_ids:
        candidate = f"{base_id}-{counter}"
        counter += 1

    existing_ids.add(candidate)
    return candidate


def parse_csv(filepath: str) -> list[dict]:
    """Parses Consensus CSV format into normalized record dicts."""
    records = []
    with open(filepath, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get("Title") or ""
            authors_str = row.get("Authors") or ""
            authors = [a.strip() for a in authors_str.split(",") if a.strip()]
            year = row.get("Year") or ""
            doi = row.get("DOI") or ""
            url = row.get("Consensus Link") or ""
            journal = row.get("Journal") or ""

            records.append({
                "title": title.strip(),
                "authors": authors,
                "year": year.strip(),
                "doi": doi.strip(),
                "url": url.strip(),
                "journal": journal.strip(),
                "source_file": os.path.basename(filepath),
            })
    return records


def parse_ris(filepath: str) -> list[dict]:
    """Parses Consensus RIS format into normalized record dicts."""
    records = []
    current_record = None
    ris_line_pat = re.compile(r'^([A-Z0-9]{2})\s*-\s*(.*)$')

    with open(filepath, mode="r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            match = ris_line_pat.match(line)
            if not match:
                continue

            tag, val = match.groups()
            val = val.strip()

            if tag == "TY":
                current_record = {
                    "title": "",
                    "authors": [],
                    "year": "",
                    "doi": "",
                    "url": "",
                    "journal": "",
                    "source_file": os.path.basename(filepath),
                }
            elif current_record is not None:
                if tag in ("TI", "T1"):
                    current_record["title"] = val
                elif tag == "AU":
                    current_record["authors"].append(val)
                elif tag in ("PY", "Y1"):
                    year_match = re.search(r'\b\d{4}\b', val)
                    current_record["year"] = year_match.group(0) if year_match else val
                elif tag == "DO":
                    current_record["doi"] = val
                elif tag == "UR":
                    current_record["url"] = val
                elif tag in ("JO", "JF", "T2", "JA"):
                    current_record["journal"] = val
                elif tag == "ER":
                    records.append(current_record)
                    current_record = None

    if current_record:
        records.append(current_record)

    return records


def main() -> int:
    args = parse_args()

    input_path = args.input_file
    if not os.path.exists(input_path):
        sys.stderr.write(f"[error] Input file does not exist: {input_path}\n")
        return 1

    # Determine file type and parse
    _, ext = os.path.splitext(input_path.lower())
    if ext == ".csv":
        raw_records = parse_csv(input_path)
    elif ext == ".ris":
        raw_records = parse_ris(input_path)
    else:
        sys.stderr.write(f"[error] Unsupported file format '{ext}'. Must be .csv or .ris\n")
        return 1

    if not raw_records:
        sys.stderr.write(f"[warn] No records found in {input_path}\n")
        return 0

    # Limit records if requested
    if args.limit is not None:
        raw_records = raw_records[:args.limit]

    # Initialize output directory structure
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_name = f"{timestamp}-consensus-ingest"
    run_dir = os.path.join(args.output_dir, run_name)
    
    pdfs_dir = os.path.join(run_dir, "pdfs")
    md_dir = os.path.join(run_dir, "md")
    metadata_dir = os.path.join(run_dir, "metadata")

    os.makedirs(pdfs_dir, exist_ok=True)
    os.makedirs(md_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    existing_ids = set()
    manifest_rows = []
    jsonl_records = []

    # Summary statistics
    total_records = len(raw_records)
    records_with_doi = 0
    records_with_url = 0

    for record in raw_records:
        record_id = generate_record_id(record, existing_ids)
        title = record.get("title") or ""
        doi = record.get("doi") or ""
        url = record.get("url") or ""

        if doi:
            records_with_doi += 1
        if url:
            records_with_url += 1

        # Phase 1: In parser-only phase, status is strictly parsed_only
        status = "parsed_only"
        error_detail = "Phase 1 parser-only; resolver not run"

        manifest_rows.append({
            "record_id": record_id,
            "title": title,
            "authors": "; ".join(record.get("authors") or []),
            "year": record.get("year") or "",
            "doi": doi,
            "url": url,
            "status": status,
            "error_detail": error_detail
        })

        jsonl_records.append({
            "record_id": record_id,
            "title": title,
            "authors": record.get("authors") or [],
            "year": record.get("year") or "",
            "doi": doi,
            "url": url,
            "journal": record.get("journal") or "",
            "source_file": record.get("source_file") or "",
            "resolver_results": {
                "status": status,
                "resolver_status": "not_started",
                "resolution_note": "Phase 1 parser-only; resolver not run",
                "unpaywall_queried": False,
                "oa_pdf_url": None,
                "pdf_download_path": None,
                "html_fallback_attempted": False,
                "markdown_path": None,
                "error_detail": error_detail
            }
        })

    # Write metadata/manifest.csv
    manifest_path = os.path.join(metadata_dir, "manifest.csv")
    with open(manifest_path, mode="w", encoding="utf-8", newline="") as csvfile:
        fieldnames = ["record_id", "title", "authors", "year", "doi", "url", "status", "error_detail"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest_rows:
            writer.writerow(row)

    # Write metadata/papers.jsonl
    papers_path = os.path.join(metadata_dir, "papers.jsonl")
    with open(papers_path, mode="w", encoding="utf-8") as jsonlfile:
        for r in jsonl_records:
            jsonlfile.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Clear terminal output summary
    print(f"Total records:      {total_records}")
    print(f"Records with DOI:   {records_with_doi}")
    print(f"Records with URL:   {records_with_url}")
    print(f"Output folder path: {run_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
