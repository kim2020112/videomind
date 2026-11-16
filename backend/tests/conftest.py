"""Keep access-protection state isolated from the running service in tests."""

import pytest


@pytest.fixture(autouse=True)
def isolated_bilibili_protection(tmp_path, monkeypatch):
    from core import bilibili_guard, bilibili_cache

    bilibili_cache.clear()

    monkeypatch.setattr(bilibili_guard, "STATE_PATH", tmp_path / "bilibili_guard.db")
    # Individual limiter tests override these values with a controlled clock.
    monkeypatch.setattr(bilibili_guard, "LIMITS", {
        "api": (0, ((3600, 10000), (86400, 100000))),
        "media": (0, ((3600, 10000), (86400, 100000))),
    })
    monkeypatch.setenv("BILIBILI_USE_ACCOUNT_COOKIE", "false")
    monkeypatch.setenv("BILIBILI_COOKIE_SCOPE", "metadata")
