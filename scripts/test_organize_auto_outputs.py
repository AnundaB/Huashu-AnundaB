import os
import tempfile
import json
import csv
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

import organize_auto_outputs

@pytest.fixture
def temp_auto_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d

def test_get_category_for_name():
    assert organize_auto_outputs.get_category_for_name("2026-youtube-abc.md") == "youtube"
    assert organize_auto_outputs.get_category_for_name("2026-x-video-123.md") == "x/video"
    assert organize_auto_outputs.get_category_for_name("2026-x-123.md") == "x/text"
    assert organize_auto_outputs.get_category_for_name("2026-chatgpt-abc.md") == "chatgpt"
    assert organize_auto_outputs.get_category_for_name("2026-github.com-repo.md") == "github"
    assert organize_auto_outputs.get_category_for_name("2026-docs-combined.md") == "docs"
    assert organize_auto_outputs.get_category_for_name("2026-medium.com-article.md") == "web"
    assert organize_auto_outputs.get_category_for_name("unknown-file.md") == "misc"
    assert organize_auto_outputs.get_category_for_name("20260608-210720-consensus.app-papers.md") == "research"
    assert organize_auto_outputs.get_category_for_name("2026-topic-pack.md") == "research"

def test_get_unique_dest_path(temp_auto_dir):
    d = Path(temp_auto_dir)
    f1 = d / "file.md"
    f1.write_text("test")
    
    dest, collision = organize_auto_outputs.get_unique_dest_path(f1)
    assert dest.name == "file-1.md"
    assert collision is True
    
    dest.write_text("test2")
    dest2, collision2 = organize_auto_outputs.get_unique_dest_path(f1)
    assert dest2.name == "file-2.md"
    assert collision2 is True

def test_main_dry_run(temp_auto_dir):
    d = Path(temp_auto_dir)
    (d / "2026-youtube-abc.md").write_text("test")
    (d / ".DS_Store").write_text("hidden")
    (d / "Quant").mkdir()
    
    with patch("sys.argv", ["organize_auto_outputs.py", "--auto-dir", str(d)]):
        organize_auto_outputs.main()
            
    plans_dir = d / "_organize-plans"
    assert plans_dir.exists()
    
    plan_files = list(plans_dir.glob("*-plan.json"))
    assert len(plan_files) == 1
    
    with open(plan_files[0], "r") as f:
        plan_data = json.load(f)
        
    moves = plan_data["moves"]
    exclusions = plan_data["exclusions"]
    
    assert len(moves) == 1
    assert moves[0]["source"] == "2026-youtube-abc.md"
    
    assert len(exclusions) == 2
    reasons = {e["reason"] for e in exclusions}
    assert "hidden_file" in reasons
    assert "unknown_directory" in reasons
    
    # Check that it didn't move anything
    assert (d / "2026-youtube-abc.md").exists()
    assert not (d / "youtube").exists()

def test_main_apply(temp_auto_dir):
    d = Path(temp_auto_dir)
    (d / "2026-youtube-abc.md").write_text("test")
    
    manifest_path = d / "manifest.csv"
    with open(manifest_path, "w") as f:
        f.write("output_path,category,short_category\n2026-youtube-abc.md,unknown,unknown\n")
        
    fake_router = MagicMock()
    with patch.dict("sys.modules", {"output_router": fake_router}):
        with patch("sys.argv", ["organize_auto_outputs.py", "--apply", "--auto-dir", str(d)]):
            organize_auto_outputs.main()
                
    assert not (d / "2026-youtube-abc.md").exists()
    assert (d / "youtube" / "2026-youtube-abc.md").exists()
    
    with open(manifest_path, "r") as f:
        content = f.read()
        assert "youtube/2026-youtube-abc.md" in content
        assert "youtube,youtube" in content
