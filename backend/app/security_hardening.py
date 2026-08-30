from __future__ import annotations

import hashlib
import hmac
import ipaddress
import threading
import time
from datetime import UTC, datetime

import httpx
from fastapi import Request
from sqlalchemy.exc import IntegrityError

from .abuse_models import NetworkObservation, SecurityEvent
from .config import settings
from .db import SessionLocal
from .security import decode_access_token


def _signal_key() -> bytes:
    raw = (settings.abuse_signal_key or settings.jwt_secret or "local-nubagz-abuse-signal").strip()
    return raw.encode("utf-8")


def hash_network_identifier(value: str) -> str:
    """Return a stable keyed digest without retaining the source network value."""
    return hmac.new(_signal_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def trusted_client_ip(request: Request) -> str:
    """Resolve the client network address without blindly trusting forwarded headers.

    In production NuBagz's API is reached through its own Nginx container, which
    overwrites X-Real-IP. Direct development traffic keeps proxy trust disabled.
    """
    direct = (request.client.host if request.client else "unknown") or "unknown"
    candidate = request.headers.get("x-real-ip", "").strip() if settings.trust_proxy_headers else ""
    if candidate:
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    try:
        return str(ipaddress.ip_address(direct))
    except ValueError:
        return direct[:128]


def request_user_id(request: Request) -> int | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    try:
        claims = decode_access_token(authorization.split(" ", 1)[1].strip())
        return int(claims.get("sub"))
    except Exception:
        # Authentication remains the route dependency's responsibility. The
        # anti-abuse layer must never turn a malformed token into an identity.
        return None


class NetworkObserver:
    """Coalesce normal request observations so the database is not written per hit."""

    def __init__(self, minimum_interval_seconds: int = 300):
        self.minimum_interval_seconds = minimum_interval_seconds
        self._lock = threading.Lock()
        self._last_touch: dict[tuple[int, str], float] = {}

    def clear(self) -> None:
        with self._lock:
            self._last_touch.clear()

    def touch(self, user_id: int | None, network_value: str) -> None:
        if not user_id or not network_value:
            return
        digest = hash_network_identifier(network_value)
        now_mono = time.monotonic()
        cache_key = (user_id, digest)
        with self._lock:
            last = self._last_touch.get(cache_key)
            if last is not None and now_mono - last < self.minimum_interval_seconds:
                return
            self._last_touch[cache_key] = now_mono

        now = datetime.now(UTC)
        day_bucket = now.date().isoformat()
        with SessionLocal() as db:
            try:
                row = db.query(NetworkObservation).filter(
                    NetworkObservation.user_id == user_id,
                    NetworkObservation.ip_hash == digest,
                    NetworkObservation.day_bucket == day_bucket,
                ).first()
                if row:
                    row.last_seen_at = now
                    row.request_count = int(row.request_count or 0) + 1
                else:
                    db.add(NetworkObservation(
                        user_id=user_id,
                        ip_hash=digest,
                        day_bucket=day_bucket,
                        request_count=1,
                        first_seen_at=now,
                        last_seen_at=now,
                    ))
                db.commit()
            except IntegrityError:
                # A concurrent request may win the unique insert. The next
                # coalesced observation will update the row; no raw identifier is lost.
                db.rollback()
            except Exception:
                db.rollback()
                # Network observations are supporting evidence. A telemetry write
                # must never take the product offline or block a legitimate request.


network_observer = NetworkObserver()


def record_security_event(
    *,
    user_id: int | None,
    network_value: str,
    event_type: str,
    route_group: str,
    detail: str,
) -> None:
    digest = hash_network_identifier(network_value or "unknown")
    with SessionLocal() as db:
        try:
            db.add(SecurityEvent(
                user_id=user_id,
                ip_hash=digest,
                event_type=event_type[:64],
                route_group=route_group[:64],
                detail=detail[:2000],
                created_at=datetime.now(UTC),
            ))
            db.commit()
        except Exception:
            db.rollback()
            # Security-event persistence supports investigation but a telemetry
            # outage must not replace the primary security decision itself.


async def verify_turnstile(token: str, remote_ip: str) -> bool:
    """Verify a Cloudflare Turnstile response without retaining the response token."""
    secret = (settings.turnstile_secret_key or "").strip()
    if not secret or not token.strip():
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                settings.turnstile_verify_url,
                data={"secret": secret, "response": token.strip(), "remoteip": remote_ip},
            )
            response.raise_for_status()
            payload = response.json()
            return bool(payload.get("success"))
    except Exception:
        # Human verification fails closed. The ordinary Retry-After path remains
        # available and an upstream CAPTCHA outage does not grant a bypass.
        return False
