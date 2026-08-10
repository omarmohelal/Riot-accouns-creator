"""
Account Checker - Verify account status and region
"""
import httpx
import asyncio
from typing import Dict, Optional
from datetime import datetime

class AccountChecker:
    def __init__(self):
        self.session = None
    
    async def check_account(
        self,
        username: str,
        password: str,
        region: Optional[str] = None
    ) -> Dict:
        """
        Check if account is valid and get its details
        """
        
        try:
            print(f"🔍 Checking account: {username}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: Try to authenticate
                auth_result = await self._authenticate(client, username, password, region)
                
                if not auth_result.get('success'):
                    return {
                        "username": username,
                        "status": "INVALID",
                        "error": auth_result.get('error', 'Authentication failed'),
                        "checked_at": datetime.now().isoformat()
                    }
                
                # Step 2: Get account details
                access_token = auth_result.get('access_token')
                account_details = await self._get_account_details(client, access_token)
                
                # Step 3: Detect region
                detected_region = await self._detect_region(client, access_token)
                
                return {
                    "username": username,
                    "status": "VALID",
                    "region": detected_region or region or "UNKNOWN",
                    "level": account_details.get('level', 1),
                    "summoner_name": account_details.get('summoner_name', username),
                    "blue_essence": account_details.get('blue_essence', 0),
                    "rp": account_details.get('rp', 0),
                    "email_verified": account_details.get('email_verified', False),
                    "banned": account_details.get('banned', False),
                    "restrictions": account_details.get('restrictions', []),
                    "checked_at": datetime.now().isoformat()
                }
                
        except Exception as e:
            print(f"❌ Check failed for {username}: {e}")
            return {
                "username": username,
                "status": "CHECK_FAILED",
                "error": str(e),
                "checked_at": datetime.now().isoformat()
            }
    
    async def _authenticate(
        self,
        client: httpx.AsyncClient,
        username: str,
        password: str,
        region: Optional[str]
    ) -> Dict:
        """Authenticate and get access token"""
        
        try:
            # Riot authentication endpoint
            auth_url = "https://auth.riotgames.com/api/v1/authorization"
            
            # Authentication payload
            payload = {
                "client_id": "riot-client",
                "nonce": "oYnVwCSrlS5IHKh7iI16oQ",
                "redirect_uri": "http://localhost/redirect",
                "response_type": "token id_token",
                "scope": "openid link ban lol_region",
                "username": username,
                "password": password
            }
            
            response = await client.put(auth_url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('type') == 'response':
                    # Extract token from response
                    uri = data.get('response', {}).get('parameters', {}).get('uri', '')
                    
                    # Parse access token from URI
                    if 'access_token=' in uri:
                        access_token = uri.split('access_token=')[1].split('&')[0]
                        
                        return {
                            "success": True,
                            "access_token": access_token
                        }
                
                return {
                    "success": False,
                    "error": "Invalid credentials"
                }
            
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _get_account_details(
        self,
        client: httpx.AsyncClient,
        access_token: str
    ) -> Dict:
        """Get account details using access token"""
        
        try:
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            
            # Get account info
            response = await client.get(
                "https://account.riotgames.com/api/account/v1/user",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                
                return {
                    "summoner_name": data.get('username', ''),
                    "email_verified": data.get('email_verified', False),
                    "level": data.get('account_level', 1),
                    "blue_essence": 0,  # Requires game-specific API
                    "rp": 0,  # Requires game-specific API
                    "banned": False,
                    "restrictions": []
                }
            
        except Exception as e:
            print(f"Failed to get account details: {e}")
        
        return {}
    
    async def _detect_region(
        self,
        client: httpx.AsyncClient,
        access_token: str
    ) -> Optional[str]:
        """Detect account region"""
        
        try:
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            
            # Try to get region from account settings
            response = await client.get(
                "https://account.riotgames.com/api/account/v1/user",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Region might be in different fields
                region = (
                    data.get('region') or
                    data.get('preferred_region') or
                    data.get('locale', '').split('_')[1] if '_' in data.get('locale', '') else None
                )
                
                return region
                
        except Exception as e:
            print(f"Region detection failed: {e}")
        
        return None
    
    async def batch_check(
        self,
        accounts: list[Dict],
        concurrency: int = 5
    ) -> list[Dict]:
        """Check multiple accounts concurrently"""
        
        print(f"🔍 Checking {len(accounts)} accounts with concurrency {concurrency}")
        
        semaphore = asyncio.Semaphore(concurrency)
        results = []
        
        async def check_with_semaphore(account):
            async with semaphore:
                result = await self.check_account(
                    account['username'],
                    account['password'],
                    account.get('region')
                )
                results.append(result)
                
                # Progress
                print(f"✓ Checked {len(results)}/{len(accounts)}")
        
        tasks = [check_with_semaphore(acc) for acc in accounts]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Summary
        valid = len([r for r in results if r['status'] == 'VALID'])
        invalid = len([r for r in results if r['status'] == 'INVALID'])
        failed = len([r for r in results if r['status'] == 'CHECK_FAILED'])
        
        print(f"\n📊 Check Results:")
        print(f"   ✅ Valid: {valid}")
        print(f"   ❌ Invalid: {invalid}")
        print(f"   ⚠️ Failed: {failed}")
        
        return results
    
    async def quick_check(self, username: str, password: str) -> bool:
        """Quick check if account is valid (just login test)"""
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                result = await self._authenticate(client, username, password, None)
                return result.get('success', False)
        except:
            return False
