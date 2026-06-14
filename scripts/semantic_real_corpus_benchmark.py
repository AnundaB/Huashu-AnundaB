import os
import sys
import json
import time
import datetime
import tempfile
import hashlib
import numpy as np
import importlib

# Add scripts directory to path to load semantic_index
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(REPO_ROOT, "scripts"))

import semantic_index

# Safety ignored paths
IGNORED_PATTERNS = [
    ".git", ".venv", ".pytest_cache", ".gemini", "node_modules", "venv", "env",
    "browser-profiles", "cookies", "login data", "outputs/media",
    "audio_work", "video_work"
]

def discover_corpus_files(max_files=200) -> list[str]:
    """
    Discovers markdown files in real Huashu output and docs directories.
    Safely ignores environment, authentication, and media temp files.
    Prioritizes expected query target documents to prevent skipped queries.
    """
    search_dirs = [
        os.path.join(REPO_ROOT, "outputs", "consensus"),
        os.path.join(REPO_ROOT, "docs"),
        os.path.join(REPO_ROOT, "outputs", "auto")
    ]
    
    # Load expected target filenames for prioritization
    queries_path = os.path.join(REPO_ROOT, "scripts", "semantic_benchmark_queries.json")
    expected_basenames = set()
    if os.path.exists(queries_path):
        try:
            with open(queries_path, "r", encoding="utf-8") as f:
                queries_data = json.load(f)
                for q_entry in queries_data:
                    for exp in q_entry.get("expected_docs", []):
                        expected_basenames.add(os.path.basename(exp).lower())
        except Exception as e:
            print(f"[warn] Failed to load expected docs for prioritization: {e}")
            
    discovered_priority = []
    discovered_normal = []
    
    for s_dir in search_dirs:
        if not os.path.exists(s_dir):
            continue
        dir_files = []
        for root, _, files in os.walk(s_dir):
            for file in files:
                if not file.lower().endswith(".md"):
                    continue
                full_path = os.path.join(root, file)
                
                # Safety checks
                normalized_path = full_path.replace("\\", "/").lower()
                if any(pattern in normalized_path for pattern in IGNORED_PATTERNS):
                    continue
                if file.startswith(".") or file.startswith("~"):
                    continue
                
                dir_files.append(full_path)
        dir_files.sort()
        for f_path in dir_files:
            bname = os.path.basename(f_path).lower()
            if bname in expected_basenames:
                discovered_priority.append(f_path)
            else:
                discovered_normal.append(f_path)
                
    # Combine priority files first, then normal files
    all_discovered = discovered_priority + discovered_normal
    return all_discovered[:max_files]

def matches_expected(doc_path: str, expected_list: list[str]) -> bool:
    """
    Returns True if the discovered doc_path matches any expected document identifier.
    Matches either base name or trailing relative path.
    """
    doc_path_norm = doc_path.replace("\\", "/").lower()
    for expected in expected_list:
        expected_norm = expected.replace("\\", "/").lower()
        if doc_path_norm.endswith(expected_norm) or os.path.basename(doc_path_norm) == os.path.basename(expected_norm):
            return True
    return False

