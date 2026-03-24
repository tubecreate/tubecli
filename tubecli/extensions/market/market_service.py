"""
Market CLI Service — HTTP client for PHP Market API.
Mirrors the pattern from python-video-studio marketplace_service.py.
"""
import requests
import json
from typing import List, Dict, Any, Optional

API_BASE = "https://api.tubecreate.com/api/market-cli"
TIMEOUT = 15


class MarketService:
    def __init__(self):
        self.api_base = API_BASE

    def list_items(
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
        """Fetch marketplace items with filters."""
        url = f"{self.api_base}/list.php"
        params = {"page": page, "limit": limit, "sort": sort, "mode": mode}

        if category:
            params["category"] = category
        if search:
            params["search"] = search
        if min_price is not None:
            params["min_price"] = min_price
        if max_price is not None:
            params["max_price"] = max_price
        if min_rating is not None:
            params["min_rating"] = min_rating
        if tags:
            params["tags"] = tags
        if user_id:
            params["user_id"] = user_id

        try:
            response = requests.get(url, params=params, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"[MarketCLI] List error: {e}")

        return {"status": "error", "data": [], "pagination": {}}

    def get_detail(self, public_id: str) -> Dict:
        """Get item detail with reviews."""
        url = f"{self.api_base}/detail.php"
        try:
            response = requests.get(url, params={"id": public_id}, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"[MarketCLI] Detail error: {e}")
        return {"status": "error"}

    def download_item_data(self, public_id: str) -> Dict:
        """Download item_data (packaged files) for a marketplace item."""
        url = f"{self.api_base}/download-data.php"
        try:
            response = requests.get(url, params={"id": public_id}, timeout=30)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"[MarketCLI] Download data error: {e}")
        return {"status": "error"}

    def upload_item(
        self,
        token: str,
        title: str,
        description: str,
        category: str,
        price: float,
        item_data: str,
        visibility: str = "PUBLIC",
        tags: list = None,
        version: str = "1.0.0",
        thumbnail_url: str = None,
    ) -> Dict:
        """Upload a new item to marketplace."""
        url = f"{self.api_base}/upload.php"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "title": title,
            "description": description,
            "category": category,
            "price": price,
            "item_data": item_data,
            "visibility": visibility,
            "tags": tags or [],
            "version": version,
        }
        if thumbnail_url:
            payload["thumbnail_url"] = thumbnail_url

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            return response.json()
        except Exception as e:
            print(f"[MarketCLI] Upload error: {e}")
        return {"status": "error", "error": str(e)}

    def buy_item(self, token: str, item_id: str) -> Dict:
        """Purchase an item."""
        url = f"{self.api_base}/buy.php"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"item_id": item_id}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            return response.json()
        except Exception as e:
            print(f"[MarketCLI] Buy error: {e}")
        return {"status": "error", "message": str(e)}

    def delete_item(self, token: str, public_id: str) -> Dict:
        """Delete a listing."""
        url = f"{self.api_base}/delete.php"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"public_id": public_id}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            return response.json()
        except Exception as e:
            print(f"[MarketCLI] Delete error: {e}")
        return {"status": "error", "message": str(e)}

    def get_reviews(self, item_id: str) -> Dict:
        """Get reviews for an item."""
        url = f"{self.api_base}/review.php"
        try:
            response = requests.get(url, params={"item_id": item_id}, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"[MarketCLI] Reviews error: {e}")
        return {"status": "error", "data": []}

    def post_review(self, token: str, item_id: str, rating: int, comment: str = "") -> Dict:
        """Submit a review."""
        url = f"{self.api_base}/review.php"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"item_id": item_id, "rating": rating, "comment": comment}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            return response.json()
        except Exception as e:
            print(f"[MarketCLI] Review submit error: {e}")
        return {"status": "error", "message": str(e)}

    def get_categories(self) -> Dict:
        """Get categories with counts."""
        url = f"{self.api_base}/categories.php"
        try:
            response = requests.get(url, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"[MarketCLI] Categories error: {e}")
        return {"status": "error", "categories": []}

    def get_user_profile(self, token: str) -> Dict:
        """Get user profile."""
        url = f"{self.api_base}/user.php"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"[MarketCLI] Profile error: {e}")
        return {"status": "error"}

    def link_google(self, token: str, google_id: str, google_email: str, google_name: str = None, google_avatar: str = None) -> Dict:
        """Link Google account to profile."""
        url = f"{self.api_base}/user.php?action=link-google"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "google_id": google_id,
            "google_email": google_email,
            "google_name": google_name,
            "google_avatar": google_avatar,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            return response.json()
        except Exception as e:
            print(f"[MarketCLI] Link Google error: {e}")
        return {"status": "error", "error": str(e)}


market_service = MarketService()
