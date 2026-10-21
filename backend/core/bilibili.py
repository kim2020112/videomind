"""B 站请求公共配置：Cookie 来源、yt-dlp 选项与错误翻译。

yt-dlp 抓 www.bilibili.com 页面和 api.bilibili.com 接口时若无 Cookie 会被
风控 412 拦截。http_headers 里的 Cookie 只会绑定到首个请求域名（api 域名
收不到），因此统一生成 Netscape cookiefile（域 .bilibili.com）供 yt-dlp 使用。
"""

from __future__ import annotations

import atexit
import os
import tempfile
import threading
import time
import uuid

from core.video import is_bilibili_video

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
BILIBILI_REFERER = "https://www.bilibili.com/"

_cookiefile_path: str | None = None
_cookiefile_lock = threading.Lock()


def default_cookie() -> str:
    """优先 BILIBILI_COOKIE，缺省用匿名 buvid。"""
    cookie = os.getenv("BILIBILI_COOKIE", "").strip()
    if cookie:
        return cookie
    return f"buvid3={str(uuid.uuid4()).upper()}infoc; b_nut={int(time.time())}"


def _cleanup_cookiefile(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _cookiefile() -> str:
    """把 Cookie 写成 Netscape 文件（.bilibili.com 域），进程退出时清理。"""
    global _cookiefile_path
    with _cookiefile_lock:
        if _cookiefile_path and os.path.isfile(_cookiefile_path):
            return _cookiefile_path
        fd, path = tempfile.mkstemp(prefix="videomind_bili_", suffix=".txt")
        os.chmod(path, 0o600)
        expiry = int(time.time()) + 30 * 86400
        lines = ["# Netscape HTTP Cookie File", "# generated from BILIBILI_COOKIE"]
        for part in default_cookie().split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            name, value = name.strip(), value.strip()
            if name:
                lines.append(f".bilibili.com\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}")
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        atexit.register(_cleanup_cookiefile, path)
        _cookiefile_path = path
        return path


def ydl_opts_for(url: str = "", *more_urls: str) -> dict:
    """yt-dlp 额外选项：B 站请求带 cookiefile 与浏览器头，绕过 412 风控。"""
    if not any(is_bilibili_video(u) for u in (url, *more_urls)):
        return {}
    return {
        "cookiefile": _cookiefile(),
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Referer": BILIBILI_REFERER,
        },
    }


def ytdlp_error_message(err: BaseException) -> str:
    """把 yt-dlp 报错翻译成用户可操作的提示。"""
    text = str(err)
    lowered = text.lower()
    if "412: precondition failed" in lowered or "http error 412" in lowered:
        return (
            "B 站风控拦截了解析请求（HTTP 412）："
            "请在 backend/.env 更新 BILIBILI_COOKIE 后重试"
        )
    if (
        "deleted or geo-restricted" in lowered
        or "private video" in lowered
        or "video does not exist" in lowered
        or "this video is unavailable" in lowered
    ):
        return "视频不存在、已删除或属于付费/专属内容（如 B 站课堂课程），暂不支持解析"
    if "login" in lowered and ("required" in lowered or "cookie" in lowered):
        return "该视频需要登录后访问：请在 backend/.env 配置 BILIBILI_COOKIE 后重试"
    return text
