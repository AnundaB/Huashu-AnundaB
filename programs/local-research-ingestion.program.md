# Program: Local Research Ingestion
Version: 1.3.0
Status: Phase-2C-Complete-Phase-2D-Planned

This program specification outlines the technical contract, execution steps, and validation rules for the local research ingestion script.

---

## 1. Interface & Contract

### 1.1 CLI Arguments
```bash
python3 scripts/consensus_ingest.py <input_file> [options]
```
- `<input_file>`: Positional argument. Path to a local `.csv` or `.ris` file.
- `--limit <int>`: Optional. Maximum number of records to process.
- `--email <str>`: Optional. Email query parameter for Unpaywall requests. Defaults to `consensus-ingest@example.com`.
- `--output-dir <str>`: Optional. Base directory for output runs. Defaults to `outputs/consensus`.
- `--delay <float>`: Optional. Sleep delay (in seconds) between DOI queries. Defaults to `1.0` (polite rate limit).
- `--mock-resolver`: Optional. Run in Phase 2B offline mock resolver harness mode.
- `--resolve-doi`: Optional. Run in Phase 2C real DOI resolver mode using live API lookups.

### 1.2 Output Layout
Each execution creates a directory: `<output-dir>/<YYYYMMDD-HHMMSS-ffffff>-consensus-ingest/` (where `ffffff` is microseconds) with the following structure:
- `pdfs/`: Downloaded open-access PDFs, named `<record_id>.pdf` (empty in Phase 1).
- `md/`: Converted Markdown files, named `<record_id>.md` (empty in Phase 1).
- `metadata/manifest.csv`: CSV summary of all processed records.
- `metadata/papers.jsonl`: Rich JSONL records with full resolver logs.

---

## 2. Step-by-Step Execution Sequence

### Step 1: Input Detection & Dispatch
- Validate that `<input_file>` exists. If not, exit with error code `1`.
- Retrieve file extension. If not `.csv` or `.ris`, exit with error code `1`.
- Dispatch to corresponding parser: `parse_csv` or `parse_ris`.

### Step 2: Record Parsing & Normalization
- **CSV Parsing**:
  - Parse headers: `Title`, `Authors`, `Year`, `DOI`, `Consensus Link`, `Journal`.
  - Normalize authors by splitting on commas.
- **RIS Parsing**:
  - Match RIS tags: `TI`/`T1` (title), `AU` (authors), `PY`/`Y1` (publication year), `DO` (DOI), `UR` (URL), `JO`/`JF` (journal).
  - Collect multiple `AU` lines into a list of authors.
  - Parse `PY`/`Y1` values, extracting the first 4-digit number.
- Apply `--limit` parameter if specified to slice the records list.

### Step 3: Unique Record ID Generation
- Generate `record_id` for each record using:
  `{first_author_lastname_slug}-{year_4_digits}-{title_slug_first_3_words}`
- Maintain a running set of generated IDs. If a collision occurs, append an incrementing suffix (e.g. `-1`, `-2`).

### Step 4: Setup Run Directory
- Create the output folder with current timestamp including microseconds: `YYYYMMDD-HHMMSS-ffffff-consensus-ingest`.
- Recursively initialize subfolders: `pdfs/` (empty), `md/` (empty), and `metadata/`.

### Step 5: Resolver Loop (Phase 2 - Partially Completed)
*Note: Phase 2 resolver planning (Phase 2A) is complete, and the design is detailed in [PHASE_2_RESOLVER_PLAN.md](file:///Users/AnundaB/huashu-md-html/docs/PHASE_2_RESOLVER_PLAN.md).*

The resolver loop supports two modes in addition to the parser-only baseline:
1. **Offline Mock Resolver (Completed in Phase 2B)**:
   - Activated via `--mock-resolver`.
   - Simulates resolving, downloading, and converting without using network requests.
   - Writes placeholder `.pdf` and `.md` files labeled internally with `MOCK PLACEHOLDER` headers.
2. **Real DOI Resolver (Completed in Phase 2C)**:
   - Activated via `--resolve-doi`.
   - **OA API Query**:
     - Query Unpaywall API: `https://api.unpaywall.org/v2/{doi}?email={email}`.
     - Secondary Fallback: If Unpaywall query fails (e.g., HTTP 422 domain check), query OpenAlex Works API: `https://api.openalex.org/works/https://doi.org/{doi}` with polite `mailto` User-Agent.
     - Enforces polite rate limits by sleeping `--delay` seconds (defaults to `1.0`s) between network requests.
   - **PDF Download Test**:
     - If direct OA PDF URL is returned, download using standard library `urllib` to `pdfs/<record_id>.pdf`.
     - Verify `%PDF` signature header. If verified, set `status = success_pdf`, and `real_download_performed = True`.
     - If download fails, catch errors and set `status = failed`.
   - **No Resolution**:
     - If DOI exists but no OA PDF is found, set `status = no_oa_pdf`.
     - If no DOI and no URL exist, set `status = manual_needed`.
     - No `huashu` conversion is executed in this phase.
3. **HTML Landing Page extraction (Planned in Phase 2D)**:
   - If direct PDF is not found, extract and convert article landing pages using `scripts/html_to_md.py` to `md/<record_id>.md`.
   - Mark `status = success_html` if conversion succeeds. No paywall bypass is performed.

### Step 6: Write Indexes
- Append record information and status to `manifest.csv`.
- Serialize the complete record and execution logs to `papers.jsonl`.

### Step 7: Print Ingestion Summary
- Write a report to stdout listing:
  - Total papers processed.
  - Number of downloaded PDFs.
  - Number of converted HTML pages.
  - Number of failed / manual / no-OA entries.

---

## 3. Validation Rules

A run is considered successful if and only if:
1. **Manifest Parity**: The number of lines in `manifest.csv` (excluding headers) is exactly equal to the number of input papers (or `--limit`).
2. **Filename Consistency**: For every `record_id` with status `success_pdf` or `success_html` (in Phase 2), a corresponding markdown file `md/<record_id>.md` exists.
3. **PDF Signature**: For every file in `pdfs/`, the file must start with `%PDF` bytes.
4. **JSONL Format**: Every line in `papers.jsonl` is a valid JSON object containing the `record_id` and `resolver_results` key.
