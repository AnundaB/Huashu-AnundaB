# Local Research Ingestion Tool PRD
Version 1.0

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

### 2.2 Resolving Pipeline
The resolving pipeline is strictly legal and must not bypass paywalls:
1. **Open Access Check**: If a DOI exists, query Unpaywall API (`https://api.unpaywall.org/v2/{doi}`).
2. **PDF Download**: If Unpaywall returns an Open Access PDF URL, download it to `pdfs/` and verify the `%PDF` header signature.
3. **PDF-to-Markdown Conversion**: Run the downloaded PDF through the existing `scripts/any_to_md.py` converter, saving the result in `md/`.
4. **HTML Fallback**: If no PDF is found or conversion fails, and an alternative URL exists, run the existing `scripts/html_to_md.py` fetcher and converter, saving the output in `md/`.
5. **No Resolution**: If no PDF or HTML is resolved, classify the paper for manual action.

---

## 3. Output Run Structure
Each run creates a timestamped folder under `outputs/consensus/YYYYMMDD-HHMMSS-consensus-ingest/` containing:

```
├── pdfs/               # Successfully downloaded Open Access PDFs
│   └── *.pdf
├── md/                 # Converted Markdown papers (from PDF or HTML)
│   └── *.md
└── metadata/           # Run logs and indexes
    ├── manifest.csv    # Flattened table listing statuses
    └── papers.jsonl    # Rich JSONL record details and resolver outputs
```

### 3.1 Status Classification
Every record in `manifest.csv` must be labeled with one of the following statuses:
- `success_pdf`: PDF downloaded and converted successfully.
- `success_html`: HTML page retrieved and converted successfully (fallback).
- `no_oa_pdf`: DOI exists but no OA PDF is found (and no alternative URL succeeded).
- `failed`: An attempt was made (PDF or HTML) but failed due to network or conversion errors.
- `manual_needed`: No DOI and no URL are present, requiring human lookup.

---

## 4. CLI Parameters
The tool should support parameters to customize runs:
- `--limit <int>`: Process only the first N papers (great for testing).
- `--email <str>`: Override email parameter for Unpaywall requests.
- `--output-dir <str>`: Change output folder location.
- `--delay <float>`: Change delay in seconds between external requests.

---

## 5. Success Metrics
- **Zero Paywall Violations**: The tool never attempts to bypass subscription portals.
- **Accurate Normalization**: CSV and RIS files yield identical normalized records.
- **Error Resilience**: A crash on one paper does not interrupt the ingestion of subsequent papers.
