from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from api import state
from api.deps import get_current_user, websocket_user
from api.services.riot_creator import RiotAccountCreator

router = APIRouter(prefix="/api/creation", tags=["creation"], dependencies=[Depends(get_current_user)])


class CaptchaSettings(BaseModel):
    service: Literal["capsolver", "2captcha", "anticaptcha"] = "capsolver"
    api_key: Optional[str] = None


class CreationRequest(BaseModel):
    count: int = Field(ge=1, le=1000)
    captcha_settings: Optional[CaptchaSettings] = None
    use_proxies: bool = False
    concurrency: int = Field(default=3, ge=1, le=20)
    target_region: Optional[str] = Field(default=None, max_length=32)


@router.post("/start")
async def start_creation(request: CreationRequest, user=Depends(get_current_user)):
    if state.active_creation:
        raise HTTPException(409, "A creation job is already in progress")

    stored_provider = state.storage.load_captcha_settings()
    request_provider = request.captcha_settings or CaptchaSettings(service=stored_provider.get("service", "capsolver"))
    service = request_provider.service or stored_provider.get("service") or "capsolver"
    api_key = (request_provider.api_key or stored_provider.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(400, "Provider API key is required. Save it once in Provider settings.")

    email_stats = state.email_manager.get_statistics()
    if email_stats["available"] < request.count:
        raise HTTPException(400, f"Not enough available emails: need {request.count}, have {email_stats['available']}")

    if request.use_proxies:
        proxy_stats = state.proxy_handler.get_statistics()
        if proxy_stats["working"] == 0:
            raise HTTPException(400, "No healthy saved proxies are available")
        if request.target_region and not state.proxy_handler.get_proxies_by_region(request.target_region):
            raise HTTPException(400, f"No healthy proxy is available for region {request.target_region}")

    saved = {**state.DEFAULT_APP_SETTINGS, **(state.storage.load_setting("app_settings", {}) or {})}
    fixed_password = state.storage.load_secret("account_fixed_password", "") if saved.get("use_fixed_password") else None
    if saved.get("use_fixed_password") and not fixed_password:
        raise HTTPException(400, "Fixed password mode is enabled but no saved fixed password exists")

    state.active_creation = True
    state.active_job_id = uuid.uuid4().hex[:12]
    state.creation_results = []
    state.storage.create_job(state.active_job_id, request.count, request.concurrency, request.use_proxies, request.target_region)
    state.storage.add_job_event(state.active_job_id, "job.started", "Job started", {"count": request.count, "concurrency": request.concurrency, "use_proxies": request.use_proxies, "target_region": request.target_region})
    state.storage.add_audit_event("jobs.started", actor_email=user["email"], entity_type="job", entity_id=state.active_job_id, detail={"count": request.count, "concurrency": request.concurrency, "use_proxies": request.use_proxies, "target_region": request.target_region})
    state.riot_creator = RiotAccountCreator(
        captcha_service=service,
        captcha_api_key=api_key,
        username_min=saved["username_min"],
        username_max=saved["username_max"],
        password_length=saved["password_length"],
        fixed_password=fixed_password,
    )
    state.creation_task = asyncio.create_task(create_accounts_task(request, state.active_job_id))
    return {"status": "started", "job_id": state.active_job_id, "count": request.count, "concurrency": request.concurrency, "use_proxies": request.use_proxies, "target_region": request.target_region}


@router.post("/stop")
async def stop_creation(user=Depends(get_current_user)):
    state.active_creation = False
    job_id = state.active_job_id
    if job_id:
        state.storage.update_job(job_id, status="stopping", message="Stop requested by owner")
        state.storage.add_job_event(job_id, "job.stop_requested", "Stop requested by owner")
        state.storage.add_audit_event("jobs.stop_requested", actor_email=user["email"], entity_type="job", entity_id=job_id)
    if state.creation_task and not state.creation_task.done():
        state.creation_task.cancel()
        try:
            await state.creation_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    state.creation_task = None
    await state.broadcast_update({"type": "creation_stopped", "message": "Stopped by owner", **state.current_status(False)})
    return {"status": "stopped"}


@router.get("/status")
async def get_creation_status():
    return state.current_status(include_results=False)


async def create_accounts_task(request: CreationRequest, job_id: str):
    semaphore = asyncio.Semaphore(request.concurrency)
    cancelled = False

    async def create_single(index: int):
        email_acc: Optional[Dict[str, Any]] = None
        async with semaphore:
            if not state.active_creation:
                return
            email_acc = state.email_manager.get_next_available()
            if not email_acc:
                return
            proxy = None
            if request.use_proxies:
                proxy = state.proxy_handler.get_random_proxy(request.target_region or None)
                if not proxy:
                    state.email_manager.release(email_acc["email"])
                    return

            async def progress(status_text: str, message: str):
                await state.broadcast_update({"type": "progress", "job_id": job_id, "index": index, "status": status_text, "message": message})

            try:
                result = await state.riot_creator.create_account(
                    email=email_acc["email"], email_password=email_acc["password"], proxy=proxy, progress_callback=progress,
                )
                result = dict(result or {})
                result.setdefault("email", email_acc["email"])
                result.setdefault("email_password", email_acc["password"])
                result["job_id"] = job_id
                if result.get("status") == "SUCCESS":
                    state.email_manager.mark_used(email_acc["email"])
                else:
                    state.email_manager.release(email_acc["email"])
                history_id = state.storage.append_result(result)
                result["history_id"] = history_id
                state.creation_results.append(result)
                snapshot = state.current_status(include_results=False)
                state.storage.update_job(job_id, success_count=snapshot["success"], failed_count=snapshot["failed"])
                state.storage.add_job_event(job_id, "account.completed", f"Account {index + 1} finished", {"status": result.get("status"), "history_id": history_id, "region": result.get("region")})
                await state.broadcast_update({
                    "type": "account_created", "job_id": job_id, "index": index + 1, "total_requested": request.count,
                    "status": result.get("status"), "history_id": history_id, "email_accounts": state.email_manager.get_statistics(),
                    **state.current_status(include_results=False),
                })
            except asyncio.CancelledError:
                if email_acc:
                    state.email_manager.release(email_acc["email"])
                raise
            except Exception as exc:
                if email_acc:
                    state.email_manager.release(email_acc["email"])
                result = {"status": "FAILED", "error": type(exc).__name__, "message": str(exc), "email": email_acc.get("email") if email_acc else None, "job_id": job_id}
                history_id = state.storage.append_result(result)
                result["history_id"] = history_id
                state.creation_results.append(result)
                snapshot = state.current_status(include_results=False)
                state.storage.update_job(job_id, success_count=snapshot["success"], failed_count=snapshot["failed"])
                state.storage.add_job_event(job_id, "account.failed", f"Account {index + 1} failed", {"history_id": history_id, "error": type(exc).__name__})
                await state.broadcast_update({
                    "type": "account_created", "job_id": job_id, "index": index + 1, "total_requested": request.count,
                    "status": "FAILED", "history_id": history_id, "email_accounts": state.email_manager.get_statistics(),
                    **state.current_status(include_results=False),
                })

    try:
        tasks = [asyncio.create_task(create_single(i)) for i in range(request.count)]
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        state.active_creation = False
        snapshot = state.current_status(include_results=False)
        final_status = "stopped" if cancelled else "completed"
        state.storage.update_job(job_id, status=final_status, success_count=snapshot["success"], failed_count=snapshot["failed"], message=("Stopped by owner" if cancelled else "Job finished"), finished=True)
        state.storage.add_job_event(job_id, f"job.{final_status}", "Job stopped" if cancelled else "Job completed", {"success": snapshot["success"], "failed": snapshot["failed"]})
        if state.active_job_id == job_id:
            state.active_job_id = None
        state.creation_task = None
        await state.broadcast_update({"type": "creation_complete", "job_id": job_id, **state.current_status(include_results=False), "email_accounts": state.email_manager.get_statistics()})


async def websocket_endpoint(websocket: WebSocket):
    user = await websocket_user(websocket)
    if not user:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    state.connected_websockets.append(websocket)
    try:
        await websocket.send_json({"type": "status_update", **state.current_status(include_results=False), "email_accounts": state.email_manager.get_statistics()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in state.connected_websockets:
            state.connected_websockets.remove(websocket)
