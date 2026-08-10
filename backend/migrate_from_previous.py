from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
DEST = Path(os.getenv("RIOT_CREATOR_DATA_DIR", str(HERE / "data")))


def resolve_source(value: str) -> Path:
    source = Path(value.strip().strip('"')).expanduser().resolve()
    if (source / "backend" / "data" / "app.db").exists():
        return source / "backend" / "data"
    if (source / "app.db").exists():
        return source
    raise FileNotFoundError("Could not find backend/data/app.db in the selected previous folder")


def sqlite_backup(source_db: Path, destination_db: Path) -> None:
    destination_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as source:
        with sqlite3.connect(destination_db) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"Copied database failed integrity check: {result}")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python migrate_from_previous.py <previous project folder or data folder>")
        return 2
    try:
        source = resolve_source(sys.argv[1])
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    source_db = source / "app.db"
    source_key = source / ".secret.key"
    if not source_key.exists():
        print("[ERROR] The previous .secret.key is missing. Encrypted saved credentials cannot be migrated without it.")
        return 1

    DEST.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if (DEST / "app.db").exists():
        safety = DEST / f"pre_migration_{stamp}.db"
        sqlite_backup(DEST / "app.db", safety)
        if (DEST / ".secret.key").exists():
            shutil.copy2(DEST / ".secret.key", DEST / f"pre_migration_{stamp}.secret.key")
        print(f"[INFO] Safety copy created: {safety.name}")

    temp_db = DEST / ".migration_app.db"
    temp_db.unlink(missing_ok=True)
    sqlite_backup(source_db, temp_db)
    shutil.copy2(source_key, DEST / ".secret.key")
    temp_db.replace(DEST / "app.db")

    source_backups = source / "backups"
    if source_backups.exists():
        shutil.copytree(source_backups, DEST / "backups", dirs_exist_ok=True)

    print("[PASS] Previous database and encryption key migrated successfully.")
    print(f"[INFO] Source: {source}")
    print(f"[INFO] Destination: {DEST}")
    print("[INFO] Start v2.4 normally now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
