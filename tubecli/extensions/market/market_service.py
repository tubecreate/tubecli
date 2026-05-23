"""
Market CLI Service — HTTP client for PHP Market API.
Mirrors the pattern from python-video-studio marketplace_service.py.
"""
import os
import json
from typing import List, Dict, Any, Optional
from tubecli.config import DATA_DIR

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    import requests
    _HTTPX_AVAILABLE = False

API_BASE = "https://tubecli.zeabur.app/api/market-cli"
TIMEOUT = 15
TIMEOUT_LONG = 60  # For upload/download large extensions


class MarketService:
    def __init__(self):
        self.api_base = API_BASE
        self._client = None  # Lazy-init persistent httpx client
        self._cache = {}     # In-memory cache: key -> (data, expires_at)

    def _get_client(self):
        """Get or create persistent httpx AsyncClient with connection pooling."""
        if _HTTPX_AVAILABLE:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=TIMEOUT,
                    http2=False,
                    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                )
            return self._client
        return None

    def _cache_get(self, key: str):
        """Get cached value if not expired."""
        import time
        entry = self._cache.get(key)
        if entry and entry[1] > time.time():
            return entry[0]
        return None

    def _cache_set(self, key: str, data, ttl_seconds: int = 60):
        """Set cache with TTL."""
        import time
        self._cache[key] = (data, time.time() + ttl_seconds)

    async def _get(self, url: str, params: dict = None, headers: dict = None) -> dict:
        """Non-blocking GET using persistent httpx client or asyncio.to_thread."""
        if _HTTPX_AVAILABLE:
            client = self._get_client()
            r = await client.get(url, params=params, headers=headers or {})
            r.raise_for_status()
            return r.json()
        else:
            import asyncio
            import requests as _req
            def _sync():
                r = _req.get(url, params=params, headers=headers, timeout=TIMEOUT)
                r.raise_for_status()
                return r.json()
            return await asyncio.to_thread(_sync)

    async def _post(self, url: str, payload: dict, headers: dict = None, timeout: int = None) -> dict:
        """Non-blocking POST using persistent httpx client or asyncio.to_thread."""
        _timeout = timeout or TIMEOUT
        if _HTTPX_AVAILABLE:
            client = self._get_client()
            r = await client.post(url, json=payload, headers=headers, timeout=_timeout)
            r.raise_for_status()
            return r.json()
        else:
            import asyncio
            import requests as _req
            def _sync():
                r = _req.post(url, json=payload, headers=headers, timeout=_timeout)
                r.raise_for_status()
                return r.json()
            return await asyncio.to_thread(_sync)


    async def list_items(
        self,
        category: str = None,
        search: str = None,
        sort: str = "newest",
        min_price: float = None,
        max_price: float = None,
        min_rating: float = None,
        tags: str = None,
        user_id: str = None,
        mode: str = "public",
        page: int = 1,
        limit: int = 20,
    ) -> Dict:
        """Fetch marketplace items with filters (non-blocking)."""
        url = f"{self.api_base}/list.php"
        params = {"page": page, "limit": limit, "sort": sort, "mode": mode}
        if category: params["category"] = category
        if search: params["search"] = search
        if min_price is not None: params["min_price"] = min_price
        if max_price is not None: params["max_price"] = max_price
        if min_rating is not None: params["min_rating"] = min_rating
        if tags: params["tags"] = tags
        if user_id: params["user_id"] = user_id

        try:
            # Check in-memory cache first (fast path, 60s TTL)
            import hashlib
            param_str = json.dumps(params, sort_keys=True)
            cache_key = f"list_{hashlib.md5(param_str.encode()).hexdigest()}"
            cached = self._cache_get(cache_key)
            if cached:
                return cached

            result = await self._get(url, params=params)
            cache_hash = cache_key.replace("list_", "")
            cache_file = os.path.join(str(DATA_DIR), f"market_cache_{cache_hash}.json")
            
            if result and result.get("status") == "success":
                # Save to in-memory cache (60s TTL)
                self._cache_set(cache_key, result, ttl_seconds=60)
                # Save to disk cache (offline fallback)
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False)
                except Exception as e:
                    print(f"[MarketCLI] Save cache warning: {e}")
            return result
        except Exception as e:
            print(f"[MarketCLI] List error ({e}). Trying to load from cache...")
            import hashlib
            param_str = json.dumps(params, sort_keys=True)
            cache_hash = hashlib.md5(param_str.encode()).hexdigest()
            cache_file = os.path.join(str(DATA_DIR), f"market_cache_{cache_hash}.json")
            
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached_result = json.load(f)
                        cached_result["_is_cached"] = True
                        return cached_result
                except Exception as ce:
                    print(f"[MarketCLI] Cache read error: {ce}")

        return {"status": "error", "data": [], "pagination": {}}

    async def get_detail(self, public_id: str) -> Dict:
        """Get item detail with reviews."""
        try:
            return await self._get(f"{self.api_base}/detail.php", params={"id": public_id})
        except Exception as e:
            print(f"[MarketCLI] Detail error: {e}")
        return {"status": "error"}

    async def download_item_data(self, public_id: str) -> Dict:
        """Download item_data (packaged files) for a marketplace item."""
        try:
            return await self._get(f"{self.api_base}/download-data.php", params={"id": public_id})
        except Exception as e:
            print(f"[MarketCLI] Download data error: {e}")
        return {"status": "error"}

    async def upload_item(self, token: str, title: str, description: str, category: str,
                          price: float, item_data: str, visibility: str = "PUBLIC",
                          tags: list = None, version: str = "1.0.0", thumbnail_url: str = None, git_url: str = None) -> Dict:
        """Upload a new item to marketplace."""
        self._cache.clear()
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"title": title, "description": description, "category": category,
                   "price": price, "item_data": item_data, "visibility": visibility,
                   "tags": tags or [], "version": version}
        if thumbnail_url:
            payload["thumbnail_url"] = thumbnail_url
        if git_url:
            payload["git_url"] = git_url

        # Log payload size for debugging
        import json as _json
        payload_size = len(_json.dumps(payload))
        print(f"[MarketCLI] Upload payload size: {payload_size / 1024:.1f} KB")

        try:
            url = f"{self.api_base}/upload.php"
            if _HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=TIMEOUT_LONG) as client:
                    r = await client.post(url, json=payload, headers=headers)
                    if r.status_code >= 400:
                        try:
                            err_data = r.json()
                            error_msg = err_data.get("error", r.text[:200])
                        except Exception:
                            error_msg = f"Server error (HTTP {r.status_code}). Server có thể đang bảo trì."
                        print(f"[MarketCLI] Upload HTTP {r.status_code}: {error_msg}")
                        return {"status": "error", "error": error_msg}
                    # Guard: server returned 200 but might be HTML (Cloudflare)
                    content_type = r.headers.get("content-type", "")
                    if "text/html" in content_type:
                        print(f"[MarketCLI] Upload got HTML response (likely Cloudflare): {r.text[:200]}")
                        return {"status": "error", "error": "Market server không phản hồi. Vui lòng thử lại sau."}
                    return r.json()
            else:
                import asyncio
                import requests as _req
                def _sync():
                    r = _req.post(url, json=payload, headers=headers, timeout=TIMEOUT_LONG)
                    if r.status_code >= 400:
                        try:
                            err_data = r.json()
                            error_msg = err_data.get("error", r.text[:200])
                        except Exception:
                            error_msg = r.text[:200]
                        print(f"[MarketCLI] Upload HTTP {r.status_code}: {error_msg}")
                        return {"status": "error", "error": error_msg}
                    return r.json()
                return await asyncio.to_thread(_sync)
        except Exception as e:
            print(f"[MarketCLI] Upload error: {e}")
            return {"status": "error", "error": f"Upload failed: {str(e)}"}

    async def update_item(self, token: str, public_id: str, title: str, description: str,
                          category: str, price: float, item_data: str, visibility: str = "PUBLIC",
                          tags: list = None, version: str = "1.0.0",
                          thumbnail_url: str = None, git_url: str = None) -> Dict:
        """Update an existing marketplace item."""
        self._cache.clear()
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "public_id": public_id,
            "title": title, "description": description, "category": category,
            "price": price, "item_data": item_data, "visibility": visibility,
            "tags": tags or [], "version": version
        }
        if thumbnail_url:
            payload["thumbnail_url"] = thumbnail_url
        if git_url:
            payload["git_url"] = git_url
        try:
            url = f"{self.api_base}/update.php"
            if _HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=TIMEOUT_LONG) as client:
                    r = await client.post(url, json=payload, headers=headers)
                    if r.status_code >= 400:
                        try:
                            err_data = r.json()
                            error_msg = err_data.get("error", r.text[:200])
                        except Exception:
                            error_msg = r.text[:200]
                        print(f"[MarketCLI] Update HTTP {r.status_code}: {error_msg}")
                        return {"status": "error", "error": error_msg}
                    return r.json()
            else:
                import asyncio
                import requests as _req
                def _sync():
                    r = _req.post(url, json=payload, headers=headers, timeout=TIMEOUT_LONG)
                    if r.status_code >= 400:
                        try:
                            err_data = r.json()
                            error_msg = err_data.get("error", r.text[:200])
                        except Exception:
                            error_msg = r.text[:200]
                        return {"status": "error", "error": error_msg}
                    return r.json()
                return await asyncio.to_thread(_sync)
        except Exception as e:
            print(f"[MarketCLI] Update error: {e}")
            return {"status": "error", "error": f"Update failed: {str(e)}"}

    async def buy_item(self, token: str, item_id: str) -> Dict:
        """Purchase an item."""
        try:
            return await self._post(f"{self.api_base}/buy.php",
                                    payload={"item_id": item_id},
                                    headers={"Authorization": f"Bearer {token}"})
        except Exception as e:
            print(f"[MarketCLI] Buy error: {e}")
            return {"status": "error", "message": str(e)}


    async def get_reviews(self, item_id: str) -> Dict:
        """Get reviews for an item."""
        try:
            return await self._get(f"{self.api_base}/review.php", params={"item_id": item_id})
        except Exception as e:
            print(f"[MarketCLI] Reviews error: {e}")
        return {"status": "error", "data": []}

    async def delete_item(self, item_id: str, token: str) -> Dict:
        """Delete an item from marketplace."""
        self._cache.clear()
        try:
            return await self._post(f"{self.api_base}/delete.php",
                                    payload={"public_id": item_id},
                                    headers={"Authorization": f"Bearer {token}"})
        except Exception as e:
            print(f"[MarketCLI] Delete error: {e}")
            return {"status": "error", "message": str(e)}

    async def add_review(self, item_id: str, rating: float, comment: str, token: str) -> Dict:
        """Submit a review."""
        try:
            return await self._post(f"{self.api_base}/review.php",
                                    payload={"item_id": item_id, "rating": rating, "comment": comment},
                                    headers={"Authorization": f"Bearer {token}"})
        except Exception as e:
            print(f"[MarketCLI] Review submit error: {e}")
        return {"status": "error", "message": str(e)}

    async def get_categories(self) -> Dict:
        """Get categories with counts (cached 5 min)."""
        cached = self._cache_get("categories")
        if cached:
            return cached
        try:
            result = await self._get(f"{self.api_base}/categories.php")
            if result and result.get("status") == "success":
                self._cache_set("categories", result, ttl_seconds=300)
            return result
        except Exception as e:
            print(f"[MarketCLI] Categories error: {e}")
        return {"status": "error", "categories": []}

    async def get_user_profile(self, token: str) -> Dict:
        """Get user profile."""
        try:
            return await self._get(f"{self.api_base}/user.php",
                                   headers={"Authorization": f"Bearer {token}"})
        except Exception as e:
            print(f"[MarketCLI] Profile error: {e}")
        return {"status": "error"}

    async def link_google(self, token: str, google_id: str, google_email: str,
                          google_name: str = None, google_avatar: str = None) -> Dict:
        """Link Google account to profile."""
        payload = {"google_id": google_id, "google_email": google_email,
                   "google_name": google_name, "google_avatar": google_avatar}
        try:
            return await self._post(f"{self.api_base}/user.php?action=link-google",
                                    payload=payload,
                                    headers={"Authorization": f"Bearer {token}"})
        except Exception as e:
            print(f"[MarketCLI] Link Google error: {e}")
        return {"status": "error", "error": str(e)}


    async def check_name_exists(self, title: str, token: str = None) -> Dict:
        """Check if an item with the same title already exists on the market.
        Returns: {exists: bool, item: {...}, is_owner: bool}
        """
        try:
            # Search by exact title
            result = await self.list_items(search=title, limit=50)
            if result.get("status") != "success":
                return {"exists": False}

            items = result.get("data", [])
            title_lower = title.strip().lower().replace(" ", "_")

            for item in items:
                item_title = (item.get("title") or "").strip().lower().replace(" ", "_")
                if item_title == title_lower:
                    # Found exact match — check ownership
                    is_owner = False
                    if token:
                        try:
                            profile = await self.get_user_profile(token)
                            user_id = (
                                profile.get("profile", {}).get("user_id")
                                or profile.get("user", {}).get("user_id")
                                or profile.get("user_id")
                            )
                            item_seller = item.get("seller_id") or item.get("user_id")
                            if user_id and item_seller and str(user_id) == str(item_seller):
                                is_owner = True
                        except Exception:
                            pass

                    return {
                        "exists": True,
                        "item": item,
                        "public_id": item.get("public_id"),
                        "is_owner": is_owner,
                        "owner_name": item.get("seller_name") or item.get("author") or "Unknown",
                    }

            return {"exists": False}
        except Exception as e:
            print(f"[MarketCLI] check_name_exists error: {e}")
            return {"exists": False}


market_service = MarketService()
