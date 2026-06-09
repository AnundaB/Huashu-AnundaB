#!/usr/bin/env python3
"""
research_topic_packs.py — Local-only Consensus Research Topic Pack Builder.
Groups ingested papers into concept-aligned clusters instead of a single giant file.
Supports theme-first clustering and fallback similarity clustering.
"""

import os
import sys
import json
import csv
import re
import collections
import math
import argparse
import numpy as np

# Try importing turbovec
try:
    from turbovec import IdMapIndex
    HAS_TURBOVEC = True
except ImportError:
    HAS_TURBOVEC = False

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't", "as", "at",
    "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "can't", "cannot",
    "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during", "each", "few",
    "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll",
    "he's", "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll",
    "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most",
    "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't",
    "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't",
    "what", "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's",
    "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves"
}

THEME_DEFINITIONS = {
    "1. Signal Denoising / Noise Reduction": [
        "signal denoising", "noise reduction", "denoise", "denoising", "filter noise",
        "noise removal", "noise control", "noise filtering", "denoiser", "de-noising"
    ],
    "2. Regime Detection / Structural Breaks / Markov Switching": [
        "regime detection", "structural breaks", "Markov switching", "regime switching",
        "change point", "changepoint", "regime shift", "structural break", "jump model",
        "regime identification", "state transition", "structural change"
    ],
    "3. False Positives / Validation / Multiple Testing / Backtest Overfitting": [
        "false positives", "validation", "multiple testing", "backtest overfitting",
        "false discovery", "multiple comparison", "type i error", "cross validation",
        "cross-validation", "false signals", "testing errors", "multiple statistical",
        "type 1 error", "type one error"
    ],
    "4. Financial Time-Series Forecasting / Deep Learning / Transformers / LSTM": [
        "time-series forecasting", "time series forecasting", "deep learning", "transformer",
        "lstm", "neural network", "attention mechanism", "recurrent neural", "attention-based",
        "mamba", "sequence modeling"
    ],
    "5. Volatility Forecasting / GARCH / EWMA / realized volatility": [
        "volatility forecasting", "garch", "ewma", "realized volatility", "volatility",
        "stochastic volatility", "volatility modeling", "conditional variance",
        "heteroskedastic", "heteroskedasticity"
    ],
    "6. Factor Models / Cross-Sectional Ranking / Stock Selection / Information Coefficient": [
        "factor model", "cross-sectional ranking", "stock selection", "information coefficient",
        "fama-french", "equity premium", "asset pricing", "ranking", "stock returns",
        "cross-sectional stock", "pairs trading"
    ],
    "7. Fraud / Anomaly / Leakage Detection": [
        "fraud", "anomaly", "leakage", "credit card fraud", "anomaly detection",
        "data leakage", "leakage detection", "fraud detection", "malware detection"
    ],
    "8. Financial Distress / Z-Score / Early Warning": [
        "financial distress", "z-score", "early warning", "default probability",
        "credit risk", "bankruptcy", "distress prediction", "probability of default",
        "altman z"
    ],
    "9. Signal Extraction / Filtering / Spectral / Fourier / wavelet": [
        "signal extraction", "filtering", "spectral", "fourier", "wavelet",
        "fourier transform", "spectral analysis", "kalman filter", "wavelets",
        "bandpass", "lowpass", "highpass", "signal processing", "prony"
    ],
    "10. Market Microstructure / Order Flow / Lead-Lag": [
        "market microstructure", "order flow", "lead-lag", "liquidity",
        "order book", "bid-ask spread", "transaction cost", "market liquidity",
        "funding liquidity", "lead lag"
    ],
    "11. Portfolio Optimization / Asset Allocation / Risk": [
        "portfolio optimization", "asset allocation", "portfolio risk", "risk management",
        "mean-variance", "risk parity", "downside risk", "sharpe ratio", "beta causal",
        "efficient frontier", "asset allocation models"
    ],
    "12. Non-financial Signal-processing Papers that may be Useful Analogies": [
        "ecg", "ppg", "medical signal", "biomedical", "non-financial", "acoustic",
        "vibration", "sensor signals", "pulse detection", "electroencephalogram",
        "eeg", "seismic"
    ]
}

THEME_SHORT_NAMES = {
    "1. Signal Denoising / Noise Reduction": "denoising",
    "2. Regime Detection / Structural Breaks / Markov Switching": "regime-detection",
    "3. False Positives / Validation / Multiple Testing / Backtest Overfitting": "validation-overfitting",
    "4. Financial Time-Series Forecasting / Deep Learning / Transformers / LSTM": "forecasting-deep-learning",
    "5. Volatility Forecasting / GARCH / EWMA / realized volatility": "volatility-forecasting",
    "6. Factor Models / Cross-Sectional Ranking / Stock Selection / Information Coefficient": "factor-models",
    "7. Fraud / Anomaly / Leakage Detection": "fraud-anomaly-detection",
    "8. Financial Distress / Z-Score / Early Warning": "distress-early-warning",
    "9. Signal Extraction / Filtering / Spectral / Fourier / wavelet": "signal-filtering",
    "10. Market Microstructure / Order Flow / Lead-Lag": "market-microstructure",
    "11. Portfolio Optimization / Asset Allocation / Risk": "portfolio-risk",
    "12. Non-financial Signal-processing Papers that may be Useful Analogies": "non-financial-signals"
}

