import hashlib
import hmac
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from .challenge_models import Challenge, SocialAccount
from .config import settings


OEMBED_URL = "https://publish.x.com/oembed"
PROOF_PATTERN = re.compile(r"\bNBZ-[A-F0-9]{12}\b", re.IGNORECASE)
X_HOSTS = {"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}


class XVerificationUnavailable(Exception):
    pass


class _TweetTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._inside_p = False
        self._seen_p = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "p" and not self._seen_p:
            self._inside_p = True
            self._seen_p = True

    def handle_endtag(self, tag: str):
        if tag.lower() == "p" and self._inside_p:
            self._inside_p = False

    def handle_data(self, data: str):
        if self._inside_p:
            self.parts.append(data)


def make_x_proof_code(user_id: int, challenge_id: int) -> str:
    secret = (settings.social_proof_secret or settings.jwt_secret or "change-me-in-production").encode()
    payload = f"x-proof:{user_id}:{challenge_id}".encode()
    digest = hmac.new(secret, payload, hashlib.sha256).hexdigest()[:12].upper()
    return f"NBZ-{digest}"


def _parse_public_post_url(post_url: str) -> tuple[str, str]:
    raw = (post_url or "").strip()
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise HTTPException(400, "Paste a valid public X post URL") from exc
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or host not in X_HOSTS:
        raise HTTPException(400, "Paste a valid public X post URL")
    if len(parts) < 3 or parts[1].lower() != "status" or not parts[2].isdigit():
        raise HTTPException(400, "Paste the URL of your public X post, not an X profile or search page")
    return parts[0].lstrip("@"), parts[2]


def _username_from_author_url(author_url: str) -> str:
    try:
        parsed = urlparse(author_url or "")
        parts = [part for part in parsed.path.split("/") if part]
        return parts[0].lstrip("@") if parts else ""
    except ValueError:
        return ""


def _tweet_text(markup: str) -> str:
    parser = _TweetTextParser()
    parser.feed(markup or "")
    return " ".join(" ".join(parser.parts).split())


def _required_domain(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        host = (urlparse(candidate).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _requirement_matches(challenge: Challenge, text: str, markup: str) -> tuple[bool, str]:
    config = dict(challenge.config or {})
    action = (challenge.action or "").upper()
    folded = text.casefold()

    if action == "POST":
        required = str(config.get("required_text") or "").strip()
        return (bool(required) and required.casefold() in folded, required)

    if action == "MENTION":
        required = str(config.get("required_mention") or "").strip().lstrip("@")
        pattern = re.compile(rf"(?<![\w])@{re.escape(required)}(?![\w])", re.IGNORECASE) if required else None
        return (bool(pattern and pattern.search(text)), f"@{required}" if required else "")

    if action == "HASHTAG":
        required = str(config.get("required_hashtag") or "").strip().lstrip("#")
        pattern = re.compile(rf"(?<![\w])#{re.escape(required)}(?![\w])", re.IGNORECASE) if required else None
        return (bool(pattern and pattern.search(text)), f"#{required}" if required else "")

    if action == "LINK":
        required = str(config.get("required_link") or "").strip()
        domain = _required_domain(required)
        haystack = f"{text} {markup}".casefold()
        return (bool(domain) and domain.casefold() in haystack, required)

    raise HTTPException(400, f"Free X proof verification is not available for action {action or 'UNKNOWN'}")


def _verify_with_client(
    client: httpx.Client,
    account: SocialAccount,
    challenge: Challenge,
    post_url: str,
    expected_proof: str,
) -> tuple[bool, dict]:
    submitted_username, tweet_id = _parse_public_post_url(post_url)
    linked_username = (account.username or "").strip().lstrip("@")
    if not linked_username:
        raise XVerificationUnavailable("Your connected X identity does not expose a username that NuBagz can verify")

    try:
        response = client.get(
            OEMBED_URL,
            params={"url": post_url.strip(), "omit_script": "1", "dnt": "true"},
        )
    except httpx.HTTPError as exc:
        raise XVerificationUnavailable("X public-post verification could not be reached") from exc

    if 400 <= response.status_code < 500:
        return False, {"source": "X_OEMBED_PUBLIC", "reason": "post_not_public_or_not_found", "tweet_id": tweet_id}
    if response.status_code >= 500:
        raise XVerificationUnavailable(f"X public-post verification returned {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise XVerificationUnavailable("X returned an unreadable public-post response") from exc

    author_username = _username_from_author_url(str(payload.get("author_url") or ""))
    if not author_username:
        raise XVerificationUnavailable("X did not return the post author's public identity")

    if author_username.casefold() != linked_username.casefold():
        return False, {
            "source": "X_OEMBED_PUBLIC",
            "reason": "wrong_author",
            "tweet_id": tweet_id,
            "author_username": author_username,
        }

    if submitted_username.casefold() != linked_username.casefold():
        return False, {
            "source": "X_OEMBED_PUBLIC",
            "reason": "url_author_mismatch",
            "tweet_id": tweet_id,
            "author_username": author_username,
        }

    markup = str(payload.get("html") or "")
    text = _tweet_text(markup)
    if not text:
        return False, {"source": "X_OEMBED_PUBLIC", "reason": "post_text_unavailable", "tweet_id": tweet_id}

    proof_codes = {token.upper() for token in PROOF_PATTERN.findall(text)}
    if expected_proof.upper() not in proof_codes:
        return False, {"source": "X_OEMBED_PUBLIC", "reason": "proof_code_missing", "tweet_id": tweet_id}
    if len(proof_codes) != 1:
        return False, {"source": "X_OEMBED_PUBLIC", "reason": "multiple_proof_codes", "tweet_id": tweet_id}

    matches, requirement = _requirement_matches(challenge, text, markup)
    if not matches:
        return False, {
            "source": "X_OEMBED_PUBLIC",
            "reason": "challenge_requirement_missing",
            "tweet_id": tweet_id,
            "requirement": requirement,
        }

    canonical_url = str(payload.get("url") or post_url).strip()
    return True, {
        "source": "X_OEMBED_PUBLIC",
        "provider": "X",
        "action": (challenge.action or "").upper(),
        "post_url": canonical_url,
        "tweet_id": tweet_id,
        "author_username": author_username,
        "proof_code": expected_proof.upper(),
        "matched_requirement": requirement,
        "post_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def verify_x_post_proof(
    account: SocialAccount,
    challenge: Challenge,
    post_url: str,
    expected_proof: str,
    client: httpx.Client | None = None,
) -> tuple[bool, dict]:
    """Verify a public X post without the paid X API.

    X's official oEmbed endpoint is public, requires no authentication, and is
    documented by X as not rate-limited. NuBagz uses it only to validate the
    public post supplied by the worker; it does not crawl X or inspect private
    likes/follows.
    """
    if client is not None:
        return _verify_with_client(client, account, challenge, post_url, expected_proof)
    with httpx.Client(timeout=12.0, follow_redirects=True) as owned_client:
        return _verify_with_client(owned_client, account, challenge, post_url, expected_proof)
