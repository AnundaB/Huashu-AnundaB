#!/usr/bin/env python3
"""
research_memory_index.py — Build and query a local vector memory index over ingested markdown papers using turbovec.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import datetime
import numpy as np

try:
    from turbovec import IdMapIndex
    HAS_TURBOVEC = True
except ImportError:
    HAS_TURBOVEC = False


def text_to_vector_128(text: str) -> np.ndarray:
    """
    Deterministically embeds a text chunk into a 128-dimensional dense vector space.
    Uses MD5 hashes of individual words to seed a deterministic generator, projecting
    words onto a unit hypersphere, and aggregates/renormalizes.
    """
    words = [w.strip() for w in text.lower().split() if w.strip()]
    if not words:
        return np.zeros(128, dtype=np.float32)

    vec = np.zeros(128, dtype=np.float32)
    for word in words:
        # Compute deterministic seed from word hash
        h = hashlib.md5(word.encode("utf-8")).digest()
        seed_int = int.from_bytes(h, byteorder="big") % (2**32)
        rng = np.random.default_rng(seed_int)
        
        # Generate 128-dim normal random projection
        word_vec = rng.standard_normal(128)
        norm = np.linalg.norm(word_vec)
        if norm > 0:
            word_vec /= norm
        vec += word_vec

    # Renormalize final aggregated vector
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.astype(np.float32)


def chunk_text(text: str, chunk_size: int = 150, chunk_overlap: int = 40) -> list[str]:
    """
    Chunks a string into overlapping word windows.
    """
    words = text.split()
    if not words:
        return []
    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i:i + chunk_size]
        chunks.append(" ".join(chunk_words))
        i += chunk_size - chunk_overlap
    return chunks


def build_index(run_dir: str, chunk_size: int, chunk_overlap: int) -> int:
    """
    Reads papers.jsonl and converted Markdown files, chunks them, embeds them,
    and indexes them with turbovec.IdMapIndex, saving outputs in the memory/ subdirectory.
    """
    if not os.path.exists(run_dir):
        sys.stderr.write(f"[error] Run directory does not exist: {run_dir}\n")
        return 1

    papers_jsonl_path = os.path.join(run_dir, "metadata", "papers.jsonl")
    if not os.path.exists(papers_jsonl_path):
        sys.stderr.write(f"[error] papers.jsonl not found at: {papers_jsonl_path}\n")
        return 1

    # Initialize memory folder
    memory_dir = os.path.join(run_dir, "memory")
    os.makedirs(memory_dir, exist_ok=True)

    print(f"Reading papers from {papers_jsonl_path}...")
    records = []
    with open(papers_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    chunks_data = []
    vectors_list = []
    chunk_counter = 1

    for r in records:
        record_id = r.get("record_id")
        title = r.get("title") or ""
        doi = r.get("doi") or ""
        url = r.get("url") or ""
        
        results = r.get("resolver_results") or {}
        markdown_path = results.get("markdown_path")
        
        if not markdown_path:
            continue
            
        full_md_path = os.path.join(run_dir, markdown_path)
        if not os.path.exists(full_md_path):
            print(f"[warn] Markdown file not found for {record_id}: {full_md_path}")
            continue

        try:
            with open(full_md_path, "r", encoding="utf-8") as mdf:
                content = mdf.read()
        except Exception as e:
            print(f"[error] Failed to read markdown for {record_id}: {e}")
            continue

        paper_chunks = chunk_text(content, chunk_size, chunk_overlap)
        print(f"  {record_id}: chunked into {len(paper_chunks)} text segments.")

        for idx, text in enumerate(paper_chunks):
            embedding = text_to_vector_128(text)
            vectors_list.append(embedding)
            
            chunks_data.append({
                "chunk_id": chunk_counter,
                "record_id": record_id,
                "title": title,
                "doi": doi,
                "url": url,
                "source_path": markdown_path,
                "offset_index": idx,
                "text": text
            })
            chunk_counter += 1

    if not chunks_data:
        print("[warn] Ingestion completed, but no Markdown artifacts were created. Memory index skipped.")
        return 0

    # Build dense arrays
    vectors = np.vstack(vectors_list).astype(np.float32)
    ids = np.array([c["chunk_id"] for c in chunks_data], dtype=np.uint64)

    # turbovec Indexing
    index_file = os.path.join(memory_dir, "index.tvim")
    if HAS_TURBOVEC:
        print(f"Initializing turbovec.IdMapIndex with dimension=128...")
        index = IdMapIndex(dim=128, bit_width=4)
        index.add_with_ids(vectors, ids)
        index.write(index_file)
        print(f"Index successfully written using turbovec to: {index_file}")
    else:
        print("[warn] turbovec not available. Writing fallback numpy raw vectors index...")
        np.save(os.path.join(memory_dir, "vectors.npy"), vectors)
        np.save(os.path.join(memory_dir, "ids.npy"), ids)

    # Save chunks metadata manifest
    chunks_jsonl_path = os.path.join(memory_dir, "chunks.jsonl")
    with open(chunks_jsonl_path, "w", encoding="utf-8") as f:
        for chunk in chunks_data:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    # Save mapping manifest
    id_map_path = os.path.join(memory_dir, "id_map.jsonl")
    with open(id_map_path, "w", encoding="utf-8") as f:
        for chunk in chunks_data:
            f.write(json.dumps({"chunk_id": chunk["chunk_id"], "record_id": chunk["record_id"]}, ensure_ascii=False) + "\n")

    # Index manifest
    manifest_path = os.path.join(memory_dir, "index_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_dir": os.path.basename(os.path.abspath(run_dir)),
            "dimension": 128,
            "total_chunks": len(chunks_data),
            "engine": "turbovec" if HAS_TURBOVEC else "numpy_fallback",
            "created_at": datetime.datetime.now().isoformat(),
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap
        }, f, indent=2)

    print(f"Successfully processed {len(chunks_data)} chunks. Index built under {memory_dir}.")
    return 0


def query_index(run_dir: str, query_text: str, k: int) -> int:
    """
    Loads vector index and chunks from run_dir, embeds query_text,
    searches top-k closest chunks, and prints formatted output.
    """
    memory_dir = os.path.join(run_dir, "memory")
    if not os.path.exists(memory_dir):
        # check if run_dir itself is the memory directory
        if os.path.exists(os.path.join(run_dir, "chunks.jsonl")):
            memory_dir = run_dir
        else:
            sys.stderr.write(f"[error] Memory subdirectory not found in {run_dir}\n")
            return 1

    chunks_jsonl_path = os.path.join(memory_dir, "chunks.jsonl")
    if not os.path.exists(chunks_jsonl_path):
        sys.stderr.write(f"[error] chunks.jsonl not found at: {chunks_jsonl_path}\n")
        return 1

    # Load chunks metadata
    chunks_by_id = {}
    with open(chunks_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunks_by_id[c["chunk_id"]] = c

    # Embed query
    query_vec = text_to_vector_128(query_text)

    index_file = os.path.join(memory_dir, "index.tvim")
    
    # Run Search
    if HAS_TURBOVEC and os.path.exists(index_file):
        try:
            index = IdMapIndex.load(index_file)
            # turbovec search expects shape (num_queries, dim), i.e. (1, 128)
            scores, ids = index.search(query_vec.reshape(1, -1), k=k)
            scores = scores[0]
            ids = ids[0]
        except Exception as e:
            sys.stderr.write(f"[error] Failed to load or search via turbovec: {e}\n")
            return 1
    else:
        # Fallback numpy raw search
        vectors_npy = os.path.join(memory_dir, "vectors.npy")
        ids_npy = os.path.join(memory_dir, "ids.npy")
        if not os.path.exists(vectors_npy) or not os.path.exists(ids_npy):
            sys.stderr.write(f"[error] No vector database found under {memory_dir}\n")
            return 1
        
        vectors = np.load(vectors_npy)
        ids = np.load(ids_npy)
        
        # Calculate cosine similarity manually: dot product of normalized vectors
        scores = np.dot(vectors, query_vec)
        top_indices = np.argsort(scores)[::-1][:k]
        scores = scores[top_indices]
        ids = ids[top_indices]

    print(f"\nSearch results for query: '{query_text}' (top {k}):\n" + "=" * 80)
    for idx, (score, chunk_id) in enumerate(zip(scores, ids)):
        chunk = chunks_by_id.get(int(chunk_id))
        if not chunk:
            print(f"{idx+1}. Score: {score:.4f} | Chunk ID {chunk_id} not found in metadata.")
            continue
        
        print(f"{idx+1}. Score: {score:.4f} | Record: {chunk['record_id']} | DOI: {chunk['doi']}")
        print(f"   Title:  {chunk['title']}")
        print(f"   Source: {chunk['source_path']} (Offset index: {chunk['offset_index']})")
        snippet = chunk["text"]
        if len(snippet) > 250:
            snippet = snippet[:247] + "..."
        print(f"   Text:   \"{snippet}\"")
        print("-" * 80)

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Build and query a local vector memory index using turbovec.")
    subparsers = p.add_subparsers(dest="command", required=True, help="Index subcommands")

    # Build subcommand
    p_build = subparsers.add_parser("build", help="Build vector index from consensus run outputs")
    p_build.add_argument("run_dir", help="Path to consensus run output folder")
    p_build.add_argument("--chunk-size", type=int, default=150, help="Chunk size in words. Default: 150")
    p_build.add_argument("--chunk-overlap", type=int, default=40, help="Chunk overlap in words. Default: 40")

    # Query subcommand
    p_query = subparsers.add_parser("query", help="Query a built local vector index")
    p_query.add_argument("run_dir", help="Path to consensus run output folder (containing memory/)")
    p_query.add_argument("query_text", help="Search string query")
    p_query.add_argument("-k", "--top-k", type=int, default=3, help="Number of results to return. Default: 3")

    args = p.parse_args()

    if args.command == "build":
        return build_index(args.run_dir, args.chunk_size, args.chunk_overlap)
    elif args.command == "query":
        return query_index(args.run_dir, args.query_text, args.top_k)

    return 0


if __name__ == "__main__":
    sys.exit(main())
