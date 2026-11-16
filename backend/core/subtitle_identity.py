"""Shared subtitle identity and timestamp validation, independent of transport."""
import math
import re
from urllib.parse import urlsplit


class SubtitleIdentityError(RuntimeError):
    """An inconsistent subtitle must never be replaced by an unrelated source."""


def validate_subtitle_duration(segments, duration):
    try:
        limit = float(duration or 0)
        if not math.isfinite(limit) or limit < 0:
            raise ValueError('invalid duration')
        for segment in segments or []:
            start = float(segment.get('start', 0))
            end = float(segment.get('end', 0))
            if not all(math.isfinite(value) for value in (start, end)) or start < 0 or end < start:
                raise ValueError('invalid segment time')
            if limit and end > limit + max(10, limit * .02):
                raise SubtitleIdentityError('字幕时间轴超出视频时长，疑似字幕与视频不匹配，已停止使用；请重新获取字幕')
    except (TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise SubtitleIdentityError('字幕时间轴格式异常，已停止使用；请重新获取字幕') from exc


def subtitle_link_identity(url, aid, cid):
    """Recognize the observed aid+cid+hash form; opaque CDN paths remain valid."""
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise SubtitleIdentityError('字幕下载地址端口无效，已拒绝访问') from exc
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or port not in (None, 443)
            or not any(host == domain or host.endswith('.' + domain)
                       for domain in ('hdslb.com', 'bilibili.com'))):
        raise SubtitleIdentityError('字幕下载地址不受支持，已拒绝访问')
    filename = parsed.path.rsplit('/', 1)[-1]
    prefix = filename[:-32]
    structured = bool(len(prefix) >= 15 and prefix.isdigit()
                      and re.fullmatch(r'[0-9a-f]{32}', filename[-32:]))
    if structured and aid and cid:
        if prefix != f'{aid}{cid}':
            raise SubtitleIdentityError('字幕链接指向其他视频，已拒绝下载和保存；请重新获取字幕')
        return True
    return False
