from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path

from api.config import APP_VERSION
from api.state import DATA_DIR, storage


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(('Version', APP_VERSION == '2.4.0', APP_VERSION))
    checks.append(('Database file', Path(storage.db_file).exists(), str(storage.db_file)))
    try:
        with sqlite3.connect(storage.db_file) as conn:
            result = conn.execute('PRAGMA integrity_check').fetchone()[0]
        checks.append(('SQLite integrity', result == 'ok', result))
    except Exception as exc:
        checks.append(('SQLite integrity', False, str(exc)))
    secret_key = DATA_DIR / '.secret.key'
    checks.append(('Secret key', secret_key.exists(), str(secret_key)))
    frontend_dir = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    frontend = frontend_dir / 'index.html'
    checks.append(('Frontend build', frontend.exists(), str(frontend)))
    if frontend.exists():
        html = frontend.read_text(encoding='utf-8', errors='replace')
        refs = re.findall(r'(?:src|href)=[\"\']([^\"\']+)[\"\']', html)
        local_assets = [x.split('?', 1)[0] for x in refs if x.startswith('/static/')]
        missing_assets = [x for x in local_assets if not (frontend_dir / x.removeprefix('/static/')).exists()]
        checks.append(('Frontend assets', not missing_assets and bool(local_assets), 'ok' if not missing_assets and local_assets else f'missing={missing_assets} refs={local_assets}'))
        app_js = frontend_dir / 'app.js'
        if app_js.exists():
            js = app_js.read_text(encoding='utf-8', errors='replace')
            bad_commonjs = 'Object.defineProperty(exports' in js or 'require("./App.css")' in js or "require('./App.css')" in js
            checks.append(('Browser JS format', not bad_commonjs, 'browser-compatible' if not bad_commonjs else 'CommonJS markers found'))
    for module in ('fastapi', 'uvicorn', 'cryptography'):
        checks.append((f'Dependency {module}', importlib.util.find_spec(module) is not None, module))

    print(f'Riot Creator Control v{APP_VERSION} - local smoke check')
    print('-' * 64)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL':4}  {name:22} {detail}")
    failed = [c for c in checks if not c[1]]
    print('-' * 64)
    print(f'{len(checks) - len(failed)}/{len(checks)} checks passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
