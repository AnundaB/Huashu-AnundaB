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

@patch("subprocess.run")
def test_playlist_extraction_full_success(mock_run):
    import tempfile
    import os
    mock_yt_res = MagicMock()
    mock_yt_res.stdout = '{"id": "vid1", "title": "Video 1"}\n{"id": "vid2", "title": "Video 2"}'

    def side_effect(cmd, **kwargs):
        res = MagicMock()
        if "--flat-playlist" in cmd:
            res.stdout = mock_yt_res.stdout
            res.returncode = 0
            return res
        output_file_idx = cmd.index("--output-file")
        out_path = cmd[output_file_idx + 1]
        assert "playlists/PL_test/videos" in out_path
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            f.write(f"source_type: youtube\n---------------\n# Title\n\nTranscript for {out_path}\n")
        res.returncode = 0
        return res

    mock_run.side_effect = side_effect

    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.dict(os.environ, {"HUASHU_AUTO_DIR": temp_dir}):
            ret = youtube_playlist_extract.run_playlist_extraction("https://youtube.com/playlist?list=PL_test")
            assert ret == 0
            playlist_dir = os.path.join(temp_dir, "youtube", "playlists", "PL_test")
            assert os.path.exists(os.path.join(playlist_dir, "playlist_index.md"))
            assert os.path.exists(os.path.join(playlist_dir, "combined.md"))
            assert os.path.exists(os.path.join(playlist_dir, "videos", "001-vid1-video-1.md"))
            assert os.path.exists(os.path.join(playlist_dir, "videos", "002-vid2-video-2.md"))
            with open(os.path.join(playlist_dir, "combined.md")) as f:
                content = f.read()
                assert "Transcript for" in content
                assert "001-vid1" in content
            with open(os.path.join(playlist_dir, "playlist_index.md")) as f:
                content = f.read()
                assert "status: success" in content
                assert "✅ [Video 1]" in content

@patch("subprocess.run")
def test_playlist_extraction_partial_and_failed(mock_run):
    import tempfile
    import os
    mock_yt_res = MagicMock()
    mock_yt_res.stdout = '{"id": "vid1", "title": "Video 1"}\n{"id": "vid2", "title": "Video 2"}'

    def side_effect_partial(cmd, **kwargs):
        res = MagicMock()
        if "--flat-playlist" in cmd:
            res.stdout = mock_yt_res.stdout
            res.returncode = 0
            return res
        if any("vid1" in c for c in cmd):
            res.returncode = 0
            out_path = cmd[cmd.index("--output-file") + 1]
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w") as f:
                f.write("text")
        else:
            res.returncode = 1
            res.stderr = "error"
        return res

    mock_run.side_effect = side_effect_partial

    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.dict(os.environ, {"HUASHU_AUTO_DIR": temp_dir}):
            ret = youtube_playlist_extract.run_playlist_extraction("https://youtube.com/playlist?list=PL_test_part")
            assert ret == 0
            playlist_dir = os.path.join(temp_dir, "youtube", "playlists", "PL_test_part")
            with open(os.path.join(playlist_dir, "playlist_index.md")) as f:
                content = f.read()
                assert "status: partial_success" in content
                assert "❌ Video 2" in content

    def side_effect_fail(cmd, **kwargs):
        res = MagicMock()
        if "--flat-playlist" in cmd:
            res.stdout = mock_yt_res.stdout
            res.returncode = 0
            return res
        res.returncode = 1
        res.stderr = "error"
        return res

    mock_run.side_effect = side_effect_fail

    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.dict(os.environ, {"HUASHU_AUTO_DIR": temp_dir}):
            ret = youtube_playlist_extract.run_playlist_extraction("https://youtube.com/playlist?list=PL_test_fail")
            assert ret == 1
            playlist_dir = os.path.join(temp_dir, "youtube", "playlists", "PL_test_fail")
            with open(os.path.join(playlist_dir, "playlist_index.md")) as f:
                content = f.read()
                assert "status: failed" in content
            assert not os.path.exists(os.path.join(playlist_dir, "combined.md"))
