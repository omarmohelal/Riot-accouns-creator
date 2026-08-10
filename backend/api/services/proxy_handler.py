"""Proxy inventory and health checking with persistent deduplication."""
from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote, unquote, urlsplit

import httpx

from .persistent_storage import PersistentStorage


COUNTRY_TO_REGION = {
    'TR': ('TR', 'Turkey'),
    'GB': ('EUW', 'EU West'), 'FR': ('EUW', 'EU West'), 'DE': ('EUW', 'EU West'),
    'ES': ('EUW', 'EU West'), 'IT': ('EUW', 'EU West'), 'NL': ('EUW', 'EU West'),
    'BE': ('EUW', 'EU West'), 'PT': ('EUW', 'EU West'), 'IE': ('EUW', 'EU West'),
    'CH': ('EUW', 'EU West'), 'AT': ('EUW', 'EU West'),
    'PL': ('EUNE', 'EU Nordic & East'), 'CZ': ('EUNE', 'EU Nordic & East'),
    'SK': ('EUNE', 'EU Nordic & East'), 'HU': ('EUNE', 'EU Nordic & East'),
    'RO': ('EUNE', 'EU Nordic & East'), 'BG': ('EUNE', 'EU Nordic & East'),
    'SE': ('EUNE', 'EU Nordic & East'), 'NO': ('EUNE', 'EU Nordic & East'),
    'DK': ('EUNE', 'EU Nordic & East'), 'FI': ('EUNE', 'EU Nordic & East'),
    'US': ('NA', 'North America'), 'CA': ('NA', 'North America'),
    'BR': ('BR', 'Brazil'), 'JP': ('JP', 'Japan'), 'KR': ('KR', 'Korea'),
}


