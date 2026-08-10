from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.services.email_manager import EmailAccountManager
from api.services.persistent_storage import PersistentStorage, apply_pending_restore
from api.services.proxy_handler import ProxyHandler
from api.services.riot_creator import RiotAccountCreator

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("RIOT_CREATOR_DATA_DIR", str(BASE_DIR.parent / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
restore_applied = apply_pending_restore(str(DATA_DIR))

storage = PersistentStorage(data_dir=str(DATA_DIR))
if restore_applied:
    storage.clear_sessions()
storage.recover_interrupted_jobs()
proxy_handler = ProxyHandler(storage=storage)
email_manager = EmailAccountManager(storage=storage)

active_creation = False
active_job_id: Optional[str] = None
creation_results: List[Dict[str, Any]] = []
connected_websockets: List[Any] = []
creation_task: Optional[asyncio.Task] = None
riot_creator: Optional[RiotAccountCreator] = None

DEFAULT_APP_SETTINGS = {
    "count": 20,
    "username_min": 6,
    "username_max": 12,
    "password_length": 12,
    "use_fixed_password": False,
    "password_fixed": "",
    "concurrency": 3,
    "use_proxies": False,
    "target_region": "",
}


def current_status(include_results: bool = True) -> Dict[str, Any]:
    success = sum(1 for r in creation_results if r.get("status") == "SUCCESS")
    failed = sum(1 for r in creation_results if r.get("status") == "FAILED")
    pending = sum(1 for r in creation_results if r.get("status") == "PENDING")
    by_region: Dict[str, int] = {}
    for result in creation_results:
        if result.get("status") == "SUCCESS":
            region = result.get("region") or "UNKNOWN"
            by_region[region] = by_region.get(region, 0) + 1
    payload: Dict[str, Any] = {
        "active": active_creation,
        "job_id": active_job_id,
        "total": len(creation_results),
        "success": success,
        "failed": failed,
        "pending": pending,
        "by_region": by_region,
    }
    if include_results:
        payload["results"] = creation_results
    return payload


async def broadcast_update(data: Dict[str, Any]) -> None:
    dead = []
    for ws in list(connected_websockets):
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in connected_websockets:
            connected_websockets.remove(ws)


def refresh_managers() -> None:
    """Refresh cached service views after restore or bulk mutation."""
    email_manager._reload()
    proxy_handler._reload()
