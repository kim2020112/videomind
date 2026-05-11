from pydantic import BaseModel, field_validator
from typing import Optional


class ParseRequest(BaseModel):
    url: str


class FormatOption(BaseModel):
    format_id: str          # yt-dlp 格式字符串，可以是 "bestvideo+bestaudio/best" 等
    ext: str
    resolution: Optional[str] = None
    height: Optional[int] = None
    width: Optional[int] = None
    fps: Optional[float] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    filesize: Optional[int] = None
    filesize_str: Optional[str] = None
    tbr: Optional[float] = None
    format_note: Optional[str] = None
    is_audio_only: bool = False
    is_video_only: bool = False
    is_combined: bool = False
    is_best: bool = False       # 是否为"最佳画质"合并选项
    label: Optional[str] = None  # 前端展示标签

    @field_validator('height', 'width', 'filesize', mode='before')
    @classmethod
    def coerce_to_int(cls, v):
        if v is None:
            return None
        return int(v)


class SubtitleTrack(BaseModel):
    lang: str               # 语言代码，如 "en", "zh-Hans"
    name: str               # 显示名称，如 "English", "中文（自动生成）"
    ext: str                # 文件格式，如 "srt", "vtt"
    is_auto: bool = False   # 是否为自动生成字幕


class VideoPart(BaseModel):
    index: int
    title: str
    duration: Optional[int] = None


class VideoInfo(BaseModel):
    title: str
    webpage_url: str
    duration: Optional[float] = None   # 保留浮点，前端展示时取整
    duration_string: Optional[str] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    uploader: Optional[str] = None
    view_count: Optional[int] = None
    upload_date: Optional[str] = None
    extractor: Optional[str] = None
    formats: list[FormatOption] = []
    parts: list[VideoPart] = []
    subtitles: list[SubtitleTrack] = []

    @field_validator('view_count', mode='before')
    @classmethod
    def coerce_view_count(cls, v):
        if v is None:
            return None
        return int(v)


class DownloadRequest(BaseModel):
    url: str
    format_id: str = "best"


class DownloadTask(BaseModel):
    task_id: str
    title: str
    status: str = "pending"  # pending, downloading, processing, completed, failed
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[int] = None
    file_path: Optional[str] = None
    error: Optional[str] = None


class ProgressData(BaseModel):
    status: str
    percent: float
    speed: Optional[str] = None
    eta: Optional[int] = None
    downloaded: Optional[int] = None
    total: Optional[int] = None
    file_path: Optional[str] = None
    error: Optional[str] = None