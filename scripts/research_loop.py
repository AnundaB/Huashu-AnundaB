#!/usr/bin/env python3
"""
research_loop.py — Run the autoresearch-style Research Council loop over local memory index.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import sys
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Adjust path to import research_memory_index
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from research_memory_index import text_to_vector_128, HAS_TURBOVEC

try:
    from turbovec import IdMapIndex
except ImportError:
    pass


def load_memory_index(memory_dir: str) -> tuple[dict, np.ndarray | IdMapIndex, bool]:
    """
    Loads chunks metadata and the vector index from the memory folder.
    """
    chunks_jsonl = os.path.join(memory_dir, "chunks.jsonl")
    if not os.path.exists(chunks_jsonl):
        raise FileNotFoundError(f"chunks.jsonl not found under {memory_dir}")

    chunks_by_id = {}
    with open(chunks_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunks_by_id[c["chunk_id"]] = c

    index_file = os.path.join(memory_dir, "index.tvim")
    if HAS_TURBOVEC and os.path.exists(index_file):
        index = IdMapIndex.load(index_file)
        is_turbovec = True
    else:
        vectors_npy = os.path.join(memory_dir, "vectors.npy")
        ids_npy = os.path.join(memory_dir, "ids.npy")
        if not os.path.exists(vectors_npy) or not os.path.exists(ids_npy):
            raise FileNotFoundError(f"No vector database found under {memory_dir}")
        vectors = np.load(vectors_npy)
        ids = np.load(ids_npy)
        index = (vectors, ids)
        is_turbovec = False

    return chunks_by_id, index, is_turbovec


def search_chunks(query_text: str, index: np.ndarray | IdMapIndex, is_turbovec: bool, k: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Searches the index for top-k closest chunks.
    """
    query_vec = text_to_vector_128(query_text)
    if is_turbovec:
        # turbovec expects (num_queries, dim) shape
        scores, ids = index.search(query_vec.reshape(1, -1), k=k)
        return scores[0], ids[0]
    else:
        vectors, ids = index
        scores = np.dot(vectors, query_vec)
        top_indices = np.argsort(scores)[::-1][:k]
        return scores[top_indices], ids[top_indices]


