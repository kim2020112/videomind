"""B 站空间目录适配：输入解析、wbi 签名、投稿/分 P 接口与错误分类。

只做目录发现；所有请求共享持久化限速与熔断，错误按
login / rate_limit / network / unavailable / api / invalid_input 分类，
调用方据此决定重试、暂停还是提示用户。
"""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import re
import time
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from core.bilibili import default_cookie, LOGIN_API_PATHS
from core.bilibili_guard import BilibiliAccessBlocked, guarded_get
from core.bilibili_cache import cached_get, refresh_responses
from core.logging_config import get_logger

logger = get_logger("blogger.catalog")

MIXIN_KEY_TABLE = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)

class CatalogError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_creator_input(value: str) -> str:
    """从 UID / 空间链接 / 分享文本中解析出 UP 主 UID。不支持昵称搜索。"""
    value = (value or "").strip()
    if re.fullmatch(r"[1-9][0-9]{0,19}", value):
        return value
    match = re.search(r"https?://[^\s，,；;]+", value)
    url = match.group(0) if match else ""
    if not url:
        raise CatalogError("invalid_input", "请粘贴 UP 主空间地址或数字 UID，不支持昵称搜索")
    for _ in range(5):
        parsed = urlparse(url)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.username or parsed.password
            or parsed.port not in (None, 80, 443)
        ):
            break
        if parsed.hostname in ("space.bilibili.com", "m.bilibili.com"):
            uid_match = re.fullmatch(r"/(?:space/)?([1-9][0-9]{0,19})(?:/.*)?", parsed.path)
            if uid_match:
                return uid_match.group(1)
            break
        if parsed.hostname != "b23.tv":
            break
        try:
            response = guarded_get(url, timeout=10)
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            url = urljoin(url, response.headers.get("Location", ""))
        except BilibiliAccessBlocked as exc:
            raise CatalogError(exc.code, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise CatalogError("network", "分享链接解析失败，请粘贴完整空间地址") from exc
    raise CatalogError("invalid_input", "这不是 UP 主空间链接；单个视频请使用工作台解析入口")


def sign_wbi(params: dict, mixin_key: str) -> dict:
    """标准 wbi 签名：过滤 !'()* 后按 key 排序拼接，md5(query + mixin) 写入 w_rid。"""
    cleaned = {key: re.sub(r"[!'()*]", "", str(value)) for key, value in params.items()}
    query = urlencode(sorted(cleaned.items()))
    cleaned["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return cleaned


def parse_length(value) -> int:
    """把 vlist 的 length（"mm:ss" / "hh:mm:ss" / 秒数）转成秒。"""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    try:
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds
    except (ValueError, TypeError):
        return 0


def is_lesson_entry(entry: dict) -> bool:
    """B 站课堂付费课程的推广条目：非普通投稿，解析/下载均不可用。"""
    if entry.get("is_lesson_video"):
        return True
    return "/cheese/" in (entry.get("jump_url") or "")


class BilibiliCatalogClient:
    """官方 Web API 目录客户端。Cookie 可选：有 SESSDATA 时校验登录态。"""

    def __init__(self, cookie: str | None = None, timeout: float = 20.0):
        self.cookie = cookie if cookie is not None else default_cookie()
        self.timeout = timeout
        self._mixin_key = ""

    # ── 基础请求 ──

    def get(self, path: str, params: dict | None = None, allow_codes: tuple = (), *, live: bool = False) -> dict:
        """请求 api.bilibili.com 并返回 data；错误统一转 CatalogError。"""
        headers = {
            "Cookie": self.cookie if path in LOGIN_API_PATHS else "",
            "Referer": "https://space.bilibili.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        }
        try:
            with refresh_responses(False) if path == "/x/web-interface/nav" else nullcontext():
                response = cached_get(
                    f"https://api.bilibili.com{path}", params=params,
                    headers=headers, timeout=self.timeout, ttl=0 if live else 1800 if path == "/x/web-interface/nav" else 120,
                )
        except BilibiliAccessBlocked as exc:
            raise CatalogError(exc.code, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise CatalogError("network", "B 站接口暂时不可用，请稍后重试") from exc

        if response.status_code >= 500:
            raise CatalogError("network", "B 站接口暂时不可用，请稍后重试")
        if response.status_code >= 400:
            raise CatalogError("api", f"B 站接口返回异常（HTTP {response.status_code}）")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CatalogError("api", "B 站接口返回了无法识别的数据，未将结果视为空目录") from exc
        if not isinstance(payload, dict):
            raise CatalogError("api", "B 站接口返回了无法识别的数据，未将结果视为空目录")

        code = payload.get("code")
        if code == -101 and code not in allow_codes:
            raise CatalogError("login", "B 站接口需要有效登录，自动访问已暂停；请在官方客户端查看，勿反复提交 Cookie")
        if code in (-404, 62002, 62012):
            if path in ("/x/web-interface/card", "/x/space/wbi/arc/search"):
                raise CatalogError("unavailable", "B 站博主不存在或投稿目录不可访问")
            raise CatalogError("unavailable", "B 站视频不存在或当前账号无权访问")
        if code not in (0, *allow_codes) or not isinstance(payload.get("data"), dict):
            raise CatalogError("api", f"B 站接口返回异常（{code}），未将结果视为空目录")
        return payload["data"]

    # ── wbi ──

    def ensure_wbi(self) -> str:
        if self._mixin_key:
            return self._mixin_key
        # 匿名 nav 返回 code=-101，但 data.wbi_img 仍带签名素材
        nav = self.get("/x/web-interface/nav", allow_codes=(-101,))
        image = nav.get("wbi_img") or {}
        raw_key = "".join(
            urlparse(image.get(key, "")).path.rsplit("/", 1)[-1].split(".")[0]
            for key in ("img_url", "sub_url")
        )
        if len(raw_key) < 64:
            raise CatalogError("api", "无法取得 B 站目录签名信息，请稍后重试")
        self._mixin_key = "".join(raw_key[i] for i in MIXIN_KEY_TABLE)[:32]
        return self._mixin_key

    def check_session(self) -> dict:
        """有 SESSDATA 时校验登录态；匿名 buvid 不强制登录。"""
        has_sessdata = any(
            part.strip().startswith("SESSDATA=") and part.strip() != "SESSDATA="
            for part in self.cookie.split(";")
        )
        nav = self.get("/x/web-interface/nav", allow_codes=() if has_sessdata else (-101,), live=True)
        if has_sessdata and not nav.get("isLogin"):
            raise CatalogError("login", "B 站接口需要有效登录，自动访问已暂停；请在官方客户端查看，勿反复提交 Cookie")
        image = nav.get("wbi_img") or {}
        raw_key = "".join(
            urlparse(image.get(key, "")).path.rsplit("/", 1)[-1].split(".")[0]
            for key in ("img_url", "sub_url")
        )
        if len(raw_key) >= 64:
            self._mixin_key = "".join(raw_key[i] for i in MIXIN_KEY_TABLE)[:32]
        return nav

    # ── 目录接口 ──

    def profile(self, uid: str) -> dict:
        data = self.get("/x/web-interface/card", {"mid": uid})
        card = data.get("card") or {}
        follower = data.get("follower")
        if not isinstance(follower, int):
            follower = card.get("fans") or (data.get("follow_info") or {}).get("follower") or 0
        return {
            "name": card.get("name") or f"UP {uid}",
            "avatar": card.get("face") or "",
            "follower_count": int(follower),
        }

    def videos(self, uid: str, page: int) -> tuple[list, int]:
        """投稿列表一页（ps=30）。返回 (vlist, total)。"""
        mixin = self.ensure_wbi()
        params = sign_wbi(
            {"mid": uid, "pn": page, "ps": 30, "order": "pubdate", "wts": int(time.time())},
            mixin,
        )
        data = self.get("/x/space/wbi/arc/search", params)
        entries = (data.get("list") or {}).get("vlist")
        if not isinstance(entries, list):
            raise CatalogError("api", "投稿目录格式变化，无法确认是否已同步完成")
        total = (data.get("page") or {}).get("count") or 0
        return entries, int(total)

    def parts(self, bvid: str) -> tuple[dict, list]:
        """视频详情与分 P 列表。返回 (view_data, pages[])。"""
        data = self.get("/x/web-interface/view", {"bvid": bvid})
        pages = data.get("pages")
        if not isinstance(pages, list) or not pages:
            raise CatalogError("unavailable", "视频未返回可读取的分 P 信息")
        return data, pages
