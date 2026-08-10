from __future__ import annotations

import csv
import io
import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.config import APP_VERSION
from api.deps import get_current_user
from api.state import DEFAULT_APP_SETTINGS, current_status, email_manager, proxy_handler, storage

router = APIRouter(prefix="/api", tags=["workspace"], dependencies=[Depends(get_current_user)])


class CaptchaSettings(BaseModel):
    service: Literal["capsolver", "2captcha", "anticaptcha"] = "capsolver"
    api_key: Optional[str] = Field(default=None, max_length=1024)


class AppSettings(BaseModel):
    count: int = Field(default=20, ge=1, le=1000)
    username_min: int = Field(default=6, ge=3, le=32)
    username_max: int = Field(default=12, ge=3, le=32)
    password_length: int = Field(default=12, ge=8, le=128)
    use_fixed_password: bool = False
    password_fixed: str = Field(default="", max_length=256)
    concurrency: int = Field(default=3, ge=1, le=20)
    use_proxies: bool = False
    target_region: str = Field(default="", max_length=32)


class ProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    settings: AppSettings


class BulkResultAction(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=5000)
    action: str


def validate_settings(settings: AppSettings) -> dict:
    if settings.username_min > settings.username_max:
        raise HTTPException(400, "Username minimum cannot be greater than maximum")
    if settings.use_fixed_password and settings.password_fixed and len(settings.password_fixed) < 8:
        raise HTTPException(400, "Fixed password must be at least 8 characters")
    return settings.model_dump()


def public_settings() -> dict:
    saved = {**DEFAULT_APP_SETTINGS, **(storage.load_setting("app_settings", {}) or {})}
    saved["password_fixed"] = ""
    saved["fixed_password_configured"] = bool(storage.load_secret("account_fixed_password", ""))
    return saved


def persist_settings(settings: AppSettings) -> dict:
    payload = validate_settings(settings)
    incoming_fixed = payload.pop("password_fixed", "")
    if payload.get("use_fixed_password"):
        if incoming_fixed:
            storage.save_secret("account_fixed_password", incoming_fixed)
        elif not storage.load_secret("account_fixed_password", ""):
            raise HTTPException(400, "Enter a fixed password once before enabling fixed-password mode")
    payload["password_fixed"] = ""
    storage.save_setting("app_settings", payload)
    return public_settings()


@router.get("/bootstrap")
async def bootstrap(user=Depends(get_current_user)):
    app_settings = public_settings()
    provider = storage.load_captcha_settings()
    proxy_stats = proxy_handler.get_statistics()
    return {
        "version": APP_VERSION,
        "user": {"email": user["email"], "role": user["role"]},
        "settings": app_settings,
        "provider": {"service": provider.get("service", "capsolver"), "configured": bool(provider.get("configured")), "masked": provider.get("masked", "")},
        "email_stats": email_manager.get_statistics(),
        "proxy_stats": proxy_stats,
        "available_regions": proxy_stats.get("by_region", {}),
        "creation": current_status(include_results=False),
        "profiles": storage.list_profiles(),
        "jobs": storage.list_jobs(limit=10),
    }


@router.get("/settings")
async def get_settings():
    return public_settings()


@router.put("/settings")
async def save_settings(settings: AppSettings, user=Depends(get_current_user)):
    public = persist_settings(settings)
    storage.add_audit_event("settings.saved", actor_email=user["email"], entity_type="settings", detail={k: v for k, v in public.items() if k not in {"password_fixed", "fixed_password_configured"}})
    return {"status": "saved", "settings": public}


@router.get("/provider/config")
async def get_provider_config():
    provider = storage.load_captcha_settings()
    return {"service": provider.get("service", "capsolver"), "configured": bool(provider.get("configured")), "masked": provider.get("masked", "")}


@router.put("/provider/config")
async def save_provider_config(settings: CaptchaSettings, user=Depends(get_current_user)):
    existing = storage.load_captcha_settings()
    api_key = (settings.api_key or "").strip()
    existing_key = (existing.get("api_key") or "").strip()
    existing_service = existing.get("service") or "capsolver"
    if not api_key and not existing_key:
        raise HTTPException(400, "API key is required for first-time provider configuration")
    if settings.service != existing_service and not api_key:
        raise HTTPException(400, "Enter the API key when changing provider service")
    storage.save_captcha_settings({"service": settings.service, "api_key": api_key or existing_key})
    saved = storage.load_captcha_settings()
    storage.add_audit_event("provider.saved", actor_email=user["email"], entity_type="provider", detail={"service": saved.get("service"), "key_replaced": bool(api_key)})
    return {"status": "saved", "service": saved.get("service"), "configured": bool(saved.get("configured")), "masked": saved.get("masked", "")}


