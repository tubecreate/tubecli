"""
Marketplace API routes — Proxy to PHP backend.
"""
from fastapi import APIRouter, HTTPException, Header
from typing import Optional
from pydantic import BaseModel
from tubecli.extensions.market.market_service import market_service

router = APIRouter(prefix="/api/v1/market", tags=["market"])


# ── Pydantic Models ──

class UploadRequest(BaseModel):
    title: str
    description: str = ""
    category: str  # extension, node, skill, model3d
    price: float = 0
    item_data: str  # JSON string
    visibility: str = "PUBLIC"
    tags: list = []
    version: str = "1.0.0"
    thumbnail_url: Optional[str] = None


class BuyRequest(BaseModel):
    item_id: str  # public_id


class ReviewRequest(BaseModel):
    item_id: str
    rating: int  # 1-5
    comment: str = ""


class DeleteRequest(BaseModel):
    public_id: str


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None


class GoogleLinkRequest(BaseModel):
    google_id: str
    google_email: str
    google_name: Optional[str] = None
    google_avatar: Optional[str] = None


# ── Helper ──

def _get_token(authorization: Optional[str]) -> str:
    """Get Bearer token from Authorization header. Raises 401 if missing."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bạn cần đăng nhập để thực hiện thao tác này")
    return authorization.replace("Bearer ", "")


# ── Items ──

@router.get("/items")
async def list_items(
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "newest",
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_rating: Optional[float] = None,
    tags: Optional[str] = None,
    user_id: Optional[str] = None,
    mode: str = "public",
    page: int = 1,
    limit: int = 20,
):
    """List marketplace items with filters."""
    return market_service.list_items(
        category=category, search=search, sort=sort,
        min_price=min_price, max_price=max_price, min_rating=min_rating,
        tags=tags, user_id=user_id, mode=mode, page=page, limit=limit,
    )


@router.get("/items/{public_id}")
async def get_item_detail(public_id: str):
    """Get item detail with reviews and seller info."""
    result = market_service.get_detail(public_id)
    if result.get("status") == "error":
        raise HTTPException(404, "Item not found")
    return result


@router.post("/items")
async def upload_item(req: UploadRequest, authorization: Optional[str] = Header(None)):
    """Upload a new item to the marketplace."""
    token = _get_token(authorization)
    result = market_service.upload_item(
        token=token, title=req.title, description=req.description,
        category=req.category, price=req.price, item_data=req.item_data,
        visibility=req.visibility, tags=req.tags, version=req.version,
        thumbnail_url=req.thumbnail_url,
    )
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/items/{public_id}/buy")
async def buy_item(public_id: str, authorization: Optional[str] = Header(None)):
    """Purchase an item."""
    token = _get_token(authorization)
    result = market_service.buy_item(token=token, item_id=public_id)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Purchase failed"))
    return result


@router.delete("/items/{public_id}")
async def delete_item(public_id: str, authorization: Optional[str] = Header(None)):
    """Delete a listing (seller only)."""
    token = _get_token(authorization)
    result = market_service.delete_item(token=token, public_id=public_id)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Delete failed"))
    return result


# ── Install Extension from Market ──

class MarketInstallRequest(BaseModel):
    item_data: str   # JSON of the extension package data
    item_name: str   # extension name
    category: str    # extension, node, skill, model3d


@router.post("/items/{public_id}/install")
async def install_from_market(public_id: str, req: MarketInstallRequest):
    """Install a purchased extension from the market.

    For category='extension': extracts full extension package to extensions_external/
    For category='skill': saves as a skill JSON file
    For category='node': registers as a custom node
    """
    import json as json_lib
    import sys
    import subprocess
    from tubecli.config import EXTENSIONS_EXTERNAL_DIR, DATA_DIR

    try:
        item_data = json_lib.loads(req.item_data) if isinstance(req.item_data, str) else req.item_data
    except json_lib.JSONDecodeError:
        raise HTTPException(400, "Invalid item_data JSON")

    category = req.category
    name = req.item_name.replace(" ", "_").lower()

    if category == "extension":
        # Full extension install: item_data should contain manifest + files info
        ext_dir = str(EXTENSIONS_EXTERNAL_DIR / name)
        import os
        os.makedirs(ext_dir, exist_ok=True)

        # If item_data contains files dict, write each file
        if isinstance(item_data, dict) and "files" in item_data:
            for file_info in item_data["files"]:
                fpath = os.path.join(ext_dir, file_info["path"])
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(file_info["content"])
        else:
            # Save item_data as the manifest or extension data
            manifest = item_data.get("manifest", item_data)
            with open(os.path.join(ext_dir, "tubecli-extension.json"), "w", encoding="utf-8") as f:
                json_lib.dump(manifest, f, indent=2, ensure_ascii=False)

        # Install pip requirements if present
        req_file = os.path.join(ext_dir, "requirements.txt")
        if os.path.exists(req_file):
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
                capture_output=True, timeout=120,
            )

        # Register with ExtensionManager
        from tubecli.core.extension_manager import extension_manager
        extension_manager.discover_external_extensions()

        return {"status": "success", "message": f"Extension '{name}' installed", "type": "extension"}

    elif category == "skill":
        # Save as skill JSON
        import os
        skills_dir = os.path.join(str(DATA_DIR), "skills")
        os.makedirs(skills_dir, exist_ok=True)
        skill_path = os.path.join(skills_dir, f"{name}.json")
        with open(skill_path, "w", encoding="utf-8") as f:
            json_lib.dump(item_data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "message": f"Skill '{name}' installed", "type": "skill"}

    elif category == "node":
        # Save as custom node
        import os
        nodes_dir = os.path.join(str(DATA_DIR), "custom_nodes")
        os.makedirs(nodes_dir, exist_ok=True)
        node_path = os.path.join(nodes_dir, f"{name}.json")
        with open(node_path, "w", encoding="utf-8") as f:
            json_lib.dump(item_data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "message": f"Node '{name}' installed", "type": "node"}

    elif category == "model3d":
        # Save as workflow
        import os
        wf_dir = os.path.join(str(DATA_DIR), "workflows")
        os.makedirs(wf_dir, exist_ok=True)
        wf_path = os.path.join(wf_dir, f"{name}.json")
        with open(wf_path, "w", encoding="utf-8") as f:
            json_lib.dump(item_data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "message": f"3D Model '{name}' installed", "type": "model3d"}

    else:
        raise HTTPException(400, f"Unknown category: {category}")


# ── Reviews ──

@router.get("/items/{public_id}/reviews")
async def get_reviews(public_id: str):
    """Get reviews for an item."""
    return market_service.get_reviews(public_id)


@router.post("/items/{public_id}/reviews")
async def post_review(public_id: str, req: ReviewRequest, authorization: Optional[str] = Header(None)):
    """Submit a review."""
    token = _get_token(authorization)
    result = market_service.post_review(token=token, item_id=public_id, rating=req.rating, comment=req.comment)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Review failed"))
    return result


# ── Categories ──

@router.get("/categories")
async def get_categories():
    """Get categories with item counts and popular tags."""
    return market_service.get_categories()


# ── User Profile ──

@router.get("/user")
async def get_user_profile(authorization: Optional[str] = Header(None)):
    """Get user marketplace profile."""
    token = _get_token(authorization)
    return market_service.get_user_profile(token)


@router.post("/user")
async def update_user_profile(req: ProfileUpdateRequest, authorization: Optional[str] = Header(None)):
    """Update user profile."""
    token = _get_token(authorization)
    # Direct proxy to PHP
    import requests as http_requests
    url = f"{market_service.api_base}/user.php"
    headers = {"Authorization": f"Bearer {token}"}
    payload = req.model_dump(exclude_none=True)
    try:
        response = http_requests.post(url, json=payload, headers=headers, timeout=15)
        return response.json()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/user/link-google")
async def link_google(req: GoogleLinkRequest, authorization: Optional[str] = Header(None)):
    """Link Google account to profile."""
    token = _get_token(authorization)
    result = market_service.link_google(
        token=token, google_id=req.google_id, google_email=req.google_email,
        google_name=req.google_name, google_avatar=req.google_avatar,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error", "Link failed"))
    return result
