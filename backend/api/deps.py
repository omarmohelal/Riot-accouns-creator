from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, WebSocket

from api.config import SESSION_COOKIE_NAME
from api.security import token_hash
from api.state import storage


def current_user_from_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    return storage.get_session_user(token_hash(token))


async def get_current_user(request: Request) -> Dict[str, Any]:
    user = current_user_from_token(request.cookies.get(SESSION_COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def websocket_user(websocket: WebSocket) -> Optional[Dict[str, Any]]:
    return current_user_from_token(websocket.cookies.get(SESSION_COOKIE_NAME))