@router.post("/captcha/balance")
async def check_captcha_balance(settings: Optional[CaptchaSettings] = None):
    from api.services.captcha_solver import CaptchaSolver
    stored = storage.load_captcha_settings()
    service = (settings.service if settings else None) or stored.get("service") or "capsolver"
    api_key = ((settings.api_key if settings else None) or stored.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(400, "Provider API key is not configured")
    solver = CaptchaSolver(service, api_key)
    try:
        balance = await solver.get_balance()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    return {"service": service, "balance": balance, "status": "ok" if balance > 0 else "low_balance"}


@router.get("/profiles")
async def list_profiles():
    return {"profiles": storage.list_profiles()}


@router.post("/profiles")
async def save_profile(payload: ProfileRequest, user=Depends(get_current_user)):
    settings = validate_settings(payload.settings)
    incoming_fixed = settings.pop("password_fixed", "")
    if settings.get("use_fixed_password"):
        if incoming_fixed:
            storage.save_secret("account_fixed_password", incoming_fixed)
        elif not storage.load_secret("account_fixed_password", ""):
            raise HTTPException(400, "Enter a fixed password once before saving this profile")
    settings["password_fixed"] = ""
    try:
        profile = storage.save_profile(payload.name, settings)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    storage.add_audit_event("profiles.saved", actor_email=user["email"], entity_type="profile", entity_id=profile["id"], detail={"name": profile["name"]})
    return {"profile": profile, "profiles": storage.list_profiles()}


@router.post("/profiles/{profile_id}/apply")
async def apply_profile(profile_id: int, user=Depends(get_current_user)):
    profile = next((x for x in storage.list_profiles() if x["id"] == profile_id), None)
    if not profile:
        raise HTTPException(404, "Profile not found")
    settings = {**DEFAULT_APP_SETTINGS, **profile.get("settings", {})}
    validated = validate_settings(AppSettings(**settings))
    if validated.get("use_fixed_password") and not storage.load_secret("account_fixed_password", ""):
        raise HTTPException(400, "This profile needs a saved fixed password. Enter it once in Settings first.")
    validated["password_fixed"] = ""
    storage.save_setting("app_settings", validated)
    storage.add_audit_event("profiles.applied", actor_email=user["email"], entity_type="profile", entity_id=profile_id, detail={"name": profile["name"]})
    return {"settings": public_settings(), "profile": profile}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: int, user=Depends(get_current_user)):
    if not storage.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    storage.add_audit_event("profiles.deleted", actor_email=user["email"], entity_type="profile", entity_id=profile_id)
    return {"profiles": storage.list_profiles()}


@router.get("/results")
async def get_results(
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    query: str = Query("", max_length=254), status: str = Query("", max_length=32),
    region: str = Query("", max_length=32), job_id: str = Query("", max_length=64),
):
    return storage.list_results_page(page=page, page_size=page_size, query=query, status=status, region=region, job_id=job_id)


@router.get("/results/{result_id}/secret")
async def reveal_result_secret(result_id: int, user=Depends(get_current_user)):
    item = storage.get_result_secret(result_id)
    if not item:
        raise HTTPException(404, "Result not found")
    storage.add_audit_event("results.secret_revealed", actor_email=user["email"], entity_type="result", entity_id=result_id)
    return item


@router.post("/results/bulk")
async def bulk_result_action(payload: BulkResultAction, user=Depends(get_current_user)):
    if not payload.ids:
        raise HTTPException(400, "Select at least one result")
    if payload.action != "delete":
        raise HTTPException(400, "Unsupported bulk action")
    changed = storage.delete_results(payload.ids)
    storage.add_audit_event("results.bulk", actor_email=user["email"], entity_type="result", detail={"action": payload.action, "selected": len(payload.ids), "changed": changed})
    return {"changed": changed}


@router.get("/results/export")
async def export_results(format: str = Query("txt", pattern="^(txt|csv|json)$"), user=Depends(get_current_user)):
    successful = [r for r in storage.list_results(limit=5000, include_secrets=True) if r.get("status") == "SUCCESS"]
    successful.reverse()
    if format == "json":
        data = json.dumps(successful, ensure_ascii=False, indent=2, default=str)
        mime = "application/json"
    elif format == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["username", "password", "email", "email_password", "region", "created_at", "job_id"])
        for account in successful:
            writer.writerow([account.get("username"), account.get("password"), account.get("email"), account.get("email_password"), account.get("region"), account.get("created_at"), account.get("job_id")])
        data = out.getvalue(); mime = "text/csv"
    else:
        lines=[]
        for account in successful:
            lines += [f"{account.get('username') or ''}:{account.get('password') or ''}", f"{account.get('email') or ''}:{account.get('email_password') or ''}", ""]
        data = "\n".join(lines); mime = "text/plain"
    storage.add_audit_event("results.exported", actor_email=user["email"], entity_type="result", detail={"format": format, "count": len(successful)})
    return {"count": len(successful), "format": format, "mime": mime, "data": data}


# Backwards-compatible path used by v2.1 UI.
@router.get("/creation/export")
async def export_accounts_compat(user=Depends(get_current_user)):
    return await export_results("txt", user)


@router.get("/jobs")
async def get_jobs(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=200), status: str = Query("", max_length=32), limit: Optional[int] = None):
    if limit is not None:
        page_size = max(1, min(int(limit), 200))
        page = 1
    data = storage.list_jobs_page(page=page, page_size=page_size, status=status)
    # compatibility with old `jobs` property while exposing pagination.
    return {**data, "jobs": data["items"]}


@router.get("/jobs/{job_id}")
async def get_job_detail(job_id: str):
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "job": job,
        "events": storage.list_job_events(job_id, limit=300),
        "results": storage.list_results_page(page=1, page_size=200, job_id=job_id)["items"],
    }


@router.get("/audit")
async def get_audit(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), query: str = Query("", max_length=254)):
    return storage.list_audit_events(page=page, page_size=page_size, query=query)
