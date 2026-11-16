"""Consistent validation for stored subtitles across workspaces and jobs."""
import re
import json
import hashlib
from core.video import video_duration_for_url, selected_video_part_index
from core.subtitle_identity import SubtitleIdentityError, validate_subtitle_duration


def validate_cached_subtitle(url, subtitle, info=None):
    if not subtitle or subtitle.get('source') != 'bilibili_cc':
        return subtitle
    result = dict(subtitle)
    proof = result.get('provenance') or {}
    if not isinstance(proof, dict) or proof.get('invalid'):
        raise SubtitleIdentityError('字幕来源记录格式异常，请重新获取字幕')
    if proof.get('text_sha256') and proof['text_sha256'] != hashlib.sha256(result.get('full_text', '').encode()).hexdigest():
        raise SubtitleIdentityError('字幕内容与来源记录不一致，请重新获取字幕')
    if proof.get('segments_sha256') and proof['segments_sha256'] != hashlib.sha256(json.dumps(result.get('segments') or [], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest():
        raise SubtitleIdentityError('字幕分段与来源记录不一致，请重新获取字幕')
    match = re.search(r'/video/(BV\w+)', url)
    if proof.get('bvid') and (not match or proof['bvid'] != match.group(1)):
        raise SubtitleIdentityError('已缓存字幕的视频标识不匹配，请重新获取字幕')
    segments = result.get('segments') or []
    if not segments:
        # Old text-only rows still carry usable [MM:SS] evidence.
        segments = [{'end': int(m[1]) * 60 + int(m[2])} for m in re.finditer(r'\[(\d+):(\d{2})\]', result.get('full_text', ''))]
    duration = video_duration_for_url(url, info) if info else None
    if info and selected_video_part_index(url, info) is None:
        parts = info.get('parts', []) if isinstance(info, dict) else getattr(info, 'parts', [])
        for part in parts or []:
            part = part if isinstance(part, dict) else part.model_dump()
            if part.get('index') == 1:
                duration = part.get('duration') or duration
    validate_subtitle_duration(segments, duration)
    if info:
        parts = info.get('parts', []) if isinstance(info, dict) else getattr(info, 'parts', [])
        index = selected_video_part_index(url, info) or 1
        for part in parts or []:
            part = part if isinstance(part, dict) else part.model_dump()
            if part.get('index') == index and proof.get('cid') and part.get('cid'):
                if str(part['cid']) != str(proof['cid']):
                    raise SubtitleIdentityError('已缓存字幕的分 P 标识不匹配，请重新获取字幕')
    result['validation'] = 'checked' if proof.get('version') == 1 else 'legacy_unverified'
    return result
