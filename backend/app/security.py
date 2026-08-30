import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
import jwt
from .config import settings


def hash_password(password:str)->str:
    salt=os.urandom(16); derived=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1,dklen=64)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(derived).decode()}"


def verify_password(password:str,stored:str)->bool:
    try:
        algo,salt_b64,digest_b64=stored.split("$",2)
        if algo!="scrypt": return False
        salt=base64.b64decode(salt_b64); expected=base64.b64decode(digest_b64)
        actual=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1,dklen=64)
        return hmac.compare_digest(actual,expected)
    except Exception: return False


def create_access_token(user_id:int,role:str,session_id:str)->str:
    now=datetime.now(timezone.utc); exp=now+timedelta(minutes=settings.access_token_minutes)
    payload={
        "sub":str(user_id),
        "role":role,
        "sid":session_id,
        "jti":secrets.token_urlsafe(24),
        "iat":now,
        "exp":exp,
        "iss":"nubagz",
        "aud":settings.jwt_audience,
    }
    headers={"kid":settings.jwt_key_id} if settings.jwt_algorithm in {"RS256","ES256"} else None
    return jwt.encode(payload,settings.signing_key,algorithm=settings.jwt_algorithm,headers=headers)


def decode_access_token(token:str)->dict:
    return jwt.decode(
        token,
        settings.verification_key,
        algorithms=[settings.jwt_algorithm],
        issuer="nubagz",
        audience=settings.jwt_audience,
        options={"require":["sub","sid","jti","iat","exp","iss","aud"]},
    )
