"""
Marketplace API routes — Proxy to PHP backend.
"""
from fastapi import APIRouter, HTTPException, Header
from typing import Optional
import json
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


@router.get("/my-items")
async def my_items(authorization: Optional[str] = Header(None)):
    """Get items listed by the current user."""
    token = _get_token(authorization)
    # Get user profile to find user_id
    profile = market_service.get_user_profile(token)
    if profile.get("status") == "error":
        raise HTTPException(401, "Could not fetch user profile")
    # user.php returns {status, profile: {user_id, display_name, ...}}
    user_id = (
        profile.get("profile", {}).get("user_id")
        or profile.get("user", {}).get("user_id")
        or profile.get("user_id")
    )
    if not user_id:
        raise HTTPException(401, "Could not determine user ID")
    # Fetch all items by this user
    result = market_service.list_items(user_id=user_id, limit=100)
    return result


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

def _make_install_id(name: str, public_id: str) -> str:
    """Create a unique install identifier: name__public_id."""
    name_clean = name.replace(" ", "_").lower()
    return f"{name_clean}__{public_id}"


def _check_item_installed(public_id: str, name: str, category: str) -> dict:
    """Check if an item is already installed locally using public_id."""
    import os
    from tubecli.config import EXTENSIONS_EXTERNAL_DIR, DATA_DIR

    install_id = _make_install_id(name, public_id)
    installed = False
    install_path = ""

    if category == "extension":
        ext_dir = str(EXTENSIONS_EXTERNAL_DIR / install_id)
        installed = os.path.isdir(ext_dir)
        install_path = ext_dir
    elif category == "skill":
        skill_path = os.path.join(str(DATA_DIR), "skills", f"{install_id}.json")
        installed = os.path.isfile(skill_path)
        install_path = skill_path
    elif category == "node":
        node_path = os.path.join(str(DATA_DIR), "custom_nodes", f"{install_id}.json")
        installed = os.path.isfile(node_path)
        install_path = node_path
    elif category == "model3d":
        wf_path = os.path.join(str(DATA_DIR), "workflows", f"{install_id}.json")
        installed = os.path.isfile(wf_path)
        install_path = wf_path

    return {"installed": installed, "path": install_path, "install_id": install_id}


@router.get("/items/{public_id}/check-installed")
async def check_installed(public_id: str, item_name: str, category: str):
    """Check if a market item is already installed locally."""
    result = _check_item_installed(public_id, item_name, category)
    return {"status": "success", **result}


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
    install_id = _make_install_id(req.item_name, public_id)

    # Check for duplicate installation by public_id
    check = _check_item_installed(public_id, req.item_name, category)
    if check["installed"]:
        raise HTTPException(
            409,
            detail={
                "message": f"'{req.item_name}' (ID: {public_id}) is already installed",
                "already_installed": True,
                "path": check["path"],
            },
        )

    if category == "extension":
        # Full extension install: item_data should contain manifest + files info
        ext_dir = str(EXTENSIONS_EXTERNAL_DIR / install_id)
        import os
        import shutil
        os.makedirs(ext_dir, exist_ok=True)

        # If item_data doesn't contain files, try downloading from server
        if not (isinstance(item_data, dict) and "files" in item_data):
            try:
                dl = market_service.download_item_data(public_id)
                if dl.get("status") == "success" and dl.get("item_data"):
                    raw = dl["item_data"]
                    if isinstance(raw, str):
                        server_data = json.loads(raw)
                    else:
                        server_data = raw
                    if isinstance(server_data, dict) and "files" in server_data:
                        item_data = server_data
            except Exception as e:
                print(f"[Market] Download item_data failed: {e}")

        # If item_data contains files dict, write each file
        if isinstance(item_data, dict) and "files" in item_data:
            for file_info in item_data["files"]:
                fpath = os.path.join(ext_dir, file_info["path"])
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(file_info["content"])
        else:
            # Fallback: try to find the extension locally and copy all files
            source_dir = None

            # Check extensions_external for a folder matching the extension name
            for entry in os.listdir(str(EXTENSIONS_EXTERNAL_DIR)):
                candidate = os.path.join(str(EXTENSIONS_EXTERNAL_DIR), entry)
                if not os.path.isdir(candidate) or candidate == ext_dir:
                    continue
                manifest_file = os.path.join(candidate, "tubecli-extension.json")
                if os.path.exists(manifest_file):
                    try:
                        with open(manifest_file, "r", encoding="utf-8") as f:
                            m = json_lib.load(f)
                        if m.get("name", "").lower() == name:
                            source_dir = candidate
                            break
                    except Exception:
                        continue

            # Also check built-in extensions
            if not source_dir:
                from tubecli.core.extension_manager import extension_manager
                ext_obj = extension_manager.get(name)
                if ext_obj and ext_obj.extension_dir and os.path.isdir(ext_obj.extension_dir):
                    source_dir = ext_obj.extension_dir

            if source_dir:
                # Copy all files from source extension
                SKIP_DIRS = {"__pycache__", ".git", "node_modules"}
                SKIP_EXTS = {".pyc", ".pyo"}
                for root, dirs, filenames in os.walk(source_dir):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for fname in filenames:
                        if any(fname.endswith(e) for e in SKIP_EXTS):
                            continue
                        src_path = os.path.join(root, fname)
                        rel_path = os.path.relpath(src_path, source_dir)
                        dst_path = os.path.join(ext_dir, rel_path)
                        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                        shutil.copy2(src_path, dst_path)
            else:
                # Last resort: save item_data as the manifest
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
        skill_path = os.path.join(skills_dir, f"{install_id}.json")
        with open(skill_path, "w", encoding="utf-8") as f:
            json_lib.dump(item_data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "message": f"Skill '{name}' installed", "type": "skill"}

    elif category == "node":
        # Save as custom node
        import os
        nodes_dir = os.path.join(str(DATA_DIR), "custom_nodes")
        os.makedirs(nodes_dir, exist_ok=True)
        node_path = os.path.join(nodes_dir, f"{install_id}.json")
        with open(node_path, "w", encoding="utf-8") as f:
            json_lib.dump(item_data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "message": f"Node '{name}' installed", "type": "node"}

    elif category == "model3d":
        # Save as workflow
        import os
        wf_dir = os.path.join(str(DATA_DIR), "workflows")
        os.makedirs(wf_dir, exist_ok=True)
        wf_path = os.path.join(wf_dir, f"{install_id}.json")
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
