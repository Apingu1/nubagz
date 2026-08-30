from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import User
from app.security import decode_access_token
from admin_helpers import privileged_admin_headers


@pytest.fixture(autouse=True)
def phase25_privileged_admin_regression_bridge(monkeypatch, request):
    """Keep older feature regressions on the real Phase 2.5 security contract.

    Historic tests log in as the seeded demo Admin and then call sensitive
    Admin endpoints directly. Phase 2.5 deliberately makes that insufficient.
    For those existing product-flow tests, this bridge obtains a genuine
    short-lived privilege token through the real password+TOTP endpoint before
    the first unsafe Admin request.

    Tests marked ``no_auto_admin_privilege`` are untouched and can prove the
    fail-closed behaviour from an ordinary Admin session.
    """
    if request.node.get_closest_marker("no_auto_admin_privilege"):
        return

    original_request = TestClient.request

    def secured_request(client, method, url, *args, **kwargs):
        method_upper = str(method).upper()
        path = urlsplit(str(url)).path
        if method_upper not in {"GET", "HEAD", "OPTIONS"} and not path.startswith("/api/admin/security/"):
            headers = dict(kwargs.get("headers") or {})
            authorization = headers.get("Authorization") or headers.get("authorization")
            if authorization and "X-NuBagz-Admin-Privilege" not in headers:
                try:
                    token = authorization.split(" ", 1)[1]
                    user_id = int(decode_access_token(token).get("sub"))
                    with SessionLocal() as db:
                        user = db.get(User, user_id)
                        is_seed_admin = bool(user and user.role == "ADMIN" and user.email == "admin@demo.nubagz.com")
                    if is_seed_admin:
                        headers = privileged_admin_headers(client, headers, "Admin123!")
                        kwargs["headers"] = headers
                except Exception:
                    # Let the application return its normal auth/security error;
                    # the bridge must never turn an invalid token into access.
                    pass
        return original_request(client, method, url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", secured_request)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "no_auto_admin_privilege: exercise Admin endpoints without the compatibility privilege bridge",
    )
