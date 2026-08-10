from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.state import email_manager, proxy_handler, storage

router = APIRouter(prefix="/api", tags=["inventory"], dependencies=[Depends(get_current_user)])


class EmailAccountsSettings(BaseModel):
    email_accounts: List[str] = Field(default_factory=list, max_length=10000)


class EmailUpdate(BaseModel):
    email: Optional[str] = Field(default=None, max_length=254)
    password: Optional[str] = Field(default=None, max_length=512)
    status: Optional[str] = None


class BulkInventoryAction(BaseModel):
    ids: List[int] = Field(default_factory=list, max_length=5000)
    action: str


class ProxySettings(BaseModel):
    proxy_list: List[str] = Field(default_factory=list, max_length=10000)
    proxy_type: Literal["http", "https", "socks5", "socks5h"] = "http"


class ProxyUpdate(BaseModel):
    ip: Optional[str] = Field(default=None, max_length=255)
    port: Optional[str] = Field(default=None, max_length=16)
    username: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, max_length=512)
    proxy_type: Optional[Literal["http", "https", "socks5", "socks5h"]] = None
    region: Optional[str] = Field(default=None, max_length=32)


@router.post("/emails/preview")
async def preview_email_accounts(settings: EmailAccountsSettings):
    return email_manager.preview_email_accounts(settings.email_accounts)


@router.post("/emails/add")
async def add_email_accounts(settings: EmailAccountsSettings, user=Depends(get_current_user)):
    summary = email_manager.add_email_accounts(settings.email_accounts)
    storage.add_audit_event("emails.import", actor_email=user["email"], entity_type="email", detail={k: summary.get(k) for k in ("received", "new", "duplicates", "conflicts", "invalid")})
    return {"status": "added", "import": summary, "statistics": email_manager.get_statistics()}


@router.get("/emails")
async def list_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    query: str = Query("", max_length=254),
    status: str = Query("", max_length=32),
):
    return storage.list_emails_page(page=page, page_size=page_size, query=query, status=status)


@router.get("/emails/stats")
async def get_email_stats():
    return email_manager.get_statistics()


@router.get("/emails/{email_id}/secret")
async def reveal_email_secret(email_id: int, user=Depends(get_current_user)):
    item = storage.get_email_secret(email_id)
    if not item:
        raise HTTPException(404, "Email account not found")
    storage.add_audit_event("emails.secret_revealed", actor_email=user["email"], entity_type="email", entity_id=email_id)
    return item


@router.put("/emails/{email_id}")
async def update_email(email_id: int, payload: EmailUpdate, user=Depends(get_current_user)):
    try:
        item = storage.update_email(email_id, email=payload.email, password=payload.password, status=payload.status)
    except KeyError:
        raise HTTPException(404, "Email account not found")
    except ValueError as exc:
        raise HTTPException(409 if "already" in str(exc).lower() else 400, str(exc))
    email_manager._reload()
    storage.add_audit_event("emails.updated", actor_email=user["email"], entity_type="email", entity_id=email_id, detail={"email_changed": payload.email is not None, "password_changed": payload.password is not None, "status": payload.status})
    item.pop("password", None)
    return {"item": item, "statistics": email_manager.get_statistics()}


@router.delete("/emails/{email_id}")
async def delete_email(email_id: int, user=Depends(get_current_user)):
    deleted = storage.delete_emails([email_id])
    if not deleted:
        raise HTTPException(404, "Email account not found")
    email_manager._reload()
    storage.add_audit_event("emails.deleted", actor_email=user["email"], entity_type="email", entity_id=email_id)
    return {"deleted": deleted, "statistics": email_manager.get_statistics()}


@router.post("/emails/bulk")
async def bulk_email_action(payload: BulkInventoryAction, user=Depends(get_current_user)):
    if not payload.ids:
        raise HTTPException(400, "Select at least one email account")
    if payload.action == "delete":
        changed = storage.delete_emails(payload.ids)
    elif payload.action in {"set_available", "set_used", "set_failed"}:
        changed = storage.bulk_email_status(payload.ids, payload.action.removeprefix("set_"))
    else:
        raise HTTPException(400, "Unsupported bulk action")
    email_manager._reload()
    storage.add_audit_event("emails.bulk", actor_email=user["email"], entity_type="email", detail={"action": payload.action, "selected": len(payload.ids), "changed": changed})
    return {"changed": changed, "statistics": email_manager.get_statistics()}


