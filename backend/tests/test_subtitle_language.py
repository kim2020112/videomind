import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.models import SubtitleTrack
from core import bilibili_guard
from core.pipeline import subtitle


URL = "https://www.bilibili.com/video/BV1language"


class SubtitleLanguageTests(unittest.TestCase):
    def test_ytdlp_prefers_auto_chinese_over_auto_english(self):
        tracks = [SubtitleTrack(lang="ai-en", name="English", ext="vtt", is_auto=True),
                  SubtitleTrack(lang="ai-zh", name="中文", ext="vtt", is_auto=True)]
        self.assertEqual("ai-zh", subtitle._select_subtitle_lang(tracks).lang)

    def test_explicit_language_preference_matches_auto_track_codes(self):
        tracks = [SubtitleTrack(lang="ai-en", name="English", ext="vtt", is_auto=True),
                  SubtitleTrack(lang="ai-zh-Hans", name="中文", ext="vtt", is_auto=True)]
        self.assertEqual("ai-zh-Hans", subtitle._select_subtitle_lang(tracks, "zh").lang)

    def test_english_cache_and_cc_fallback_to_available_chinese_track(self):
        info = SimpleNamespace(
            title="Bilibili video", webpage_url=URL, extractor="bilibili",
            subtitles=[SubtitleTrack(lang="ai-en", name="English", ext="vtt", is_auto=True),
                       SubtitleTrack(lang="ai-zh", name="中文", ext="vtt", is_auto=True)],
        )
        cached = {"full_text": "English subtitle cache " * 8,
                  "source": "bilibili_cc", "language": "ai-en"}
        english_cc = {"has_subtitle": True, "text": "English CC subtitle " * 8,
                      "language": "ai-en", "segments": []}
        with patch.object(subtitle, "get_subtitle_from_db", return_value=cached), \
             patch.object(subtitle, "try_get_bilibili_cc_subtitle", return_value=english_cc), \
             patch.object(subtitle, "_download_subtitle_content", return_value=("", "vtt")) as download, \
             patch.object(subtitle, "clean_subtitle_text", return_value="中文字幕正文 " * 8):
            result = asyncio.run(subtitle.fetch_subtitle(URL, info))

        self.assertEqual(("中文字幕正文 " * 8, "youtube_auto", "ai-zh"), result)
        download.assert_called_once_with(URL, "ai-zh", True)

    def test_native_subtitle_download_inherits_bounded_request_context(self):
        info = SimpleNamespace(
            title="YouTube video", webpage_url="https://www.youtube.com/watch?v=demo",
            extractor="youtube",
            subtitles=[SubtitleTrack(lang="en", name="English", ext="vtt", is_auto=True)],
        )
        inherited_operations = []

        def download(*args):
            inherited_operations.append(bilibili_guard._subtitle_burst_operation.get())
            return "raw subtitle", "vtt"

        with patch.object(subtitle, "get_subtitle_from_db", return_value=None), \
             patch.object(subtitle, "_download_subtitle_content", side_effect=download), \
             patch.object(subtitle, "clean_subtitle_text", return_value="字幕内容足够长 " * 10):
            with bilibili_guard.subtitle_api_burst("task-native-thread"):
                result = asyncio.run(subtitle.fetch_subtitle(info.webpage_url, info))

        self.assertEqual("youtube_auto", result[1])
        self.assertEqual(["task-native-thread"], inherited_operations)


if __name__ == "__main__":
    unittest.main()
