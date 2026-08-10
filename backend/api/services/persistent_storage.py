"""SQLite-backed persistent storage for the local control panel.

The original project stored mutable state in several JSON files.  That made
refresh/restart behaviour fragile and offered no uniqueness guarantees.  This
module keeps the public storage interface small while moving state to a single
SQLite database with transactions, indexes and encrypted secret fields.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from cryptography.fernet import Fernet, InvalidToken


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_pending_restore(data_dir: str) -> Optional[Dict[str, Any]]:
    """Apply a validated staged restore before any SQLite connection is opened."""
    root = Path(data_dir).resolve()
    pending = root / ".pending_restore.zip"
    if not pending.exists():
        return None
    temp_dir = root / ".pending_restore_extract"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(pending, "r") as zf:
            names = set(zf.namelist())
            if "app.db" not in names or ".secret.key" not in names:
                raise ValueError("Pending restore archive is incomplete")
            (temp_dir / "app.db").write_bytes(zf.read("app.db"))
            (temp_dir / ".secret.key").write_bytes(zf.read(".secret.key"))
        with sqlite3.connect(temp_dir / "app.db") as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"Pending restore failed integrity check: {integrity}")
        root.mkdir(parents=True, exist_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(root / "app.db") + suffix).unlink(missing_ok=True)
        os.replace(temp_dir / "app.db", root / "app.db")
        os.replace(temp_dir / ".secret.key", root / ".secret.key")
        pending.unlink(missing_ok=True)
        return {"status": "applied", "applied_at": _utcnow()}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class PersistentStorage:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = self.data_dir / "app.db"
        self.key_file = self.data_dir / ".secret.key"
        self._lock = threading.RLock()
        self._cipher = Fernet(self._load_or_create_key())
        self._init_db()
        self._migrate_legacy_json_once()

    # ---------- connection / schema ----------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    normalized_email TEXT NOT NULL UNIQUE,
                    password_enc TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK(status IN ('available','reserved','used','failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status);

                CREATE TABLE IF NOT EXISTS proxies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    ip TEXT NOT NULL,
                    port TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'http',
                    username TEXT,
                    password_enc TEXT,
                    working INTEGER NOT NULL DEFAULT 0,
                    actual_ip TEXT,
                    region TEXT,
                    region_name TEXT,
                    country_code TEXT,
                    country TEXT,
                    city TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proxies_working ON proxies(working);
                CREATE INDEX IF NOT EXISTS idx_proxies_region ON proxies(region);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS secrets (
                    key TEXT PRIMARY KEY,
                    value_enc TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    requested_count INTEGER NOT NULL,
                    concurrency INTEGER NOT NULL,
                    use_proxies INTEGER NOT NULL DEFAULT 0,
                    target_region TEXT,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    username TEXT,
                    password_enc TEXT,
                    email TEXT,
                    email_password_enc TEXT,
                    region TEXT,
                    error TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_results_created_at ON results(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_results_status ON results(status);

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    normalized_email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'owner',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    actor_email TEXT,
                    entity_type TEXT,
                    entity_id TEXT,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);

                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    settings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, id DESC);
                """
            )
            self._ensure_column(conn, "results", "job_id", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_results_job_id ON results(job_id)")
        self._scrub_result_payload_secrets()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _scrub_result_payload_secrets(self) -> None:
        """Remove legacy plaintext credentials from results.payload_json.

        v2.1 encrypted dedicated credential columns but also serialized the full
        result object into payload_json. This migration removes those duplicate
        plaintext copies while preserving non-secret metadata.
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT id,payload_json FROM results").fetchall()
            updates = []
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    continue
                changed = False
                for key in ("password", "email_password", "api_key", "captcha_api_key"):
                    if key in payload:
                        payload.pop(key, None)
                        changed = True
                if changed:
                    updates.append((json.dumps(payload, ensure_ascii=False, default=str), row["id"]))
            if updates:
                conn.executemany("UPDATE results SET payload_json=? WHERE id=?", updates)

    # ---------- encryption ----------
    def _load_or_create_key(self) -> bytes:
        if self.key_file.exists():
            return self.key_file.read_bytes().strip()
        key = Fernet.generate_key()
        self.key_file.write_bytes(key)
        try:
            os.chmod(self.key_file, 0o600)
        except OSError:
            pass
        return key

    def _encrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return self._cipher.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            return self._cipher.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return ""

    # ---------- helpers ----------
    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().casefold()

    @staticmethod
    def proxy_fingerprint(proxy: Dict[str, Any]) -> str:
        return "|".join(
            [
                str(proxy.get("type") or "http").strip().lower(),
                str(proxy.get("ip") or "").strip().lower(),
                str(proxy.get("port") or "").strip(),
                str(proxy.get("username") or "").strip(),
            ]
        )

    # ---------- e-mail persistence ----------
    def load_emails(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM emails ORDER BY id ASC"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "email": row["email"],
                "password": self._decrypt(row["password_enc"]),
                "status": row["status"],
                "used": row["status"] == "used",
                "attempts": row["attempts"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_used_at": row["last_used_at"],
            }
            for row in rows
        ]

    def import_emails(self, email_lines: Iterable[str], apply: bool = True) -> Dict[str, Any]:
        # Materialize once so generators are handled consistently and the received
        # count is accurate.  Keep the first valid credential for a normalized
        # address; later identical credentials are duplicates, while a different
        # password for the same address is an explicit conflict.
        raw_lines = list(email_lines)
        parsed: Dict[str, Dict[str, str]] = {}
        invalid: List[str] = []
        duplicate_in_batch = 0
        conflict_in_batch: List[str] = []

        for raw in raw_lines:
            value = (raw or "").strip()
            if not value:
                continue
            if ":" not in value:
                invalid.append(value)
                continue
            email, password = value.split(":", 1)
            email = email.strip()
            password = password.strip()
            if not email or "@" not in email or not password:
                invalid.append(value)
                continue
            normalized = self.normalize_email(email)
            previous = parsed.get(normalized)
            if previous is not None:
                if previous["password"] == password:
                    duplicate_in_batch += 1
                else:
                    conflict_in_batch.append(email)
                continue
            parsed[normalized] = {"email": email, "password": password}

        normalized_values = list(parsed.keys())
        existing: Dict[str, sqlite3.Row] = {}
        if normalized_values:
            placeholders = ",".join("?" for _ in normalized_values)
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT normalized_email,email,password_enc FROM emails WHERE normalized_email IN ({placeholders})",
                    normalized_values,
                ).fetchall()
            existing = {row["normalized_email"]: row for row in rows}

        duplicates = 0
        conflicts: List[str] = list(conflict_in_batch)
        new_rows: List[Dict[str, str]] = []
        for normalized, item in parsed.items():
            row = existing.get(normalized)
            if row is None:
                new_rows.append(item)
                continue
            existing_password = self._decrypt(row["password_enc"]) or ""
            if existing_password == item["password"]:
                duplicates += 1
            else:
                conflicts.append(item["email"])

        if apply and new_rows:
            now = _utcnow()
            with self._lock, self._connect() as conn:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO emails
                    (email, normalized_email, password_enc, status, attempts, created_at, updated_at)
                    VALUES (?, ?, ?, 'available', 0, ?, ?)
                    """,
                    [
                        (
                            item["email"],
                            self.normalize_email(item["email"]),
                            self._encrypt(item["password"]),
                            now,
                            now,
                        )
                        for item in new_rows
                    ],
                )

        return {
            "received": len([x for x in raw_lines if (x or "").strip()]),
            "new": len(new_rows),
            "duplicates": duplicates + duplicate_in_batch,
            "conflicts": len(conflicts),
            "invalid": len(invalid),
            "conflict_emails": conflicts[:25],
            "invalid_lines": invalid[:25],
        }

    def save_emails(self, emails: List[Dict[str, Any]]) -> bool:
        """Compatibility upsert for existing services."""
        now = _utcnow()
        try:
            with self._lock, self._connect() as conn:
                for item in emails:
                    email = str(item.get("email") or "").strip()
                    password = str(item.get("password") or "")
                    if not email:
                        continue
                    status = item.get("status") or ("used" if item.get("used") else "available")
                    if status not in {"available", "reserved", "used", "failed"}:
                        status = "available"
                    conn.execute(
                        """
                        INSERT INTO emails
                        (email,normalized_email,password_enc,status,attempts,created_at,updated_at,last_used_at)
                        VALUES (?,?,?,?,?,?,?,?)
                        ON CONFLICT(normalized_email) DO UPDATE SET
                          email=excluded.email,
                          password_enc=excluded.password_enc,
                          status=excluded.status,
                          attempts=excluded.attempts,
                          updated_at=excluded.updated_at,
                          last_used_at=excluded.last_used_at
                        """,
                        (
                            email,
                            self.normalize_email(email),
                            self._encrypt(password),
                            status,
                            int(item.get("attempts") or 0),
                            item.get("created_at") or now,
                            now,
                            item.get("last_used_at"),
                        ),
                    )
            return True
        except Exception as exc:
            print(f"Failed to save emails: {exc}")
            return False

    def set_email_status(self, email: str, status: str, increment_attempts: bool = False) -> None:
        if status not in {"available", "reserved", "used", "failed"}:
            raise ValueError("Invalid email status")
        now = _utcnow()
        attempts_sql = "attempts = attempts + 1," if increment_attempts else ""
        last_used = now if status == "used" else None
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                UPDATE emails
                SET status=?, {attempts_sql} updated_at=?, last_used_at=COALESCE(?, last_used_at)
                WHERE normalized_email=?
                """,
                (status, now, last_used, self.normalize_email(email)),
            )

    def reset_emails(self) -> None:
        now = _utcnow()
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE emails SET status='available', updated_at=?", (now,))

    # ---------- proxy persistence ----------
    def load_proxies(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM proxies ORDER BY id ASC").fetchall()
        results = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "ip": row["ip"],
                    "port": row["port"],
                    "type": row["type"],
                    "username": row["username"],
                    "password": self._decrypt(row["password_enc"]),
                    "working": bool(row["working"]),
                    "actual_ip": row["actual_ip"],
                    "region": row["region"],
                    "region_name": row["region_name"],
                    "country_code": row["country_code"],
                    "country": row["country"],
                    "city": row["city"],
                }
            )
        return results

    def save_proxies(self, proxies: List[Dict[str, Any]]) -> bool:
        now = _utcnow()
        try:
            with self._lock, self._connect() as conn:
                for proxy in proxies:
                    fingerprint = self.proxy_fingerprint(proxy)
                    if not proxy.get("ip") or not proxy.get("port"):
                        continue
                    conn.execute(
                        """
                        INSERT INTO proxies
                        (fingerprint,ip,port,type,username,password_enc,working,actual_ip,region,region_name,
                         country_code,country,city,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(fingerprint) DO UPDATE SET
                          password_enc=excluded.password_enc,
                          working=excluded.working,
                          actual_ip=excluded.actual_ip,
                          region=excluded.region,
                          region_name=excluded.region_name,
                          country_code=excluded.country_code,
                          country=excluded.country,
                          city=excluded.city,
                          updated_at=excluded.updated_at
                        """,
                        (
                            fingerprint,
                            proxy.get("ip"),
                            str(proxy.get("port")),
                            proxy.get("type") or "http",
                            proxy.get("username"),
                            self._encrypt(proxy.get("password")),
                            1 if proxy.get("working") else 0,
                            proxy.get("actual_ip"),
                            proxy.get("region"),
                            proxy.get("region_name"),
                            proxy.get("country_code"),
                            proxy.get("country"),
                            proxy.get("city"),
                            now,
                            now,
                        ),
                    )
            return True
        except Exception as exc:
            print(f"Failed to save proxies: {exc}")
            return False

    # ---------- settings / secrets ----------
    def save_setting(self, key: str, value: Any) -> None:
        now = _utcnow()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key,value_json,updated_at) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), now),
            )

    def load_setting(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def save_secret(self, key: str, value: str) -> None:
        now = _utcnow()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO secrets(key,value_enc,updated_at) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET value_enc=excluded.value_enc, updated_at=excluded.updated_at
                """,
                (key, self._encrypt(value), now),
            )

    def load_secret(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value_enc FROM secrets WHERE key=?", (key,)).fetchone()
        return self._decrypt(row["value_enc"]) if row else default

    def save_captcha_settings(self, settings: Dict[str, Any]) -> bool:
        # Kept for backwards compatibility.  Secret is encrypted at rest.
        try:
            service = str(settings.get("service") or "capsolver")
            self.save_setting("captcha_service", service)
            if settings.get("api_key"):
                self.save_secret("captcha_api_key", str(settings["api_key"]))
            return True
        except Exception as exc:
            print(f"Failed to save provider settings: {exc}")
            return False

    def load_captcha_settings(self) -> Dict[str, Any]:
        api_key = self.load_secret("captcha_api_key", "")
        return {
            "service": self.load_setting("captcha_service", "capsolver"),
            "api_key": api_key,
            "configured": bool(api_key),
            "masked": ("••••" + api_key[-4:]) if api_key else "",
        }

    # ---------- job history ----------
    def recover_interrupted_jobs(self) -> int:
        """Mark jobs left running by an unclean process exit as interrupted."""
        now = _utcnow()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status='interrupted', finished_at=?, message=COALESCE(message, 'Process exited before the job finished')
                WHERE status IN ('queued','running','stopping')
                """,
                (now,),
            )
            return int(cur.rowcount or 0)

    def create_job(self, job_id: str, requested_count: int, concurrency: int, use_proxies: bool, target_region: Optional[str]) -> None:
        now = _utcnow()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs
                (id,status,requested_count,concurrency,use_proxies,target_region,created_at,started_at)
                VALUES (?, 'running', ?, ?, ?, ?, ?, ?)
                """,
                (job_id, int(requested_count), int(concurrency), 1 if use_proxies else 0, target_region, now, now),
            )

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        success_count: Optional[int] = None,
        failed_count: Optional[int] = None,
        message: Optional[str] = None,
        finished: bool = False,
    ) -> None:
        fields: List[str] = []
        values: List[Any] = []
        if status is not None:
            fields.append('status=?'); values.append(status)
        if success_count is not None:
            fields.append('success_count=?'); values.append(int(success_count))
        if failed_count is not None:
            fields.append('failed_count=?'); values.append(int(failed_count))
        if message is not None:
            fields.append('message=?'); values.append(message)
        if finished:
            fields.append('finished_at=?'); values.append(_utcnow())
        if not fields:
            return
        values.append(job_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", values)

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [
            {
                'id': row['id'],
                'status': row['status'],
                'requested_count': row['requested_count'],
                'concurrency': row['concurrency'],
                'use_proxies': bool(row['use_proxies']),
                'target_region': row['target_region'],
                'success_count': row['success_count'],
                'failed_count': row['failed_count'],
                'created_at': row['created_at'],
                'started_at': row['started_at'],
                'finished_at': row['finished_at'],
                'message': row['message'],
            }
            for row in rows
        ]

    # ---------- result history ----------
    def append_result(self, result: Dict[str, Any]) -> int:
        clean = dict(result)
        payload_clean = dict(clean)
        for secret_key in ("password", "email_password", "api_key", "captcha_api_key"):
            payload_clean.pop(secret_key, None)
        now = _utcnow()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO results
                (status,username,password_enc,email,email_password_enc,region,error,payload_json,created_at,job_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(clean.get("status") or "UNKNOWN"),
                    clean.get("username"),
                    self._encrypt(clean.get("password")),
                    clean.get("email"),
                    self._encrypt(clean.get("email_password")),
                    clean.get("region"),
                    clean.get("error"),
                    json.dumps(payload_clean, ensure_ascii=False, default=str),
                    now,
                    clean.get("job_id"),
                ),
            )
            return int(cur.lastrowid)

    def list_results(self, limit: int = 500, include_secrets: bool = True) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 5000))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM results ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            try:
                item = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                item = {}
            item.update(
                {
                    "history_id": row["id"],
                    "status": row["status"],
                    "username": row["username"],
                    "email": row["email"],
                    "region": row["region"],
                    "error": row["error"],
                    "created_at": row["created_at"],
                    "job_id": row["job_id"] if "job_id" in row.keys() else item.get("job_id"),
                }
            )
            if include_secrets:
                item["password"] = self._decrypt(row["password_enc"])
                item["email_password"] = self._decrypt(row["email_password_enc"])
            else:
                item.pop("password", None)
                item.pop("email_password", None)
            results.append(item)
        return results

    # ---------- owner auth / sessions ----------
    def has_users(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def ensure_owner(self, email: str, password_hash: str) -> Dict[str, Any]:
        normalized = self.normalize_email(email)
        now = _utcnow()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE normalized_email=?", (normalized,)).fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO users(email,normalized_email,password_hash,role,is_active,created_at,updated_at)
                    VALUES (?,?,?,?,1,?,?)
                    """,
                    (email.strip(), normalized, password_hash, "owner", now, now),
                )
                row = conn.execute("SELECT * FROM users WHERE normalized_email=?", (normalized,)).fetchone()
        return self._user_row(row)

    @staticmethod
    def _user_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "email": row["email"],
            "normalized_email": row["normalized_email"],
            "password_hash": row["password_hash"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_login_at": row["last_login_at"],
        }

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE normalized_email=?", (self.normalize_email(email),)).fetchone()
        return self._user_row(row) if row else None

    def update_user_password(self, user_id: int, password_hash: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?", (password_hash, _utcnow(), int(user_id)))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (int(user_id),))

    def mark_login(self, user_id: int) -> None:
        now = _utcnow()
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", (now, now, int(user_id)))

    def create_session(self, user_id: int, token_hash_value: str, days: int = 7) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=max(1, min(int(days), 90)))
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
            cur = conn.execute(
                """
                INSERT INTO sessions(user_id,token_hash,created_at,last_seen_at,expires_at)
                VALUES (?,?,?,?,?)
                """,
                (int(user_id), token_hash_value, now.isoformat(), now.isoformat(), expires.isoformat()),
            )
        return {"id": int(cur.lastrowid), "expires_at": expires.isoformat()}

    def get_session_user(self, token_hash_value: str) -> Optional[Dict[str, Any]]:
        now = _utcnow()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=1
                """,
                (token_hash_value, now),
            ).fetchone()
            if row:
                conn.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now, token_hash_value))
        return self._user_row(row) if row else None

    def delete_session(self, token_hash_value: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash_value,))

    def delete_all_sessions(self, user_id: int, except_token_hash: Optional[str] = None) -> None:
        with self._lock, self._connect() as conn:
            if except_token_hash:
                conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (int(user_id), except_token_hash))
            else:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (int(user_id),))

    def clear_sessions(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions")
            return int(cur.rowcount or 0)

    # ---------- audit log ----------
    def add_audit_event(
        self,
        event_type: str,
        *,
        actor_email: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[Any] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO audit_events(event_type,actor_email,entity_type,entity_id,detail_json,created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    event_type,
                    actor_email,
                    entity_type,
                    None if entity_id is None else str(entity_id),
                    json.dumps(detail or {}, ensure_ascii=False, default=str),
                    _utcnow(),
                ),
            )
            return int(cur.lastrowid)

    def list_audit_events(self, *, page: int = 1, page_size: int = 50, query: str = "") -> Dict[str, Any]:
        page = max(1, int(page)); page_size = max(1, min(int(page_size), 200))
        clauses: List[str] = []; params: List[Any] = []
        q = (query or "").strip()
        if q:
            clauses.append("(event_type LIKE ? OR actor_email LIKE ? OR entity_type LIKE ? OR entity_id LIKE ? OR detail_json LIKE ?)")
            term = f"%{q}%"; params.extend([term] * 5)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM audit_events{where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM audit_events{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        items = []
        for row in rows:
            try: detail = json.loads(row["detail_json"])
            except Exception: detail = {}
            items.append({
                "id": row["id"], "event_type": row["event_type"], "actor_email": row["actor_email"],
                "entity_type": row["entity_type"], "entity_id": row["entity_id"], "detail": detail,
                "created_at": row["created_at"],
            })
        return {"items": items, "total": int(total), "page": page, "page_size": page_size}

    # ---------- profiles ----------
    def save_profile(self, name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        clean_name = " ".join((name or "").strip().split())
        if not clean_name:
            raise ValueError("Profile name is required")
        if len(clean_name) > 80:
            raise ValueError("Profile name is too long")
        now = _utcnow()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles(name,settings_json,created_at,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at
                """,
                (clean_name, json.dumps(settings, ensure_ascii=False), now, now),
            )
            row = conn.execute("SELECT * FROM profiles WHERE name=?", (clean_name,)).fetchone()
        return self._profile_row(row)

    @staticmethod
    def _profile_row(row: sqlite3.Row) -> Dict[str, Any]:
        try: settings = json.loads(row["settings_json"])
        except Exception: settings = {}
        return {"id": row["id"], "name": row["name"], "settings": settings, "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def list_profiles(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM profiles ORDER BY name COLLATE NOCASE").fetchall()
        return [self._profile_row(row) for row in rows]

    def delete_profile(self, profile_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM profiles WHERE id=?", (int(profile_id),))
            return bool(cur.rowcount)

    # ---------- inventory CRUD / pagination ----------
    def list_emails_page(self, *, page: int = 1, page_size: int = 50, query: str = "", status: str = "") -> Dict[str, Any]:
        page = max(1, int(page)); page_size = max(1, min(int(page_size), 200))
        clauses: List[str] = []; params: List[Any] = []
        if (query or "").strip():
            clauses.append("email LIKE ?"); params.append(f"%{query.strip()}%")
        if status in {"available", "reserved", "used", "failed"}:
            clauses.append("status=?"); params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM emails{where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM emails{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        items = [{
            "id": row["id"], "email": row["email"], "status": row["status"], "attempts": row["attempts"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "last_used_at": row["last_used_at"],
            "password_masked": "••••••••" if row["password_enc"] else "",
        } for row in rows]
        return {"items": items, "total": int(total), "page": page, "page_size": page_size}

    def get_email_secret(self, email_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT id,email,password_enc,status FROM emails WHERE id=?", (int(email_id),)).fetchone()
        if not row: return None
        return {"id": row["id"], "email": row["email"], "password": self._decrypt(row["password_enc"]), "status": row["status"]}

    def update_email(self, email_id: int, *, email: Optional[str] = None, password: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
        fields: List[str] = []; params: List[Any] = []
        if email is not None:
            clean = email.strip()
            if not clean or "@" not in clean: raise ValueError("Invalid email")
            fields += ["email=?", "normalized_email=?"]; params += [clean, self.normalize_email(clean)]
        if password is not None:
            if not password: raise ValueError("Password cannot be empty")
            fields.append("password_enc=?"); params.append(self._encrypt(password))
        if status is not None:
            if status not in {"available", "reserved", "used", "failed"}: raise ValueError("Invalid status")
            fields.append("status=?"); params.append(status)
        fields.append("updated_at=?"); params.append(_utcnow()); params.append(int(email_id))
        with self._lock, self._connect() as conn:
            try:
                cur = conn.execute(f"UPDATE emails SET {', '.join(fields)} WHERE id=?", params)
            except sqlite3.IntegrityError as exc:
                raise ValueError("Another saved account already uses that email") from exc
            if not cur.rowcount: raise KeyError("Email not found")
        return self.get_email_secret(email_id) or {}

    def delete_emails(self, ids: Iterable[int]) -> int:
        clean = sorted({int(x) for x in ids})
        if not clean: return 0
        placeholders = ",".join("?" for _ in clean)
        with self._lock, self._connect() as conn:
            cur = conn.execute(f"DELETE FROM emails WHERE id IN ({placeholders})", clean)
            return int(cur.rowcount or 0)

    def bulk_email_status(self, ids: Iterable[int], status: str) -> int:
        if status not in {"available", "used", "failed"}: raise ValueError("Invalid bulk status")
        clean = sorted({int(x) for x in ids})
        if not clean: return 0
        placeholders = ",".join("?" for _ in clean)
        with self._lock, self._connect() as conn:
            cur = conn.execute(f"UPDATE emails SET status=?, updated_at=? WHERE id IN ({placeholders})", [status, _utcnow(), *clean])
            return int(cur.rowcount or 0)

    def list_proxies_page(self, *, page: int = 1, page_size: int = 50, query: str = "", state: str = "", region: str = "") -> Dict[str, Any]:
        page = max(1, int(page)); page_size = max(1, min(int(page_size), 200))
        clauses: List[str] = []; params: List[Any] = []
        if (query or "").strip():
            term = f"%{query.strip()}%"; clauses.append("(ip LIKE ? OR port LIKE ? OR username LIKE ? OR country LIKE ? OR city LIKE ?)"); params.extend([term] * 5)
        if state == "working": clauses.append("working=1")
        elif state == "down": clauses.append("working=0")
        if region:
            clauses.append("region=?"); params.append(region)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM proxies{where}", params).fetchone()[0]
            rows = conn.execute(f"SELECT * FROM proxies{where} ORDER BY id DESC LIMIT ? OFFSET ?", [*params, page_size, (page - 1) * page_size]).fetchall()
        items = [{
            "id": row["id"], "ip": row["ip"], "port": row["port"], "type": row["type"], "username": row["username"],
            "working": bool(row["working"]), "actual_ip": row["actual_ip"], "region": row["region"], "region_name": row["region_name"],
            "country_code": row["country_code"], "country": row["country"], "city": row["city"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "password_masked": "••••••••" if row["password_enc"] else "",
        } for row in rows]
        return {"items": items, "total": int(total), "page": page, "page_size": page_size}

    def get_proxy_secret(self, proxy_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proxies WHERE id=?", (int(proxy_id),)).fetchone()
        if not row: return None
        return {"id": row["id"], "ip": row["ip"], "port": row["port"], "type": row["type"], "username": row["username"], "password": self._decrypt(row["password_enc"]), "region": row["region"], "working": bool(row["working"])}

    def update_proxy(self, proxy_id: int, *, ip: Optional[str] = None, port: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None, proxy_type: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proxies WHERE id=?", (int(proxy_id),)).fetchone()
        if not row: raise KeyError("Proxy not found")
        item = dict(row)
        if ip is not None: item["ip"] = ip.strip()
        if port is not None: item["port"] = str(port).strip()
        if username is not None: item["username"] = username.strip() or None
        if proxy_type is not None: item["type"] = proxy_type.strip().lower() or "http"
        if region is not None: item["region"] = region.strip() or None
        if not item["ip"] or not item["port"]: raise ValueError("Proxy host and port are required")
        if any(ch.isspace() for ch in str(item["ip"])): raise ValueError("Proxy host cannot contain whitespace")
        try:
            port_number = int(str(item["port"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("Proxy port must be a number") from exc
        if not 1 <= port_number <= 65535: raise ValueError("Proxy port must be between 1 and 65535")
        item["port"] = str(port_number)
        if item["type"] not in {"http", "https", "socks5", "socks5h"}: raise ValueError("Unsupported proxy type")
        new_fingerprint = self.proxy_fingerprint(item)
        fields = ["ip=?","port=?","type=?","username=?","fingerprint=?","region=?","updated_at=?"]
        params: List[Any] = [item["ip"], item["port"], item["type"], item["username"], new_fingerprint, item.get("region"), _utcnow()]
        if password is not None:
            fields.append("password_enc=?"); params.append(self._encrypt(password) if password else None)
        params.append(int(proxy_id))
        with self._lock, self._connect() as conn:
            try: conn.execute(f"UPDATE proxies SET {', '.join(fields)} WHERE id=?", params)
            except sqlite3.IntegrityError as exc: raise ValueError("That proxy already exists") from exc
        return self.get_proxy_secret(proxy_id) or {}

    def delete_proxies(self, ids: Iterable[int]) -> int:
        clean = sorted({int(x) for x in ids})
        if not clean: return 0
        placeholders = ",".join("?" for _ in clean)
        with self._lock, self._connect() as conn:
            cur = conn.execute(f"DELETE FROM proxies WHERE id IN ({placeholders})", clean)
            return int(cur.rowcount or 0)

    # ---------- richer jobs/results ----------
    def add_job_event(self, job_id: str, event_type: str, message: str = "", detail: Optional[Dict[str, Any]] = None) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO job_events(job_id,event_type,message,detail_json,created_at) VALUES (?,?,?,?,?)",
                (job_id, event_type, message, json.dumps(detail or {}, ensure_ascii=False, default=str), _utcnow()),
            )
            return int(cur.lastrowid)

    def list_job_events(self, job_id: str, limit: int = 250) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit)).fetchall()
        result=[]
        for row in rows:
            try: detail=json.loads(row["detail_json"])
            except Exception: detail={}
            result.append({"id":row["id"],"job_id":row["job_id"],"event_type":row["event_type"],"message":row["message"],"detail":detail,"created_at":row["created_at"]})
        return result

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row: return None
        return {
            "id": row["id"], "status": row["status"], "requested_count": row["requested_count"], "concurrency": row["concurrency"],
            "use_proxies": bool(row["use_proxies"]), "target_region": row["target_region"], "success_count": row["success_count"], "failed_count": row["failed_count"],
            "created_at": row["created_at"], "started_at": row["started_at"], "finished_at": row["finished_at"], "message": row["message"],
        }

    def list_jobs_page(self, *, page: int = 1, page_size: int = 30, status: str = "") -> Dict[str, Any]:
        page=max(1,int(page)); page_size=max(1,min(int(page_size),200)); params:List[Any]=[]; where=""
        if status:
            where=" WHERE status=?"; params.append(status)
        with self._connect() as conn:
            total=conn.execute(f"SELECT COUNT(*) FROM jobs{where}",params).fetchone()[0]
            rows=conn.execute(f"SELECT * FROM jobs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",[*params,page_size,(page-1)*page_size]).fetchall()
        items=[]
        for row in rows:
            items.append({"id":row["id"],"status":row["status"],"requested_count":row["requested_count"],"concurrency":row["concurrency"],"use_proxies":bool(row["use_proxies"]),"target_region":row["target_region"],"success_count":row["success_count"],"failed_count":row["failed_count"],"created_at":row["created_at"],"started_at":row["started_at"],"finished_at":row["finished_at"],"message":row["message"]})
        return {"items":items,"total":int(total),"page":page,"page_size":page_size}

    def list_results_page(self, *, page: int = 1, page_size: int = 50, query: str = "", status: str = "", region: str = "", job_id: str = "") -> Dict[str, Any]:
        page=max(1,int(page)); page_size=max(1,min(int(page_size),200)); clauses=[]; params:List[Any]=[]
        if (query or "").strip():
            term=f"%{query.strip()}%"; clauses.append("(username LIKE ? OR email LIKE ? OR error LIKE ?)"); params.extend([term]*3)
        if status: clauses.append("status=?"); params.append(status)
        if region: clauses.append("region=?"); params.append(region)
        if job_id: clauses.append("job_id=?"); params.append(job_id)
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total=conn.execute(f"SELECT COUNT(*) FROM results{where}",params).fetchone()[0]
            rows=conn.execute(f"SELECT * FROM results{where} ORDER BY id DESC LIMIT ? OFFSET ?",[*params,page_size,(page-1)*page_size]).fetchall()
        items=[]
        for row in rows:
            items.append({
                "history_id":row["id"],"status":row["status"],"username":row["username"],"email":row["email"],"region":row["region"],"error":row["error"],"created_at":row["created_at"],"job_id":row["job_id"],
                "password_masked":"••••••••" if row["password_enc"] else "", "email_password_masked":"••••••••" if row["email_password_enc"] else "",
            })
        return {"items":items,"total":int(total),"page":page,"page_size":page_size}

    def get_result_secret(self, result_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row=conn.execute("SELECT id,username,password_enc,email,email_password_enc FROM results WHERE id=?",(int(result_id),)).fetchone()
        if not row: return None
        return {"history_id":row["id"],"username":row["username"],"password":self._decrypt(row["password_enc"]),"email":row["email"],"email_password":self._decrypt(row["email_password_enc"])}

    def delete_results(self, ids: Iterable[int]) -> int:
        clean=sorted({int(x) for x in ids})
        if not clean: return 0
        placeholders=",".join("?" for _ in clean)
        with self._lock,self._connect() as conn:
            cur=conn.execute(f"DELETE FROM results WHERE id IN ({placeholders})",clean)
            return int(cur.rowcount or 0)

    # ---------- backup / restore ----------
    def create_backup(self, destination_zip: str) -> Dict[str, Any]:
        destination = Path(destination_zip).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_db = destination.with_suffix(".sqlite.tmp")
        with self._lock:
            source = self._connect()
            target = sqlite3.connect(temp_db)
            try:
                source.backup(target)
            finally:
                target.close(); source.close()
            manifest = {
                "format": "riot-creator-backup-v1",
                "created_at": _utcnow(),
                "database": "app.db",
                "secret_key": ".secret.key",
            }
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(temp_db, "app.db")
                if self.key_file.exists(): zf.write(self.key_file, ".secret.key")
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            temp_db.unlink(missing_ok=True)
        return {"path": str(destination), "size_bytes": destination.stat().st_size, "created_at": manifest["created_at"]}

    def validate_backup_archive(self, backup_zip: str) -> Dict[str, Any]:
        source = Path(backup_zip).resolve()
        if not source.exists():
            raise ValueError("Backup file not found")
        if source.stat().st_size > 100 * 1024 * 1024:
            raise ValueError("Backup is too large")
        validate_dir = self.data_dir / ".validate_backup_tmp"
        if validate_dir.exists():
            shutil.rmtree(validate_dir, ignore_errors=True)
        validate_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(source, "r") as zf:
                names = set(zf.namelist())
                if "app.db" not in names or ".secret.key" not in names:
                    raise ValueError("Invalid backup: app.db or secret key missing")
                candidate = validate_dir / "app.db"
                candidate.write_bytes(zf.read("app.db"))
                key_bytes = zf.read(".secret.key")
                if not key_bytes.strip():
                    raise ValueError("Invalid backup: encryption key is empty")
                manifest = {}
                if "manifest.json" in names:
                    try:
                        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                    except Exception:
                        manifest = {}
            with sqlite3.connect(candidate) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                required = {"emails", "proxies", "settings", "secrets", "jobs", "results"}
                if not required.issubset(tables):
                    raise ValueError("Backup database schema is not recognized")
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise ValueError(f"Backup database integrity check failed: {integrity}")
            return {"valid": True, "manifest": manifest, "size_bytes": source.stat().st_size}
        finally:
            shutil.rmtree(validate_dir, ignore_errors=True)

    def stage_restore_backup(self, backup_zip: str) -> Dict[str, Any]:
        info = self.validate_backup_archive(backup_zip)
        backups_dir = self.data_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        safety = backups_dir / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        self.create_backup(str(safety))
        pending = self.data_dir / ".pending_restore.zip"
        shutil.copy2(Path(backup_zip).resolve(), pending)
        return {
            "status": "staged",
            "restart_required": True,
            "pending_restore": str(pending),
            "safety_backup": str(safety),
            "backup": info,
        }

    # ---------- migration / diagnostics ----------
    def _migrate_legacy_json_once(self) -> None:
        if self.load_setting("legacy_json_migrated", False):
            return
        email_file = self.data_dir / "emails.json"
        proxy_file = self.data_dir / "proxies.json"
        captcha_file = self.data_dir / "captcha.json"
        try:
            if email_file.exists():
                data = json.loads(email_file.read_text(encoding="utf-8"))
                self.save_emails(data if isinstance(data, list) else [])
            if proxy_file.exists():
                data = json.loads(proxy_file.read_text(encoding="utf-8"))
                self.save_proxies(data if isinstance(data, list) else [])
            if captcha_file.exists():
                data = json.loads(captcha_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.save_captcha_settings(data)
            self.save_setting("legacy_json_migrated", True)
        except Exception as exc:
            print(f"Legacy JSON migration skipped: {exc}")

    def diagnostics(self) -> Dict[str, Any]:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1").fetchone()
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                counts = {
                    "emails": conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0],
                    "proxies": conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0],
                    "results": conn.execute("SELECT COUNT(*) FROM results").fetchone()[0],
                    "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                    "profiles": conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0],
                    "audit_events": conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
                    "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                }
            return {
                "database": "ok" if integrity == "ok" else "warning",
                "integrity": integrity,
                "database_path": str(self.db_file),
                "database_size_bytes": self.db_file.stat().st_size if self.db_file.exists() else 0,
                "secret_key": "ok" if self.key_file.exists() else "missing",
                **counts,
            }
        except Exception as exc:
            return {"database": "error", "error": str(exc)}

    def clear_all(self) -> bool:
        try:
            with self._lock, self._connect() as conn:
                conn.executescript(
                    "DELETE FROM emails; DELETE FROM proxies; DELETE FROM results; DELETE FROM jobs; DELETE FROM settings; DELETE FROM secrets;"
                )
            return True
        except Exception as exc:
            print(f"Failed to clear data: {exc}")
            return False
