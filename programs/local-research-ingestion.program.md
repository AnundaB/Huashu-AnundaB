# Program: Local Research Ingestion
Version: 2.0.0
Status: Complete


This program specification outlines the technical contract, execution steps, and validation rules for the local research ingestion script.

---

## 1. Interface & Contract

### 1.1 CLI Arguments
```bash
python3 scripts/consensus_ingest.py <input_file> [options]
```
- `<input_file>`: Positional argument. Path to a local `.csv` or `.ris` file.
- `--limit <int>`: Optional. Maximum number of records to process.
- `--output-dir <str>`: Optional. Base directory for output runs. Defaults to `outputs/consensus`.
- `--resolve-doi`: Optional. Enable live DOI querying.
- `--download-pdf`: Optional. Enable downloading of open-access PDFs when resolved.
- `--html-fallback`: Optional. Enable public HTML article extraction when PDF is unavailable.
- `--convert-md`: Optional. Enable PDF-to-Markdown conversion for downloaded PDFs using Microsoft MarkItDown.
- `--mock-resolver`: Optional. Run in offline mock resolver mode.
- `--email <str>`: Optional. Email query parameter for Unpaywall requests. Defaults to `consensus-ingest@example.com`.
- `--delay <float>`: Optional. Sleep delay (in seconds) between DOI queries. Defaults to `1.0` (polite rate limit).

### 1.2 Output Layout
Each execution creates a directory: `<output-dir>/<YYYYMMDD-HHMMSS-ffffff>-consensus-ingest/` (where `ffffff` is microseconds) with the following structure:
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
- **CSV Parsing**: Parse standard Consensus headers.
- **RIS Parsing**: Collect multiple `AU` lines, parse publication years.
- Apply `--limit` parameter if specified to slice the records list.

### Step 3: Unique Record ID Generation
- Generate unique `record_id` for each record: `{first_author_lastname_slug}-{year_4_digits}-{title_slug_first_3_words}`. Suffix collisions with `-1`, `-2`, etc.

### Step 4: Setup Run Directory
- Create directory structure: `pdfs/`, `md/`, and `metadata/`.

### Step 5: Duplicate and Resolver Processing
- Check duplicates: Keep track of processed DOIs/titles in this batch. If duplicate is found, set `status = duplicate` and skip resolving.
- **Offline Mock Resolver**: Run simulations based on flags if `--mock-resolver` is active.
- **Real DOI Resolver**: Query Unpaywall API with OpenAlex fallback. Rate limit requests using `--delay`.
- **PDF Download**: If `--download-pdf` is enabled and OA PDF exists, download and verify `%PDF` header.
- **PDF-to-MD Conversion**: If `--convert-md` is enabled, convert PDF to markdown using `scripts/any_to_md.py` (which uses Microsoft MarkItDown).
- **HTML Fallback**: If `--html-fallback` is enabled and PDF is unavailable, run `scripts/html_to_md.py` via `trafilatura` to extract landing pages to Markdown.

### Step 6: Ingestion Quality Gate
- Validate generated Markdown files for existence, non-emptiness, length (>100 chars), duplicate records, browser bot checking boilerplate, and presence of title keywords.
- Set quality statuses: `passed`, `empty_markdown`, `bad_extraction`, `needs_manual_review`.

### Step 7: Write Indexes
- Append record information to `manifest.csv` and write detailed JSON logs to `papers.jsonl`.

### Step 8: Print Ingestion Summary
- Write a report to stdout detailing run stats.

---

## 3. Validation Rules
A run is considered successful if:
1. **Manifest Parity**: The number of lines in `manifest.csv` (excluding headers) is equal to input papers.
2. **Quality Gate Mapping**: Every record includes `extraction_quality_status` and `extraction_quality_note` fields.
3. **No Unrequested Network Access**: Live networks queries are executed only when `--resolve-doi` is explicitly specified.

---

## 4. Unified Huashu CLI Wrapper Contract
The `scripts/huashu_cli.py` script acts as the main command entry point for easy invocation.

### 4.1 CLI Commands:
- `python3 scripts/huashu_cli.py -ingest <filename> [--limit <num>]` (Ingest and build vector index)
- `python3 scripts/huashu_cli.py -search "<query>"` (Search local vector memory database)
- `python3 scripts/huashu_cli.py -note "<question>"` (Synthesize note over retrieved chunks)
- `python3 scripts/huashu_cli.py -latest` (Display run directories of the latest pipeline states)

### 4.2 Shell / Alias installation:
To run the tool as `huashu` from anywhere:
```bash
alias huashu="python3 $(pwd)/scripts/huashu_cli.py"
```
Or copy/link a wrapper script to your path:
```bash
ln -sf $(pwd)/scripts/huashu_cli.py /usr/local/bin/huashu
```

