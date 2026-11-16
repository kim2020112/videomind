"""Learning metadata does not require opening a video webpage or media stream."""
import re
from urllib.parse import urlsplit, parse_qs

from core.cache import get_video_info_cache
from core.models import VideoInfo, VideoPart
from core.video import is_bilibili_video


def learning_video_info(url, downloader):
    if not is_bilibili_video(url):
        return downloader.parse_info(url)
    cached = get_video_info_cache(url)
    if cached:
        return VideoInfo.model_validate(cached)
    match = re.fullmatch(r'/video/(BV[a-zA-Z0-9]+)/*', urlsplit(url).path)
    if not match:
        return downloader.parse_info(url)
    bvid = match.group(1)
    part = int(parse_qs(urlsplit(url).query).get('p', ['1'])[0])
    from core.blogger import store
    record = store.get_video_by_bvid(bvid)
    if record and part == 1 and 'p' not in parse_qs(urlsplit(url).query):
        pages = store.list_pages(record['id'])
        return VideoInfo(
            id=bvid, title=record['title'], webpage_url=url, extractor='bilibili',
            thumbnail=record.get('cover'), description=record.get('description'),
            duration=record.get('duration'),
            parts=[VideoPart(index=p['page'], title=p['part_title'], cid=p['cid'],
                             duration=p.get('duration')) for p in pages],
        )
    # This is the primary metadata path, not a retry after a webpage refusal.
    from core.blogger.catalog import BilibiliCatalogClient
    from core.bilibili_guard import BilibiliAccessBlocked
    from core.blogger.catalog import CatalogError
    try:
        data, pages = BilibiliCatalogClient().parts(bvid)
    except CatalogError as exc:
        if exc.code in ('rate_limit', 'budget', 'protection'):
            raise BilibiliAccessBlocked(str(exc), exc.code) from exc
        raise
    selected = next((page for page in pages if page['page'] == part), None)
    if not selected:
        raise ValueError('所选分 P 不存在')
    return VideoInfo(
        id=bvid, title=data.get('title') or bvid, webpage_url=url, extractor='bilibili',
        thumbnail=data.get('pic'), description=data.get('desc'),
        uploader=(data.get('owner') or {}).get('name'),
        duration=selected.get('duration') if 'p' in parse_qs(urlsplit(url).query) else data.get('duration'),
        parts=[VideoPart(index=p['page'], title=p.get('part') or f"P{p['page']}",
                         cid=p.get('cid'), duration=p.get('duration')) for p in pages],
    )
