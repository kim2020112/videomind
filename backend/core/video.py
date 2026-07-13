import re
from urllib.parse import urlsplit


def _value(info, key, default=None):
    if isinstance(info, dict):
        return info.get(key, default)
    return getattr(info, key, default)


def selected_video_part_index(url: str, info=None) -> int | None:
    candidates = [url]
    webpage_url = _value(info, "webpage_url", "") if info is not None else ""
    if webpage_url:
        candidates.append(webpage_url)
    for candidate in candidates:
        match = re.search(r"[?&]p=(\d+)", candidate or "", re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def canonical_video_url(original_url: str, info) -> str:
    canonical = str(_value(info, "webpage_url", "") or original_url)
    original_part = re.search(r"[?&]p=(\d+)", original_url or "", re.IGNORECASE)
    if not original_part:
        return canonical

    part_index = original_part.group(1)
    if re.search(r"[?&]p=\d+", canonical, re.IGNORECASE):
        return re.sub(
            r"([?&])p=\d+",
            rf"\1p={part_index}",
            canonical,
            count=1,
            flags=re.IGNORECASE,
        )
    separator = "&" if "?" in canonical else "?"
    return f"{canonical}{separator}p={part_index}"


def video_duration_for_url(url: str, info) -> float:
    duration = _value(info, "duration", 0) or 0
    part_index = selected_video_part_index(url, info)
    if part_index is None:
        return duration

    parts = _value(info, "parts", []) or []
    for part in parts:
        if _value(part, "index") == part_index:
            return _value(part, "duration", duration) or duration
    return duration


def is_bilibili_video(url: str = "", info=None) -> bool:
    extractor = str(_value(info, "extractor", "") or "").lower() if info is not None else ""
    if "bilibili" in extractor:
        return True
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "b23.tv" or host == "bilibili.com" or host.endswith(".bilibili.com")
