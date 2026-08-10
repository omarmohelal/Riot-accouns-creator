"""Riot Creator Control local owner dashboard.

v2.4 focuses on runtime stability: stale-server detection, structured errors,
request tracing, flexible localhost ports, SPA fallback, and no-white-screen
frontend recovery. Existing persistent data remains compatible with v2.2.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import APP_VERSION, BOOTSTRAP_OWNER_EMAIL, BOOTSTRAP_OWNER_PASSWORD
from api.routes import auth, creation, inventory, system, workspace
from api.security import hash_password
from api.state import BASE_DIR, DATA_DIR, storage

if BOOTSTRAP_OWNER_EMAIL and BOOTSTRAP_OWNER_PASSWORD:
    storage.ensure_owner(BOOTSTRAP_OWNER_EMAIL, hash_password(BOOTSTRAP_OWNER_PASSWORD))
elif not storage.has_users():
    raise RuntimeError(
        "First run requires RC_OWNER_EMAIL and RC_OWNER_PASSWORD. "
        "Set them in your shell, start the app once, then they can be removed."
    )

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"
logger = logging.getLogger("riot_creator")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

app = FastAPI(title="Riot Creator Control API", version=APP_VERSION, docs_url=None, redoc_url=None)

# Same-origin requests on a dynamically selected localhost port do not need CORS,
# but these explicit origins keep local Vite development convenient.
allowed_origins = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]
allowed_origins.extend([x.strip() for x in os.getenv("RC_ALLOWED_ORIGINS", "").split(",") if x.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)


def _trusted_mutation_origin(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").casefold()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return True
    configured = {urlparse(x).netloc.casefold() for x in allowed_origins}
    return parsed.netloc.casefold() in configured


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
        if not _trusted_mutation_origin(request.headers.get("origin")):
            return JSONResponse(
                status_code=403,
                content={"error": {"message": "Untrusted request origin", "request_id": request_id}},
                headers={"X-Request-ID": request_id, "X-RC-Version": APP_VERSION},
            )
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request error request_id=%s method=%s path=%s", request_id, request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "request_id": request_id}},
            headers={"X-Request-ID": request_id, "X-RC-Version": APP_VERSION},
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-RC-Version"] = APP_VERSION
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws: wss:; base-uri 'self'; frame-ancestors 'none'"
    return response


def _api_error(detail: Any, request_id: str | None = None) -> Dict[str, Any]:
    if isinstance(detail, str):
        payload: Dict[str, Any] = {"message": detail}
    else:
        payload = {"message": "Request failed", "details": detail}
    if request_id:
        payload["request_id"] = request_id
    return {"error": payload}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    fields = []
    for err in exc.errors():
        location = ".".join(str(x) for x in err.get("loc", []) if x != "body") or "request"
        fields.append({"field": location, "message": err.get("msg", "Invalid value")})
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=422, content={"error": {"message": "Invalid request", "fields": fields, "request_id": request_id}})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=_api_error(exc.detail, getattr(request.state, "request_id", None)))


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Keep API 404s machine-readable; non-API routes are handled by the SPA fallback below.
    if request.url.path.startswith("/api/") or request.url.path == "/ws":
        return JSONResponse(status_code=exc.status_code, content=_api_error(exc.detail, getattr(request.state, "request_id", None)))
    return JSONResponse(status_code=exc.status_code, content=_api_error(exc.detail, getattr(request.state, "request_id", None)))


app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(workspace.router)
app.include_router(system.router)
app.include_router(creation.router)
app.websocket("/ws")(creation.websocket_endpoint)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "app": "riot-creator-control",
        "data_backend": "sqlite",
    }


@app.get("/api/version")
async def api_version():
    return {"version": APP_VERSION, "app": "riot-creator-control"}


frontend_path = BASE_DIR.parent.parent / "frontend" / "dist"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


def _index_response():
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path, headers={"Cache-Control": "no-store, max-age=0"})
    return JSONResponse({"status": "ok", "message": f"Riot Creator Control API v{APP_VERSION}", "health": "/health"})


@app.get("/")
async def root():
    return _index_response()


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    # Prevent blank/404 pages if the browser restores a client-side path.
    if full_path.startswith("api/") or full_path.startswith("static/") or full_path == "ws":
        raise HTTPException(status_code=404, detail="Not Found")
    return _index_response()


logger.info("Application loaded version=%s data_dir=%s frontend=%s", APP_VERSION, DATA_DIR, frontend_path)

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("RC_HOST", "127.0.0.1")
    port = int(os.getenv("RC_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
