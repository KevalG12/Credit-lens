"""FastAPI dependencies."""
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import db
from app.config import get_settings
from app.security import AuthError, decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    unauthorized = HTTPException(
        status_code=401, detail="Not authenticated.", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    settings = get_settings()
    try:
        user_id = decode_token(creds.credentials, settings.jwt_secret)
    except AuthError:
        raise unauthorized from None
    user = db.get_user(settings.db_path, user_id)
    if user is None:
        raise unauthorized
    return user


_attempts: dict[str, deque] = defaultdict(deque)


def rate_limit_auth(request: Request) -> None:
    """Tiny in-memory sliding-window limiter for /auth/* (per client IP, per minute).
    Per-process only; use a shared store (e.g. Redis) if you run several workers."""
    limit = get_settings().auth_rate_limit
    if limit <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    q = _attempts[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if not q:
        _attempts.pop(ip, None)   # don't let the table grow forever
        q = _attempts[ip]
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a minute and try again.",
                            headers={"Retry-After": "60"})
    q.append(now)
