import os
import tempfile
import unittest
import json
import numpy as np
import importlib

# Force clean test isolation by choosing a temp directory for index files
TEST_DIR = tempfile.TemporaryDirectory()
os.environ["HUASHU_AUTO_DIR"] = TEST_DIR.name

import semantic_index

class TestSemanticBenchmarks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["HUASHU_AUTO_DIR"] = self.temp_dir.name
        
        # Reload to use the correct directory paths
        importlib.reload(semantic_index)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_retrieval_benchmark(self):
        """
        Retrieval quality benchmark fixture.
        Indexes a synthetic document set and measures Mean Reciprocal Rank (MRR)
        of queries against the local_projected_hash_128 baseline.
        """
        idx = semantic_index.SemanticIndex()
        
        # Synthetic Documents
        documents = {
            "doc1_finance": "Stock trading algorithm, backtesting platform, options and futures, portfolio optimization and IBKR broker.",
            "doc2_crypto": "Decentralized smart contracts on Ethereum, blockchain cryptography, consensus algorithms and DeFi tokens.",
            "doc3_ai": "Transformer models, deep neural networks, supervised fine-tuning, training weights and large language models LLMs.",
            "doc4_legal": "Legal terms of service, compliance framework, corporate privacy policy and government regulation laws."
        }
        
        for doc_id, text in documents.items():
            idx.add_document(doc_id, text)
            
        # Synthetic Queries and expected primary document
        queries = [
            ("algorithmic portfolio backtest", "doc1_finance"),
            ("smart contract DeFi Solidity", "doc2_crypto"),
            ("LLM fine-tuning transformers training", "doc3_ai"),
            ("corporate policy compliance legal", "doc4_legal")
        ]
        
        rr_sum = 0.0
        print("\n=== Retrieval Quality Benchmark (local_projected_hash_128) ===")
        for query, expected_doc in queries:
            results = idx.search_similar(query, k=4)
            # Find rank of expected doc
            rank = None
            for idx_rank, (doc_id, score) in enumerate(results):
                if doc_id == expected_doc:
                    rank = idx_rank + 1
                    break
            
            reciprocal_rank = 1.0 / rank if rank is not None else 0.0
            rr_sum += reciprocal_rank
            print(f"Query: '{query}' -> Expected: {expected_doc} -> Rank: {rank} (Reciprocal Rank: {reciprocal_rank})")
            
        mrr = rr_sum / len(queries)
        print(f"Mean Reciprocal Rank (MRR): {mrr:.4f}")
        print("==============================================================\n")
        
        # Default baseline should achieve perfect or near-perfect ranking on these distinct categories
        self.assertGreaterEqual(mrr, 0.75, "Retrieval quality fell below acceptable baseline threshold.")

    def test_provider_mismatch_fails_closed(self):
        """
        Ensures that loading an index created with a different provider fails closed.
        """
        # Save an index with the default provider
        idx = semantic_index.SemanticIndex(provider_name="local_projected_hash_128")
        idx.add_document("doc1", "Sample text for testing")
        
        # Attempt to load it as a different provider (e.g. sentence-transformers)
        with self.assertRaises(ValueError) as ctx:
            semantic_index.SemanticIndex(provider_name="sentence-transformers")
        self.assertIn("Provider mismatch", str(ctx.exception))

    def test_model_mismatch_fails_closed(self):
        """
        Ensures that loading an index created with a different model ID fails closed.
        """
        # Save an index with model A
        idx = semantic_index.SemanticIndex(model_id="model_a")
        idx.add_document("doc1", "Sample text for testing")
        
        # Attempt to load it as model B
        with self.assertRaises(ValueError) as ctx:
            semantic_index.SemanticIndex(model_id="model_b")
        self.assertIn("Model ID mismatch", str(ctx.exception))

    def test_dimension_mismatch_fails_closed(self):
        """
        Ensures that loading an index created with a different dimension fails closed.
        """
        # Save an index with dimension 128
        idx = semantic_index.SemanticIndex(dimension=128)
        idx.add_document("doc1", "Sample text for testing")
        
        # Attempt to load it as dimension 256
        with self.assertRaises(ValueError) as ctx:
            semantic_index.SemanticIndex(dimension=256)
        self.assertIn("Dimension mismatch", str(ctx.exception))

    def test_corrupted_id_length_fails_closed(self):
        """
        Ensures that a length mismatch between IDs and loaded vectors fails closed.
        """
        # Save a valid index
        idx = semantic_index.SemanticIndex()
        idx.add_document("doc1", "Sample text for testing")
        
        # Manually corrupt the metadata file by adding an extra ID without a corresponding vector
        with open(semantic_index.METADATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["ids"].append(999) # Add mismatched ID
        
        with open(semantic_index.METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
            
        # Re-loading the corrupted index should raise ValueError
        with self.assertRaises(ValueError) as ctx:
            semantic_index.SemanticIndex()
        self.assertIn("Index corruption", str(ctx.exception))

    def test_never_mix_dimensions_adds(self):
        """
        Ensures that trying to add a document with mismatching vector dimension fails.
        """
        idx = semantic_index.SemanticIndex(dimension=256)
        # Attempt to index with default 128-dimension embedder
        with self.assertRaises(ValueError) as ctx:
            idx.add_document("doc1", "Sample text")
        self.assertIn("dimension mismatch", str(ctx.exception).lower())

if __name__ == "__main__":
    unittest.main()