def run_council(chunks: list[dict], scores: np.ndarray) -> dict:
    """
    Simulates the Research Council session reviewing the retrieved paper chunks.
    """
    review_log = []
    evidence_rows = []
    
    # Aggregated sections
    claims = []
    methods = []
    datasets = []
    weaknesses = []
    backtest_cautions = []
    next_questions = []

    claims_by_record = {}
    methods_by_record = {}
    weaknesses_by_record = {}
    backtest_by_record = {}

    for idx, (chunk, score) in enumerate(zip(chunks, scores)):
        record_id = chunk["record_id"]
        title = chunk["title"]
        doi = chunk["doi"]
        text = chunk["text"]
        text_lower = text.lower()

        review_log.append(f"### Chunk {chunk['chunk_id']} (Score: {score:.4f}) from {record_id}")
        review_log.append(f"Title: {title}")

        # LITERATURE SCOUT
        scout_claim = f"Identified regime/fluctuation feature under '{title}'"
        if "regime switching" in text_lower or "regime identification" in text_lower:
            scout_claim = "Proposed an extended HMM/jump model to identify and smoothed persistent regimes in daily returns."
        elif "denois" in text_lower:
            scout_claim = "Introduced a novel denoising method (wavelet/diffusion/ICEEMDAN) to enhance predictability and filter noise."
        elif "overfitting" in text_lower:
            scout_claim = "Analyzed model evaluation and compared validation methods (CPCV, Walk-Forward) to control overfitting."
        
        claims_by_record.setdefault(record_id, set()).add(scout_claim)
        review_log.append(f"- **Literature Scout**: {scout_claim}")

        # MATH KERNEL SCOUT
        math_found = []
        if "hmm" in text_lower or "hidden markov" in text_lower:
            math_found.append("Hidden Markov Model (HMM)")
        if "garch" in text_lower:
            math_found.append("ARMA-GARCH")
        if "wavelet" in text_lower:
            math_found.append("Wavelet Threshold Denoising (WaveL2E / ICEEMDAN)")
        if "diffusion" in text_lower:
            math_found.append("Conditional Diffusion Generative Model")
        if "fourier" in text_lower:
            math_found.append("Fourier Frequency Domain Filtering")
        if "lstm" in text_lower:
            math_found.append("LSTM Recurrent Neural Networks")
        
        math_str = ", ".join(math_found) if math_found else "Statistical Hashing Projection"
        methods_by_record.setdefault(record_id, set()).add(f"Utilizes {math_str}")
        review_log.append(f"- **Math Kernel Scout**: Found math kernel: {math_str}")

        # SIGNAL SKEPTIC
        skeptic_note = "High volatility and low signal-to-noise ratio in daily returns may degrade predictive power."
        sentiment = "Neutral"
        if "overfitting" in text_lower:
            skeptic_note = "High risk of backtest overfitting due to multiple testing of strategies; Walk-Forward shows temporal instability."
            sentiment = "Skeptical"
        elif "noise" in text_lower:
            skeptic_note = "Microstructure noise and outliers can warp empirical quantiles and skew standard models."
            sentiment = "Cautionary"
        elif "mock" in text_lower:
            skeptic_note = "Mock placeholder run. No real empirical verification performed."
            sentiment = "Mock Neutral"
            
        weaknesses_by_record.setdefault(record_id, set()).add(skeptic_note)
        review_log.append(f"- **Signal Skeptic**: {skeptic_note}")

        # BACKTEST METHODOLOGIST
        method_note = "Apply standard out-of-sample forward testing with leakage control."
        if "combinatorial purged" in text_lower or "cpcv" in text_lower:
            method_note = "Implement Combinatorial Purged Cross-Validation (CPCV) to compute deflated Sharpe ratios and prevent leakage."
        elif "denois" in text_lower:
            method_note = "Ensure denoising parameters are not fit using look-ahead data; slide the window strictly out-of-sample."
        elif "mock" in text_lower:
            method_note = "Needs validation on real historical stock/index returns."

        backtest_by_record.setdefault(record_id, set()).add(method_note)
        review_log.append(f"- **Backtest Methodologist**: Recommended validation: {method_note}")

        # EVIDENCE CURATOR
        evidence_rows.append({
            "chunk_id": chunk["chunk_id"],
            "record_id": record_id,
            "title": title,
            "doi": doi,
            "key_claim": scout_claim,
            "math_kernel": math_str,
            "skeptic_sentiment": sentiment,
            "recommended_validation": method_note,
            "relevance_score": f"{score:.4f}"
        })

    # Limit and build claims list (max 2 unique items per record_id)
    for record_id, record_claims in sorted(claims_by_record.items()):
        for clm in sorted(list(record_claims))[:2]:
            claims.append(f"- **{record_id}**: {clm}")

    for record_id, record_methods in sorted(methods_by_record.items()):
        for mth in sorted(list(record_methods))[:2]:
            methods.append(f"- **{record_id}**: {mth}")

    for record_id, record_weaknesses in sorted(weaknesses_by_record.items()):
        for wk in sorted(list(record_weaknesses))[:2]:
            weaknesses.append(f"- **{record_id}**: {wk}")

    for record_id, record_backtest in sorted(backtest_by_record.items()):
        for bt in sorted(list(record_backtest))[:2]:
            backtest_cautions.append(f"- **{record_id}**: {bt}")

    # Aggregated datasets
    datasets.append("- S&P 500 Daily Time Series (Wang 2025)")
    datasets.append("- Synthetic Controlled Environments with Stochastic Volatility (Arian 2024)")
    datasets.append("- High-frequency limit order book datasets (Passalis 2019)")

    # Aggregated next questions
    next_questions.append("- How does CPCV cross-validation perform on highly non-stationary regime-switching regimes?")
    next_questions.append("- Can the MD5 deterministic feature hashing scale to larger corpora without collision bottlenecks?")
    next_questions.append("- Does wavelet denoising trigger leakage when applied on rolling lookback windows?")

    return {
        "review_log": "\n".join(review_log),
        "evidence_rows": evidence_rows,
        "claims": "\n".join(claims),
        "methods": "\n".join(methods),
        "datasets": "\n".join(datasets),
        "weaknesses": "\n".join(weaknesses),
        "backtest_cautions": "\n".join(backtest_cautions),
        "next_questions": "\n".join(next_questions)
    }



