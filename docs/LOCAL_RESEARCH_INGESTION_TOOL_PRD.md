# Local Research Ingestion Tool PRD
Version 1.1

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
  `{first_author_lastname}-{year}-{first_3_words_of_title}` (all lowercased and slugified).

### 2.2 Resolving Pipeline (Phase 2 - Partially Completed)
The resolving pipeline is strictly legal, open-access only, and must not bypass paywalls. The complete design details are established in [PHASE_2_RESOLVER_PLAN.md](file:///Users/AnundaB/huashu-md-html/docs/PHASE_2_RESOLVER_PLAN.md):
1. **Open Access Check (Completed in Phase 2C)**: Query Unpaywall API (`https://api.unpaywall.org/v2/{doi}`) using a rate limit of 1 req/sec. Check OpenAlex Work API as a secondary fallback if Unpaywall fails.
2. **PDF Download (Completed in Phase 2C)**: Fetch the direct PDF URL from the resolved API, download it to `pdfs/`, and verify the `%PDF` signature header.
3. **PDF-to-Markdown Conversion (Planned)**: Convert the PDF using `scripts/any_to_md.py` into `md/`.
4. **HTML Fallback (Planned in Phase 2D)**: Fetch and convert alternative URL landing pages using `scripts/html_to_md.py` into `md/`.
5. **No Resolution (Completed in Phase 2C)**: If all lookups fail, set appropriate failure/manual status flags (`no_oa_pdf`, `failed`, `manual_needed`).

---

## 3. Output Run Structure
Each run creates a unique timestamped folder (using microseconds for collision prevention) under `outputs/consensus/YYYYMMDD-HHMMSS-ffffff-consensus-ingest/` containing:

```
├── pdfs/               # Downloaded Open Access PDFs (empty in Phase 1)
│   └── *.pdf
├── md/                 # Converted Markdown papers (empty in Phase 1)
│   └── *.md
└── metadata/           # Run logs and indexes
    ├── manifest.csv    # Flattened table listing statuses
    └── papers.jsonl    # Rich JSONL record details and resolver outputs
```

### 3.1 Status Classification
Every record in `manifest.csv` must be labeled with one of the following statuses:

#### Active resolver statuses (Phase 2):
- `success_pdf`: PDF downloaded (and converted once conversion is enabled).
- `success_html`: HTML page retrieved and converted successfully (fallback).
- `no_oa_pdf`: DOI exists but no OA PDF is found (and no alternative URL succeeded).
- `failed`: An attempt was made (PDF or HTML) but failed due to network or conversion errors.
- `manual_needed`: No DOI and no URL are present, requiring human lookup.

#### Parser-only baseline status (Phase 1 - Completed):
- `parsed_only`: Record parsed and normalized correctly, but resolver/downloads were not run.

#### Manifest / JSONL Evidence Fields:
- `resolver_mode`: `"real"`, `"mock"`, or `"offline_parser"`.
- `network_used`: `True` or `False`.
- `resolver_source`: `"unpaywall"`, `"openalex"`, or `"none"`.
- `resolver_http_status`: The HTTP status code of the query.
- `oa_pdf_url`: The direct PDF URL found.
- `article_url`: The alternative landing page URL.
- `real_download_performed`: `True` (if direct OA PDF was downloaded) or `False`.
- `huashu_conversion_performed`: `False`.
- `mock_artifact`: `True` (if mock placeholder generated) or `False`.

---

## 4. CLI Parameters
The tool supports parameters to customize runs:
- `input_file`: Positional argument. Path to the input CSV or RIS file.
- `--limit <int>`: Process only the first N papers (great for testing).
- `--email <str>`: Override email parameter for Unpaywall requests.
- `--output-dir <str>`: Change output folder location.
- `--delay <float>`: Change delay in seconds between external requests.

---

## 5. Development Phases

### Phase 1: Parser-Only Ingestion Slice (Completed)
- **Deliverables**: Added `scripts/consensus_ingest.py` parsing CSV and RIS metadata inputs, creating output run directories with microsecond uniqueness, and outputting `manifest.csv`/`papers.jsonl` with `parsed_only` statuses.
- **Status**: Completed.

### Phase 2: DOI/URL Resolver Pipeline (Partially Completed)
- **Phase 2A (Design)**: Established resolver contracts and state machine. **Status**: Completed.
- **Phase 2B (Offline Mock)**: Added offline `--mock-resolver` harness mode. **Status**: Completed.
- **Phase 2C (Real DOI Resolver)**: Added live resolver `--resolve-doi` querying Unpaywall (primary) and OpenAlex (fallback), rate limiting, and direct PDF downloading. **Status**: Completed.
- **Phase 2D (Landing Page HTML Fallback)**: Extract and convert alternative URL landing pages using `scripts/html_to_md.py` to Markdown without paywall bypass. **Status**: Next.
