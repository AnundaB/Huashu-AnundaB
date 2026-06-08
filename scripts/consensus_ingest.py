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
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Local Consensus research ingestion pipeline. Handles parsing, resolving, downloading, and converting papers.",
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
        help="Run in Phase 2B offline mock resolver harness mode (simulated pipeline).",
    )
    p.add_argument(
        "--resolve-doi",
        action="store_true",
        help="Run in Phase 2C real DOI resolver mode using live API lookups.",
    )
    p.add_argument(
        "--download-pdf",
        action="store_true",
        help="Enable downloading of open-access PDFs when resolved (requires --resolve-doi or --mock-resolver).",
    )
    p.add_argument(
        "--html-fallback",
        action="store_true",
        help="Enable public HTML article extraction when PDF is unavailable (requires --resolve-doi or --mock-resolver).",
    )
    p.add_argument(
        "--convert-md",
        action="store_true",
        help="Enable PDF-to-Markdown conversion for downloaded PDFs using Microsoft MarkItDown (requires --download-pdf).",
    )
    p.add_argument(
        "--email",
        default="consensus-ingest@example.com",
        help="Email address for Unpaywall and OpenAlex requests.",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between API queries (polite rate limit).",
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


def resolve_doi_real(doi: str, email: str) -> tuple[bool, str, int | None, bool, str | None, str | None, str]:
    """
    Resolves a DOI to its Open Access status, PDF URL, and landing page URL.
    Returns: (success, resolver_source, http_status, is_oa, pdf_url, landing_page_url, error_msg)
    """
    doi = doi.strip()
    unpaywall_url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(unpaywall_url, headers={"User-Agent": "consensus-ingest-agent"})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            status_code = response.getcode()
            data = json.loads(response.read().decode("utf-8"))
            is_oa = bool(data.get("is_oa"))
            pdf_url = None
            landing_page_url = None
            best_loc = data.get("best_oa_location")
            if best_loc:
                pdf_url = best_loc.get("url_for_pdf")
                landing_page_url = best_loc.get("url")
            return True, "unpaywall", status_code, is_oa, pdf_url, landing_page_url, ""
    except urllib.error.HTTPError as e:
        status_code = e.code
        try:
            err_body = e.read().decode("utf-8")
            err_msg = f"HTTP Error {e.code}: {e.reason} ({err_body.strip()})"
        except Exception:
            err_msg = f"HTTP Error {e.code}: {e.reason}"

        # Fallback to OpenAlex
        openalex_url = f"https://api.openalex.org/works/https://doi.org/{doi}"
        try:
            req = urllib.request.Request(
                openalex_url,
                headers={"User-Agent": f"mailto:{email}"}
            )
            with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                alex_status = response.getcode()
                data = json.loads(response.read().decode("utf-8"))
                oa = data.get("open_access", {})
                is_oa = bool(oa.get("is_oa"))
                pdf_url = None
                landing_page_url = None
                best_loc = data.get("best_oa_location")
                if best_loc:
                    pdf_url = best_loc.get("pdf_url")
                    landing_page_url = best_loc.get("landing_page_url")
                return True, "openalex", alex_status, is_oa, pdf_url, landing_page_url, ""
        except urllib.error.HTTPError as e2:
            return False, "unpaywall", status_code, False, None, None, f"Unpaywall failed with {status_code}. OpenAlex fallback failed with HTTP {e2.code}: {e2.reason}."
        except Exception as e2:
            return False, "unpaywall", status_code, False, None, None, f"Unpaywall failed with {status_code}. OpenAlex fallback error: {str(e2)}."
    except Exception as e:
        # General exception (DNS, connection reset, timeout)
        openalex_url = f"https://api.openalex.org/works/https://doi.org/{doi}"
        try:
            req = urllib.request.Request(
                openalex_url,
                headers={"User-Agent": f"mailto:{email}"}
            )
            with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                alex_status = response.getcode()
                data = json.loads(response.read().decode("utf-8"))
                oa = data.get("open_access", {})
                is_oa = bool(oa.get("is_oa"))
                pdf_url = None
                landing_page_url = None
                best_loc = data.get("best_oa_location")
                if best_loc:
                    pdf_url = best_loc.get("pdf_url")
                    landing_page_url = best_loc.get("landing_page_url")
                return True, "openalex", alex_status, is_oa, pdf_url, landing_page_url, ""
        except urllib.error.HTTPError as e2:
            return False, "none", None, False, None, None, f"Unpaywall query error: {str(e)}. OpenAlex fallback failed with HTTP {e2.code}: {e2.reason}."
        except Exception as e2:
            return False, "none", None, False, None, None, f"Unpaywall query error: {str(e)}. OpenAlex fallback error: {str(e2)}."


def check_markdown_quality(file_path: str, title: str, doi: str) -> tuple[str, str]:
    """
    Checks the quality of the generated Markdown file.
    Returns: (quality_status, quality_note)
    Possible statuses: 'passed', 'empty_markdown', 'bad_extraction', 'needs_manual_review'
    """
    if not os.path.exists(file_path):
        return "empty_markdown", "Markdown file does not exist"
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception as e:
        return "bad_extraction", f"Failed to read file: {str(e)}"
        
    if not content:
        return "empty_markdown", "Markdown file is empty"
        
    # Check length
    if len(content) < 100:
        return "bad_extraction", f"Content is too short ({len(content)} chars)"
        
    # Check for nav/footer noise or error boilerplate
    content_lower = content.lower()
    error_keywords = [
        "403 forbidden", "404 not found", "access denied", "robot check", "please enable js",
        "cloudflare", "just a moment", "checking your browser", "hcaptcha", "recaptcha"
    ]
    for kw in error_keywords:
        if kw in content_lower:
            return "bad_extraction", f"Error page/boilerplate pattern found: '{kw}'"
            
    # Check for too few lines
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    if len(lines) < 3:
        return "bad_extraction", "Content has too few lines"
        
    # Check for title keywords
    title_words = [w.lower() for w in re.sub(r'[^a-zA-Z0-9\s]', '', title).split() if len(w) > 3]
    if title_words:
        found_title_words = [w for w in title_words if w in content_lower]
        if len(found_title_words) == 0:
            return "needs_manual_review", "None of the title keywords were found in the extracted text"
            
    return "passed", "Quality checks passed"


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
    seen_dois = set()
    seen_titles = set()
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
        resolver_source = "none"
        resolver_http_status = None
        article_url = None
        real_download_performed = False
        huashu_conversion_performed = False
        html_to_md_performed = False
        mock_artifact = False
        download_http_status = None
        download_error_detail = ""
        conversion_status = None
        conversion_error_detail = ""
        extraction_quality_status = "not_applicable"
        extraction_quality_note = "No Markdown generated"

        # Check duplicate
        is_duplicate = False
        if doi and doi in seen_dois:
            is_duplicate = True
        elif title and title.lower() in seen_titles:
            is_duplicate = True

        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title.lower())

        if is_duplicate:
            status = "duplicate"
            resolver_status = "not_started"
            resolution_note = "Duplicate record detected; skipping processing"
            extraction_quality_status = "duplicate"
            extraction_quality_note = "Duplicate paper in input batch"

        # Phase 2C Real DOI Resolver Logic
        if args.resolve_doi and not is_duplicate:
            resolver_mode = "real"
            if doi:
                network_used = True

                # Polite rate limiting
                time.sleep(args.delay)

                success, source, http_status, is_oa, pdf_url, landing_url, err_msg = resolve_doi_real(doi, args.email)
                resolver_source = source
                resolver_http_status = http_status
                oa_pdf_url = pdf_url
                article_url = landing_url

                if success:
                    if is_oa and pdf_url:
                        resolver_status = "completed"
                        if args.download_pdf:
                            pdf_filename = f"{record_id}.pdf"
                            pdf_dest_path = os.path.join(pdfs_dir, pdf_filename)

                            try:
                                req = urllib.request.Request(
                                    pdf_url,
                                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                                )
                                ctx = ssl.create_default_context()
                                with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
                                    download_http_status = response.getcode()
                                    pdf_data = response.read()

                                if len(pdf_data) >= 4 and pdf_data.startswith(b"%PDF"):
                                    with open(pdf_dest_path, "wb") as f:
                                        f.write(pdf_data)
                                    status = "success_pdf"
                                    pdf_download_path = f"pdfs/{pdf_filename}"
                                    real_download_performed = True
                                    downloaded_pdfs += 1
                                    resolution_note = f"Resolved and downloaded PDF successfully via {source} API"

                                    if args.convert_md:
                                        # Convert PDF to Markdown using scripts/any_to_md.py
                                        md_filename = f"{record_id}.md"
                                        md_dest_path = os.path.join(md_dir, md_filename)
                                        try:
                                            res_conv = subprocess.run(
                                                [sys.executable, "scripts/any_to_md.py", pdf_dest_path, "-o", md_dest_path, "--quiet"],
                                                capture_output=True, text=True, timeout=60
                                            )
                                            if res_conv.returncode == 0:
                                                huashu_conversion_performed = True
                                                conversion_status = "completed"
                                                markdown_path = f"md/{md_filename}"
                                                resolution_note += " and converted to Markdown successfully"
                                            else:
                                                conversion_status = "failed"
                                                conversion_error_detail = res_conv.stderr.strip()
                                                resolution_note += f" but PDF to MD conversion failed: {conversion_error_detail}"
                                        except Exception as conv_err:
                                            conversion_status = "failed"
                                            conversion_error_detail = str(conv_err)
                                            resolution_note += f" but PDF to MD conversion exception: {conversion_error_detail}"
                                else:
                                    status = "invalid_pdf"
                                    download_error_detail = "Invalid PDF header: does not start with %PDF"
                                    resolution_note = "Downloaded file is not a valid PDF"
                                    if os.path.exists(pdf_dest_path):
                                        try:
                                            os.remove(pdf_dest_path)
                                        except Exception:
                                            pass
                            except urllib.error.HTTPError as dl_err:
                                download_http_status = dl_err.code
                                download_error_detail = f"HTTP Error {dl_err.code}: {dl_err.reason}"
                                if dl_err.code in (401, 403):
                                    status = "download_forbidden"
                                else:
                                    status = "download_failed"
                                resolution_note = f"OA PDF download failed: {download_error_detail}"
                            except Exception as dl_err:
                                download_error_detail = str(dl_err)
                                status = "download_failed"
                                resolution_note = f"OA PDF download failed: {str(dl_err)}"
                        else:
                            status = "resolved_pdf"
                            resolution_note = "OA PDF resolved successfully; download not requested"
                    else:
                        status = "no_oa_pdf"
                        resolution_note = f"DOI resolved via {source} but no OA PDF found"
                        no_oa_pdf += 1
                else:
                    status = "failed"
                    resolver_status = "failed"
                    error_detail = err_msg
                    resolution_note = f"DOI resolver query failed: {err_msg}"
                    failed_attempts += 1

                if status in ("download_forbidden", "download_failed", "invalid_pdf", "no_oa_pdf", "resolved_pdf", "failed"):
                    if args.html_fallback:
                        url_to_use = landing_url or url
                        if url_to_use:
                            resolver_status = "html_fallback"
                            md_filename = f"{record_id}.md"
                            md_dest_path = os.path.join(md_dir, md_filename)
                            time.sleep(args.delay)
                            html_to_md_performed = True
                            try:
                                res = subprocess.run(
                                    [sys.executable, "scripts/html_to_md.py", url_to_use, "-o", md_dest_path, "--quiet"],
                                    capture_output=True, text=True, timeout=30
                                )
                                if res.returncode == 0:
                                    status = "success_html"
                                    markdown_path = f"md/{md_filename}"
                                    huashu_conversion_performed = True
                                    converted_htmls += 1
                                    resolution_note = f"DOI lookup / PDF download failed or skipped, but HTML landing page converted successfully"
                                else:
                                    stderr_lower = res.stderr.lower()
                                    if any(x in stderr_lower for x in ("403", "forbidden", "401", "unauthorized")):
                                        status = "manual_needed"
                                        resolution_note = f"HTML fallback forbidden: paywalled or blocked; do not bypass"
                                        error_detail = f"HTML error: {res.stderr.strip()}"
                                        manual_needed += 1
                                    else:
                                        status = "failed"
                                        resolution_note = f"HTML fallback failed: {res.stderr.strip()}"
                                        error_detail = f"HTML error: {res.stderr.strip()}"
                                        failed_attempts += 1
                            except Exception as html_err:
                                status = "failed"
                                resolution_note = f"HTML fallback exception: {str(html_err)}"
                                error_detail = f"HTML error: {str(html_err)}"
                                failed_attempts += 1
                        else:
                            if status == "download_forbidden":
                                status = "manual_needed"
                                resolution_note = f"OA PDF download forbidden ({download_error_detail}) and no fallback URL exists"
                                error_detail = f"PDF download forbidden: {download_error_detail}"
                                manual_needed += 1
                            elif status == "resolved_pdf":
                                pass
                            elif status == "no_oa_pdf":
                                pass
                            else:
                                error_detail = f"Failed to download PDF from {pdf_url}: {download_error_detail}"
                                resolution_note = f"OA PDF download failed ({download_error_detail}) and no fallback URL exists"
                                failed_attempts += 1
                    else:
                        if status == "download_forbidden":
                            status = "manual_needed"
                            manual_needed += 1
                        elif status == "resolved_pdf":
                            pass
                        elif status == "no_oa_pdf":
                            pass
                        elif status in ("download_failed", "invalid_pdf", "failed"):
                            failed_attempts += 1
            else:
                if url:
                    if args.html_fallback:
                        network_used = True
                        resolver_status = "html_fallback"
                        md_filename = f"{record_id}.md"
                        md_dest_path = os.path.join(md_dir, md_filename)
                        time.sleep(args.delay)
                        html_to_md_performed = True
                        try:
                            res = subprocess.run(
                                [sys.executable, "scripts/html_to_md.py", url, "-o", md_dest_path, "--quiet"],
                                capture_output=True, text=True, timeout=30
                            )
                            if res.returncode == 0:
                                status = "success_html"
                                markdown_path = f"md/{md_filename}"
                                huashu_conversion_performed = True
                                converted_htmls += 1
                                resolution_note = "No DOI available; HTML landing page converted successfully"
                            else:
                                stderr_lower = res.stderr.lower()
                                if any(x in stderr_lower for x in ("403", "forbidden", "401", "unauthorized")):
                                    status = "manual_needed"
                                    resolution_note = "No DOI available. HTML fallback forbidden: paywalled or blocked; do not bypass"
                                    error_detail = res.stderr.strip()
                                    manual_needed += 1
                                else:
                                    status = "failed"
                                    resolution_note = f"No DOI available; HTML fallback failed: {res.stderr.strip()}"
                                    error_detail = res.stderr.strip()
                                    failed_attempts += 1
                        except Exception as html_err:
                            status = "failed"
                            resolution_note = f"No DOI available; HTML fallback exception: {str(html_err)}"
                            error_detail = str(html_err)
                            failed_attempts += 1
                    else:
                        status = "manual_needed"
                        resolver_status = "not_started"
                        resolution_note = "No DOI available; HTML fallback disabled"
                        manual_needed += 1
                else:
                    status = "manual_needed"
                    resolver_status = "not_started"
                    resolution_note = "No DOI and no URL available"
                    manual_needed += 1

        # Phase 2B Mock Resolver Logic
        elif args.mock_resolver and not is_duplicate:
            resolver_mode = "mock"
            if doi:
                if "10.1371" in doi or "10.1186" in doi:
                    # Success PDF path
                    resolver_status = "completed"
                    oa_pdf_url = "http://localhost/mock/paper.pdf"
                    
                    if args.download_pdf:
                        status = "success_pdf"
                        pdf_download_path = f"pdfs/{record_id}.pdf"
                        download_http_status = 200
                        downloaded_pdfs += 1
                        mock_artifact = True

                        # Create mock files
                        pdf_full_path = os.path.join(pdfs_dir, f"{record_id}.pdf")
                        with open(pdf_full_path, "wb") as f:
                            f.write(b"%PDF-1.4\n% MOCK PLACEHOLDER\n")

                        if args.convert_md:
                            markdown_path = f"md/{record_id}.md"
                            conversion_status = "completed"
                            conversion_error_detail = ""
                            md_full_path = os.path.join(md_dir, f"{record_id}.md")
                            with open(md_full_path, "w", encoding="utf-8") as f:
                                f.write(f"# MOCK PLACEHOLDER\n\n# {title}\nMock parsed markdown from simulated PDF. This dummy text is here to ensure the file is longer than the quality gate threshold.\n")
                    else:
                        status = "resolved_pdf"
                        resolution_note = "Mock only: simulated OA PDF success; download not requested"
                elif "10.1145" in doi or "10.2139" in doi:
                    # Non-OA DOI but has URL fallback
                    if url:
                        if args.html_fallback:
                            status = "success_html"
                            resolver_status = "html_fallback"
                            resolution_note = "Mock only: simulated HTML fallback using placeholder Markdown; no network/fetch/conversion run"
                            oa_pdf_url = None
                            pdf_download_path = None
                            markdown_path = f"md/{record_id}.md"
                            html_fallback_attempted = True
                            mock_artifact = True
                            converted_htmls += 1
                            download_http_status = None

                            # Create mock file
                            md_full_path = os.path.join(md_dir, f"{record_id}.md")
                            with open(md_full_path, "w", encoding="utf-8") as f:
                                f.write(f"# MOCK PLACEHOLDER\n\n# {title}\nMock parsed markdown from simulated HTML. This dummy text is here to ensure the file is longer than the quality gate threshold.\n")
                        else:
                            status = "manual_needed"
                            resolver_status = "not_started"
                            resolution_note = "Mock only: DOI has no OA PDF, and HTML fallback not requested"
                            manual_needed += 1
                    else:
                        status = "failed"
                        resolver_status = "failed"
                        resolution_note = "Mock only: simulated download failure/timeout; no network run"
                        download_error_detail = "Mock only: simulated download failure/timeout"
                        failed_attempts += 1
                elif "10.3390" in doi:
                    # PDF lookup OA found, download/conversion fails
                    status = "download_failed"
                    resolver_status = "failed"
                    resolution_note = "Mock only: simulated download failure/timeout; no network run"
                    download_error_detail = "Mock only: simulated download failure/timeout"
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
                    if args.html_fallback:
                        status = "success_html"
                        resolver_status = "html_fallback"
                        resolution_note = "Mock only: simulated HTML fallback using placeholder Markdown; no network/fetch/conversion run"
                        markdown_path = f"md/{record_id}.md"
                        html_fallback_attempted = True
                        mock_artifact = True
                        converted_htmls += 1

                        md_full_path = os.path.join(md_dir, f"{record_id}.md")
                        with open(md_full_path, "w", encoding="utf-8") as f:
                            f.write(f"# MOCK PLACEHOLDER\n\n# {title}\nMock parsed markdown from simulated HTML. This dummy text is here to ensure the file is longer than the quality gate threshold.\n")
                    else:
                        status = "manual_needed"
                        resolver_status = "not_started"
                        resolution_note = "Mock only: No DOI available; HTML fallback disabled"
                        manual_needed += 1
                else:
                    status = "manual_needed"
                    resolver_status = "not_started"
                    resolution_note = "No DOI and no URL available"
                    manual_needed += 1
        elif not is_duplicate:
            # Phase 1 baseline error detail mapping
            if not doi and not url:
                status = "manual_needed"
                error_detail = "No DOI and no URL available"
                manual_needed += 1
            else:
                error_detail = "Phase 1 parser-only; resolver not run"

        # Run quality checks if Markdown was generated successfully
        if status in ("success_pdf", "success_html") and markdown_path:
            md_full_path = os.path.join(run_dir, markdown_path)
            q_status, q_note = check_markdown_quality(md_full_path, title, doi)
            extraction_quality_status = q_status
            extraction_quality_note = q_note
            if q_status != "passed":
                status = q_status

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
            "resolver_source": resolver_source,
            "resolver_http_status": resolver_http_status if resolver_http_status is not None else "",
            "oa_pdf_url": oa_pdf_url or "",
            "article_url": article_url or "",
            "real_download_performed": real_download_performed,
            "huashu_conversion_performed": huashu_conversion_performed,
            "html_to_md_performed": html_to_md_performed,
            "mock_artifact": mock_artifact,
            "download_http_status": download_http_status if download_http_status is not None else "",
            "download_error_detail": download_error_detail,
            "conversion_status": conversion_status if conversion_status is not None else "",
            "conversion_error_detail": conversion_error_detail,
            "extraction_quality_status": extraction_quality_status,
            "extraction_quality_note": extraction_quality_note
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
                "unpaywall_queried": True if ((args.mock_resolver or args.resolve_doi) and doi) else False,
                "oa_pdf_url": oa_pdf_url,
                "pdf_download_path": pdf_download_path,
                "html_fallback_attempted": html_fallback_attempted,
                "markdown_path": markdown_path,
                "error_detail": error_detail or resolution_note,
                "resolver_mode": resolver_mode,
                "network_used": network_used,
                "resolver_source": resolver_source,
                "resolver_http_status": resolver_http_status,
                "article_url": article_url,
                "real_download_performed": real_download_performed,
                "huashu_conversion_performed": huashu_conversion_performed,
                "html_to_md_performed": html_to_md_performed,
                "mock_artifact": mock_artifact,
                "download_http_status": download_http_status,
                "download_error_detail": download_error_detail,
                "conversion_status": conversion_status,
                "conversion_error_detail": conversion_error_detail,
                "extraction_quality_status": extraction_quality_status,
                "extraction_quality_note": extraction_quality_note
            }
        })

    # Write metadata/manifest.csv
    manifest_path = os.path.join(metadata_dir, "manifest.csv")
    with open(manifest_path, mode="w", encoding="utf-8", newline="") as csvfile:
        fieldnames = [
            "record_id", "title", "authors", "year", "doi", "url",
            "status", "resolver_status", "resolution_note",
            "pdf_download_path", "markdown_path",
            "resolver_mode", "network_used", "resolver_source", "resolver_http_status",
            "oa_pdf_url", "article_url", "real_download_performed",
            "huashu_conversion_performed", "html_to_md_performed", "mock_artifact",
            "download_http_status", "download_error_detail",
            "conversion_status", "conversion_error_detail",
            "extraction_quality_status", "extraction_quality_note"
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
    if args.mock_resolver or args.resolve_doi:
        print(f"Downloaded PDFs:    {downloaded_pdfs}")
        print(f"Converted HTMLs:    {converted_htmls}")
        print(f"No OA PDF (No PDF):  {no_oa_pdf}")
        print(f"Failed Attempt:      {failed_attempts}")
        print(f"Manual Retrieval:    {manual_needed}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
