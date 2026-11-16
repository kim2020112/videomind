"""An instance-local yt-dlp transport that returns every HTTP redirect.

The access guard handles redirects explicitly so each hop receives its own
admission check and request budget. Transport-level redirects must never hide
extra requests from that guard.
"""

import urllib.request

from yt_dlp.networking._urllib import UrllibRH
from yt_dlp.networking.exceptions import RequestError


def _stop_redirect(*args, **kwargs):
    # HTTPErrorProcessor turns this unhandled 30x response into HTTPError,
    # preserving its status, headers and body for the caller.
    return None


class SingleHopUrllibRH(UrllibRH):
    _SUPPORTED_URL_SCHEMES = ("http", "https")

    def _create_instance(self, *args, **kwargs):
        opener = super()._create_instance(*args, **kwargs)
        redirect_handlers = [
            handler for handler in opener.handlers
            if isinstance(handler, urllib.request.HTTPRedirectHandler)
        ]
        if not redirect_handlers:
            # A future yt-dlp transport change must not silently restore
            # automatic redirects or fall through to an unguarded handler.
            raise RequestError("无法配置 B 站单次请求保护，已停止联网")
        for handler in redirect_handlers:
            handler.redirect_request = _stop_redirect
        return opener


def install_single_hop_transport(ydl):
    """Install one HTTP handler; retain this downloader's Cookie jar/settings.

    No process-global networking or extractor methods are modified. A single
    handler also prevents the director from trying an alternative transport.
    """
    replacement = ydl.build_request_director([SingleHopUrllibRH])
    previous = vars(ydl).get("_request_director")
    ydl._request_director = replacement
    if previous is not None:
        previous.close()
