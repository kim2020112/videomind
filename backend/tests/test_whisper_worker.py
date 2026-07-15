import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from workers import whisper_worker
from core import whisper


class WhisperWorkerTests(unittest.TestCase):
    def test_download_audio_uses_direct_stream_without_reopening_video_page(self):
        page_url = "https://www.bilibili.com/video/BV1demo"
        audio_url = "https://audio.example.com/best.m4s?deadline=9999999999"
        targets = []
        options = []

        class FakeYoutubeDL:
            def __init__(self, ydl_opts):
                self.ydl_opts = ydl_opts
                options.append(ydl_opts)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, target, download=True):
                targets.append(target)
                filename = self.prepare_filename({"id": "direct", "ext": "m4a"})
                Path(filename).with_suffix(".mp3").write_bytes(b"audio")
                return {"id": "direct", "ext": "m4a"}

            def prepare_filename(self, info):
                return self.ydl_opts["outtmpl"].replace("%(id)s", info["id"]).replace(
                    "%(ext)s", info["ext"]
                )

        with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
            audio_path = whisper._download_audio(page_url, audio_url=audio_url)

        try:
            self.assertEqual([audio_url], targets)
            self.assertEqual("https://www.bilibili.com/", options[0]["http_headers"]["Referer"])
        finally:
            shutil.rmtree(Path(audio_path).parent, ignore_errors=True)

    def test_run_prefers_cached_audio_stream_over_video_page(self):
        page_url = "https://www.bilibili.com/video/BV1demo"
        audio_url = "https://audio.example.com/best.m4s?deadline=9999999999"

        class FakeWhisperModel:
            def __init__(self, *_args, **_kwargs):
                pass

            def transcribe(self, _audio_path, **_options):
                segment = SimpleNamespace(start=0, end=1, text=" transcribed text ")
                return [segment], SimpleNamespace(duration=1)

        fake_module = SimpleNamespace(WhisperModel=FakeWhisperModel)
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.mp3"
            audio_path.write_bytes(b"audio")
            result_path = Path(tmpdir) / "result.json"
            with (
                patch.object(whisper_worker, "is_model_available", return_value=True),
                patch.object(
                    whisper_worker,
                    "_download_audio",
                    return_value=str(audio_path),
                ) as download_audio,
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
            ):
                whisper_worker.run(page_url, None, result_path, audio_url=audio_url)

        download_audio.assert_called_once_with(page_url, audio_url=audio_url)


if __name__ == "__main__":
    unittest.main()
