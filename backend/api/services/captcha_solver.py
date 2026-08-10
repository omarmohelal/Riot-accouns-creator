"""
Captcha Solver Integration - Multiple Services
"""
import httpx
import asyncio
from typing import Optional

class CaptchaSolver:
    def __init__(self, service: str = "capsolver", api_key: str = ""):
        self.service = service.lower()
        self.api_key = api_key
        self.base_urls = {
            "2captcha": "https://2captcha.com",
            "capsolver": "https://api.capsolver.com",
            "anticaptcha": "https://api.anti-captcha.com",
            "capmonster": "https://api.capmonster.cloud"
        }
    
    async def solve_hcaptcha(
        self,
        site_key: str,
        page_url: str,
        rqdata: Optional[str] = None
    ) -> Optional[str]:
        """Solve hCaptcha using configured service"""
        
        if not self.api_key:
            print("[Captcha] No API key provided")
            return None
        
        if self.service == "2captcha":
            return await self._solve_2captcha(site_key, page_url, rqdata)
        elif self.service == "capsolver":
            return await self._solve_capsolver(site_key, page_url, rqdata)
        elif self.service == "anticaptcha":
            return await self._solve_anticaptcha(site_key, page_url, rqdata)
        elif self.service == "capmonster":
            return await self._solve_capmonster(site_key, page_url, rqdata)
        
        return None
    
    async def _solve_capsolver(self, site_key: str, page_url: str, rqdata: Optional[str]) -> Optional[str]:
        """Solve using CapSolver API"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Create task
                task_payload = {
                    "clientKey": self.api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": site_key,
                    }
                }
                
                if rqdata:
                    task_payload["task"]["enterprisePayload"] = {"rqdata": rqdata}
                
                create_response = await client.post(
                    f"{self.base_urls['capsolver']}/createTask",
                    json=task_payload
                )
                create_result = create_response.json()
                
                if create_result.get("errorId") != 0:
                    print(f"[CapSolver] Create error: {create_result.get('errorDescription')}")
                    return None
                
                task_id = create_result.get("taskId")
                print(f"[CapSolver] Task ID: {task_id}")
                
                # Poll for result
                for attempt in range(60):  # 2 minutes max
                    await asyncio.sleep(2)
                    
                    result_response = await client.post(
                        f"{self.base_urls['capsolver']}/getTaskResult",
                        json={
                            "clientKey": self.api_key,
                            "taskId": task_id
                        }
                    )
                    result_data = result_response.json()
                    
                    if result_data.get("status") == "ready":
                        token = result_data.get("solution", {}).get("gRecaptchaResponse")
                        print(f"[CapSolver] Solved! ({attempt * 2}s)")
                        return token
                    elif result_data.get("status") == "failed":
                        print(f"[CapSolver] Failed: {result_data.get('errorDescription')}")
                        return None
                    
                    if attempt % 5 == 0:
                        print(f"[CapSolver] Waiting... ({attempt * 2}s)")
                
                print("[CapSolver] Timeout")
                return None
                
        except Exception as e:
            print(f"[CapSolver] Exception: {e}")
            return None
    
    async def _solve_2captcha(self, site_key: str, page_url: str, rqdata: Optional[str]) -> Optional[str]:
        """Solve using 2Captcha API"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Submit captcha
                params = {
                    "key": self.api_key,
                    "method": "hcaptcha",
                    "sitekey": site_key,
                    "pageurl": page_url,
                    "json": 1
                }
                
                if rqdata:
                    params["data"] = rqdata
                
                response = await client.post(
                    f"{self.base_urls['2captcha']}/in.php",
                    data=params
                )
                result = response.json()
                
                if result.get("status") != 1:
                    print(f"[2Captcha] Submit error: {result.get('request')}")
                    return None
                
                task_id = result["request"]
                print(f"[2Captcha] Task ID: {task_id}")
                
                # Poll for result
                for attempt in range(60):
                    await asyncio.sleep(2)
                    
                    check_response = await client.get(
                        f"{self.base_urls['2captcha']}/res.php",
                        params={
                            "key": self.api_key,
                            "action": "get",
                            "id": task_id,
                            "json": 1
                        }
                    )
                    check_result = check_response.json()
                    
                    if check_result.get("status") == 1:
                        print(f"[2Captcha] Solved! ({attempt * 2}s)")
                        return check_result["request"]
                    elif check_result.get("request") != "CAPCHA_NOT_READY":
                        print(f"[2Captcha] Error: {check_result.get('request')}")
                        return None
                    
                    if attempt % 5 == 0:
                        print(f"[2Captcha] Waiting... ({attempt * 2}s)")
                
                print("[2Captcha] Timeout")
                return None
                
        except Exception as e:
            print(f"[2Captcha] Exception: {e}")
            return None
    
    async def _solve_anticaptcha(self, site_key: str, page_url: str, rqdata: Optional[str]) -> Optional[str]:
        """Solve using AntiCaptcha API"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                task_payload = {
                    "clientKey": self.api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": site_key
                    }
                }
                
                create_response = await client.post(
                    f"{self.base_urls['anticaptcha']}/createTask",
                    json=task_payload
                )
                create_result = create_response.json()
                
                if create_result.get("errorId") != 0:
                    print(f"[AntiCaptcha] Error: {create_result.get('errorDescription')}")
                    return None
                
                task_id = create_result.get("taskId")
                print(f"[AntiCaptcha] Task ID: {task_id}")
                
                for attempt in range(60):
                    await asyncio.sleep(2)
                    
                    result_response = await client.post(
                        f"{self.base_urls['anticaptcha']}/getTaskResult",
                        json={
                            "clientKey": self.api_key,
                            "taskId": task_id
                        }
                    )
                    result_data = result_response.json()
                    
                    if result_data.get("status") == "ready":
                        token = result_data.get("solution", {}).get("gRecaptchaResponse")
                        print(f"[AntiCaptcha] Solved! ({attempt * 2}s)")
                        return token
                    
                    if attempt % 5 == 0:
                        print(f"[AntiCaptcha] Waiting... ({attempt * 2}s)")
                
                return None
                
        except Exception as e:
            print(f"[AntiCaptcha] Exception: {e}")
            return None
    
    async def _solve_capmonster(self, site_key: str, page_url: str, rqdata: Optional[str]) -> Optional[str]:
        """Solve using CapMonster API"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                task_payload = {
                    "clientKey": self.api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": site_key
                    }
                }
                
                create_response = await client.post(
                    f"{self.base_urls['capmonster']}/createTask",
                    json=task_payload
                )
                create_result = create_response.json()
                
                if create_result.get("errorId") != 0:
                    print(f"[CapMonster] Error: {create_result.get('errorDescription')}")
                    return None
                
                task_id = create_result.get("taskId")
                print(f"[CapMonster] Task ID: {task_id}")
                
                for attempt in range(60):
                    await asyncio.sleep(2)
                    
                    result_response = await client.post(
                        f"{self.base_urls['capmonster']}/getTaskResult",
                        json={
                            "clientKey": self.api_key,
                            "taskId": task_id
                        }
                    )
                    result_data = result_response.json()
                    
                    if result_data.get("status") == "ready":
                        token = result_data.get("solution", {}).get("gRecaptchaResponse")
                        print(f"[CapMonster] Solved! ({attempt * 2}s)")
                        return token
                    
                    if attempt % 5 == 0:
                        print(f"[CapMonster] Waiting... ({attempt * 2}s)")
                
                return None
                
        except Exception as e:
            print(f"[CapMonster] Exception: {e}")
            return None
    
    async def get_balance(self) -> float:
        """Return provider balance and distinguish invalid credentials from network failure."""
        if not self.api_key:
            raise ValueError("Provider API key is not configured")
        if self.service not in self.base_urls:
            raise ValueError("Unsupported captcha provider")

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                if self.service == "2captcha":
                    response = await client.get(
                        f"{self.base_urls['2captcha']}/res.php",
                        params={"key": self.api_key, "action": "getbalance", "json": 1},
                    )
                    response.raise_for_status()
                    result = response.json()
                    if result.get("status") != 1:
                        reason = str(result.get("request") or "Provider rejected the request")[:200]
                        raise ValueError(f"2Captcha rejected the API key/request: {reason}")
                    return float(result.get("request", 0))

                response = await client.post(
                    f"{self.base_urls[self.service]}/getBalance",
                    json={"clientKey": self.api_key},
                )
                response.raise_for_status()
                result = response.json()
                if int(result.get("errorId", 0) or 0) != 0:
                    reason = str(result.get("errorDescription") or result.get("errorCode") or "Provider rejected the request")[:200]
                    raise ValueError(f"Provider rejected the API key/request: {reason}")
                if "balance" not in result:
                    raise ValueError("Provider response did not contain a balance")
                return float(result.get("balance", 0))
        except ValueError:
            raise
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Provider returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, TimeoutError) as exc:
            raise RuntimeError(f"Could not reach provider: {type(exc).__name__}") from exc
        except Exception as exc:
            raise RuntimeError(f"Could not read provider balance: {type(exc).__name__}") from exc

