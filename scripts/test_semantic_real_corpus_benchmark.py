import os
import tempfile
import unittest
import json
import importlib

# Force clean test isolation by setting HUASHU_AUTO_DIR
TEST_DIR = tempfile.TemporaryDirectory()
os.environ["HUASHU_AUTO_DIR"] = TEST_DIR.name

import semantic_real_corpus_benchmark

class TestSemanticRealCorpusBenchmark(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        
    def tearDown(self):
        self.temp_dir.cleanup()
        
    def test_discover_corpus_files_safety(self):
        """
        Verifies that only safe, valid markdown files are discovered,
        and that ignored directories/files are correctly bypassed.
        """
        # Create mock directories and files
        corpus_dir = os.path.join(self.temp_dir.name, "outputs", "consensus")
        os.makedirs(corpus_dir, exist_ok=True)
        
        # Safe markdown file
        safe_file = os.path.join(corpus_dir, "doc1.md")
        with open(safe_file, "w") as f:
            f.write("# Dummy Content")
            
        # Ignored pattern path
        ignored_dir = os.path.join(self.temp_dir.name, "outputs", "consensus", "browser-profiles")
        os.makedirs(ignored_dir, exist_ok=True)
        ignored_file = os.path.join(ignored_dir, "stolen_profile.md")
        with open(ignored_file, "w") as f:
            f.write("# Secrets")
            
        # Non-markdown file
        non_md_file = os.path.join(corpus_dir, "doc2.txt")
        with open(non_md_file, "w") as f:
            f.write("Text content")
            
        # Mock REPO_ROOT in discover_corpus_files
        original_repo_root = semantic_real_corpus_benchmark.REPO_ROOT
        semantic_real_corpus_benchmark.REPO_ROOT = self.temp_dir.name
        
        try:
            discovered = semantic_real_corpus_benchmark.discover_corpus_files()
            self.assertEqual(len(discovered), 1)
            self.assertEqual(os.path.basename(discovered[0]), "doc1.md")
        finally:
            semantic_real_corpus_benchmark.REPO_ROOT = original_repo_root

    def test_matches_expected(self):
        """
        Verifies expected target matching logic for both Unix and Windows path formats.
        """
        self.assertTrue(semantic_real_corpus_benchmark.matches_expected(
            "/path/to/adesina-2024-algorithmic-trading-machine.md",
            ["adesina-2024-algorithmic-trading-machine.md"]
        ))
        self.assertTrue(semantic_real_corpus_benchmark.matches_expected(
            "C:\\path\\to\\adesina-2024-algorithmic-trading-machine.md",
            ["adesina-2024-algorithmic-trading-machine.md"]
        ))
        self.assertFalse(semantic_real_corpus_benchmark.matches_expected(
            "/path/to/other.md",
            ["adesina-2024-algorithmic-trading-machine.md"]
        ))

    def test_run_benchmark_and_metrics_calculation(self):
        """
        Asserts correctness of MRR, Recall, and latency metric calculations in isolated temp directories.
        """
        # Create temp files
        doc1_path = os.path.join(self.temp_dir.name, "doc1.md")
        doc2_path = os.path.join(self.temp_dir.name, "doc2.md")
        
        with open(doc1_path, "w") as f:
            f.write("Stock algorithmic trading machine learning broker IBKR")
        with open(doc2_path, "w") as f:
            f.write("Smart contract Solidity Ethereum blockchain consensus")
            
        corpus_files = [doc1_path, doc2_path]
        
        queries_data = [
            {
                "query": "algorithmic trading machine learning",
                "expected_docs": ["doc1.md"]
            },
            {
                "query": "smart contract Solidity blockchain",
                "expected_docs": ["doc2.md"]
            },
            {
                "query": "completely missing topic",
                "expected_docs": ["doc_missing.md"]
            }
        ]
        
        with tempfile.TemporaryDirectory() as index_temp_dir:
            metrics = semantic_real_corpus_benchmark.run_benchmark(
                corpus_files, queries_data, index_temp_dir
            )
            
            # Evaluated query count must be 2 (the missing one should be skipped)
            self.assertEqual(metrics["query_count"], 2)
            self.assertEqual(metrics["skipped_query_count"], 1)
            
            # Since doc1 matches query 1 best and doc2 matches query 2 best, MRR/Recall should be 1.0
            self.assertEqual(metrics["mrr"], 1.0)
            self.assertEqual(metrics["recall_at_5"], 1.0)
            self.assertEqual(metrics["recall_at_10"], 1.0)
            self.assertGreater(metrics["avg_latency_ms"], 0.0)
            
            # Verify metadata fields
            self.assertEqual(metrics["provider"], "local_projected_hash_128")
            self.assertEqual(metrics["dimension"], 128)

if __name__ == "__main__":
    unittest.main()
