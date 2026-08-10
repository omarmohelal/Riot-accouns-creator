"""Persistent email-account inventory with duplicate/conflict protection."""
from __future__ import annotations

from typing import Dict, List, Optional

from .persistent_storage import PersistentStorage


class EmailAccountManager:
    def __init__(self, storage: Optional[PersistentStorage] = None):
        self.storage = storage
        self.email_accounts: List[Dict] = []
        self.available_emails: List[Dict] = []
        self.used_emails: List[Dict] = []
        self.reserved_emails: List[Dict] = []
        self.failed_emails: List[Dict] = []
        self._reload()

    def _reload(self) -> None:
        rows = self.storage.load_emails() if self.storage else self.email_accounts
        self.email_accounts = rows or []
        self.available_emails = [a for a in self.email_accounts if a.get("status", "available") == "available"]
        self.reserved_emails = [a for a in self.email_accounts if a.get("status") == "reserved"]
        self.used_emails = [a for a in self.email_accounts if a.get("status") == "used"]
        self.failed_emails = [a for a in self.email_accounts if a.get("status") == "failed"]

    def preview_email_accounts(self, email_list: List[str]) -> Dict:
        if self.storage:
            return self.storage.import_emails(email_list, apply=False)
        return {"received": len(email_list), "new": len(email_list), "duplicates": 0, "conflicts": 0, "invalid": 0}

    def add_email_accounts(self, email_list: List[str]) -> Dict:
        """Import email:password lines and skip duplicates safely."""
        if self.storage:
            summary = self.storage.import_emails(email_list, apply=True)
            self._reload()
            summary["statistics"] = self.get_statistics()
            return summary

        existing = {str(a.get("email", "")).strip().casefold() for a in self.email_accounts}
        added = 0
        duplicates = 0
        invalid = 0
        for raw in email_list:
            value = (raw or "").strip()
            if ":" not in value:
                invalid += 1
                continue
            email, password = value.split(":", 1)
            email, password = email.strip(), password.strip()
            if not email or "@" not in email or not password:
                invalid += 1
                continue
            normalized = email.casefold()
            if normalized in existing:
                duplicates += 1
                continue
            item = {"email": email, "password": password, "status": "available", "used": False, "attempts": 0}
            self.email_accounts.append(item)
            existing.add(normalized)
            added += 1
        self._reload()
        return {
            "received": len(email_list),
            "new": added,
            "duplicates": duplicates,
            "conflicts": 0,
            "invalid": invalid,
            "statistics": self.get_statistics(),
        }

    def get_next_email(self) -> Optional[Dict]:
        """Reserve (rather than immediately consume) the next available account."""
        self._reload()
        if not self.available_emails:
            return None
        item = dict(self.available_emails[0])
        item["status"] = "reserved"
        item["used"] = False
        if self.storage:
            self.storage.set_email_status(item["email"], "reserved", increment_attempts=True)
        self._reload()
        return item

    # Compatibility for the caller in main.py from the original project.
    def get_next_available(self) -> Optional[Dict]:
        return self.get_next_email()

    def mark_used(self, email: str) -> None:
        if self.storage:
            self.storage.set_email_status(email, "used")
        self._reload()

    def release(self, email: str) -> None:
        if self.storage:
            self.storage.set_email_status(email, "available")
        self._reload()

    def mark_failed(self, email: str) -> None:
        if self.storage:
            self.storage.set_email_status(email, "failed")
        self._reload()

    def get_statistics(self) -> Dict:
        self._reload()
        return {
            "total": len(self.email_accounts),
            "available": len(self.available_emails),
            "reserved": len(self.reserved_emails),
            "used": len(self.used_emails),
            "failed": len(self.failed_emails),
        }

    def reset(self) -> None:
        if self.storage:
            self.storage.reset_emails()
        else:
            for account in self.email_accounts:
                account["status"] = "available"
                account["used"] = False
        self._reload()
