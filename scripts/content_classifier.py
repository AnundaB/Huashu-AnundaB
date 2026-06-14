import os
import re
import sys
import numpy as np

# Add scripts directory to path to import semantic_index
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(REPO_ROOT, "scripts"))
import semantic_index

CATEGORY_PROTOTYPES = {
    "trading-finance": "Quantitative finance, algorithmic trading, stock analysis, portfolio management, stock market, brokers like IBKR, options, futures, risk management, asset pricing, trading strategies, technical indicators.",
    "crypto-web3": "Blockchain, cryptocurrency, DeFi, Ethereum, Bitcoin, smart contracts, tokenomics, web3, consensus algorithms, solidity, decentralization, tokens, wallets.",
    "ai-ml": "Artificial intelligence, machine learning, deep learning, large language models, neural networks, computer vision, natural language processing, embeddings, reinforcement learning, transformers, weights, training.",
    "programming": "Software engineering, coding, Python, TypeScript, Rust, system architecture, database design, git repositories, APIs, web development, refactoring, algorithms, libraries, cargo, npm.",
    "research-paper": "Academic papers, scientific research, mathematical equations, theorems, experimental results, abstracts, bibliography, dataset methodology, study, researchers.",
    "business-ops": "Enterprise operations, startup management, SaaS, revenue, marketing strategies, business models, sales funnels, product management, logistics, economics, companies.",
    "legal-policy": "Legal documents, privacy policies, compliance requirements, government regulation, terms of service, governance, litigation, laws, policies.",
    "documentation": "API references, software documentation, guide, developer documentation, install commands, tutorials, config guides, setup guide.",
    "tutorial": "How-to guides, educational materials, course, tutorial walkthrough, steps to compile, coding tutorials, examples.",
    "transcript": "Video transcripts, YouTube captions, lecture transcripts, interview dialogues, spoken speech transcription, talking, speaking.",
    "social-post": "X posts, Twitter tweets, social media feeds, short commentary, online status updates, discussion forums, social networking."
}

# Deterministic keyword patterns for high-confidence matches
KEYWORDS = {
    "trading-finance": ["quant", "trading", "broker", "ibkr", "portfolio", "sharpe", "asset", "futures", "options", "stock", "drawdown", "backtest"],
    "crypto-web3": ["blockchain", "crypto", "defi", "ethereum", "bitcoin", "solidity", "token", "uniswap", "web3"],
    "ai-ml": ["artificial intelligence", "machine learning", "deep learning", "embeddings", "neural network", "transformer", "llm", "posttrain", "pretrain", "weights"],
    "programming": ["typescript", "javascript", "rust", "python", "compilation", "git", "api", "database", "repository", "cargo", "npm", "package.json"],
    "legal-policy": ["legal", "policy", "compliance", "regulation", "governance", "terms of service", "copyright"],
    "documentation": ["documentation", "setup guide", "install guide", "config guide", "reference manual"],
    "transcript": ["youtube transcript", "transcript", "uploader", "duration", "captions"],
    "social-post": ["twitter", "x post", "tweet", "status update"]
}


def classify_content(doc_text: str, doc_path: str | None = None) -> dict:
    """
    Classifies the document content and returns metadata:
    - content_category
    - topics
    - confidence
    - classifier_engine
    - classifier_version
    - semantic_neighbors
    - embedding_model
    - vector_backend
    """
    doc_text_clean = doc_text.lower()
    
    # 1. Deterministic Keyword Pass
    keyword_scores = {}
    for cat, words in KEYWORDS.items():
        score = 0
        for word in words:
            if word in doc_text_clean:
                score += doc_text_clean.count(word)
        if score > 0:
            keyword_scores[cat] = score

    # Choose category if keyword density is extremely high
    chosen_category = None
    keyword_confidence = 0.0
    if keyword_scores:
        best_cat = max(keyword_scores, key=keyword_scores.get)
        # Require a minimum score threshold for deterministic matching
        if keyword_scores[best_cat] >= 5:
            chosen_category = best_cat
            keyword_confidence = min(0.9, 0.5 + (keyword_scores[best_cat] * 0.02))

    # 2. Vector Proximity Pass
    # Pre-embed prototypes
    proto_embeddings = {cat: semantic_index.text_to_vector_128(desc) for cat, desc in CATEGORY_PROTOTYPES.items()}
    
    # Embed document first 10,000 characters for safety and performance
    sample_text = doc_text[:10000]
    doc_vec = semantic_index.text_to_vector_128(sample_text)
    
    vector_scores = {}
    for cat, vec in proto_embeddings.items():
        # Cosine similarity (dot product of unit vectors)
        vector_scores[cat] = float(np.dot(vec, doc_vec))

    best_vector_cat = max(vector_scores, key=vector_scores.get)
    vector_confidence = vector_scores[best_vector_cat]

    # Resolve final classification and confidence
    final_category = "unknown"
    confidence = 0.0
    engine = "keyword_boosted_vector"

    if chosen_category:
        final_category = chosen_category
        confidence = max(keyword_confidence, vector_confidence)
    else:
        # Fall back to vector classifier if confidence is sufficient
        if vector_confidence >= 0.15:
            final_category = best_vector_cat
            confidence = vector_confidence
            engine = "semantic_vector_only"
        else:
            final_category = "unknown"
            confidence = vector_confidence
            engine = "semantic_vector_low_confidence"

    # 3. Find semantic neighbors and index document
    semantic_neighbors = []
    if doc_path:
        idx = semantic_index.SemanticIndex()
        # Find neighbors *before* adding the current doc to avoid returning self
        try:
            similar = idx.search_similar(sample_text, k=4)
            for path, score in similar:
                if os.path.abspath(path) != os.path.abspath(doc_path):
                    semantic_neighbors.append(path)
            semantic_neighbors = semantic_neighbors[:3]
        except Exception:
            pass
            
        # Index this document for future queries
        try:
            idx.add_document(doc_path, sample_text)
        except Exception as e:
            print(f"[warn] Failed to index document in semantic memory: {e}")

    # Extract top 3 topics based on keyword matching
    topics = []
    if keyword_scores:
        sorted_keys = sorted(keyword_scores, key=keyword_scores.get, reverse=True)
        topics = sorted_keys[:3]
    if not topics and final_category != "unknown":
        topics = [final_category]

    return {
        "content_category": final_category,
        "topics": ",".join(topics) if topics else "general",
        "confidence": round(confidence, 4),
        "classifier_engine": engine,
        "classifier_version": "1.0.0",
        "semantic_neighbors": ",".join(semantic_neighbors) if semantic_neighbors else "",
        "embedding_model": "local_projected_hash_128",
        "vector_backend": "turbovec" if semantic_index.HAS_TURBOVEC else "numpy_fallback"
    }
