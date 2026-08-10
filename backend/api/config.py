from __future__ import annotations

import os

APP_VERSION = "2.4.0"
SESSION_COOKIE_NAME = "rc_session"
SESSION_DAYS = int(os.getenv("RC_SESSION_DAYS", "7"))
SECURE_COOKIES = os.getenv("RC_SECURE_COOKIES", "0") == "1"

# Owner credentials are only needed when the local database has no users yet.
# Keep them outside source control and provide them as environment variables.
BOOTSTRAP_OWNER_EMAIL = os.getenv("RC_OWNER_EMAIL", "").strip()
BOOTSTRAP_OWNER_PASSWORD = os.getenv("RC_OWNER_PASSWORD", "")
