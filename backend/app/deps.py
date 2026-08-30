from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .account_policy import AUTHENTICATE, EARN_REWARDS, SWAP, allows, require_capability
from .db import get_db
from .models import User, UserSession
from .security import decode_access_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _required_request_capability(request: Request) -> tuple[str, str] | None:
    if request.method.upper() != "POST":
        return None
    path = request.url.path.rstrip("/")
    if path.startswith("/api/swaps/"):
        return SWAP, "This account is restricted from initiating swaps"
    if path.startswith("/api/challenges/") and (path.endswith("/join") or path.endswith("/complete")):
        return EARN_REWARDS, "This account is restricted from new reward opportunities"
    if path.startswith("/api/campaigns/") and path.endswith("/enroll"):
        return EARN_REWARDS, "This account is restricted from new reward opportunities"
    return None


def get_current_session(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserSession:
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
        session_id = str(payload.get("sid") or "")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session-bound login required")
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id,
        UserSession.user_id == user_id,
    ).first()
    now = datetime.now(UTC)
    if not session or session.revoked_at is not None or _as_utc(session.expires_at) <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")
    # Throttle activity writes while keeping enough recency for later Admin security tooling.
    if (now - _as_utc(session.last_seen_at)).total_seconds() >= 300:
        session.last_seen_at = now
        db.commit()
    return session


def get_current_user(request: Request, session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)) -> User:
    user = db.get(User, session.user_id)
    if not user or not allows(user, AUTHENTICATE):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not available")
    required = _required_request_capability(request)
    if required:
        capability, detail = required
        require_capability(user, capability, detail)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
