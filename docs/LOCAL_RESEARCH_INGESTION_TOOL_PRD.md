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

### 2.2 Resolving Pipeline (Phase 2 - Not Started)
The resolving pipeline is strictly legal and must not bypass paywalls:
1. **Open Access Check**: If a DOI exists, query Unpaywall API (`https://api.unpaywall.org/v2/{doi}`).
2. **PDF Download**: If Unpaywall returns an Open Access PDF URL, download it to `pdfs/` and verify the `%PDF` header signature.
3. **PDF-to-Markdown Conversion**: Run the downloaded PDF through the existing `scripts/any_to_md.py` converter, saving the result in `md/`.
4. **HTML Fallback**: If no PDF is found or conversion fails, and an alternative URL exists, run the existing `scripts/html_to_md.py` fetcher and converter, saving the output in `md/`.
5. **No Resolution**: If no PDF or HTML is resolved, classify the paper for manual action.

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
- `success_pdf`: PDF downloaded and converted successfully.
- `success_html`: HTML page retrieved and converted successfully (fallback).
- `no_oa_pdf`: DOI exists but no OA PDF is found (and no alternative URL succeeded).
- `failed`: An attempt was made (PDF or HTML) but failed due to network or conversion errors.
- `manual_needed`: No DOI and no URL are present, requiring human lookup.

#### Parser-only baseline status (Phase 1 - Completed):
- `parsed_only`: Record parsed and normalized correctly, but resolver/downloads were not run.
- **Resolver fields**:
  - `resolver_status` = `not_started`
  - `resolution_note` = `"Phase 1 parser-only; resolver not run"`

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
- **Deliverables**: Added `scripts/consensus_ingest.py` parsing CSV and RIS metadata inputs, creating output run directories with microsecond uniqueness, instantiating empty `pdfs/` and `md/` directories, and outputting `manifest.csv`/`papers.jsonl` with `parsed_only` statuses.
- **Status**: Completed.

### Phase 2: DOI/URL Resolver Pipeline (Next)
- **Deliverables**: Connect parser output to Unpaywall lookup, PDF downloader with signature verification, fallback HTML converter using `html_to_md.py`, and populate `pdfs/` and `md/` folders.
- **Status**: Not Started.
