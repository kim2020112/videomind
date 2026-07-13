import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import auth_routes
from api.auth_routes import AuthRequest


def make_request(*, authorization: str = "", cookie: str = "", query: str = "") -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": query.encode(),
        }
    )


class WindowSessionTests(unittest.IsolatedAsyncioTestCase):
    def test_bearer_session_wins_over_conflicting_cookie(self):
        request = make_request(
            authorization="Bearer admin-window-session",
            cookie="vm_session=regular-user-cookie",
        )

        def lookup(session_id):
            return {
                "admin-window-session": {"id": 1, "username": "admin", "role": "admin"},
                "regular-user-cookie": {"id": 2, "username": "user", "role": "user"},
            }.get(session_id)

        with patch.object(auth_routes, "get_user_by_session", side_effect=lookup) as get_user:
            user = auth_routes.get_current_user(request)

        self.assertEqual("admin", user["role"])
        get_user.assert_called_once_with("admin-window-session")

    def test_invalid_explicit_session_does_not_fall_back_to_cookie(self):
        request = make_request(
            authorization="Bearer expired-window-session",
            cookie="vm_session=other-user-cookie",
        )

        with patch.object(auth_routes, "get_user_by_session", return_value=None) as get_user:
            user = auth_routes.get_current_user(request)

        self.assertIsNone(user)
        get_user.assert_called_once_with("expired-window-session")

    def test_query_session_wins_for_media_requests_that_cannot_set_headers(self):
        request = make_request(
            query="session_id=admin-window-session",
            cookie="vm_session=regular-user-cookie",
        )

        with patch.object(
            auth_routes,
            "get_user_by_session",
            return_value={"id": 1, "username": "admin", "role": "admin"},
        ) as get_user:
            user = auth_routes.get_current_user(request)

        self.assertEqual("admin", user["role"])
        get_user.assert_called_once_with("admin-window-session")

    def test_explicit_guest_mode_does_not_fall_back_to_cookie(self):
        request = make_request(cookie="vm_session=other-user-cookie")
        request.scope["headers"].append((b"x-session-mode", b"guest"))

        with patch.object(auth_routes, "get_user_by_session") as get_user:
            user = auth_routes.get_current_user(request)

        self.assertIsNone(user)
        get_user.assert_not_called()

    def test_query_guest_mode_does_not_fall_back_to_cookie(self):
        request = make_request(
            cookie="vm_session=other-user-cookie",
            query="session_mode=guest&guest_id=guest-device-id",
        )

        with patch.object(auth_routes, "get_user_by_session") as get_user:
            user = auth_routes.get_current_user(request)

        self.assertIsNone(user)
        get_user.assert_not_called()

    async def test_logout_deletes_only_explicit_window_session(self):
        request = make_request(
            authorization="Bearer admin-window-session",
            cookie="vm_session=regular-user-cookie",
        )

        with patch.object(auth_routes, "delete_session") as delete_session:
            response = await auth_routes.logout(request)

        delete_session.assert_called_once_with("admin-window-session")
        self.assertNotIn("vm_session=", response.headers.get("set-cookie", ""))

    async def test_login_returns_created_session_id(self):
        user = {
            "id": 7,
            "username": "admin",
            "password_hash": "hash",
            "is_active": 1,
            "is_deleted": 0,
        }
        with (
            patch.object(auth_routes, "get_user_by_username", return_value=user),
            patch.object(auth_routes, "verify_password", return_value=True),
            patch.object(auth_routes, "create_session", return_value="new-window-session"),
        ):
            response = await auth_routes.login(AuthRequest(username="admin", password="secret"))

        self.assertEqual("new-window-session", json.loads(response.body)["session_id"])

    async def test_me_returns_cookie_session_for_window_migration(self):
        request = make_request(cookie="vm_session=legacy-cookie-session")
        identity = {
            "user_id": 7,
            "guest_id": None,
            "guest_sig": None,
            "role": "user",
            "daily_limit": 20,
        }
        user = {"id": 7, "username": "legacy-user", "role": "user"}

        with (
            patch.object(auth_routes, "get_identity", return_value=identity),
            patch.object(auth_routes, "get_user_by_id", return_value=user),
            patch("core.auth.check_usage_limit", return_value=(True, 0, 20)),
        ):
            response = await auth_routes.me(request)

        self.assertTrue(response["logged_in"])
        self.assertEqual("legacy-cookie-session", response["session_id"])


if __name__ == "__main__":
    unittest.main()
