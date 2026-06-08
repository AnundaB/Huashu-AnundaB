# Local Research Ingestion Tool PRD
Version 1.2

## 1. Problem Statement & Objectives
Researchers often export search queries from platforms like Consensus as CSV or RIS files. Manually resolving these exports—finding Open Access PDFs, downloading them, extracting content, and saving them as markdown—is a repetitive and time-consuming workflow. 

The **Local Research Ingestion Tool** solves this pain by automating the downloading, converting, and indexing of research papers from Consensus exports using legal Open Access paths.

---

## 2. Core Requirements

### 2.1 Inputs & Parsing
- The tool must accept exactly one input file as a CLI parameter.
- Supported file types:
  - **CSV**: Parse standard Consensus headers (`Title`, `Takeaway`, `Authors`, `Year`, `Citations`, `Abstract`, `Study Type`, `Journal`, `Journal SJR Quartile`, `DOI`, `Consensus Link`).
  - **RIS**: Parse structured RIS tags (`TY`, `TI`/`T1`, `AU`, `PY`/`Y1`, `DO`, `UR`, `JO`/`JF`/`T2`/`JA`, `ER`).
- Duplicate/unique records must be assigned a stable, unique ID (`record_id`) matching:
  `{first_author_lastname_slug}-{year}-{first_3_words_of_title_slug}` (all lowercased and slugified).

### 2.2 Resolving & Conversion Pipeline (Phases 2-5 Completed)
The resolving pipeline is strictly legal, open-access only, and must not bypass paywalls.
1. **Open Access Check**: Query Unpaywall API using a rate limit of 1 req/sec. Check OpenAlex Work API as a secondary fallback if Unpaywall fails.
2. **PDF Download**: Fetch the direct PDF URL from the resolved API, download it to `pdfs/`, and verify the `%PDF` signature header.
3. **PDF-to-Markdown Conversion**: Convert successfully downloaded PDFs using Microsoft MarkItDown via `scripts/any_to_md.py` into `md/`.
4. **HTML Fallback**: Fetch and convert alternative URL landing pages using `scripts/html_to_md.py` into `md/` using `trafilatura` when direct PDF download fails or is unavailable.
5. **No Resolution**: If all lookups fail, set appropriate failure/manual status flags (`no_oa_pdf`, `failed`, `manual_needed`).
6. **Quality Gate**: Check the generated Markdown for size, duplicate entry in run, boilerplate error text, and presence of keywords.

---

## 3. Output Run Structure
Each run creates a unique timestamped folder under `outputs/consensus/YYYYMMDD-HHMMSS-ffffff-consensus-ingest/` containing:

```
├── pdfs/               # Downloaded Open Access PDFs
│   └── *.pdf
├── md/                 # Converted Markdown papers
│   └── *.md
└── metadata/           # Run logs and indexes
    ├── manifest.csv    # Flattened table listing statuses
    └── papers.jsonl    # Rich JSONL record details and resolver outputs
```

### 3.1 Status Classification
Every record in `manifest.csv` must be labeled with one of the following statuses:
- `success_pdf`: PDF resolved, downloaded, and converted to Markdown successfully.
- `success_html`: HTML page retrieved and converted fallback successfully.
- `resolved_pdf`: PDF resolved successfully, but download was not requested.
- `no_oa_pdf`: DOI exists but no OA PDF is found (and no alternative URL fallback succeeded).
- `download_forbidden`: PDF download was blocked by forbidden/unauthorized (401/403) status codes.
- `download_failed`: PDF download failed due to network / HTTP errors.
- `invalid_pdf`: PDF download succeeded but the file did not begin with `%PDF`.
- `duplicate`: Paper with the same DOI or title was already seen and processed in this run.
- `bad_extraction`: Quality gate failed because the file is missing, empty, too short, or contains boilerplate error messages.
- `empty_markdown`: Quality gate failed because the generated file contains no text.
- `needs_manual_review`: Extracted Markdown exists, but has low confidence (e.g. no title keywords found).
- `failed`: Pipeline failed due to network errors or subprocess extraction crashes.
- `manual_needed`: No DOI and no URL are present, or HTML fetch was blocked by 403.
- `parsed_only`: Record parsed correctly, but resolver/downloads were not run.

### 3.2 Manifest / JSONL Evidence Fields
- `resolver_mode`: `"real"`, `"mock"`, or `"offline_parser"`.
- `network_used`: `True` or `False`.
- `resolver_source`: `"unpaywall"`, `"openalex"`, or `"none"`.
- `resolver_http_status`: The HTTP status code of the DOI resolver query.
- `oa_pdf_url`: The direct PDF URL found.
- `article_url`: The alternative landing page URL.
- `pdf_download_path`: Path to saved PDF (`pdfs/record_id.pdf` or empty).
- `markdown_path`: Path to saved Markdown file (`md/record_id.md` or empty).
- `real_download_performed`: `True` or `False`.
- `huashu_conversion_performed`: `True` (if converted to Markdown) or `False`.
- `mock_artifact`: `True` or `False`.
- `download_http_status`: HTTP status code of the PDF download response.
- `download_error_detail`: Error details if the PDF download failed.
- `conversion_status`: `"completed"`, `"failed"`, or empty.
- `conversion_error_detail`: Subprocess errors during PDF conversion.
- `extraction_quality_status`: `"passed"`, `"empty_markdown"`, `"bad_extraction"`, `"needs_manual_review"`, `"duplicate"`, or `"not_applicable"`.
- `extraction_quality_note`: Detailed diagnostic messages from the quality gate checks.

---

## 4. CLI Parameters
The tool supports parameters to customize runs:
- `input_file`: Positional argument. Path to the input CSV or RIS file.
- `--limit <int>`: Process only the first N papers (great for testing).
- `--output-dir <str>`: Change output folder location.
- `--mock-resolver`: Run in offline mock resolver mode.
- `--resolve-doi`: Run in real DOI resolver mode using live API lookups.
- `--download-pdf`: Enable downloading of resolved PDFs.
- `--html-fallback`: Enable HTML landing page fallback if PDF is unavailable.
- `--convert-md`: Enable PDF-to-Markdown conversion.
- `--email <str>`: Override email parameter for Unpaywall requests.
- `--delay <float>`: Change delay in seconds between external requests.

---

## 5. Development Phases

### Phase 1: Parser-Only Ingestion Slice (Completed)
- Parse CSV/RIS input metadata and output initial runs.
- **Status**: Completed.

### Phase 2: Resolver Integration & Fallbacks (Completed)
- Implement Unpaywall/OpenAlex DOI resolvers, HTML fallback parser, and safe PDF download pipeline.
- **Status**: Completed.

### Phase 3: PDF Ingestion & Conversion Hardening (Completed)
- Implement safety boundaries, `%PDF` byte headers checks, error auditing, and PDF-to-Markdown conversion.
- **Status**: Completed.

### Phase 4: CLI Polish (Completed)
- Refine argument flags to be safe, explicit, and opt-in by default.
- **Status**: Completed.

### Phase 5: Quality Gate (Completed)
- Filter out empty extractions, duplicates, redirect boilerplate, and low-quality files.
- **Status**: Completed.

### Phase 6: Docs Alignment (Completed)
- Align all documents and schemas.
- **Status**: Completed.
