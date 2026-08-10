from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from api.config import APP_VERSION
from api.deps import get_current_user
from api.state import BASE_DIR, DATA_DIR, email_manager, proxy_handler, storage

router = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(get_current_user)])


def _backup_dir() -> Path:
    path = DATA_DIR / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.get("/diagnostics")
async def diagnostics():
    checks = []
    db = storage.diagnostics()
    checks.append({"name": "Database", "ok": db.get("database") == "ok", "detail": db})
    checks.append({"name": "Secret key", "ok": db.get("secret_key") == "ok", "detail": "Encryption key is present" if db.get("secret_key") == "ok" else "Encryption key is missing"})

    frontend_index = BASE_DIR.parent.parent / "frontend" / "dist" / "index.html"
    checks.append({"name": "Frontend build", "ok": frontend_index.exists(), "detail": str(frontend_index)})

    data_writable = os.access(DATA_DIR, os.W_OK)
    checks.append({"name": "Data directory writable", "ok": data_writable, "detail": str(DATA_DIR)})

    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        try:
            browser_path = Path(pw.chromium.executable_path)
            browser_ok = browser_path.exists()
            checks.append({"name": "Chromium runtime", "ok": browser_ok, "detail": str(browser_path)})
        finally:
            await pw.stop()
    except Exception as exc:
        checks.append({"name": "Chromium runtime", "ok": False, "detail": str(exc)})

    provider = storage.load_captcha_settings()
    checks.append({"name": "Provider configured", "ok": bool(provider.get("configured")), "detail": provider.get("service") if provider.get("configured") else "No saved provider key"})
    emails = email_manager.get_statistics()
    checks.append({"name": "Email inventory", "ok": emails.get("available", 0) > 0, "detail": emails})
    proxies = proxy_handler.get_statistics()
    checks.append({"name": "Proxy inventory", "ok": True, "detail": proxies})

    required_routes = {
        "/api/bootstrap", "/api/settings", "/api/provider/config",
        "/api/emails/add", "/api/proxies/add", "/api/results",
        "/api/creation/start", "/api/creation/stop",
    }
    try:
        from api.main import app
        present = {getattr(route, "path", "") for route in app.routes}
        missing = sorted(required_routes - present)
        checks.append({"name": "API route map", "ok": not missing, "detail": {"missing": missing, "required": len(required_routes)}})
    except Exception as exc:
        checks.append({"name": "API route map", "ok": False, "detail": str(exc)})

    log_file = DATA_DIR / "logs" / "app.log"
    checks.append({"name": "Runtime log", "ok": log_file.parent.exists(), "detail": str(log_file)})

    passed = sum(1 for item in checks if item["ok"])
    return {
        "status": "ok" if passed == len(checks) else "attention",
        "version": APP_VERSION,
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "recent_jobs": storage.list_jobs(limit=5),
    }


@router.get("/runtime")
async def runtime_info():
    from api.main import app
    return {
        "version": APP_VERSION,
        "data_dir": str(DATA_DIR),
        "frontend_dir": str(BASE_DIR.parent.parent / "frontend" / "dist"),
        "routes": sorted({getattr(route, "path", "") for route in app.routes if getattr(route, "path", "").startswith("/api/")}),
        "effective_port": os.getenv("RC_EFFECTIVE_PORT", os.getenv("RC_PORT", "8000")),
    }


@router.get("/logs/recent")
async def recent_logs(lines: int = 120):
    lines = max(10, min(int(lines), 500))
    path = DATA_DIR / "logs" / "app.log"
    if not path.exists():
        return {"lines": [], "path": str(path)}
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise HTTPException(500, f"Could not read runtime log: {exc}")
    return {"lines": content[-lines:], "path": str(path)}


@router.get("/backups")
async def list_backups():
    files = []
    for path in sorted(_backup_dir().glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        stat = path.stat()
        files.append({"name": path.name, "size_bytes": stat.st_size, "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()})
    return {"backups": files}


@router.post("/backups/create")
async def create_backup(user=Depends(get_current_user)):
    name = f"riot_creator_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    path = _backup_dir() / name
    info = storage.create_backup(str(path))
    storage.add_audit_event("backup.created", actor_email=user["email"], entity_type="backup", entity_id=name, detail={"size_bytes": info["size_bytes"]})
    return {"backup": {"name": name, **info}}


@router.get("/backups/{name}")
async def download_backup(name: str, user=Depends(get_current_user)):
    safe = Path(name).name
    if safe != name or not safe.endswith(".zip"):
        raise HTTPException(400, "Invalid backup name")
    path = _backup_dir() / safe
    if not path.exists():
        raise HTTPException(404, "Backup not found")
    storage.add_audit_event("backup.downloaded", actor_email=user["email"], entity_type="backup", entity_id=safe)
    return FileResponse(path, filename=safe, media_type="application/zip")


@router.post("/backups/restore")
async def restore_backup(file: UploadFile = File(...), user=Depends(get_current_user)):
    filename = Path(file.filename or "backup.zip").name
    if not filename.lower().endswith(".zip"):
        raise HTTPException(400, "Upload a .zip backup")
    data = await file.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(413, "Backup is too large")
    tmp_path = Path(tempfile.gettempdir()) / f"rc_restore_{os.getpid()}_{datetime.now().timestamp()}.zip"
    tmp_path.write_bytes(data)
    try:
        result = storage.stage_restore_backup(str(tmp_path))
        storage.add_audit_event("backup.restore_staged", actor_email=user["email"], entity_type="backup", entity_id=filename)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)
