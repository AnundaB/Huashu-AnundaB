# Program: Research Council Loop
Version: 1.0.0
Status: Active

This program specification outlines the Research Council loop for synthesizing local paper content into structured research notes.

---

## 1. Council Roles & Perspectives

- **Literature Scout**: Focuses on identifying core claims, paper objectives, and contextual relevance of the research.
- **Math Kernel Scout**: Extracts mathematical formulations, algorithm details (e.g., HMM, GARCH, wavelets, ICEEMDAN), and specific methodology kernels.
- **Signal Skeptic**: Identifies risks of data mining, overfitting, low signal-to-noise ratio, and general skepticism regarding reported returns.
- **Backtest Methodologist**: Outlines how to validate the strategy out-of-sample, cross-validation methods (e.g., Combinatorial Purged CV), and cautions regarding transaction costs.
- **Evidence Curator**: Aggregates quotes, DOIs, and URLs into a structured reference evidence table.

---

## 2. Ingestion & Execution Flow

### Step 1: Input Question & Query
- Accept a research question/query from the command line.
- Resolve the vector index in the specified run directory.
- Query the vector index to retrieve the top `k` relevant chunks (governed by chunk budget).

### Step 2: Council Review Session
- For each retrieved chunk:
  - LITERATURE SCOUT parses and logs paper metadata, authors, and claims.
  - MATH KERNEL SCOUT checks the text for mathematical keywords (e.g., HMM, GARCH, wavelet, neural, LSTM, ICEEMDAN).
  - SIGNAL SKEPTIC checks for limitations, overfitting mentions, and data noise issues.
  - BACKTEST METHODOLOGIST designs validation rules based on the paper context.

### Step 3: Synthesis & Output Generation
- Create `outputs/research-runs/<timestamp>/` run folder.
- Write the following output artifacts:
  - **`research_note.md`**: Main synthesis note containing Claims, Equations/Methods, Datasets, Validation Ideas, Weaknesses, and Backtest Cautions.
  - **`evidence_table.csv`**: Tabular mapping of Chunk ID, Title, DOI, Key Claim, and Council Sentiment.
  - **`run_log.md`**: Audit log of the council review session.
  - **`next_questions.md`**: Unresolved questions or follow-up research hypotheses suggested by the Skeptic and Scout.
- Label the outcome as `keep`, `reject`, or `needs_human_review`.
