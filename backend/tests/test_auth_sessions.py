import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import auth_routes
from api import security
from api.auth_routes import AuthRequest


def make_request(
    *,
    authorization: str = "",
    cookie: str = "",
    query: str = "",
    guest_id: str = "",
    guest_sig: str = "",
) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if guest_id:
        headers.append((b"x-guest-id", guest_id.encode()))
    if guest_sig:
        headers.append((b"x-guest-sig", guest_sig.encode()))
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

    def test_cookie_cannot_authenticate_generic_http_request(self):
        request = make_request(
            cookie="vm_session=regular-user-cookie",
        )

        with patch.object(auth_routes, "get_user_by_session") as get_user:
            user = auth_routes.get_current_user(request)

        self.assertIsNone(user)
        get_user.assert_not_called()

    def test_query_session_cannot_authenticate_generic_http_request(self):
        request = make_request(query="session_id=admin-window-session")

        with patch.object(auth_routes, "get_user_by_session") as get_user:
            user = auth_routes.get_current_user(request)

        self.assertIsNone(user)
        get_user.assert_not_called()

    def test_query_guest_credentials_cannot_authenticate_generic_http_request(self):
        request = make_request(
            query="guest_id=guest-device-id&guest_sig=valid-signature",
        )

        with (
            patch.object(security, "guest_signing_enabled", return_value=True),
            patch.object(security, "verify_guest_id", return_value=True) as verify_guest,
        ):
            with self.assertRaises(HTTPException):
                security.require_identity(request)

        verify_guest.assert_not_called()

    def test_invalid_bearer_cannot_fall_back_to_generic_http_guest(self):
        request = make_request(
            authorization="Bearer expired-window-session",
            guest_id="guest-device-id",
            guest_sig="valid-signature",
        )

        with (
            patch.object(auth_routes, "get_user_by_session", return_value=None),
            patch.object(security, "guest_signing_enabled", return_value=True),
            patch.object(security, "verify_guest_id", return_value=True) as verify_guest,
        ):
            with self.assertRaises(HTTPException):
                security.require_identity(request)

        verify_guest.assert_not_called()

    def test_media_query_session_authenticates_explicit_stream_scope(self):
        request = make_request(query="session_id=admin-window-session")

        with patch.object(
            security,
            "get_user_by_session",
            return_value={
                "id": 1,
                "username": "admin",
                "role": "admin",
                "daily_limit": 20,
            },
        ) as get_user:
            identity = security.require_media_identity(request)

        self.assertEqual(1, identity["user_id"])
        self.assertEqual("admin", identity["role"])
        get_user.assert_called_once_with("admin-window-session")

    def test_media_query_guest_authenticates_explicit_stream_scope(self):
        request = make_request(
            query="guest_id=guest-device-id&guest_sig=valid-signature",
        )

        with (
            patch.object(security, "guest_signing_enabled", return_value=True),
            patch.object(security, "verify_guest_id", return_value=True) as verify_guest,
        ):
            identity = security.require_media_identity(request)

        self.assertEqual("guest-device-id", identity["guest_id"])
        verify_guest.assert_called_once_with("guest-device-id", "valid-signature")

    def test_invalid_bearer_cannot_fall_back_to_media_query_guest(self):
        request = make_request(
            authorization="Bearer expired-window-session",
            query="guest_id=guest-device-id&guest_sig=valid-signature",
        )

        with (
            patch.object(security, "get_user_by_session", return_value=None),
            patch.object(security, "guest_signing_enabled", return_value=True),
            patch.object(security, "verify_guest_id", return_value=True) as verify_guest,
        ):
            with self.assertRaises(HTTPException):
                security.require_media_identity(request)

        verify_guest.assert_not_called()

    def test_malformed_bearer_cannot_fall_back_to_media_query_session(self):
        request = make_request(
            authorization="Basic legacy-credential",
            query="session_id=valid-window-session",
        )

        with patch.object(security, "get_user_by_session") as get_user:
            with self.assertRaises(HTTPException):
                security.require_media_identity(request)

        get_user.assert_not_called()

    def test_websocket_query_session_remains_supported(self):
        request = make_request(query="session_id=websocket-window-session")

        with patch.object(
            security,
            "get_user_by_session",
            return_value={
                "id": 2,
                "username": "viewer",
                "role": "user",
                "daily_limit": 20,
            },
        ) as get_user:
            identity = security.require_websocket_identity(request)

        self.assertEqual(2, identity["user_id"])
        get_user.assert_called_once_with("websocket-window-session")

    def test_invalid_websocket_query_session_cannot_fall_back_to_query_guest(self):
        request = make_request(
            query=(
                "session_id=expired-window-session&guest_id=guest-device-id"
                "&guest_sig=valid-signature"
            ),
        )

        with (
            patch.object(security, "get_user_by_session", return_value=None),
            patch.object(security, "guest_signing_enabled", return_value=True),
            patch.object(security, "verify_guest_id", return_value=True) as verify_guest,
        ):
            with self.assertRaises(HTTPException):
                security.require_websocket_identity(request)

        verify_guest.assert_not_called()

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
        self.assertNotIn("set-cookie", response.headers)

    async def test_register_returns_created_session_without_cookie(self):
        with (
            patch.object(auth_routes, "REGISTRATION_ENABLED", True),
            patch.object(auth_routes, "get_user_by_username", return_value=None),
            patch.object(auth_routes, "create_user", return_value=8),
            patch.object(auth_routes, "create_session", return_value="registered-window-session"),
        ):
            response = await auth_routes.register(
                AuthRequest(username="new-user", password="secret")
            )

        self.assertEqual(
            "registered-window-session",
            json.loads(response.body)["session_id"],
        )
        self.assertNotIn("set-cookie", response.headers)

    async def test_logout_ignores_cookie_and_never_cleans_it_up(self):
        request = make_request(cookie="vm_session=legacy-cookie-session")

        with patch.object(auth_routes, "delete_session") as delete_session:
            response = await auth_routes.logout(request)

        delete_session.assert_not_called()
        self.assertNotIn("set-cookie", response.headers)

    async def test_me_never_returns_session_credentials(self):
        request = make_request(authorization="Bearer window-session")
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
        self.assertNotIn("session_id", response)


if __name__ == "__main__":
    unittest.main()
