import secrets

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.config import get_settings
from app.deps import get_current_user, rate_limit_auth
from app.schemas import Credentials, RegisterCredentials, TokenResponse, UserInfo
from app.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
_limited = [Depends(rate_limit_auth)]

# Verified against when the email is unknown, so response time doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/register", response_model=TokenResponse, status_code=201, dependencies=_limited)
def register(body: RegisterCredentials) -> TokenResponse:
    s = get_settings()
    email = body.email.strip().lower()
    try:
        user_id = db.create_user(s.db_path, email, hash_password(body.password))
    except db.DuplicateEmail:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from None
    return TokenResponse(access_token=create_token(user_id, s.jwt_secret, s.jwt_minutes))


@router.post("/login", response_model=TokenResponse, dependencies=_limited)
def login(body: Credentials) -> TokenResponse:
    s = get_settings()
    user = db.get_user_by_email(s.db_path, body.email.strip().lower())
    stored = user["password_hash"] if user else _DUMMY_HASH
    ok = verify_password(body.password, stored)
    if not (user and ok):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return TokenResponse(access_token=create_token(user["id"], s.jwt_secret, s.jwt_minutes))


@router.post("/demo", response_model=TokenResponse, status_code=201, dependencies=_limited)
def demo_login() -> TokenResponse:
    """One-click guest session for judges/testers: a throw-away account, purged after 24 hours."""
    s = get_settings()
    db.purge_old_guests(s.db_path)
    email = f"guest-{secrets.token_hex(6)}{db.GUEST_DOMAIN}"
    user_id = db.create_user(s.db_path, email, hash_password(secrets.token_urlsafe(24)))
    return TokenResponse(access_token=create_token(user_id, s.jwt_secret, s.jwt_minutes))


@router.get("/me", response_model=UserInfo)
def me(user: dict = Depends(get_current_user)) -> UserInfo:
    return UserInfo(email=user["email"], created_at=user["created_at"], is_guest=user["email"].endswith(db.GUEST_DOMAIN))
