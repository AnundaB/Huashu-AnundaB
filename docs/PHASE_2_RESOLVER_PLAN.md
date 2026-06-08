# Phase 2A Resolver Design Plan

This document establishes the technical design, API boundaries, state-machine transitions, output schemas, and verification plans for the Phase 2 Resolver Pipeline.

---

## 1. Resolver Contracts

### 1.1 DOI Resolver Contract
The DOI resolver is responsible for identifying Open Access PDF links from paper DOIs.

- **Primary Source (Unpaywall)**:
  - **Endpoint**: `https://api.unpaywall.org/v2/{doi}`
  - **Required Parameters**: `email` (string query parameter; must be a valid email syntax).
  - **Rate Limiting**: Bounded to maximum 1 request per second (using a thread delay of `1.0`s).
  - **JSON Response Mapping**:
    - Check `is_oa` (bool).
    - If true, parse `best_oa_location` -> `url_for_pdf` (string URL).
- **Secondary Source (OpenAlex Fallback)**:
  - **Endpoint**: `https://api.openalex.org/works/https://doi.org/{doi}`
  - **Required Headers**: `User-Agent` containing email (e.g. `mailto:email@example.com`).
  - **JSON Response Mapping**:
    - Check `open_access.is_oa` (bool).
    - If true, parse `best_oa_location.pdf_url` (string URL).
- **Metadata Fallback (Crossref)**:
  - Used only for enriching missing record fields (such as titles, publication years) if RIS/CSV is incomplete.

### 1.2 URL Resolver Contract
The URL resolver extracts main text content from landing pages when a direct OA PDF cannot be found.

- **Trigger**: No OA PDF URL returned by DOI query, but an alternative landing page URL is present.
- **Conversion Engine**: Invoke subprocess `scripts/html_to_md.py <url> -o md/{record_id}.md --quiet`.
- **Content Filtering**: Uses `trafilatura` to extract main article text while stripping noise (navigation, sidebars, headers, ads).
- **User-Agent**: Custom header imitating a standard web browser (e.g., Chrome on macOS) to prevent simple bot blocks on public landing pages.

---

## 2. API & Safety Boundaries

### 2.1 Legal & Open-Access Policy
- **Open Access Only**: We only fetch PDFs explicitly marked as Open Access with open licenses.
- **No Paywall Bypassing**: The tool must never scrape behind paywalls, login screens, or manipulate cookies to access restricted articles.
- **No CAPTCHA / Proxy Bypassing**: If a page returns `401 Unauthorized`, `403 Forbidden`, `429 Too Many Requests`, or triggers bot protection, the resolver must abort and label the paper as `failed` or `manual_needed`.
- **No Sci-Hub**: Banned. The tool must not query unauthorized repositories.

---

## 3. Resolver State Machine

### 3.1 Status Transitions
The resolving process moves records from Phase 1 parsed baselines through resolver pipelines:

```mermaid
stateDiagram-v2
    [*] --> parsed_only : Phase 1 Baseline
    parsed_only --> resolver_ready : Has DOI or URL
    parsed_only --> manual_needed : No DOI and No URL
    
    resolver_ready --> oa_pdf_found : DOI resolved to PDF
    resolver_ready --> article_url_found : DOI failed/no PDF, but URL exists
    resolver_ready --> no_oa_pdf : DOI exists, no PDF, no URL
    
    oa_pdf_found --> success_pdf : PDF downloaded & converted
    oa_pdf_found --> article_url_found : PDF download/conversion failed (URL exists)
    oa_pdf_found --> failed : PDF download/conversion failed (No URL)
    
    article_url_found --> success_html : HTML downloaded & converted
    article_url_found --> failed : HTML conversion failed
    
    resolver_ready --> resolver_failed : Network/API timeout (no fallbacks)
```

---

## 4. Manifest & JSONL Metadata Schema

### 4.1 manifest.csv Schema
Columns required for the Phase 2 index:
- `record_id`: Unique slug.
- `title`: Paper title.
- `authors`: Semicolon-separated list of authors.
- `year`: Publication year.
- `doi`: Document Object Identifier.
- `url`: Alternative URL / landing page.
- `status`: `success_pdf`, `success_html`, `no_oa_pdf`, `failed`, `manual_needed`.
- `resolver_status`: `not_started`, `unpaywall_lookup`, `openalex_lookup`, `html_fallback`, `completed`, `failed`.
- `resolution_note`: Text description of results or failure details.
- `pdf_download_path`: Path to saved PDF (`pdfs/record_id.pdf` or empty).
- `markdown_path`: Path to saved Markdown file (`md/record_id.md` or empty).

### 4.2 papers.jsonl Schema
Each JSON object contains full normalized metadata plus a rich `resolver_results` dict:
```json
{
  "record_id": "...",
  "title": "...",
  "authors": ["..."],
  "year": "...",
  "doi": "...",
  "url": "...",
  "journal": "...",
  "source_file": "...",
  "resolver_results": {
    "status": "...",
    "resolver_status": "...",
    "resolution_note": "...",
    "unpaywall_queried": true,
    "oa_pdf_url": "...",
    "pdf_download_path": "...",
    "html_fallback_attempted": true,
    "markdown_path": "...",
    "error_detail": "..."
  }
}
```

---

## 5. Verification Plan (Phase 2B Implementation)

To safely implement the resolver without querying live networks during building:

### 5.1 Local Mock Server
1. Create a Python mock HTTP server (`http.server` or `flask` script) running on `localhost:8000`.
2. Configure the script endpoints:
   - `/unpaywall/{doi}`: Returns mock JSON with `is_oa: true` and `url_for_pdf: "http://localhost:8000/download/{doi}.pdf"` or `is_oa: false`.
   - `/download/{doi}.pdf`: Serves a dummy file starting with `%PDF`.
   - `/html/{doi}`: Serves a simple HTML page containing a dummy article body.
3. Add an environment variable override in `consensus_ingest.py` (e.g. `UNPAYWALL_API_BASE_URL`) to redirect requests from `https://api.unpaywall.org` to the mock server.

### 5.2 Assertions Checklist
- **Manifest Count**: Verify row count matches the parsed export.
- **Microsecond Folders**: Verify separate unique runs generate independent directories.
- **Valid PDF Headers**: Verify files written in `pdfs/` start with `%PDF`.
- **Conversion Outputs**: Verify `md/` files are written for `success_pdf` and `success_html` statuses.