def main() -> int:
    p = argparse.ArgumentParser(description="Run local paper Research Council loops.")
    p.add_argument("run_dir", help="Consensus run directory containing the memory index")
    p.add_argument("question", help="Research question to analyze")
    p.add_argument("-k", "--top-k", type=int, default=3, help="Number of chunks to retrieve (default: 3)")
    p.add_argument("--output-dir", default=os.path.join(REPO_ROOT, "outputs", "research-runs"), help="Base output folder for research runs")
    p.add_argument("--max-iterations", type=int, default=1, help="Max loop iteration budget")

    args = p.parse_args()

    memory_dir = os.path.join(args.run_dir, "memory")
    if not os.path.exists(memory_dir):
        # Allow run_dir itself to be memory dir
        if os.path.exists(os.path.join(args.run_dir, "chunks.jsonl")):
            memory_dir = args.run_dir
        else:
            sys.stderr.write(f"[error] Memory subdirectory not found under: {args.run_dir}\n")
            return 1

    try:
        chunks_by_id, index, is_turbovec = load_memory_index(memory_dir)
    except Exception as e:
        sys.stderr.write(f"[error] Failed to load memory index: {e}\n")
        return 1

    # Query index
    scores, ids = search_chunks(args.question, index, is_turbovec, args.top_k)
    
    retrieved_chunks = []
    valid_scores = []
    for s, cid in zip(scores, ids):
        chunk = chunks_by_id.get(int(cid))
        if chunk:
            retrieved_chunks.append(chunk)
            valid_scores.append(s)

    if not retrieved_chunks:
        print("[error] No relevant chunks found for the question.")
        return 1

    # Run Council Simulation
    council_results = run_council(retrieved_chunks, np.array(valid_scores))

    # Determine recommendation status
    max_score = float(max(valid_scores)) if valid_scores else 0.0
    if max_score > 0.25:
        recommendation = "keep"
    elif max_score < 0.1:
        recommendation = "reject"
    else:
        recommendation = "needs_human_review"

    # Setup unique output folder
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_output_dir = os.path.join(args.output_dir, timestamp)
    os.makedirs(run_output_dir, exist_ok=True)

    # Write evidence_table.csv
    evidence_csv_path = os.path.join(run_output_dir, "evidence_table.csv")
    with open(evidence_csv_path, "w", encoding="utf-8", newline="") as csvfile:
        fieldnames = [
            "chunk_id", "record_id", "title", "doi", "key_claim",
            "math_kernel", "skeptic_sentiment", "recommended_validation", "relevance_score"
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in council_results["evidence_rows"]:
            writer.writerow(row)

    # Write run_log.md
    log_path = os.path.join(run_output_dir, "run_log.md")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# Research Council Review Log\n")
        f.write(f"Date: {datetime.datetime.now().isoformat()}\n")
        f.write(f"Query: '{args.question}'\n")
        f.write(f"Recommending Decision: **{recommendation.upper()}** (Max Score: {max_score:.4f})\n\n")
        f.write(council_results["review_log"])

    # Write next_questions.md
    next_path = os.path.join(run_output_dir, "next_questions.md")
    with open(next_path, "w", encoding="utf-8") as f:
        f.write(f"# Unresolved Council Hypotheses & Follow-up Questions\n\n")
        f.write(council_results["next_questions"])

    # Warn when corpus is small
    corpus_size_warning = None
    manifest_path = os.path.join(memory_dir, "index_manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
                total_chunks = manifest_data.get("total_chunks", 0)
                if total_chunks < 10:
                    corpus_size_warning = f"> [!WARNING]\n> The indexed research corpus contains only {total_chunks} chunks. Synthesized findings may have limited literature coverage.\n\n"
        except Exception:
            pass

    # Write research_note.md
    note_path = os.path.join(run_output_dir, "research_note.md")
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(f"# Research Note: Synthesis on '{args.question}'\n\n")
        if corpus_size_warning:
            f.write(corpus_size_warning)
        f.write(f"- **Recommendation**: {recommendation.upper()}\n")
        f.write(f"- **Max Query Score**: {max_score:.4f}\n")
        f.write(f"- **Indexed Directory**: {os.path.basename(memory_dir)}\n\n")
        
        f.write(f"## 1. Core Literature Claims\n")
        f.write(council_results["claims"] + "\n\n")

        
        f.write(f"## 2. Mathematical Kernels & Methodologies\n")
        f.write(council_results["methods"] + "\n\n")
        
        f.write(f"## 3. Data Context & Baselines\n")
        f.write(council_results["datasets"] + "\n\n")
        
        f.write(f"## 4. Potential Weaknesses & Noise Vulnerabilities\n")
        f.write(council_results["weaknesses"] + "\n\n")
        
        f.write(f"## 5. Backtest Cautions & Leakage Controls\n")
        f.write(council_results["backtest_cautions"] + "\n\n")

    print(f"Research Council loop completed successfully.")
    print(f"Outcome:              {recommendation.upper()}")
    print(f"Max Relevance Score:  {max_score:.4f}")
    print(f"Research Run Folder:  {run_output_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