def run_benchmark(corpus_files: list[str], queries_data: list[dict], temp_dir_path: str) -> dict:
    """
    Executes the benchmark by building a temporary index and running evaluation queries.
    """
    # Override HUASHU_AUTO_DIR to point to our isolated benchmark directory
    os.environ["HUASHU_AUTO_DIR"] = temp_dir_path
    importlib.reload(semantic_index)
    
    # Initialize the semantic index inside isolated directory
    idx = semantic_index.SemanticIndex()
    
    # Index corpus files
    corpus_size_bytes = 0
    start_index_time = time.perf_counter()
    for f_path in corpus_files:
        try:
            with open(f_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            corpus_size_bytes += len(content.encode("utf-8"))
            idx.add_document(f_path, content)
        except Exception as e:
            print(f"[warn] Failed to index {f_path}: {e}")
            
    indexing_duration = time.perf_counter() - start_index_time
    
    # Collect query results
    evaluated_queries = []
    skipped_queries = []
    
    for q_entry in queries_data:
        query_text = q_entry.get("query", "")
        expected_docs = q_entry.get("expected_docs", [])
        
        # Verify if at least one expected document actually exists in our indexed corpus
        corpus_has_expected = False
        for indexed_path in corpus_files:
            if matches_expected(indexed_path, expected_docs):
                corpus_has_expected = True
                break
                
        if not corpus_has_expected:
            skipped_queries.append({
                "query": query_text,
                "reason": "None of the expected target documents exist in the discovered corpus."
            })
            continue
            
        # Run similarity query and measure latency
        start_q_time = time.perf_counter()
        search_results = idx.search_similar(query_text, k=10)
        q_latency = time.perf_counter() - start_q_time
        
        # Find the rank of the first matching expected document
        found_rank = None
        for rank_idx, (retrieved_path, _) in enumerate(search_results):
            if matches_expected(retrieved_path, expected_docs):
                found_rank = rank_idx + 1
                break
                
        reciprocal_rank = 1.0 / found_rank if found_rank is not None else 0.0
        recall_at_5 = 1.0 if (found_rank is not None and found_rank <= 5) else 0.0
        recall_at_10 = 1.0 if (found_rank is not None and found_rank <= 10) else 0.0
        
        evaluated_queries.append({
            "query": query_text,
            "expected_docs": expected_docs,
            "latency_ms": q_latency * 1000.0,
            "found_rank": found_rank,
            "reciprocal_rank": reciprocal_rank,
            "recall_at_5": recall_at_5,
            "recall_at_10": recall_at_10,
            "retrieved": [os.path.basename(p) for p, _ in search_results]
        })
        
    # Aggregate metrics
    query_count = len(evaluated_queries)
    if query_count > 0:
        mrr = sum(q["reciprocal_rank"] for q in evaluated_queries) / query_count
        recall_5 = sum(q["recall_at_5"] for q in evaluated_queries) / query_count
        recall_10 = sum(q["recall_at_10"] for q in evaluated_queries) / query_count
        avg_latency_ms = sum(q["latency_ms"] for q in evaluated_queries) / query_count
    else:
        mrr, recall_5, recall_10, avg_latency_ms = 0.0, 0.0, 0.0, 0.0
        
    # Calculate index files size on disk
    index_files_size = 0
    semantic_dir_path = os.path.join(temp_dir_path, "semantic_index")
    if os.path.exists(semantic_dir_path):
        for root, _, files in os.walk(semantic_dir_path):
            for file in files:
                index_files_size += os.path.getsize(os.path.join(root, file))
                
    return {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provider": idx.provider_name,
        "model_id": idx.model_id,
        "dimension": idx.dimension,
        "corpus_files_count": len(corpus_files),
        "corpus_size_bytes": corpus_size_bytes,
        "index_size_bytes": index_files_size,
        "indexing_duration_seconds": indexing_duration,
        "query_count": query_count,
        "skipped_query_count": len(skipped_queries),
        "mrr": round(mrr, 4),
        "recall_at_5": round(recall_5, 4),
        "recall_at_10": round(recall_10, 4),
        "avg_latency_ms": round(avg_latency_ms, 2),
        "evaluated_queries": evaluated_queries,
        "skipped_queries": skipped_queries
    }

def generate_markdown_report(metrics: dict) -> str:
    """
    Renders a clean, aesthetic Markdown report.
    """
    timestamp = metrics["timestamp"]
    
    # Generate Evaluated Queries Table
    eval_rows = []
    for eq in metrics["evaluated_queries"]:
        expected_str = ", ".join(eq["expected_docs"])
        found_rank_str = str(eq["found_rank"]) if eq["found_rank"] is not None else "N/A"
        eval_rows.append(
            f"| `{eq['query']}` | {expected_str} | **{found_rank_str}** | {eq['reciprocal_rank']:.2f} | {eq['recall_at_5']:.0f} | {eq['recall_at_10']:.0f} | {eq['latency_ms']:.1f}ms |"
        )
    eval_table = "\n".join(eval_rows)
    
    # Generate Skipped Queries Table
    skip_rows = []
    for sq in metrics["skipped_queries"]:
        skip_rows.append(f"| `{sq['query']}` | {sq['reason']} |")
    skip_table = "\n".join(skip_rows) if skip_rows else "| *None* | |"
    
    report_md = f"""# Huashu Semantic Retrieval Benchmark Report

> [!NOTE]
> Generated on `{timestamp}` using target backend `{metrics['provider']}`.

## 📊 Summary Metrics

| Metric | Value |
| :--- | :--- |
| **Vector Backend / Provider** | `{metrics['provider']}` |
| **Model ID** | `{metrics['model_id']}` |
| **Dimension** | `{metrics['dimension']}` |
| **Total Corpus Files** | {metrics['corpus_files_count']} |
| **Corpus Size** | {metrics['corpus_size_bytes'] / (1024*1024):.2f} MB |
| **Index Disk Size** | {metrics['index_size_bytes'] / 1024:.2f} KB |
| **Mean Reciprocal Rank (MRR)** | **{metrics['mrr']:.4f}** |
| **Recall @ 5** | {metrics['recall_at_5']:.4f} |
| **Recall @ 10** | {metrics['recall_at_10']:.4f} |
| **Average Query Latency** | {metrics['avg_latency_ms']:.2f} ms |
| **Total Queries Run** | {metrics['query_count']} |
| **Total Queries Skipped** | {metrics['skipped_query_count']} |

---

## 🔍 Evaluated Queries Detail

| Query | Expected Targets | Found Rank | Reciprocal Rank | Recall@5 | Recall@10 | Latency |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
{eval_table}

---

## ⚠️ Skipped Queries

| Query | Reason |
| :--- | :--- |
{skip_table}

---

## 💡 Recommendation
- **Semantic Strength Assessment**: The deterministic hash baseline achieves an MRR of `{metrics['mrr']:.4f}`. Because it uses simple word token hashing, it succeeds where exact keywords overlap but lacks synonym awareness.
- **Pluggable sentence-transformers Transition**: Keep this benchmark as a reference fixture. Once `sentence-transformers` is added as an optional extra, we will run the exact same corpus benchmark to verify whether retrieval quality materially outperforms the hash baseline without breaking constraints.
"""
    return report_md

def main():
    # 1. Discover corpus
    corpus_files = discover_corpus_files(max_files=200)
    if not corpus_files:
        print("NO_REAL_CORPUS_FOUND")
        sys.exit(1)
        
    print(f"Discovered {len(corpus_files)} Markdown files in real corpus.")
    
    # 2. Read queries
    queries_path = os.path.join(REPO_ROOT, "scripts", "semantic_benchmark_queries.json")
    if not os.path.exists(queries_path):
        print(f"[error] Queries file not found: {queries_path}")
        sys.exit(1)
        
    with open(queries_path, "r", encoding="utf-8") as f:
        queries_data = json.load(f)
        
    # 3. Create isolated benchmark folder
    with tempfile.TemporaryDirectory() as temp_dir:
        metrics = run_benchmark(corpus_files, queries_data, temp_dir)
        
    # 4. Save report outputs
    timestamp_slug = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = os.path.join(REPO_ROOT, "outputs", "auto", "semantic_benchmarks", timestamp_slug)
    os.makedirs(report_dir, exist_ok=True)
    
    report_json_path = os.path.join(report_dir, "benchmark_report.json")
    report_md_path = os.path.join(report_dir, "benchmark_report.md")
    
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
        
    report_md = generate_markdown_report(metrics)
    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print(f"Benchmark executed successfully.")
    print(f"MRR: {metrics['mrr']} | Recall@5: {metrics['recall_at_5']} | Recall@10: {metrics['recall_at_10']}")
    print(f"Report JSON: {report_json_path}")
    print(f"Report MD: {report_md_path}")
    
    # Reset HUASHU_AUTO_DIR to default
    if "HUASHU_AUTO_DIR" in os.environ:
        del os.environ["HUASHU_AUTO_DIR"]

if __name__ == "__main__":
    main()
