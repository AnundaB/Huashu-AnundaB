# Program: Local Research Ingestion
Version: 1.0.0
Status: Spec-Draft

This program specification outlines the technical contract, execution steps, and validation rules for the local research ingestion script.

---

## 1. Interface & Contract

### 1.1 CLI Arguments
```bash
python3 scripts/consensus_ingest.py <input_file> [options]
```
- `<input_file>`: Positional argument. Path to a local `.csv` or `.ris` file.
- `--limit <int>`: Optional. Maximum number of records to process (for quick testing).
- `--email <str>`: Optional. Email query parameter for Unpaywall requests. Defaults to `consensus-ingest@example.com` or `UNPAYWALL_EMAIL` environment variable.
- `--output-dir <str>`: Optional. Base directory for output runs. Defaults to `outputs/consensus`.
- `--delay <float>`: Optional. Sleep delay (in seconds) between DOI queries. Defaults to `1.0`.

### 1.2 Output Layout
Each execution creates a directory: `<output-dir>/<YYYYMMDD-HHMMSS>-consensus-ingest/` with the following structure:
- `pdfs/`: Downloaded open-access PDFs, named `<record_id>.pdf`.
- `md/`: Converted Markdown files, named `<record_id>.md`.
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
- Create the output folder with current timestamp `YYYYMMDD-HHMMSS-consensus-ingest`.
- Recursively initialize subfolders: `pdfs/`, `md/`, and `metadata/`.

### Step 5: Resolver Loop
Iterate through each normalized record:
1. **Unpaywall Query**:
   - If `doi` is present, query `https://api.unpaywall.org/v2/{doi}?email={email}`.
   - If a valid `url_for_pdf` is returned, proceed to download.
   - Sleep for the duration of `--delay` to comply with rate limits.
2. **PDF Downloader**:
   - Download the file using a standard browser `User-Agent`.
   - Write content stream to `pdfs/<record_id>.pdf`.
   - Verify that the first 4 bytes of the saved file are `%PDF`. If not, delete the file and fail download.
3. **PDF-to-Markdown Conversion**:
   - If PDF download was successful, run subprocess:
     `python3 scripts/any_to_md.py pdfs/<record_id>.pdf -o md/<record_id>.md --quiet`
   - Mark as `success_pdf` if return code is 0.
4. **HTML Fallback**:
   - If PDF download or conversion did not succeed, and the record has a `url`:
     - Run subprocess:
       `python3 scripts/html_to_md.py <url> -o md/<record_id>.md --quiet`
     - Mark as `success_html` if return code is 0.
5. **Fallback to Failure/Manual States**:
   - If no PDF was found and no HTML fallback succeeded:
     - Set status to `no_oa_pdf` if DOI exists.
     - Set status to `manual_needed` if no DOI and no URL are present.
     - Set status to `failed` if an download/conversion attempt failed.

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
2. **Filename Consistency**: For every `record_id` with status `success_pdf` or `success_html`, a corresponding markdown file `md/<record_id>.md` exists.
3. **PDF Signature**: For every file in `pdfs/`, the file must start with `%PDF` bytes.
4. **JSONL Format**: Every line in `papers.jsonl` is a valid JSON object containing the `record_id` and `resolver_results` key.
