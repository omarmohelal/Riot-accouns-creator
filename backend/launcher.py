from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from api.config import APP_VERSION  # noqa: E402
from api.main import app  # noqa: E402


def _port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            return sock.connect_ex((host, port)) != 0
    except OSError:
        return False


def _probe(port: int) -> dict | None:
    for host in ('127.0.0.1', 'localhost'):
        try:
            with urllib.request.urlopen(f'http://{host}:{port}/health', timeout=0.7) as response:
                body = response.read().decode('utf-8', 'replace')
                payload = json.loads(body)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
    return None


def _choose_port(preferred: int) -> tuple[int, str]:
    if _port_free('127.0.0.1', preferred):
        return preferred, 'free'
    running = _probe(preferred)
    if running and running.get('version') == APP_VERSION:
        ready, _detail = _frontend_ready(f'http://127.0.0.1:{preferred}/')
        if ready:
            return preferred, 'already-current'
    for port in range(preferred + 1, preferred + 21):
        if _port_free('127.0.0.1', port):
            return port, 'fallback'
    raise RuntimeError(f'No free local port found in {preferred}-{preferred + 20}')


def _frontend_ready(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            html = response.read().decode('utf-8', 'replace')
            if response.status != 200:
                return False, f'index returned HTTP {response.status}'
        assets = re.findall(r'(?:src|href)=[\"\']([^\"\']+)[\"\']', html)
        required = [asset for asset in assets if asset.startswith('/static/') and asset.split('?', 1)[0].endswith(('.js', '.css'))]
        if not required:
            return False, 'index has no browser JS/CSS assets'
        for asset in required:
            with urllib.request.urlopen(url.rstrip('/') + asset, timeout=2.0) as response:
                body = response.read(8192)
                if response.status != 200 or not body:
                    return False, f'asset failed: {asset} HTTP {response.status}'
                clean_asset = asset.split('?', 1)[0]
                if clean_asset.endswith('/app.js'):
                    head = body.decode('utf-8', 'replace')
                    if 'Object.defineProperty(exports' in head or 'require(\"./App.css\")' in head:
                        return False, 'app.js is CommonJS, not a browser bundle'
                    if APP_VERSION not in head:
                        return False, f'app.js version marker does not contain {APP_VERSION}'
        return True, f'{len(required)} frontend assets verified'
    except Exception as exc:
        return False, str(exc)


def _open_browser(url: str) -> None:
    def worker():
        last_error = 'server not ready'
        for _ in range(60):
            try:
                with urllib.request.urlopen(url + 'health', timeout=0.7) as response:
                    if response.status == 200:
                        ready, detail = _frontend_ready(url)
                        if ready:
                            print(f'[PASS] Frontend boot assets: {detail}')
                            webbrowser.open(url)
                            return
                        last_error = detail
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.25)
        print(f'[ERROR] Frontend readiness check failed: {last_error}')
        print(f'[INFO] Open {url}health to confirm the backend is running.')
    threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    preferred = int(os.getenv('RC_PORT', '8000'))
    port, mode = _choose_port(preferred)
    url = f'http://127.0.0.1:{port}/'
    current_url_file = BASE_DIR.parent / 'CURRENT_URL.txt'
    try:
        current_url_file.write_text(url + '\n', encoding='utf-8')
    except OSError:
        pass

    print('=' * 56)
    print(f'  Riot Creator Control v{APP_VERSION}')
    print('=' * 56)
    if mode == 'already-current':
        print(f'[INFO] v{APP_VERSION} is already running at {url}')
        webbrowser.open(url)
        return 0
    if mode == 'fallback':
        old = _probe(preferred)
        old_version = old.get('version') if old else 'unknown application'
        print(f'[WARN] Port {preferred} is already in use by {old_version}.')
        if old and old.get('version') == APP_VERSION:
            print("[WARN] The existing process did not pass this build's frontend asset check.")
        print(f'[INFO] Starting this build safely on port {port} instead.')
        print('[INFO] This prevents old/stale Riot Creator servers from causing 404 Not Found errors.')
    else:
        print(f'[INFO] Starting on {url}')
    print(f'[INFO] Current URL saved to: {current_url_file}')

    os.environ['RC_EFFECTIVE_PORT'] = str(port)
    _open_browser(url)
    uvicorn.run(app, host=os.getenv('RC_HOST', '127.0.0.1'), port=port, log_level=os.getenv('RC_LOG_LEVEL', 'info'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
