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
        description="Local Consensus research ingestion Phase 1 & 2B (Offline).",
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
    p.add_argument(
        "--mock-resolver",
        action="store_true",
        help="Run in Phase 2B offline mock resolver harness mode.",
    )
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

    # Resolver stats (Phase 2)
    downloaded_pdfs = 0
    converted_htmls = 0
    no_oa_pdf = 0
    failed_attempts = 0
    manual_needed = 0

    for record in raw_records:
        record_id = generate_record_id(record, existing_ids)
        title = record.get("title") or ""
        doi = record.get("doi") or ""
        url = record.get("url") or ""

        if doi:
            records_with_doi += 1
        if url:
            records_with_url += 1

        # Defaults matching Phase 1 baseline
        status = "parsed_only"
        resolver_status = "not_started"
        resolution_note = "Phase 1 parser-only; resolver not run"
        oa_pdf_url = None
        pdf_download_path = None
        html_fallback_attempted = False
        markdown_path = None
        error_detail = ""
        resolver_mode = "offline_parser"
        network_used = False
        real_download_performed = False
        huashu_conversion_performed = False
        mock_artifact = False

        # Phase 2B Mock Resolver Logic
        if args.mock_resolver:
            resolver_mode = "mock"
            if doi:
                if "10.1371" in doi or "10.1186" in doi:
                    # Success PDF path
                    status = "success_pdf"
                    resolver_status = "completed"
                    resolution_note = "Mock only: simulated OA PDF success using placeholder artifact; no network/download/conversion run"
                    oa_pdf_url = "http://localhost/mock/paper.pdf"
                    pdf_download_path = f"pdfs/{record_id}.pdf"
                    markdown_path = f"md/{record_id}.md"
                    mock_artifact = True
                    downloaded_pdfs += 1

                    # Create mock files
                    pdf_full_path = os.path.join(pdfs_dir, f"{record_id}.pdf")
                    md_full_path = os.path.join(md_dir, f"{record_id}.md")
                    with open(pdf_full_path, "wb") as f:
                        f.write(b"%PDF-1.4\n% MOCK PLACEHOLDER\n")
                    with open(md_full_path, "w", encoding="utf-8") as f:
                        f.write(f"# MOCK PLACEHOLDER\n\n# {title}\nMock parsed markdown from simulated PDF.\n")
                elif "10.1145" in doi or "10.2139" in doi:
                    # Non-OA DOI but has URL fallback
                    if url:
                        status = "success_html"
                        resolver_status = "html_fallback"
                        resolution_note = "Mock only: simulated HTML fallback using placeholder Markdown; no network/fetch/conversion run"
                        oa_pdf_url = None
                        pdf_download_path = None
                        markdown_path = f"md/{record_id}.md"
                        html_fallback_attempted = True
                        mock_artifact = True
                        converted_htmls += 1

                        # Create mock file
                        md_full_path = os.path.join(md_dir, f"{record_id}.md")
                        with open(md_full_path, "w", encoding="utf-8") as f:
                            f.write(f"# MOCK PLACEHOLDER\n\n# {title}\nMock parsed markdown from simulated HTML.\n")
                    else:
                        status = "failed"
                        resolver_status = "failed"
                        resolution_note = "Mock only: simulated download failure/timeout; no network run"
                        failed_attempts += 1
                elif "10.3390" in doi:
                    # PDF lookup OA found, download/conversion fails
                    status = "failed"
                    resolver_status = "failed"
                    resolution_note = "Mock only: simulated download failure/timeout; no network run"
                    failed_attempts += 1
                elif "10.1002" in doi:
                    # DOI exists, no OA PDF, no URL fallback
                    status = "no_oa_pdf"
                    resolver_status = "unpaywall_lookup"
                    resolution_note = "Mock only: simulated Unpaywall lookup finding no OA PDF; no network run"
                    no_oa_pdf += 1
                else:
                    status = "no_oa_pdf"
                    resolver_status = "unpaywall_lookup"
                    resolution_note = "Mock only: simulated Unpaywall lookup finding no OA PDF; no network run"
                    no_oa_pdf += 1
            else:
                # No DOI
                if url:
                    status = "success_html"
                    resolver_status = "html_fallback"
                    resolution_note = "Mock only: simulated HTML fallback using placeholder Markdown; no network/fetch/conversion run"
                    markdown_path = f"md/{record_id}.md"
                    html_fallback_attempted = True
                    mock_artifact = True
                    converted_htmls += 1

                    md_full_path = os.path.join(md_dir, f"{record_id}.md")
                    with open(md_full_path, "w", encoding="utf-8") as f:
                        f.write(f"# MOCK PLACEHOLDER\n\n# {title}\nMock parsed markdown from simulated HTML.\n")
                else:
                    status = "manual_needed"
                    resolver_status = "not_started"
                    resolution_note = "No DOI and no URL available"
                    manual_needed += 1
        else:
            # Phase 1 baseline error detail mapping
            if not doi and not url:
                status = "manual_needed"
                error_detail = "No DOI and no URL available"
                manual_needed += 1
            else:
                error_detail = "Phase 1 parser-only; resolver not run"

        manifest_rows.append({
            "record_id": record_id,
            "title": title,
            "authors": "; ".join(record.get("authors") or []),
            "year": record.get("year") or "",
            "doi": doi,
            "url": url,
            "status": status,
            "resolver_status": resolver_status,
            "resolution_note": resolution_note,
            "pdf_download_path": pdf_download_path or "",
            "markdown_path": markdown_path or "",
            "resolver_mode": resolver_mode,
            "network_used": network_used,
            "real_download_performed": real_download_performed,
            "huashu_conversion_performed": huashu_conversion_performed,
            "mock_artifact": mock_artifact
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
                "resolver_status": resolver_status,
                "resolution_note": resolution_note,
                "unpaywall_queried": True if (args.mock_resolver and doi) else False,
                "oa_pdf_url": oa_pdf_url,
                "pdf_download_path": pdf_download_path,
                "html_fallback_attempted": html_fallback_attempted,
                "markdown_path": markdown_path,
                "error_detail": error_detail or resolution_note,
                "resolver_mode": resolver_mode,
                "network_used": network_used,
                "real_download_performed": real_download_performed,
                "huashu_conversion_performed": huashu_conversion_performed,
                "mock_artifact": mock_artifact
            }
        })

    # Write metadata/manifest.csv
    manifest_path = os.path.join(metadata_dir, "manifest.csv")
    with open(manifest_path, mode="w", encoding="utf-8", newline="") as csvfile:
        fieldnames = [
            "record_id", "title", "authors", "year", "doi", "url",
            "status", "resolver_status", "resolution_note",
            "pdf_download_path", "markdown_path",
            "resolver_mode", "network_used", "real_download_performed",
            "huashu_conversion_performed", "mock_artifact"
        ]
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
    if args.mock_resolver:
        print(f"Downloaded PDFs:    {downloaded_pdfs}")
        print(f"Converted HTMLs:    {converted_htmls}")
        print(f"No OA PDF (No PDF):  {no_oa_pdf}")
        print(f"Failed Attempt:      {failed_attempts}")
        print(f"Manual Retrieval:    {manual_needed}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
