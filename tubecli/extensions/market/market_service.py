"""
Market CLI Service — HTTP client for PHP Market API.
Mirrors the pattern from python-video-studio marketplace_service.py.
"""
import json
from typing import List, Dict, Any, Optional

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    import requests
    _HTTPX_AVAILABLE = False

API_BASE = "https://api.tubecreate.com/api/market-cli"
TIMEOUT = 15
TIMEOUT_LONG = 60  # For upload/download large extensions


class MarketService:
    def __init__(self):
        self.api_base = API_BASE

    async def _get(self, url: str, params: dict = None, headers: dict = None) -> dict:
        """Non-blocking GET using httpx or asyncio.to_thread."""
        if _HTTPX_AVAILABLE:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
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
        """Non-blocking POST using httpx or asyncio.to_thread."""
        _timeout = timeout or TIMEOUT
        if _HTTPX_AVAILABLE:
            async with httpx.AsyncClient(timeout=_timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
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
            return await self._get(url, params=params)
        except Exception as e:
            print(f"[MarketCLI] List error: {e}")

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
                          tags: list = None, version: str = "1.0.0", thumbnail_url: str = None) -> Dict:
        """Upload a new item to marketplace."""
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"title": title, "description": description, "category": category,
                   "price": price, "item_data": item_data, "visibility": visibility,
                   "tags": tags or [], "version": version}
        if thumbnail_url:
            payload["thumbnail_url"] = thumbnail_url

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
                            error_msg = r.text[:200]
                        print(f"[MarketCLI] Upload HTTP {r.status_code}: {error_msg}")
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
                        print(f"[MarketCLI] Upload HTTP {r.status_code}: {error_msg}")
                        return {"status": "error", "error": error_msg}
                    return r.json()
                return await asyncio.to_thread(_sync)
        except Exception as e:
            print(f"[MarketCLI] Upload error: {e}")
            return {"status": "error", "error": f"Upload failed: {str(e)}"}

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
        """Get categories with counts."""
        try:
            return await self._get(f"{self.api_base}/categories.php")
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


market_service = MarketService()
