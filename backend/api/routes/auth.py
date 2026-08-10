from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.config import SECURE_COOKIES, SESSION_COOKIE_NAME, SESSION_DAYS
from api.deps import get_current_user
from api.security import LoginRateLimiter, hash_password, new_session_token, token_hash, verify_password
from api.state import storage

router = APIRouter(prefix="/api/auth", tags=["auth"])
_limiter = LoginRateLimiter(max_attempts=8, window_seconds=300, block_seconds=300)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=512)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="strict",
        path="/",
    )


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    client_ip = request.client.host if request.client else "local"
    limiter_key = f"{client_ip}:{payload.email.strip().casefold()}"
    allowed, retry_after = _limiter.can_attempt(limiter_key)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many login attempts. Try again in {retry_after} seconds.")

    user = storage.get_user_by_email(payload.email)
    if not user or not user.get("is_active") or not verify_password(payload.password, user.get("password_hash", "")):
        _limiter.record_failure(limiter_key)
        storage.add_audit_event("auth.login_failed", actor_email=payload.email.strip(), detail={"client": client_ip})
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _limiter.record_success(limiter_key)
    token = new_session_token()
    storage.create_session(user["id"], token_hash(token), days=SESSION_DAYS)
    storage.mark_login(user["id"])
    storage.add_audit_event("auth.login", actor_email=user["email"], entity_type="user", entity_id=user["id"], detail={"client": client_ip})
    _set_session_cookie(response, token)
    return {"authenticated": True, "user": {"email": user["email"], "role": user["role"]}}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {"authenticated": True, "user": {"email": user["email"], "role": user["role"], "last_login_at": user.get("last_login_at")}}


@router.post("/logout")
async def logout(request: Request, response: Response, user=Depends(get_current_user)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        storage.delete_session(token_hash(token))
    storage.add_audit_event("auth.logout", actor_email=user["email"], entity_type="user", entity_id=user["id"])
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"authenticated": False}


@router.post("/change-password")
async def change_password(payload: ChangePasswordRequest, request: Request, response: Response, user=Depends(get_current_user)):
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    new_hash = hash_password(payload.new_password)
    storage.update_user_password(user["id"], new_hash)
    token = new_session_token()
    storage.create_session(user["id"], token_hash(token), days=SESSION_DAYS)
    storage.add_audit_event("auth.password_changed", actor_email=user["email"], entity_type="user", entity_id=user["id"])
    _set_session_cookie(response, token)
    return {"status": "changed"}
