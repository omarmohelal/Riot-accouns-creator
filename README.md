# Riot Creator Control

A local control panel for managing Riot account-creation workflows from one place. The project uses a FastAPI backend, a React/Vite frontend, SQLite for local state, and Playwright for browser automation.

> This is an independent project and is not affiliated with, endorsed by, or sponsored by Riot Games.

## What is included

- Local owner dashboard with session-based authentication
- Email inventory and account history
- Proxy inventory, health checks, and region metadata
- Captcha provider settings stored locally
- Job history, live progress, and WebSocket updates
- Encrypted local secret fields using Fernet
- Backup/restore and migration support for previous local data
- Windows and Linux/macOS startup helpers

## Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn, SQLite
- **Automation:** Playwright
- **Frontend:** React 18, Vite, Tailwind CSS
- **Storage:** local SQLite database with encrypted secret fields

## Quick start

### Windows

Requirements: Python 3.11 or 3.12, Node.js 18+.

```bat
SETUP.bat
```

For the first run, create the local owner account from environment variables:

```bat
set RC_OWNER_EMAIL=you@example.com
set RC_OWNER_PASSWORD=choose-a-strong-password
START.bat
```

Once the owner is stored in `backend/data/app.db`, those two environment variables are no longer required for later starts.

### Linux / macOS

```bash
export RC_OWNER_EMAIL="you@example.com"
export RC_OWNER_PASSWORD="choose-a-strong-password"
./start.sh
```

The local dashboard opens on `http://127.0.0.1:8000` by default. If that port is already occupied, the launcher looks for the next available local port.

## Development

Backend:

```bash
python -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
backend/.venv/bin/python -m playwright install chromium
cd backend
.venv/bin/python -m uvicorn api.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Vite proxies API and WebSocket requests to the local backend during development.

## Project layout

```text
backend/
  api/
    routes/       HTTP and WebSocket endpoints
    services/     storage, email, proxy and automation services
  launcher.py     local launcher and port selection
  requirements.txt
frontend/
  public/
  src/
  package.json
SETUP.bat          Windows setup
START.bat          Windows launcher
start.sh           Linux/macOS launcher
```

Runtime databases, encryption keys, logs, virtual environments, frontend build output, test files, and local scratch data are intentionally excluded from Git.

## Security notes

- Do not commit `backend/data/`, `.secret.key`, `.env` files, API keys, email lists, proxies, or exported databases.
- Use a strong owner password and keep the dashboard bound to localhost unless you have added your own trusted reverse-proxy/authentication layer.
- Review the terms and policies of any third-party service before using automation against it.

## Credits

Created and maintained by **Omar Mohamed Helal**.

Discord: **nex0or**  
GitHub: **[@omarmohelal](https://github.com/omarmohelal)**

## License

MIT. See [LICENSE](LICENSE).
