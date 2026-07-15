"""CLI worker that downloads audio and runs Faster-Whisper in this process only."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import WHISPER_MODEL, WHISPER_MODELS_DIR
from core.whisper import _download_audio, is_model_available, model_directory


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def lower_priority() -> None:
    if hasattr(os, "nice"):
        try:
            os.nice(10)
        except OSError:
            pass


def run(
    url: str,
    language: str | None,
    result_path: Path,
    *,
    audio_url: str | None = None,
) -> None:
    lower_priority()
    if not is_model_available():
        raise RuntimeError(f"Whisper model is unavailable: {model_directory()}")

    emit({"type": "progress", "stage": "downloading", "progress": 2, "message": "正在下载音频"})
    audio_path = _download_audio(url, audio_url=audio_url)
    audio_dir = os.path.dirname(audio_path)
    try:
        emit({"type": "progress", "stage": "transcribing", "progress": 15, "message": "正在加载转录模型"})
        from faster_whisper import WhisperModel

        model = WhisperModel(
            str(model_directory()),
            device="cpu",
            compute_type="int8",
            local_files_only=True,
            cpu_threads=2,
            num_workers=1,
        )
        options = {"beam_size": 3, "vad_filter": True}
        if language:
            options["language"] = language
        segments, info = model.transcribe(audio_path, **options)
        duration = max(float(getattr(info, "duration", 0) or 0), 1.0)
        lines = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                minutes = int(segment.start // 60)
                seconds = int(segment.start % 60)
                lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")
            progress = min(94, 15 + int((float(segment.end) / duration) * 79))
            emit(
                {
                    "type": "progress",
                    "stage": "transcribing",
                    "progress": progress,
                    "message": "正在转录音频",
                }
            )

        subtitle_text = "\n".join(lines)
        if not subtitle_text.strip():
            raise RuntimeError("Whisper transcription produced no text")
        result = {"subtitle_text": subtitle_text, "language": language or "auto", "source": "whisper"}
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        emit({"type": "result", "result_path": str(result_path)})
    finally:
        shutil.rmtree(audio_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--audio-url", default=None)
    parser.add_argument("--language", default=None)
    parser.add_argument("--result-path", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.url, args.language, args.result_path, audio_url=args.audio_url)
        return 0
    except Exception as exc:
        emit({"type": "error", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
