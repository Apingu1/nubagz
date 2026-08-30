from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings
from .security_hardening import (
    hash_network_identifier,
    network_observer,
    record_security_event,
    request_user_id,
    trusted_client_ip,
    verify_turnstile,
)


@dataclass(frozen=True)
class RateRule:
    name: str
    limit: int
    window_seconds: int


class SlidingWindowLimiter:
    """Process-local sliding-window limiter used as the Phase 2.6 API throttle.

    The current production topology runs one API service. The implementation is
    intentionally isolated behind this class so a future multi-replica deployment
    can replace the store with Redis without changing route semantics.
    """

    def __init__(self):
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def check_many(self, keys: list[str], rule: RateRule, now: float | None = None) -> tuple[bool, int]:
        if rule.limit <= 0:
            return True, 0
        current = time.monotonic() if now is None else now
        cutoff = current - rule.window_seconds
        with self._lock:
            blocked_retry = 0
            buckets: list[deque[float]] = []
            for key in keys:
                bucket_key = f"{rule.name}:{key}"
                bucket = self._events.setdefault(bucket_key, deque())
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                buckets.append(bucket)
                if len(bucket) >= rule.limit:
                    retry = max(1, math.ceil(rule.window_seconds - (current - bucket[0])))
                    blocked_retry = max(blocked_retry, retry)
            if blocked_retry:
                return False, blocked_retry
            for bucket in buckets:
                bucket.append(current)

            # Bound stale cardinality in long-running development processes.
            if len(self._events) > 20000:
                empty = [key for key, bucket in self._events.items() if not bucket or bucket[-1] <= cutoff]
                for key in empty[:5000]:
                    self._events.pop(key, None)
            return True, 0


limiter = SlidingWindowLimiter()


def _route_group(path: str, method: str) -> str:
    if path in {"/api/auth/login", "/api/auth/register", "/api/auth/privy"} and method == "POST":
        return "auth"
    if path.startswith("/api/admin/security/") and method not in {"GET", "HEAD", "OPTIONS"}:
        return "credential"
    if path in {"/api/users/wallets/challenge", "/api/users/wallets/verify"} and method == "POST":
        return "credential"
    if path.startswith("/api/swaps/") or path.startswith("/api/gas/"):
        return "value"
    if path.startswith("/api/challenges/") and method == "POST" and (path.endswith("/join") or path.endswith("/complete")):
        return "value"
    if method in {"GET", "HEAD"}:
        return "read"
    return "write"


def _rules(group: str) -> list[RateRule]:
    if group == "auth":
        return [
            RateRule("auth-minute", settings.rate_limit_auth_per_minute, 60),
            RateRule("auth-15m", settings.rate_limit_auth_per_15_minutes, 15 * 60),
        ]
    if group == "credential":
        return [RateRule("credential-minute", settings.rate_limit_credential_per_minute, 60)]
    if group == "value":
        return [RateRule("value-minute", settings.rate_limit_value_per_minute, 60)]
    if group == "read":
        return [RateRule("read-minute", settings.rate_limit_read_per_minute, 60)]
    return [RateRule("write-minute", settings.rate_limit_write_per_minute, 60)]


def _subject_keys(user_id: int | None, network_value: str) -> list[str]:
    keys = [f"ip:{hash_network_identifier(network_value)}"]
    if user_id:
        keys.append(f"user:{user_id}")
    return keys


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled or request.method == "OPTIONS" or not request.url.path.startswith("/api/") or request.url.path == "/api/health":
            return await call_next(request)

        network_value = trusted_client_ip(request)
        user_id = request_user_id(request)
        group = _route_group(request.url.path, request.method.upper())
        keys = _subject_keys(user_id, network_value)

        retry_after = 0
        blocked_rule = None
        for rule in _rules(group):
            allowed, retry = limiter.check_many(keys, rule)
            if not allowed:
                retry_after = max(retry_after, retry)
                blocked_rule = rule
                break

        if blocked_rule is not None:
            captcha_configured = bool((settings.turnstile_secret_key or "").strip() and (settings.turnstile_site_key or "").strip())
            captcha_allowed = group in {"auth", "write"}
            human_required = captcha_configured and captcha_allowed
            human_token = request.headers.get("x-nubagz-human-token", "")
            if human_required and human_token and await verify_turnstile(human_token, network_value):
                record_security_event(
                    user_id=user_id,
                    network_value=network_value,
                    event_type="HUMAN_VERIFICATION_PASSED",
                    route_group=group,
                    detail="Turnstile verification allowed one throttled request to proceed.",
                )
                if user_id:
                    network_observer.touch(user_id, network_value)
                return await call_next(request)

            record_security_event(
                user_id=user_id,
                network_value=network_value,
                event_type="RATE_LIMIT_BLOCK",
                route_group=group,
                detail=f"{blocked_rule.name} request threshold exceeded.",
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Try again shortly.",
                    "code": "RATE_LIMITED",
                    "retry_after": retry_after,
                    "human_verification_required": human_required,
                },
                headers={"Retry-After": str(retry_after)},
            )

        if user_id:
            network_observer.touch(user_id, network_value)
        return await call_next(request)
