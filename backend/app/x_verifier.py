import re
from urllib.parse import urlparse
import httpx
from fastapi import HTTPException
from .challenge_models import Challenge, SocialAccount
from .config import settings


class XVerificationUnavailable(Exception):
    pass


def _headers() -> dict[str, str]:
    token = (settings.x_api_bearer_token or "").strip()
    if not token:
        raise XVerificationUnavailable("X automatic verification is not configured")
    return {"Authorization": f"Bearer {token}"}


def _tweet_id(challenge: Challenge) -> str:
    if challenge.target_id and str(challenge.target_id).isdigit():
        return str(challenge.target_id)
    match = re.search(r"/status/(\d+)", challenge.target_url or "")
    if not match:
        raise HTTPException(400, "This X challenge does not have a valid post URL")
    return match.group(1)


def _target_username(challenge: Challenge) -> str:
    if challenge.target_id and not str(challenge.target_id).isdigit():
        return str(challenge.target_id).lstrip("@").strip()
    raw = (challenge.target_url or "").strip()
    if raw.startswith("@"):
        return raw[1:]
    try:
        path = urlparse(raw).path.strip("/")
        if path:
            return path.split("/")[0].lstrip("@")
    except ValueError:
        pass
    return raw.lstrip("@").strip()


def _contains_user(client: httpx.Client, url: str, user_id: str, max_pages: int = 12, max_results: int = 100) -> tuple[bool, dict]:
    pagination_token = None
    checked = 0
    for _ in range(max_pages):
        params: dict[str, str | int] = {"max_results": max_results}
        if pagination_token:
            params["pagination_token"] = pagination_token
        response = client.get(url, params=params, headers=_headers())
        if response.status_code >= 400:
            raise XVerificationUnavailable(f"X API returned {response.status_code} while checking this activity")
        payload = response.json()
        data = payload.get("data") or []
        checked += len(data)
        if any(str(row.get("id")) == str(user_id) for row in data if isinstance(row, dict)):
            return True, {"source": "X_API", "checked_users": checked}
        pagination_token = (payload.get("meta") or {}).get("next_token")
        if not pagination_token:
            break
    return False, {"source": "X_API", "checked_users": checked}


def _resolve_x_user_id(client: httpx.Client, account: SocialAccount) -> str:
    if str(account.provider_user_id).isdigit():
        return str(account.provider_user_id)
    if not account.username:
        raise XVerificationUnavailable("The connected X account does not expose a usable user id")
    response = client.get(
        f"{settings.x_api_base_url.rstrip('/')}/users/by/username/{account.username.lstrip('@')}",
        headers=_headers(),
    )
    if response.status_code >= 400:
        raise XVerificationUnavailable("NuBagz could not resolve the connected X account")
    user_id = str((response.json().get("data") or {}).get("id") or "")
    if not user_id:
        raise XVerificationUnavailable("NuBagz could not resolve the connected X account")
    return user_id


def _resolve_target_user_id(client: httpx.Client, challenge: Challenge) -> str:
    if challenge.target_id and str(challenge.target_id).isdigit():
        return str(challenge.target_id)
    username = _target_username(challenge)
    if not username:
        raise HTTPException(400, "This follow challenge does not have a valid X account target")
    response = client.get(
        f"{settings.x_api_base_url.rstrip('/')}/users/by/username/{username}",
        headers=_headers(),
    )
    if response.status_code >= 400:
        raise XVerificationUnavailable("NuBagz could not resolve the target X account")
    target_id = str((response.json().get("data") or {}).get("id") or "")
    if not target_id:
        raise XVerificationUnavailable("NuBagz could not resolve the target X account")
    return target_id


def verify_x_action(account: SocialAccount, challenge: Challenge) -> tuple[bool, dict]:
    """Verify supported public X actions using the official X API.

    NuBagz intentionally uses the app's server-side bearer token rather than
    trusting anything supplied by the browser. Protected/private activity may
    not be visible to the app and is reported as unverifiable rather than being
    silently awarded.
    """
    action = (challenge.action or "").upper()
    base = settings.x_api_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=12.0) as client:
            x_user_id = _resolve_x_user_id(client, account)
            if action == "REPOST":
                tweet_id = _tweet_id(challenge)
                verified, evidence = _contains_user(client, f"{base}/tweets/{tweet_id}/retweeted_by", x_user_id)
                return verified, {**evidence, "provider": "X", "action": action, "tweet_id": tweet_id, "x_user_id": x_user_id}
            if action == "LIKE":
                tweet_id = _tweet_id(challenge)
                verified, evidence = _contains_user(client, f"{base}/tweets/{tweet_id}/liking_users", x_user_id)
                return verified, {**evidence, "provider": "X", "action": action, "tweet_id": tweet_id, "x_user_id": x_user_id}
            if action == "FOLLOW":
                target_id = _resolve_target_user_id(client, challenge)
                verified, evidence = _contains_user(client, f"{base}/users/{target_id}/followers", x_user_id, max_results=1000)
                return verified, {**evidence, "provider": "X", "action": action, "target_user_id": target_id, "x_user_id": x_user_id}
    except httpx.HTTPError as exc:
        raise XVerificationUnavailable("X could not be reached for automatic verification") from exc
    raise HTTPException(400, f"Automatic X verification is not available for action {action or 'UNKNOWN'}")
