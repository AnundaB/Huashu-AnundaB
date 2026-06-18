import os
import subprocess
import pytest
from unittest import mock
import argparse
import tempfile
import shutil

import x_video_download

def test_cli_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("-o", "--output-dir", default=None)
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--transcript-timeout", type=int, default=0)
    parser.add_argument("--language", default=None)
    parser.add_argument("--engine", default=None, choices=["auto", "faster-whisper", "openai-whisper", "whisper-cli"])
    
    args = parser.parse_args([
        "https://x.com/user/status/123",
        "--model", "base",
        "--transcript-timeout", "3600",
        "--language", "en",
        "--engine", "openai-whisper"
    ])
    
    assert args.url == "https://x.com/user/status/123"
    assert args.model == "base"
    assert args.transcript_timeout == 3600
    assert args.language == "en"
    assert args.engine == "openai-whisper"

@mock.patch("x_video_download.extract_status_id", return_value="123")
@mock.patch("x_video_download.subprocess.run")
@mock.patch("x_video_download.write_markdown")
@mock.patch("x_video_download.shutil.which", return_value="/usr/bin/ffmpeg")
@mock.patch("os.listdir")
@mock.patch("os.path.exists")
@mock.patch("x_video_download.datetime")
@mock.patch("x_video_download._route_output_helper")
def test_mocked_success(mock_route, mock_dt, mock_exists, mock_listdir, mock_which, mock_write_md, mock_run, mock_extract):
    tmp_dir = tempfile.mkdtemp()
    mock_route.return_value = os.path.join(tmp_dir, "mocked.md")
    class MockDT:
        @classmethod
        def now(cls):
            class M:
                def strftime(self, fmt):
                    return "20240101-000000"
            return M()
    mock_dt.datetime = MockDT
    
    mock_listdir.return_value = ["info.json", "raw.mp4", "audio.wav"]
    
    def fake_exists(path):
        return True
    mock_exists.side_effect = fake_exists

    def fake_run(cmd, *args, **kwargs):
        res = mock.MagicMock()
        res.returncode = 0
        cmd_str = " ".join(str(c) for c in cmd)
        if "yt_dlp" in cmd_str and "--dump-json" in cmd_str:
            res.stdout = '{"title": "test", "uploader": "user", "duration": 100}'
        elif "ffprobe" in cmd_str:
            res.stdout = "100.0"
        elif "faster_whisper" in cmd_str:
            res.stdout = "Successful transcript"
        else:
            res.stdout = ""
        res.stderr = ""
        return res
    
    mock_run.side_effect = fake_run

    res = x_video_download.run_download("https://x.com/user/status/123", output_dir=tmp_dir)
    assert res == 0
    
    calls = mock_write_md.call_args_list
    last_call = calls[-1][1]
    assert last_call["status"] == "success"
    assert last_call["transcript"] == "Successful transcript"
    assert last_call["transcript_engine"] == "faster-whisper"

@mock.patch("x_video_download.extract_status_id", return_value="123")
@mock.patch("x_video_download.subprocess.run")
@mock.patch("x_video_download.write_markdown")
@mock.patch("x_video_download.shutil.which", return_value="/usr/bin/ffmpeg")
@mock.patch("os.listdir")
@mock.patch("os.path.exists")
@mock.patch("x_video_download.datetime")
@mock.patch("x_video_download._route_output_helper")
def test_timeout_fails_transcription(mock_route, mock_dt, mock_exists, mock_listdir, mock_which, mock_write_md, mock_run, mock_extract):
    tmp_dir = tempfile.mkdtemp()
    mock_route.return_value = os.path.join(tmp_dir, "mocked.md")
    class MockDT:
        @classmethod
        def now(cls):
            class M:
                def strftime(self, fmt):
                    return "20240101-000000"
            return M()
    mock_dt.datetime = MockDT
    
    mock_listdir.return_value = ["info.json", "raw.mp4", "audio.wav"]
    
    def fake_exists(path):
        return True
    mock_exists.side_effect = fake_exists

    def fake_run(cmd, *args, **kwargs):
        res = mock.MagicMock()
        res.returncode = 0
        cmd_str = " ".join(str(c) for c in cmd)
        if "yt_dlp" in cmd_str and "--dump-json" in cmd_str:
            res.stdout = '{"title": "test", "uploader": "user", "duration": 100}'
        elif "ffprobe" in cmd_str:
            res.stdout = "100.0"
        elif "whisper" in cmd_str or "faster_whisper" in cmd_str or "openai_whisper" in cmd_str:
            raise subprocess.TimeoutExpired(cmd, 180)
        return res
    
    mock_run.side_effect = fake_run

    res = x_video_download.run_download("https://x.com/user/status/123", output_dir=tmp_dir, engine="faster-whisper")
    assert res == 0
    
    calls = mock_write_md.call_args_list
    last_call = calls[-1][1]
    assert last_call["status"] == "transcript_failed"

@mock.patch("x_video_download.extract_status_id", return_value="123")
@mock.patch("x_video_download.subprocess.run")
@mock.patch("x_video_download.write_markdown")
@mock.patch("x_video_download.shutil.which", return_value="/usr/bin/ffmpeg")
@mock.patch("os.listdir")
@mock.patch("os.path.exists")
@mock.patch("x_video_download.datetime")
@mock.patch("x_video_download._route_output_helper")
def test_chunking_long_audio(mock_route, mock_dt, mock_exists, mock_listdir, mock_which, mock_write_md, mock_run, mock_extract):
    tmp_dir = tempfile.mkdtemp()
    mock_route.return_value = os.path.join(tmp_dir, "mocked.md")
    class MockDT:
        @classmethod
        def now(cls):
            class M:
                def strftime(self, fmt):
                    return "20240101-000000"
            return M()
    mock_dt.datetime = MockDT
    
    def fake_listdir(path):
        if "chunks" in path:
            return ["chunk-000.wav", "chunk-001.wav"]
        return ["info.json", "raw.mp4", "audio.wav"]
    mock_listdir.side_effect = fake_listdir
    
    def fake_exists(path):
        return True
    mock_exists.side_effect = fake_exists

    def fake_run(cmd, *args, **kwargs):
        res = mock.MagicMock()
        res.returncode = 0
        cmd_str = " ".join(str(c) for c in cmd)
        if "yt_dlp" in cmd_str and "--dump-json" in cmd_str:
            res.stdout = '{"title": "test", "uploader": "user", "duration": 2000}'
        elif "ffprobe" in cmd_str:
            res.stdout = "2000.0"
        elif "faster_whisper" in cmd_str:
            res.stdout = "chunk text"
        else:
            res.stdout = ""
        return res
    
    mock_run.side_effect = fake_run

    res = x_video_download.run_download("https://x.com/user/status/123", output_dir=tmp_dir, engine="faster-whisper")
    assert res == 0
    
    calls = mock_write_md.call_args_list
    last_call = calls[-1][1]
    assert last_call["status"] == "success"
    assert "chunk text chunk text" in last_call["transcript"]