class ProxyHandler:
    def __init__(self, storage: Optional[PersistentStorage] = None):
        self.storage = storage
        self.proxies: List[Dict] = []
        self.working_proxies: List[Dict] = []
        self.rate_limited: Dict[str, datetime] = {}
        self._reload()

    def _reload(self) -> None:
        if self.storage:
            self.proxies = self.storage.load_proxies() or []
        self.working_proxies = [p for p in self.proxies if p.get("working", False)]

    @staticmethod
    def _parse_proxy_string(proxy_string: str, proxy_type: str = "http") -> Optional[Dict]:
        raw = (proxy_string or "").strip()
        if not raw:
            return None

        allowed_types = {"http", "https", "socks5", "socks5h"}
        selected_type = (proxy_type or "http").strip().lower()
        host = port = username = password = None

        try:
            if "://" in raw:
                parsed = urlsplit(raw)
                selected_type = (parsed.scheme or selected_type).lower()
                host = parsed.hostname
                port = str(parsed.port) if parsed.port else None
                username = unquote(parsed.username) if parsed.username is not None else None
                password = unquote(parsed.password) if parsed.password is not None else None
            elif "@" in raw:
                credentials, endpoint = raw.rsplit("@", 1)
                if ":" not in endpoint:
                    return None
                host, port = endpoint.rsplit(":", 1)
                if ":" in credentials:
                    username, password = credentials.split(":", 1)
                else:
                    username = credentials
            else:
                # host:port[:user[:password]]; password may contain ':'
                parts = raw.split(":", 3)
                if len(parts) < 2:
                    return None
                host, port = parts[0], parts[1]
                username = parts[2] if len(parts) > 2 else None
                password = parts[3] if len(parts) > 3 else None
        except (TypeError, ValueError):
            return None

        host = (host or "").strip()
        port = (port or "").strip()
        username = (username or "").strip() or None
        password = password if password not in {None, ""} else None
        if selected_type not in allowed_types or not host or any(ch.isspace() for ch in host):
            return None
        try:
            port_number = int(port)
        except (TypeError, ValueError):
            return None
        if not 1 <= port_number <= 65535:
            return None

        return {
            "ip": host,
            "port": str(port_number),
            "type": selected_type,
            "username": username,
            "password": password,
            "working": False,
            "actual_ip": None,
            "region": None,
            "region_name": None,
            "country_code": None,
            "country": None,
            "city": None,
        }

    def add_proxies(self, proxy_list: List[str], proxy_type: str = "http") -> Dict:
        """Import proxies once; identical endpoints are skipped on later imports."""
        self._reload()
        existing = {
            (self.storage.proxy_fingerprint(p) if self.storage else self._fingerprint(p)): p
            for p in self.proxies
        }
        seen_batch: Dict[str, Dict] = {}
        new_items: List[Dict] = []
        invalid = 0
        duplicates = 0
        conflicts = 0
        for raw in proxy_list:
            proxy = self._parse_proxy_string(raw, proxy_type)
            if not proxy:
                if (raw or '').strip():
                    invalid += 1
                continue
            self._parse_region_from_username(proxy)
            fingerprint = self.storage.proxy_fingerprint(proxy) if self.storage else self._fingerprint(proxy)
            previous = existing.get(fingerprint) or seen_batch.get(fingerprint)
            if previous is not None:
                if (previous.get("password") or "") == (proxy.get("password") or ""):
                    duplicates += 1
                else:
                    conflicts += 1
                continue
            seen_batch[fingerprint] = proxy
            new_items.append(proxy)

        if new_items:
            self.proxies.extend(new_items)
            if self.storage:
                self.storage.save_proxies(new_items)
        self._reload()
        return {
            "received": len([x for x in proxy_list if (x or '').strip()]),
            "new": len(new_items),
            "duplicates": duplicates,
            "conflicts": conflicts,
            "invalid": invalid,
            "statistics": self.get_statistics(),
        }

    @staticmethod
    def _fingerprint(proxy: Dict) -> str:
        return "|".join([
            str(proxy.get('type') or 'http').lower(),
            str(proxy.get('ip') or '').lower(),
            str(proxy.get('port') or ''),
            str(proxy.get('username') or ''),
        ])

    def _parse_region_from_username(self, proxy: Dict) -> None:
        username = proxy.get("username", "") or ""
        match = re.search(r'country-([a-z]{2})', username.lower())
        if match:
            country_code = match.group(1).upper()
            if country_code in COUNTRY_TO_REGION:
                proxy["country_code"] = country_code
                region, region_name = COUNTRY_TO_REGION[country_code]
                proxy["region"] = region
                proxy["region_name"] = region_name

    def _format_proxy_url(self, proxy: Dict) -> str:
        scheme = proxy.get('type') or 'http'
        host = str(proxy['ip'])
        port = str(proxy['port'])
        if proxy.get("username"):
            user = quote(str(proxy.get("username") or ""), safe="")
            secret = quote(str(proxy.get("password") or ""), safe="")
            return f"{scheme}://{user}:{secret}@{host}:{port}"
        return f"{scheme}://{host}:{port}"

    async def check_proxy(self, proxy: Dict) -> bool:
        try:
            proxy_url = self._format_proxy_url(proxy)
            async with httpx.AsyncClient(proxy=proxy_url, timeout=20.0, follow_redirects=True) as client:
                response = await client.get("https://api.ipify.org?format=json")
                if response.status_code != 200:
                    proxy["working"] = False
                    return False
                proxy["actual_ip"] = response.json().get("ip")

                if not proxy.get("region"):
                    try:
                        geo = await client.get("https://ipwho.is/", timeout=10.0)
                        geo_data = geo.json() if geo.status_code == 200 else {}
                        cc = str(geo_data.get("country_code") or "").upper()
                        if cc in COUNTRY_TO_REGION:
                            proxy["country_code"] = cc
                            region, region_name = COUNTRY_TO_REGION[cc]
                            proxy["region"] = region
                            proxy["region_name"] = region_name
                        proxy["country"] = geo_data.get("country")
                        proxy["city"] = geo_data.get("city")
                    except Exception:
                        pass

                proxy["working"] = True
                return True
        except Exception:
            proxy["working"] = False
            return False

    async def check_all_proxies(self, concurrency: int = 10, detect_region: bool = True) -> int:
        self._reload()
        semaphore = asyncio.Semaphore(max(1, min(concurrency, 25)))

        async def check_with_semaphore(proxy: Dict) -> None:
            async with semaphore:
                await self.check_proxy(proxy)

        await asyncio.gather(*(check_with_semaphore(p) for p in self.proxies), return_exceptions=True)
        if self.storage:
            self.storage.save_proxies(self.proxies)
        self._reload()
        return len(self.working_proxies)

    def get_proxies_by_region(self, region: str) -> List[Dict]:
        return [p for p in self.working_proxies if p.get("region") == region and not self._is_rate_limited(p)]

    def get_random_proxy(self, region: Optional[str] = None) -> Optional[Dict]:
        available = self.get_proxies_by_region(region) if region else [
            p for p in self.working_proxies if not self._is_rate_limited(p)
        ]
        return random.choice(available) if available else None

    def mark_rate_limited(self, proxy: Dict, duration_minutes: int = 30) -> None:
        proxy_key = f"{proxy['ip']}:{proxy['port']}"
        self.rate_limited[proxy_key] = datetime.now() + timedelta(minutes=duration_minutes)

    def _is_rate_limited(self, proxy: Dict) -> bool:
        proxy_key = f"{proxy['ip']}:{proxy['port']}"
        expiry = self.rate_limited.get(proxy_key)
        if not expiry:
            return False
        if datetime.now() < expiry:
            return True
        self.rate_limited.pop(proxy_key, None)
        return False

    def format_for_playwright(self, proxy: Dict) -> Dict:
        data = {"server": f"{proxy.get('type') or 'http'}://{proxy['ip']}:{proxy['port']}"}
        if proxy.get("username"):
            data["username"] = proxy.get("username")
        if proxy.get("password"):
            data["password"] = proxy.get("password")
        return data

    def get_statistics(self) -> Dict:
        self._reload()
        by_region: Dict[str, Dict] = {}
        for proxy in self.working_proxies:
            region = proxy.get("region") or "Unknown"
            region_name = proxy.get("region_name") or region
            by_region.setdefault(region, {"name": region_name, "code": region, "count": 0})
            by_region[region]["count"] += 1
        return {
            "total": len(self.proxies),
            "working": len(self.working_proxies),
            "unchecked": len([p for p in self.proxies if not p.get('working')]),
            "rate_limited": len(self.rate_limited),
            "by_region": by_region,
        }