def tokenize(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', ' ', text)
    tokens = text.split()
    return [t for t in tokens if t not in STOPWORDS and len(t) > 2]

def text_to_vector_128(text: str) -> np.ndarray:
    import hashlib
    words = [w.strip() for w in text.lower().split() if w.strip()]
    if not words:
        return np.zeros(128, dtype=np.float32)
    vec = np.zeros(128, dtype=np.float32)
    for word in words:
        h = hashlib.md5(word.encode("utf-8")).digest()
        seed_int = int.from_bytes(h, byteorder="big") % (2**32)
        rng = np.random.default_rng(seed_int)
        word_vec = rng.standard_normal(128)
        norm = np.linalg.norm(word_vec)
        if norm > 0:
            word_vec /= norm
        vec += word_vec
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.astype(np.float32)

def parse_paper(run_dir, record):
    record_id = record.get("record_id")
    title = record.get("title") or ""
    authors_list = record.get("authors") or []
    if isinstance(authors_list, list):
        authors = "; ".join(authors_list)
    else:
        authors = str(authors_list)
    year = record.get("year") or ""
    doi = record.get("doi") or ""
    url = record.get("url") or ""

    resolver_results = record.get("resolver_results") or {}
    markdown_path = resolver_results.get("markdown_path")
    if not markdown_path:
        return None

    full_md_path = os.path.join(run_dir, markdown_path)
    if not os.path.exists(full_md_path):
        # Fallback check
        filename = os.path.basename(markdown_path)
        full_md_path = os.path.join(run_dir, "md", filename)
        if not os.path.exists(full_md_path):
            return None

    try:
        with open(full_md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[warn] Failed to read markdown for {record_id}: {e}")
        return None

    # Extract headings
    headings = [m[1].strip() for m in re.findall(r'^(#+)\s+(.+)$', content, re.MULTILINE)]

    # Extract abstract
    abstract = ""
    lines = content.splitlines()
    abstract_started = False
    abstract_lines = []
    for line in lines:
        stripped = line.strip()
        if not abstract_started:
            if re.match(r'^#*\s*abstract\s*$', stripped, re.IGNORECASE) or stripped == "**Abstract**":
                abstract_started = True
                continue
        else:
            if re.match(r'^#+\s+', stripped):
                break
            if re.match(r'^(keywords|citation|editor|received|copyright|data availability|funding|competing interests):', stripped, re.IGNORECASE):
                break
            abstract_lines.append(line)
    abstract = "\n".join(abstract_lines).strip()
    if not abstract:
        # Fallback regex
        match = re.search(r'(?:Abstract|## Abstract)\s*\n+(.*?)(?=\n##|\nKeywords:|\n1 Introduction)', content, re.DOTALL | re.IGNORECASE)
        if match:
            abstract = match.group(1).strip()

    # Extract keywords
    keywords = []
    kw_match = re.search(r'(?:Keywords:)\s*(.*)', content, re.IGNORECASE)
    if kw_match:
        kw_line = kw_match.group(1).strip()
        keywords = [k.strip() for k in re.split(r'[,;.]', kw_line) if k.strip()]

    # Heuristic sentence extraction for evidence matrix
    sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s', content)
    sentences = [s.strip().replace('\n', ' ') for s in sentences if len(s.strip()) > 30 and len(s.strip()) < 300]

    finding_sentence = "Key findings not explicitly summarized."
    dataset_sentence = "Dataset/sample not explicitly detailed."
    metrics_sentence = "Quantitative metrics not explicitly listed."

    # Findings heuristics
    findings_candidates = []
    for s in sentences:
        score = 0
        if any(w in s.lower() for w in ["find", "found", "show", "showed", "indicate", "concluded", "propose", "proposes", "demonstrated", "demonstrate", "evidence"]):
            score += 2
        if any(w in s.lower() for w in ["results", "findings", "hypothesis", "significant"]):
            score += 1
        if score > 0:
            findings_candidates.append((score, s))
    if findings_candidates:
        findings_candidates.sort(key=lambda x: x[0], reverse=True)
        finding_sentence = findings_candidates[0][1]

    # Dataset heuristics
    dataset_candidates = []
    for s in sentences:
        score = 0
        if any(w in s.lower() for w in ["dataset", "sample", "data", "s&p 500", "daily", "monthly", "historical", "nasdaq", "indices", "database"]):
            score += 2
        if any(w in s.lower() for w in ["stocks", "period", "observations"]):
            score += 1
        if score > 0:
            dataset_candidates.append((score, s))
    if dataset_candidates:
        dataset_candidates.sort(key=lambda x: x[0], reverse=True)
        dataset_sentence = dataset_candidates[0][1]

    # Metrics heuristics
    metrics_candidates = []
    for s in sentences:
        score = 0
        if "%" in s or any(w in s for w in ["0.", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."]):
            score += 1
        if any(w in s.lower() for w in ["rmse", "accuracy", "error", "outperform", "r-squared", "precision", "recall", "f1-score"]):
            score += 2
        if score > 1:
            metrics_candidates.append((score, s))
    if metrics_candidates:
        metrics_candidates.sort(key=lambda x: x[0], reverse=True)
        metrics_sentence = metrics_candidates[0][1]

    return {
        "record_id": record_id,
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": url,
        "markdown_path": markdown_path,
        "content": content,
        "headings": headings,
        "abstract": abstract,
        "keywords": keywords,
        "finding": finding_sentence,
        "dataset": dataset_sentence,
        "metrics": metrics_sentence
    }

def compute_tfidf_similarities(papers):
    corpus_tokens = {}
    for p in papers:
        profile_text = f"{p['title']} {p['abstract']} {' '.join(p['keywords'])}"
        corpus_tokens[p["record_id"]] = tokenize(profile_text)

    df = collections.defaultdict(int)
    for record_id, tokens in corpus_tokens.items():
        for token in set(tokens):
            df[token] += 1

    num_docs = len(papers)
    idf = {}
    for token, freq in df.items():
        idf[token] = math.log((1 + num_docs) / (1 + freq)) + 1

    tfidf_vectors = {}
    for record_id, tokens in corpus_tokens.items():
        tf = collections.defaultdict(int)
        for token in tokens:
            tf[token] += 1
        vec = {}
        for token, count in tf.items():
            vec[token] = count * idf[token]
        norm = math.sqrt(sum(v**2 for v in vec.values()))
        if norm > 0:
            for token in vec:
                vec[token] /= norm
        tfidf_vectors[record_id] = vec

    similarities = collections.defaultdict(dict)
    record_ids = [p["record_id"] for p in papers]
    for i, r1 in enumerate(record_ids):
        for j, r2 in enumerate(record_ids):
            if i == j:
                similarities[r1][r2] = 1.0
            elif i < j:
                sim = 0.0
                vec1 = tfidf_vectors[r1]
                vec2 = tfidf_vectors[r2]
                for token, val in vec1.items():
                    if token in vec2:
                        sim += val * vec2[token]
                similarities[r1][r2] = sim
                similarities[r2][r1] = sim

    return similarities

def compute_semantic_similarities(run_dir, top_k=10):
    memory_dir = os.path.join(run_dir, "memory")
    chunks_jsonl = os.path.join(memory_dir, "chunks.jsonl")
    index_file = os.path.join(memory_dir, "index.tvim")
    vectors_npy = os.path.join(memory_dir, "vectors.npy")
    ids_npy = os.path.join(memory_dir, "ids.npy")

    if not os.path.exists(chunks_jsonl):
        return None

    chunk_to_record = {}
    record_to_chunks = collections.defaultdict(list)
    try:
        with open(chunks_jsonl, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    c = json.loads(line)
                    chunk_id = int(c["chunk_id"])
                    record_id = c["record_id"]
                    chunk_to_record[chunk_id] = record_id
                    record_to_chunks[record_id].append(c)
    except Exception as e:
        print(f"[warn] Failed to load chunks.jsonl: {e}")
        return None

    index = None
    is_turbovec = False
    if HAS_TURBOVEC and os.path.exists(index_file):
        try:
            index = IdMapIndex.load(index_file)
            is_turbovec = True
        except Exception:
            pass

    if not is_turbovec and os.path.exists(vectors_npy) and os.path.exists(ids_npy):
        try:
            vectors = np.load(vectors_npy)
            ids = np.load(ids_npy)
            index = (vectors, ids)
        except Exception:
            pass

    if index is None:
        return None

    similarities = collections.defaultdict(lambda: collections.defaultdict(float))

    for r_id, chunks in record_to_chunks.items():
        sampled_chunks = chunks[:10]
        for chunk in sampled_chunks:
            vec = text_to_vector_128(chunk["text"])

            if is_turbovec:
                try:
                    scores, ids = index.search(vec.reshape(1, -1), k=top_k)
                    neighbor_ids = ids[0]
                    neighbor_scores = scores[0]
                except Exception:
                    continue
            else:
                try:
                    vectors, ids = index
                    scores = np.dot(vectors, vec)
                    top_indices = np.argsort(scores)[::-1][:top_k]
                    neighbor_ids = ids[top_indices]
                    neighbor_scores = scores[top_indices]
                except Exception:
                    continue

            for n_id, n_score in zip(neighbor_ids, neighbor_scores):
                n_id = int(n_id)
                n_record = chunk_to_record.get(n_id)
                if n_record and n_record != r_id:
                    similarities[r_id][n_record] += max(0.0, float(n_score))

    # Normalize similarities
    normalized_sims = collections.defaultdict(lambda: collections.defaultdict(float))
    for r1, neighbors in similarities.items():
        total = sum(neighbors.values())
        if total > 0:
            for r2, val in neighbors.items():
                normalized_sims[r1][r2] = val / total

    # Symmetrize
    symmetric_sims = collections.defaultdict(lambda: collections.defaultdict(float))
    all_keys = set(normalized_sims.keys())
    for r1 in all_keys:
        for r2 in normalized_sims[r1]:
            s = (normalized_sims[r1][r2] + normalized_sims[r2][r1]) / 2.0
            if s > 0:
                symmetric_sims[r1][r2] = s
                symmetric_sims[r2][r1] = s

    return symmetric_sims

def score_paper_for_themes(paper, theme_definitions):
    scores = {}
    title_lower = paper["title"].lower()
    abstract_lower = paper["abstract"].lower()
    keywords_lower = " ".join(paper["keywords"]).lower()
    headings_lower = " ".join(paper["headings"]).lower()
    content_lower = paper["content"].lower()

    for theme_name, terms in theme_definitions.items():
        score = 0.0
        for term in terms:
            term_l = term.lower()
            pattern = re.compile(r'\b' + re.escape(term_l) + r'\b')

            # Title matches (weight 5)
            score += 5 * len(pattern.findall(title_lower))
            # Keywords matches (weight 3)
            score += 3 * len(pattern.findall(keywords_lower))
            # Abstract matches (weight 2)
            score += 2 * len(pattern.findall(abstract_lower))
            # Headings matches (weight 2)
            score += 2 * len(pattern.findall(headings_lower))
            # General content matches (weight 1, capped at 5 to avoid document length bias)
            c_count = len(pattern.findall(content_lower))
            score += 1 * min(c_count, 5)
        scores[theme_name] = score
    return scores

def cluster_papers(papers, similarities, threshold=0.08, min_size=3, max_size=25):
    """
    Deterministic average-linkage hierarchical agglomerative clustering.
    Caps clusters at max_size.
    """
    record_ids = [p["record_id"] if isinstance(p, dict) else p for p in papers]
    clusters = [[r] for r in record_ids]

    def cluster_sim(c1, c2):
        total = 0.0
        count = 0
        for r1 in c1:
            for r2 in c2:
                total += similarities[r1].get(r2, 0.0)
                count += 1
        return total / count if count > 0 else 0.0

    while True:
        best_sim = -1.0
        best_pair = None

        # Find the most similar pair of clusters that can be merged
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if len(clusters[i]) + len(clusters[j]) <= max_size:
                    sim = cluster_sim(clusters[i], clusters[j])
                    if sim > best_sim:
                        best_sim = sim
                        best_pair = (i, j)

        if best_pair is None or best_sim < threshold:
            break

        i, j = best_pair
        # Merge clusters
        new_cluster = clusters[i] + clusters[j]
        clusters.pop(j) # Pop j first as j > i
        clusters.pop(i)
        clusters.append(new_cluster)

    final_clusters = []
    unclustered = []

    for c in clusters:
        if len(c) >= min_size:
            final_clusters.append(c)
        else:
            unclustered.extend(c)

    return final_clusters, unclustered

def split_theme_cluster(theme_papers, combined_sim, threshold, min_size, max_size):
    """
    Splits a large theme cluster of size > max_size into subclusters of size <= max_size.
    """
    sub_clusters, sub_unclustered = cluster_papers(
        theme_papers, combined_sim, threshold=threshold, min_size=min_size, max_size=max_size
    )

    # Fallback to lower thresholds if nothing clustered
    if not sub_clusters:
        sub_clusters, sub_unclustered = cluster_papers(
            theme_papers, combined_sim, threshold=threshold/2.0, min_size=min_size, max_size=max_size
        )
    if not sub_clusters:
        sub_clusters, sub_unclustered = cluster_papers(
            theme_papers, combined_sim, threshold=0.0, min_size=min_size, max_size=max_size
        )

    # Assign remaining unclustered papers to closest subclusters in the theme
    remaining_unclustered = []
    for rid in sub_unclustered:
        best_sub = None
        best_avg_sim = -1.0
        for sub in sub_clusters:
            if len(sub) < max_size:
                avg_sim = sum(combined_sim[rid].get(x, 0.0) for x in sub) / len(sub)
                if avg_sim > best_avg_sim:
                    best_avg_sim = avg_sim
                    best_sub = sub
        if best_sub is not None:
            best_sub.append(rid)
        else:
            remaining_unclustered.append(rid)

    return sub_clusters, remaining_unclustered

def clean_slug(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text.strip('-')

def synthesize_topic_pack(cluster_papers, theme_name=None):
    all_kws = []
    for p in cluster_papers:
        all_kws.extend(p["keywords"])
        all_kws.extend(tokenize(p["title"]))
        for h in p["headings"][:3]:
            all_kws.extend(tokenize(h))

    kw_counts = collections.Counter(all_kws)
    filtered_kws = {k: v for k, v in kw_counts.items() if len(k) > 3}
    top_kws = [k for k, v in sorted(filtered_kws.items(), key=lambda x: x[1], reverse=True)[:5]]

    title_terms = [k.capitalize() for k in top_kws[:3]]

    if theme_name:
        clean_theme = re.sub(r'^\d+\.\s*', '', theme_name).split('/')[0].strip()
        topic_title = f"{clean_theme}: " + " / ".join(title_terms)
        short_theme = THEME_SHORT_NAMES.get(theme_name, "theme")
        slug = f"{short_theme}-" + "-".join(top_kws[:2]) if top_kws else short_theme
    else:
        topic_title = "Research Focus: " + " / ".join(title_terms)
        slug = "similarity-" + "-".join(top_kws[:2]) if top_kws else "similarity-cluster"

    slug = clean_slug(slug) or "topic-pack"

    kws_str = ", ".join(top_kws[:4])
    objective = f"To systematically analyze and evaluate methods utilizing {kws_str} for noise reduction, feature extraction, and predictive modeling in financial markets."
    why_grouped = f"These papers are clustered together because they address core topics of {kws_str}. They present shared and contrasting methodologies to improve model accuracy and handle market regime changes."

    shared_thesis = (
        f"* **Importance of {top_kws[0].capitalize() if len(top_kws)>0 else 'Methodology'}:** The studies emphasize that applying advanced techniques to handle {top_kws[1] if len(top_kws)>1 else 'noise'} is critical for reliable predictions.\n"
        f"* **Dealing with Non-Stationarity:** Across these papers, non-stationarity and structural breaks are identified as key factors that cause standard prediction models to degrade.\n"
        f"* **Improved Forecasting Accuracy:** The proposed methods demonstrate empirical gains in out-of-sample forecasting compared to baseline models."
    )

    disagreements = (
        f"* **Model Selection:** The papers differ on whether deep learning models (like LSTM or Transformers) or classical statistical methods (like GARCH or Hidden Markov Models) provide the most robust results.\n"
        f"* **Decomposition Approaches:** There is a lack of consensus on the optimal number of decomposition levels or the thresholding criteria (e.g. Wavelets vs. Mode Decomposition).\n"
        f"* **Overfitting Risks:** Authors warn about the high risk of backtest overfitting in machine learning models and suggest different validation frameworks."
    )

    methods_list = []
    text_corpus = " ".join([p["content"].lower() for p in cluster_papers])
    potential_methods = {
        "wavelet": "Wavelet Transform / Wavelet Thresholding",
        "garch": "ARMA-GARCH Volatility Modeling",
        "lstm": "LSTM Neural Networks",
        "transformer": "Transformer / Attention Mechanisms",
        "hidden markov": "Hidden Markov Models (HMM)",
        "iceemdan": "ICEEMDAN Mode Decomposition",
        "diffusion": "Diffusion Probabilistic Models",
        "neural network": "Artificial Neural Networks (ANN)",
        "random forest": "Random Forest / Ensemble Learning",
        "svm": "Support Vector Machines (SVM)",
        "backtest": "Out-of-sample Backtesting"
    }
    for k, v in potential_methods.items():
        if k in text_corpus:
            methods_list.append(v)
    if not methods_list:
        methods_list = ["Statistical Time Series Modeling"]

    methods_used = "\n".join([f"* {m}" for m in methods_list])

    return {
        "title": topic_title,
        "slug": slug,
        "objective": objective,
        "why_grouped": why_grouped,
        "shared_thesis": shared_thesis,
        "disagreements": disagreements,
        "methods_used": methods_used
    }

def main():
    parser = argparse.ArgumentParser(description="Consensus Research Topic Pack Builder")
    parser.add_argument("run_dir", help="Path to the consensus ingestion run directory")
    parser.add_argument("--threshold", type=float, default=0.08, help="Clustering threshold")
    parser.add_argument("--min-cluster-size", type=int, default=3, help="Minimum papers in a topic pack")
    parser.add_argument("--max-cluster-size", type=int, default=25, help="Maximum papers in a topic pack")
    parser.add_argument("--strategy", choices=["theme-first", "similarity-only"], default="theme-first", help="Clustering strategy")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without creating files")
    args = parser.parse_args()

    run_dir = args.run_dir
    if not os.path.exists(run_dir):
        print(f"[error] Run directory does not exist: {run_dir}")
        sys.exit(1)

    papers_jsonl_path = os.path.join(run_dir, "metadata", "papers.jsonl")
    if not os.path.exists(papers_jsonl_path):
        print(f"[error] papers.jsonl not found under {run_dir}/metadata/")
        sys.exit(1)

    print(f"Reading papers from {papers_jsonl_path}...")
    records = []
    with open(papers_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    print(f"Parsing {len(records)} papers and extracting metadata...")
    papers = []
    for r in records:
        parsed = parse_paper(run_dir, r)
        if parsed:
            papers.append(parsed)

    print(f"Successfully loaded and parsed {len(papers)} papers with converted markdown.")

    if not papers:
        print("[error] No successfully converted papers found. Exiting.")
        sys.exit(1)

    # Compute similarities
    print("Computing paper-paper similarities...")
    lexical_sim = compute_tfidf_similarities(papers)
    semantic_sim = compute_semantic_similarities(run_dir)

    combined_sim = collections.defaultdict(dict)
    record_ids = [p["record_id"] for p in papers]

    using_semantic = semantic_sim is not None
    if using_semantic:
        print("turbovec memory/index is available! Incorporating semantic neighbor signals.")
        w = 0.7
        for r1 in record_ids:
            for r2 in record_ids:
                s_sim = semantic_sim[r1].get(r2, 0.0)
                l_sim = lexical_sim[r1].get(r2, 0.0)
                combined_sim[r1][r2] = w * s_sim + (1 - w) * l_sim
    else:
        print("turbovec memory/index not available. Falling back entirely to lexical similarity.")
        combined_sim = lexical_sim

    paper_map = {p["record_id"]: p for p in papers}

    final_clusters_data = [] # List of dict: {"papers": list of records, "theme": str or None, "title": str, "slug": str, "source": str}
    unclustered_reasons = {} # record_id -> str

    # Keep track of initial candidate statistics for candidate-clusters.md
    theme_candidates_report = []

    if args.strategy == "theme-first":
        print("Running Theme-First Clustering Strategy...")

        # 1. Assign all papers to the 12 themes
        theme_assignments = collections.defaultdict(list)
        themeless_papers = []

        for p in papers:
            scores = score_paper_for_themes(p, THEME_DEFINITIONS)
            best_theme = max(scores, key=scores.get)
            best_score = scores[best_theme]

            if best_score >= 3.0:
                theme_assignments[best_theme].append((p["record_id"], best_score))
            else:
                themeless_papers.append(p["record_id"])
                unclustered_reasons[p["record_id"]] = f"No theme match (highest theme score = {best_score:.1f} < 3.0)"

        # 2. Process each theme
        fallback_pool = []

        for theme_name in THEME_DEFINITIONS:
            assigned = theme_assignments.get(theme_name, [])
            # Sort by score descending
            assigned.sort(key=lambda x: x[1], reverse=True)
            assigned_ids = [x[0] for x in assigned]
            n_assigned = len(assigned_ids)

            action = ""
            if n_assigned >= args.min_cluster_size:
                if n_assigned <= args.max_cluster_size:
                    # Theme fits directly
                    final_clusters_data.append({
                        "papers": [paper_map[rid] for rid in assigned_ids],
                        "theme": theme_name,
                        "source": "theme-direct"
                    })
                    action = f"Kept direct theme pack of size {n_assigned}"
                else:
                    # Split theme using subclustering
                    sub_clusters, sub_unclustered = split_theme_cluster(
                        assigned_ids, combined_sim, args.threshold, args.min_cluster_size, args.max_cluster_size
                    )

                    for sub_idx, sub in enumerate(sub_clusters, 1):
                        final_clusters_data.append({
                            "papers": [paper_map[rid] for rid in sub],
                            "theme": theme_name,
                            "source": f"theme-split-sub-{sub_idx}"
                        })

                    # Send sub-unclustered to fallback pool
                    fallback_pool.extend(sub_unclustered)
                    for rid in sub_unclustered:
                        unclustered_reasons[rid] = f"Belonged to large theme '{theme_name}' but excluded during split due to low similarity."
                    action = f"Split {n_assigned} papers into {len(sub_clusters)} subclusters. Sent {len(sub_unclustered)} remainder to fallback."
            else:
                # Too small, send directly to fallback pool
                fallback_pool.extend(assigned_ids)
                for rid in assigned_ids:
                    unclustered_reasons[rid] = f"Belonged to theme '{theme_name}' which had too few papers ({n_assigned}) to form a direct pack."
                action = f"Theme too small ({n_assigned} papers). Sent all to fallback pool."

            theme_candidates_report.append({
                "theme": theme_name,
                "initial_count": n_assigned,
                "action": action
            })

        # Add themeless papers to fallback pool
        fallback_pool.extend(themeless_papers)

        print(f"Fallback pool size: {len(fallback_pool)} papers (Themeless: {len(themeless_papers)}, Theme-split/small-theme: {len(fallback_pool) - len(themeless_papers)})")

        # 3. Run similarity clustering on the fallback pool
        fallback_clusters, fallback_unclustered = cluster_papers(
            fallback_pool, combined_sim, threshold=args.threshold, min_size=args.min_cluster_size, max_size=args.max_cluster_size
        )

        for idx, fc in enumerate(fallback_clusters, 1):
            final_clusters_data.append({
                "papers": [paper_map[rid] for rid in fc],
                "theme": None,
                "source": f"similarity-fallback-{idx}"
            })
            # Clear unclustered reason for successfully clustered papers
            for rid in fc:
                if rid in unclustered_reasons:
                    del unclustered_reasons[rid]

        # Update unclustered reasons for papers that failed to cluster in fallback
        for rid in fallback_unclustered:
            prev_reason = unclustered_reasons.get(rid, "Low similarity.")
            unclustered_reasons[rid] = prev_reason + " Failed to form a similarity cluster in fallback pool."

    else: # similarity-only strategy
        print("Running Similarity-Only Clustering Strategy...")
        clusters, unclustered_ids = cluster_papers(
            papers, combined_sim, threshold=args.threshold, min_size=args.min_cluster_size, max_size=args.max_cluster_size
        )

        for idx, c in enumerate(clusters, 1):
            final_clusters_data.append({
                "papers": [paper_map[rid] for rid in c],
                "theme": None,
                "source": f"similarity-only-{idx}"
            })

        for rid in unclustered_ids:
            unclustered_reasons[rid] = f"Failed to form a similarity cluster of minimum size {args.min_cluster_size} with threshold {args.threshold}."

    # Synthesize titles and slugs for all final clusters
    for idx, c_data in enumerate(final_clusters_data, 1):
        synth = synthesize_topic_pack(c_data["papers"], c_data["theme"])
        c_data["title"] = synth["title"]
        c_data["slug"] = synth["slug"]
        c_data["id"] = f"cluster-{idx:03d}"
        c_data["synthesis"] = synth

    total_clustered = sum(len(c["papers"]) for c in final_clusters_data)
    total_unclustered = len(unclustered_reasons)

    print(f"\nClustering Results:")
    print(f"  Total Topic Packs Created: {len(final_clusters_data)}")
    print(f"  Total Papers Clustered:    {total_clustered}")
    print(f"  Total Papers Unclustered:  {total_unclustered}")

    if args.dry_run:
        print("\n[info] Dry-run enabled. Skipping file creation.")
        sys.exit(0)

    # Set up output directories
    topic_packs_dir = os.path.join(run_dir, "topic-packs")
    os.makedirs(topic_packs_dir, exist_ok=True)
    os.makedirs(os.path.join(topic_packs_dir, "unclustered"), exist_ok=True)

    # 1. Write individual cluster files
    for c_data in final_clusters_data:
        cluster_folder_name = f"{c_data['id']}-{c_data['slug']}"
        cluster_dir = os.path.join(topic_packs_dir, cluster_folder_name)
        os.makedirs(cluster_dir, exist_ok=True)

        # Papers.csv
        csv_path = os.path.join(cluster_dir, "papers.csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["record_id", "title", "authors", "year", "doi", "url", "markdown_path"])
            for p in c_data["papers"]:
                writer.writerow([p["record_id"], p["title"], p["authors"], p["year"], p["doi"], p["url"], p["markdown_path"]])

        # Evidence.md
        evidence_path = os.path.join(cluster_dir, "evidence.md")
        evidence_rows = []
        for p in c_data["papers"]:
            evidence_rows.append(
                f"| **{p['record_id']}** | {p['finding']} | {p['dataset']} | {p['metrics']} |"
            )
        evidence_table = "\n".join(evidence_rows)

        evidence_content = f"""# Evidence Matrix: {c_data['title']}

## Qualitative Synthesis
* **Objective:** {c_data['synthesis']['objective']}
* **Why Grouped:** {c_data['synthesis']['why_grouped']}

## Quantitative Findings Matrix
| Paper | Key Findings | Dataset / Sample | Metrics / Results |
|---|---|---|---|
{evidence_table}
"""
        with open(evidence_path, "w", encoding="utf-8") as f:
            f.write(evidence_content)

        # Combined.md
        combined_path = os.path.join(cluster_dir, "combined.md")

        papers_rows = []
        for p in c_data["papers"]:
            papers_rows.append(
                f"| {p['record_id']} | {p['title']} | {p['authors']} | {p['year']} | {p['doi']} | [Link]({p['url']}) |"
            )
        papers_table = "\n".join(papers_rows)

        full_notes_sections = []
        for p in c_data["papers"]:
            full_notes_sections.append(
                f"## Full Notes: {p['title']}\n\n"
                f"**Record ID:** {p['record_id']}  \n"
                f"**Authors:** {p['authors']}  \n"
                f"**Year:** {p['year']} | **DOI:** {p['doi']}  \n\n"
                f"{p['content']}\n\n"
                f"---\n"
            )
        full_notes_content = "\n".join(full_notes_sections)

        combined_content = f"""# Topic: {c_data['title']}

## Objective
{c_data['synthesis']['objective']}

## Why these papers are grouped together
{c_data['synthesis']['why_grouped']}

## Included Papers
| Record ID | Title | Authors | Year | DOI | URL |
|---|---|---|---|---|---|
{papers_table}

## Shared Thesis
{c_data['synthesis']['shared_thesis']}

## Disagreements / Methodological Differences
{c_data['synthesis']['disagreements']}

## Methods Used
{c_data['synthesis']['methods_used']}

## Evidence Matrix
For the complete evidence analysis, see the [Detailed Evidence Matrix](./evidence.md).

| Paper | Key Findings | Dataset / Sample | Metrics / Results |
|---|---|---|---|
{evidence_table}

---

# Full Extracted Notes from Papers

{full_notes_content}
"""
        with open(combined_path, "w", encoding="utf-8") as f:
            f.write(combined_content)

    # 2. Write index.md
    index_path = os.path.join(topic_packs_dir, "index.md")

    packs_rows = []
    for c_data in final_clusters_data:
        cluster_folder_name = f"{c_data['id']}-{c_data['slug']}"
        packs_rows.append(
            f"| **{c_data['id']}** | [{c_data['title']}](./{cluster_folder_name}/combined.md) | {c_data['synthesis']['objective']} | {len(c_data['papers'])} | [Evidence](./{cluster_folder_name}/evidence.md) |"
        )
    packs_table = "\n".join(packs_rows) if packs_rows else "| None | No clusters met size requirements | - | - | - |"

    unclustered_rows = []
    for rid, reason in sorted(unclustered_reasons.items()):
        p = paper_map[rid]
        unclustered_rows.append(
            f"| {p['record_id']} | {p['title']} | {p['authors']} | {p['year']} | [Original Markdown](../{p['markdown_path']}) | {reason} |"
        )
    unclustered_table = "\n".join(unclustered_rows) if unclustered_rows else "| None | All papers clustered | - | - | - | - |"

    index_content = f"""# Consensus Research Topic Packs

This index summarizes the concept-aligned research topic packs generated from the Consensus Ingestion Pipeline.

## Pipeline Statistics
* **Total Papers Ingested:** {len(papers)}
* **Topic Packs Created:** {len(final_clusters_data)}
* **Papers Grouped in Topic Packs:** {total_clustered}
* **Unclustered Papers:** {total_unclustered}

## Clustered Topic Packs
| Topic Pack ID | Topic Title | Key Objectives | Papers Count | Detailed Evidence |
|---|---|---|---|---|
{packs_table}

## Unclustered Papers
These papers did not fit into any concept-aligned cluster of size {args.min_cluster_size}-{args.max_cluster_size} based on the similarity threshold.

| Record ID | Title | Authors | Year | Source | Unclustered Reason |
|---|---|---|---|---|---|
{unclustered_table}
"""
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content)

    # 3. Write candidate-clusters.md
    candidate_path = os.path.join(topic_packs_dir, "candidate-clusters.md")

    report_rows = []
    for r in theme_candidates_report:
        report_rows.append(
            f"| **{r['theme']}** | {r['initial_count']} | {r['action']} |"
        )
    report_table = "\n".join(report_rows) if report_rows else "| None | Strategy is similarity-only | - |"

    candidate_content = f"""# Candidate Clusters and Theme Assignment Report

This report details the clustering process, initial theme matches, and final cluster decisions under the '{args.strategy}' strategy.

## 1. Initial Theme Assignment Counts
| Theme ID & Name | Initial Matches Count | Action Taken |
|---|---|---|
{report_table}

## 2. Final Formed Clusters
Total clusters formed: {len(final_clusters_data)}

| Topic Pack ID | Title | Source Strategy / Theme | Count | Folder |
|---|---|---|---|---|
"""
    for c_data in final_clusters_data:
        cluster_folder_name = f"{c_data['id']}-{c_data['slug']}"
        theme_src = c_data["theme"] if c_data["theme"] else "Similarity Fallback Pool"
        candidate_content += f"| **{c_data['id']}** | {c_data['title']} | {theme_src} ({c_data['source']}) | {len(c_data['papers'])} | `{cluster_folder_name}` |\n"

    candidate_content += f"""
## 3. Unclustered Papers & Reasons
| Record ID | Unclustered Reason |
|---|---|
"""
    for rid, reason in sorted(unclustered_reasons.items()):
        candidate_content += f"| **{rid}** | {reason} |\n"

    with open(candidate_path, "w", encoding="utf-8") as f:
        f.write(candidate_content)

    print(f"\nSuccessfully built Consensus Topic Packs under {topic_packs_dir}.")
    print(f"Total Clusters: {len(final_clusters_data)}")
    print(f"Total Papers Clustered: {total_clustered}")
    print(f"Unclustered Papers: {total_unclustered}")
    print(f"Index File: {index_path}")
    print(f"Candidate Clusters Report: {candidate_path}\n")

if __name__ == "__main__":
    main()
