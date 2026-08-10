"""
Riot Account Creator Service - Complete Automation
"""
from playwright.async_api import async_playwright, Page
import asyncio
import httpx
import random
import string
import json
from typing import Dict, Optional
from datetime import datetime, timedelta

class RiotAccountCreator:
    def __init__(
        self,
        captcha_service: str,
        captcha_api_key: str,
        username_min: int = 6,
        username_max: int = 12,
        password_length: int = 12,
        fixed_password: Optional[str] = None,
    ):
        self.captcha_service = captcha_service
        self.captcha_api_key = captcha_api_key
        self.sitekey = "019f1553-3845-481c-a6f5-5a60ccf6d830"
        self.username_min = max(3, int(username_min))
        self.username_max = max(self.username_min, int(username_max))
        self.password_length = max(8, int(password_length))
        self.fixed_password = fixed_password or None

    def generate_username(self):
        """Generate a username using the saved length range."""
        length = random.randint(self.username_min, self.username_max)
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def generate_password(self):
        """Generate a password using the saved length, unless a fixed value is configured."""
        if self.fixed_password:
            return self.fixed_password
        chars = string.ascii_letters + string.digits + "!@#$%"
        password = [
            random.choice(string.ascii_lowercase),
            random.choice(string.ascii_uppercase),
            random.choice(string.digits),
            random.choice("!@#$%")
        ]
        password += random.choices(chars, k=max(0, self.password_length - len(password)))
        random.shuffle(password)
        return ''.join(password)
    
    def generate_dob(self):
        """Generate date of birth (18-25 years old)"""
        start = datetime.now() - timedelta(days=365*25)
        end = datetime.now() - timedelta(days=365*18)
        random_days = random.randint(0, (end - start).days)
        dob = start + timedelta(days=random_days)
        return dob.strftime("%Y-%m-%d")
    
    async def solve_hcaptcha(self, page_url: str) -> Optional[str]:
        """Solve hCaptcha using selected service"""
        
        if self.captcha_service == "capsolver":
            return await self._solve_capsolver(page_url)
        elif self.captcha_service == "2captcha":
            return await self._solve_2captcha(page_url)
        elif self.captcha_service == "anticaptcha":
            return await self._solve_anticaptcha(page_url)
        
        return None
    
    async def _solve_capsolver(self, page_url: str) -> Optional[str]:
        """Solve with CapSolver"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "clientKey": self.captcha_api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyLess",
                        "websiteURL": page_url,
                        "websiteKey": self.sitekey
                    }
                }
                
                response = await client.post("https://api.capsolver.com/createTask", json=payload)
                result = response.json()
                
                if result.get("errorId") != 0:
                    return None
                
                task_id = result["taskId"]
                
                # Poll for result
                for _ in range(60):
                    await asyncio.sleep(2)
                    
                    check_response = await client.post(
                        "https://api.capsolver.com/getTaskResult",
                        json={"clientKey": self.captcha_api_key, "taskId": task_id}
                    )
                    check_result = check_response.json()
                    
                    if check_result.get("status") == "ready":
                        return check_result["solution"]["gRecaptchaResponse"]
                
                return None
        except:
            return None
    
    async def _solve_2captcha(self, page_url: str) -> Optional[str]:
        """Solve with 2Captcha"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Submit
                submit = await client.post(
                    "https://2captcha.com/in.php",
                    data={
                        "key": self.captcha_api_key,
                        "method": "hcaptcha",
                        "sitekey": self.sitekey,
                        "pageurl": page_url,
                        "json": 1
                    }
                )
                submit_result = submit.json()
                
                if submit_result.get("status") != 1:
                    return None
                
                task_id = submit_result["request"]
                
                # Poll
                for _ in range(60):
                    await asyncio.sleep(2)
                    
                    check = await client.get(
                        "https://2captcha.com/res.php",
                        params={
                            "key": self.captcha_api_key,
                            "action": "get",
                            "id": task_id,
                            "json": 1
                        }
                    )
                    check_result = check.json()
                    
                    if check_result.get("status") == 1:
                        return check_result["request"]
                
                return None
        except:
            return None
    
    async def _solve_anticaptcha(self, page_url: str) -> Optional[str]:
        """Solve with AntiCaptcha"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Create task
                payload = {
                    "clientKey": self.captcha_api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": self.sitekey
                    }
                }
                
                response = await client.post("https://api.anti-captcha.com/createTask", json=payload)
                result = response.json()
                
                if result.get("errorId") != 0:
                    return None
                
                task_id = result["taskId"]
                
                # Poll
                for _ in range(60):
                    await asyncio.sleep(2)
                    
                    check = await client.post(
                        "https://api.anti-captcha.com/getTaskResult",
                        json={"clientKey": self.captcha_api_key, "taskId": task_id}
                    )
                    check_result = check.json()
                    
                    if check_result.get("status") == "ready":
                        return check_result["solution"]["gRecaptchaResponse"]
                
                return None
        except:
            return None
    
    async def create_account(
        self,
        email: str,
        email_password: str,
        proxy: Optional[Dict] = None,
        progress_callback = None
    ) -> Dict:
        """Create a Riot account - HEADLESS (no popup)"""
        
        username = self.generate_username()
        password = self.generate_password()
        dob = self.generate_dob()
        
        if progress_callback:
            await progress_callback("STARTING", f"Creating account {username}")
        
        async with async_playwright() as p:
            browser = None
            try:
                # Launch with conservative browser flags. Avoid disabling Chromium's
                # sandbox/web-security protections in the default configuration.
                browser_args = {
                    "headless": True,
                    "args": [
                        '--disable-dev-shm-usage',
                        '--no-first-run',
                        '--no-default-browser-check'
                    ]
                }
                
                if proxy:
                    browser_args["proxy"] = {
                        "server": f"http://{proxy['ip']}:{proxy['port']}",
                        "username": proxy.get("username"),
                        "password": proxy.get("password")
                    }
                
                browser = await p.chromium.launch(**browser_args)
                
                context = await browser.new_context(
                    locale='tr-TR',
                    timezone_id='Europe/Istanbul',
                    geolocation={'latitude': 41.0082, 'longitude': 28.9784},
                    permissions=['geolocation'],
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                
                page = await context.new_page()
                
                if progress_callback:
                    await progress_callback("NAVIGATING", "Loading signup page")
                
                # Navigate
                await page.goto(
                    "https://signup.leagueoflegends.com/tr/signup/index",
                    wait_until="networkidle",
                    timeout=60000
                )
                
                await asyncio.sleep(3)
                
                if progress_callback:
                    await progress_callback("SOLVING_CAPTCHA", "Solving hCaptcha")
                
                # Solve captcha
                captcha_token = await self.solve_hcaptcha(page.url)
                
                if not captcha_token:
                    return {
                        "status": "FAILED",
                        "error": "CAPTCHA_FAILED",
                        "username": username
                    }
                
                if progress_callback:
                    await progress_callback("FILLING_FORM", "Filling signup form")
                
                # Wait for email field
                await page.wait_for_selector('input[name="email_address"]', timeout=10000)
                
                # Type email
                await page.type('input[name="email_address"]', email, delay=random.randint(50, 150))
                await asyncio.sleep(random.uniform(0.5, 1.0))
                
                # Inject captcha token
                await page.evaluate(f"""
                    document.querySelector('[name="h-captcha-response"]').value = '{captcha_token}';
                    document.querySelector('[name="g-recaptcha-response"]').value = '{captcha_token}';
                """)
                
                await asyncio.sleep(1)
                
                if progress_callback:
                    await progress_callback("SUBMITTING", "Submitting form")
                
                # Submit
                submit_button = await page.query_selector('button[type="submit"]')
                if submit_button:
                    await submit_button.click()
                else:
                    await page.click('button:has-text("İleri"), button:has-text("Continue")')
                
                # Wait for response
                await asyncio.sleep(5)
                
                # Check for errors
                error = await page.query_selector('.error, [class*="error"], [class*="Error"]')
                if error:
                    error_text = await error.inner_text()
                    return {
                        "status": "FAILED",
                        "error": error_text,
                        "username": username
                    }
                
                # Success
                if progress_callback:
                    await progress_callback("SUCCESS", f"Account {username} created!")
                
                return {
                    "status": "SUCCESS",
                    "username": username,
                    "password": password,
                    "email": email,
                    "email_password": email_password,
                    "dob": dob,
                    "region": proxy.get("region", "TR") if proxy else "TR"
                }
                
            except Exception as e:
                return {
                    "status": "FAILED",
                    "error": str(e),
                    "username": username
                }
                
            finally:
                if browser is not None:
                    await browser.close()