@router.post("/emails/reset")
async def reset_email_accounts(user=Depends(get_current_user)):
    email_manager.reset()
    storage.add_audit_event("emails.reset", actor_email=user["email"], entity_type="email")
    return {"status": "reset", "statistics": email_manager.get_statistics()}


@router.post("/proxies/add")
async def add_proxies(settings: ProxySettings, user=Depends(get_current_user)):
    summary = proxy_handler.add_proxies(settings.proxy_list, settings.proxy_type)
    stats = proxy_handler.get_statistics()
    storage.add_audit_event("proxies.import", actor_email=user["email"], entity_type="proxy", detail={k: summary.get(k) for k in ("received", "new", "duplicates", "conflicts", "invalid")})
    return {"status": "added", "import": summary, **stats}


@router.get("/proxies")
async def list_proxies(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    query: str = Query("", max_length=254),
    state: str = Query("", max_length=32),
    region: str = Query("", max_length=32),
):
    return storage.list_proxies_page(page=page, page_size=page_size, query=query, state=state, region=region)


@router.get("/proxies/stats")
async def get_proxy_stats():
    return proxy_handler.get_statistics()


@router.get("/proxies/{proxy_id}/secret")
async def reveal_proxy_secret(proxy_id: int, user=Depends(get_current_user)):
    item = storage.get_proxy_secret(proxy_id)
    if not item:
        raise HTTPException(404, "Proxy not found")
    storage.add_audit_event("proxies.secret_revealed", actor_email=user["email"], entity_type="proxy", entity_id=proxy_id)
    return item


@router.put("/proxies/{proxy_id}")
async def update_proxy(proxy_id: int, payload: ProxyUpdate, user=Depends(get_current_user)):
    try:
        item = storage.update_proxy(proxy_id, ip=payload.ip, port=payload.port, username=payload.username, password=payload.password, proxy_type=payload.proxy_type, region=payload.region)
    except KeyError:
        raise HTTPException(404, "Proxy not found")
    except ValueError as exc:
        raise HTTPException(409 if "already" in str(exc).lower() else 400, str(exc))
    proxy_handler._reload()
    storage.add_audit_event("proxies.updated", actor_email=user["email"], entity_type="proxy", entity_id=proxy_id, detail={"password_changed": payload.password is not None})
    item.pop("password", None)
    return {"item": item, "statistics": proxy_handler.get_statistics()}


@router.delete("/proxies/{proxy_id}")
async def delete_proxy(proxy_id: int, user=Depends(get_current_user)):
    deleted = storage.delete_proxies([proxy_id])
    if not deleted:
        raise HTTPException(404, "Proxy not found")
    proxy_handler._reload()
    storage.add_audit_event("proxies.deleted", actor_email=user["email"], entity_type="proxy", entity_id=proxy_id)
    return {"deleted": deleted, "statistics": proxy_handler.get_statistics()}


@router.post("/proxies/bulk")
async def bulk_proxy_action(payload: BulkInventoryAction, user=Depends(get_current_user)):
    if not payload.ids:
        raise HTTPException(400, "Select at least one proxy")
    if payload.action != "delete":
        raise HTTPException(400, "Unsupported bulk action")
    deleted = storage.delete_proxies(payload.ids)
    proxy_handler._reload()
    storage.add_audit_event("proxies.bulk", actor_email=user["email"], entity_type="proxy", detail={"action": payload.action, "selected": len(payload.ids), "changed": deleted})
    return {"changed": deleted, "statistics": proxy_handler.get_statistics()}


@router.post("/proxies/check")
async def check_proxies(user=Depends(get_current_user)):
    await proxy_handler.check_all_proxies(concurrency=10)
    stats = proxy_handler.get_statistics()
    storage.add_audit_event("proxies.health_check", actor_email=user["email"], entity_type="proxy", detail={"total": stats["total"], "working": stats["working"]})
    return {"status": "ok", **stats}
