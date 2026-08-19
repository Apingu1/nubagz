import re
import secrets
from sqlalchemy.orm import Session
from .models import User


def slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value or secrets.token_hex(4)


def unique_referral_code(db: Session, username: str) -> str:
    base = re.sub(r"[^A-Z0-9]", "", username.upper())[:8] or "BAGGER"
    for _ in range(20):
        code = f"{base}{secrets.randbelow(9999):04d}"
        if not db.query(User).filter(User.referral_code == code).first():
            return code
    return secrets.token_hex(6).upper()
