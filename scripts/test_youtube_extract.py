import pytest
import organize_auto_outputs
import youtube_extract
import youtube_playlist_extract
from unittest.mock import patch, MagicMock

def test_extract_video_id_watch_url():
    url = "https://www.youtube.com/watch?v=LqirVc5SlW0"
    assert youtube_extract.extract_video_id(url) == "LqirVc5SlW0"

def test_extract_video_id_watch_url_with_list():
    url = "https://www.youtube.com/watch?v=LqirVc5SlW0&list=PL123"
    assert youtube_extract.extract_video_id(url) == "LqirVc5SlW0"

def test_extract_video_id_playlist_url():
    url = "https://youtube.com/playlist?list=PL123"
    # It doesn't have a v= parameter, so it should return None
    assert youtube_extract.extract_video_id(url) is None

def test_extract_playlist_id():
    url = "https://youtube.com/playlist?list=PL123"
    assert youtube_playlist_extract.extract_playlist_id(url) == "PL123"
    
    url2 = "https://www.youtube.com/watch?v=LqirVc5SlW0&list=PL456"
    assert youtube_playlist_extract.extract_playlist_id(url2) == "PL456"

@pytest.mark.parametrize("url", [
    "https://youtube.com/playlist?list=PL123"
])
def test_playlist_url_fails_single_video_extractor(url):
    # Should return None, hence will cause run_extraction to fail early
    assert youtube_extract.extract_video_id(url) is None

@patch("subprocess.run")
def test_single_video_extraction_uses_no_playlist(mock_run):
    # Setup mock to return dummy metadata JSON
    mock_res = MagicMock()
    mock_res.stdout = '{"title": "test", "automatic_captions": {"en": [{"url": "http"}]}}'
    mock_run.return_value = mock_res
    
    # We expect run_extraction to return 1 eventually because of missing sub download, 
    # but the first subprocess call should contain "--no-playlist"
    youtube_extract.run_extraction("https://www.youtube.com/watch?v=LqirVc5SlW0&list=PL123", output_dir="/tmp")
    
    # Verify first call was yt-dlp --dump-json
    assert mock_run.call_count >= 1
    args, kwargs = mock_run.call_args_list[0]
    cmd = args[0]
    
    assert "yt_dlp" in cmd
    assert "--dump-json" in cmd
    assert "--no-playlist" in cmd
    # Ensure it uses the clean URL without playlist params
    assert cmd[-1] == "https://www.youtube.com/watch?v=LqirVc5SlW0"

@patch("subprocess.run")
def test_run_extraction_no_output_dir(mock_run):
    # Setup mock to return dummy metadata JSON
    mock_res = MagicMock()
    mock_res.stdout = '{"title": "test", "automatic_captions": {"en": [{"url": "http"}]}}'
    mock_run.return_value = mock_res
    
    # Run with output_dir=None, it shouldn't crash with TypeError for temp dir
    # It will fail eventually because we are mocking the caption download, but that's fine
    res = youtube_extract.run_extraction("https://www.youtube.com/watch?v=LqirVc5SlW0", output_dir=None)
    assert res == 1  # Fails gracefully due to missing VTT file, not a crash
