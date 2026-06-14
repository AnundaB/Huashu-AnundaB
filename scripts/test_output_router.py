import os
import tempfile
import unittest
import csv
import importlib

# Set env var before importing output_router for test isolation
TEST_DIR = tempfile.TemporaryDirectory()
os.environ["HUASHU_AUTO_DIR"] = TEST_DIR.name

import output_router

class TestOutputRouter(unittest.TestCase):
    def setUp(self):
        # Create a new temp directory for each test run
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["HUASHU_AUTO_DIR"] = self.temp_dir.name
        
        # Reload output_router to pick up the new HUASHU_AUTO_DIR
        importlib.reload(output_router)
        
        # Verify globals are correctly set to the temporary directory
        self.assertEqual(output_router.AUTO_DIR, self.temp_dir.name)
        self.assertEqual(output_router.MANIFEST_PATH, os.path.join(self.temp_dir.name, "manifest.csv"))
        self.assertEqual(output_router.INDEX_PATH, os.path.join(self.temp_dir.name, "index.md"))

    def tearDown(self):
        # Cleanup the temp directory
        self.temp_dir.cleanup()

    def test_classify_source_all(self):
        # YouTube
        self.assertEqual(output_router.classify_source("https://www.youtube.com/watch?v=HrkDF6VhRo8"), ("youtube", "youtube"))
        self.assertEqual(output_router.classify_source("https://youtu.be/HrkDF6VhRo8"), ("youtube", "youtube"))
        self.assertEqual(output_router.classify_source("https://example.com", "youtube"), ("youtube", "youtube"))

        # X/Twitter text
        self.assertEqual(output_router.classify_source("https://x.com/user/status/1234"), ("x_text", "x/text"))
        self.assertEqual(output_router.classify_source("https://twitter.com/user/status/1234"), ("x_text", "x/text"))
        self.assertEqual(output_router.classify_source("manual", "x-text"), ("x_text", "x/text"))

        # X/Twitter video
        self.assertEqual(output_router.classify_source("https://x.com/user/status/1234/video/1"), ("x_video", "x/video"))
        self.assertEqual(output_router.classify_source("https://x.com/user/status/1234", "x-video"), ("x_video", "x/video"))

        # ChatGPT
        self.assertEqual(output_router.classify_source("https://chatgpt.com/c/uuid"), ("chatgpt", "chatgpt"))
        self.assertEqual(output_router.classify_source("https://chat.openai.com/c/uuid"), ("chatgpt", "chatgpt"))
        self.assertEqual(output_router.classify_source("manual", "chatgpt-export"), ("chatgpt", "chatgpt"))

        # Docs
        self.assertEqual(output_router.classify_source("https://example.com", "docs"), ("docs", "docs"))

        # GitHub
        self.assertEqual(output_router.classify_source("https://github.com/user/repo"), ("github", "github"))

        # Generic web/page
        self.assertEqual(output_router.classify_source("https://example.com/article"), ("web", "web"))

        # Misc/fallback
        self.assertEqual(output_router.classify_source("local_path/file.txt"), ("misc", "misc"))

    def test_route_output_all(self):
        # Test routing paths for various categories
        self.assertTrue(output_router.route_output("https://youtube.com/watch?v=1", "f.md").endswith("youtube/f.md"))
        self.assertTrue(output_router.route_output("https://x.com/u/status/1", "f.md").endswith("x/text/f.md"))
        self.assertTrue(output_router.route_output("https://x.com/u/status/1/video/1", "f.md").endswith("x/video/f.md"))
        self.assertTrue(output_router.route_output("https://chatgpt.com/c/1", "f.md").endswith("chatgpt/f.md"))
        self.assertTrue(output_router.route_output("https://example.com/doc", "f.md", "docs").endswith("docs/f.md"))
        self.assertTrue(output_router.route_output("https://github.com/u/r", "f.md").endswith("github/f.md"))
        self.assertTrue(output_router.route_output("https://example.com", "f.md").endswith("web/f.md"))
        self.assertTrue(output_router.route_output("abc", "f.md").endswith("misc/f.md"))

    def test_register_output_manifest_and_index(self):
        # Touch mock files and register them
        files_to_register = [
            ("https://youtube.com/watch?v=1", "yt.md", "youtube", "YouTube Title"),
            ("https://x.com/u/status/123", "x_post.md", "x-text", "X Post Title"),
            ("https://x.com/u/status/123/video/1", "x_vid.md", "x-video", "X Video Title"),
            ("https://chatgpt.com/c/abc", "gpt.md", "chatgpt", "ChatGPT Title"),
            ("https://github.com/user/repo", "git.md", "github", "GitHub Title"),
            ("https://example.com/article", "web.md", "web", "Web Page Title"),
            ("some_local_fallback", "misc.md", "misc", "Misc Title")
        ]

        for source, filename, explicit_type, title in files_to_register:
            path = output_router.route_output(source, filename, explicit_type)
            with open(path, "w") as f:
                f.write("# Dummy\n")
            output_router.register_output(path, source, explicit_type, title, "success")

        # 1. Verify manifest.csv contents
        self.assertTrue(os.path.exists(output_router.MANIFEST_PATH))
        with open(output_router.MANIFEST_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 7)
            
            # Check a few records specifically
            categories = [row["category"] for row in rows]
            self.assertIn("youtube", categories)
            self.assertIn("x/text", categories)
            self.assertIn("x/video", categories)
            self.assertIn("chatgpt", categories)
            self.assertIn("github", categories)
            self.assertIn("web", categories)
            self.assertIn("misc", categories)

        # 2. Verify index.md formatting
        self.assertTrue(os.path.exists(output_router.INDEX_PATH))
        with open(output_router.INDEX_PATH, "r", encoding="utf-8") as f:
            index_content = f.read()
            self.assertIn("# Huashu Auto-Research Extract Index", index_content)
            self.assertIn("### YouTube Transcripts", index_content)
            self.assertIn("### X (Twitter) Posts", index_content)
            self.assertIn("### X (Twitter) Videos", index_content)
            self.assertIn("### ChatGPT Conversations", index_content)
            self.assertIn("### GitHub Repositories", index_content)
            self.assertIn("### Web Pages", index_content)
            self.assertIn("### Miscellaneous Extracts", index_content)
            
            # Check link matches
            self.assertIn("[YouTube Title](youtube/yt.md)", index_content)
            self.assertIn("[X Post Title](x/text/x_post.md)", index_content)
            self.assertIn("[X Video Title](x/video/x_vid.md)", index_content)
            self.assertIn("[ChatGPT Title](chatgpt/gpt.md)", index_content)
            self.assertIn("[GitHub Title](github/git.md)", index_content)
            self.assertIn("[Web Page Title](web/web.md)", index_content)
            self.assertIn("[Misc Title](misc/misc.md)", index_content)

    def test_duplicate_registration_updates_instead_of_appending(self):
        # Register a file
        source = "https://youtube.com/watch?v=dup"
        path = output_router.route_output(source, "dup.md", "youtube")
        with open(path, "w") as f:
            f.write("# Dummy\n")
            
        output_router.register_output(path, source, "youtube", "Title V1", "partial")
        
        # Verify first write
        with open(output_router.MANIFEST_PATH, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "Title V1")
            self.assertEqual(rows[0]["status"], "partial")

        # Re-register the same path with updated title/status
        output_router.register_output(path, source, "youtube", "Title V2", "success")
        
        # Verify it was updated in place and not duplicated
        with open(output_router.MANIFEST_PATH, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "Title V2")
            self.assertEqual(rows[0]["status"], "success")

if __name__ == "__main__":
    unittest.main()
