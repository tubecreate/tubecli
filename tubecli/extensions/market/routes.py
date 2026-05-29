"""
Marketplace API routes — Proxy to PHP backend.
"""
import json
from typing import Dict, Optional, List
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form, Request, Header
from pydantic import BaseModel
from tubecli.extensions.market.market_service import market_service

router = APIRouter(prefix="/api/v1/market", tags=["market"])

# ── Stripe & PayPal Payment Routes ──
from tubecli.extensions.market.stripe_routes import stripe_router
from tubecli.extensions.market.paypal_routes import paypal_router
router.include_router(stripe_router)
router.include_router(paypal_router)


# ── Check Updates ──
@router.get("/check-updates")
async def check_updates():
    """Compare local extension versions with Git repositories or marketplace versions.
    Returns list of extensions that have newer versions available.
    """
    import os
    import json
    import subprocess
    from tubecli.config import EXTENSIONS_EXTERNAL_DIR
    from tubecli.core.extension_manager import (
        compare_versions,
        get_git_tracking_branch,
        get_git_commit_version,
    )

    ext_dir = str(EXTENSIONS_EXTERNAL_DIR)
    local_extensions = {}       # name -> info (for non-git marketplace fallback)
    updates = []                # final list of updates

    if os.path.isdir(ext_dir):
        for entry in os.listdir(ext_dir):
            local_path = os.path.join(ext_dir, entry)
            manifest_file = os.path.join(local_path, "tubecli-extension.json")
            if not os.path.exists(manifest_file):
                continue
            try:
                with open(manifest_file, "r", encoding="utf-8-sig") as f:
                    manifest = json.load(f)
                name = manifest.get("name", entry)
                key = name.lower().replace(" ", "_")
                
                # Check if it has a git directory
                git_dir = os.path.join(local_path, ".git")
                if os.path.exists(git_dir):
                    # 1. Dynamic git update check
                    # Throttle git fetch to avoid blocking requests (throttle: 15 minutes)
                    fetch_head = os.path.join(git_dir, "FETCH_HEAD")
                    should_fetch = True
                    if os.path.exists(fetch_head):
                        import time
                        last_fetch = os.path.getmtime(fetch_head)
                        if time.time() - last_fetch < 900:
                            should_fetch = False
                    
                    if should_fetch:
                        subprocess.run(["git", "fetch", "origin"], cwd=local_path, capture_output=True, timeout=15)
                    branch = get_git_tracking_branch(local_path)
                    
                    # Count commits behind upstream
                    r_behind = subprocess.run(
                        ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
                        cwd=local_path, capture_output=True, text=True, timeout=10
                    )
                    commits_behind = 0
                    if r_behind.returncode == 0:
                        try:
                            commits_behind = int(r_behind.stdout.strip())
                        except Exception:
                            pass
                    
                    if commits_behind > 0:
                        # Fetch local standardized version
                        local_version = get_git_commit_version(local_path) or manifest.get("version", "0.0.0")
                        
                        # Fetch remote version from git manifest, fallback to remote commit date
                        remote_version = None
                        try:
                            res_show = subprocess.run(
                                ["git", "show", f"origin/{branch}:tubecli-extension.json"],
                                cwd=local_path, capture_output=True, text=True, timeout=10
                            )
                            if res_show.returncode == 0:
                                r_manifest = json.loads(res_show.stdout)
                                remote_version = r_manifest.get("version")
                        except Exception:
                            pass
                        
                        if not remote_version or compare_versions(remote_version, "2000.01.01.000000") < 0:
                            remote_version = get_git_commit_version(local_path, remote=True, branch=branch) or "2026.05.21.000000"
                        
                        # Get remote URL
                        git_url = ""
                        try:
                            r_url = subprocess.run(
                                ["git", "remote", "get-url", "origin"],
                                cwd=local_path, capture_output=True, text=True, timeout=5
                            )
                            if r_url.returncode == 0:
                                git_url = r_url.stdout.strip()
                        except Exception:
                            pass

                        updates.append({
                            "name": name,
                            "display_name": manifest.get("display_name", name),
                            "icon": manifest.get("icon", "📦"),
                            "local_version": local_version,
                            "market_version": remote_version,
                            "public_id": "",
                            "description": manifest.get("description", ""),
                            "git_url": git_url,
                            "is_git": True,
                        })
                else:
                    # Non-git marketplace based extension
                    local_extensions[key] = {
                        "name": name,
                        "display_name": manifest.get("display_name", name),
                        "version": manifest.get("version", "0.0.0"),
                        "icon": manifest.get("icon", "📦"),
                        "path": local_path,
                    }
            except Exception:
                continue

    # Step 2: Fetch marketplace items and check for updates for non-git extensions
    if local_extensions:
        try:
            market_data = await market_service.list_items(category="extension", limit=100)
            market_items = market_data.get("data", [])
            for item in market_items:
                item_title = (item.get("title") or "").strip().lower().replace(" ", "_")
                market_version = item.get("version", "0.0.0")

                if item_title in local_extensions:
                    local = local_extensions[item_title]
                    local_version = local["version"]

                    if compare_versions(market_version, local_version) > 0:
                        updates.append({
                            "name": local["name"],
                            "display_name": local["display_name"],
                            "icon": local["icon"],
                            "local_version": local_version,
                            "market_version": market_version,
                            "public_id": item.get("public_id", ""),
                            "description": item.get("description", ""),
                            "git_url": item.get("git_url", ""),
                            "is_git": False,
                        })
        except Exception as e:
            print(f"[Market check-updates] Error fetching marketplace items: {e}")

    return {"updates": updates, "total": len(updates)}



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
    git_url: Optional[str] = None

class GitInstallRequest(BaseModel):
    git_url: str


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
    return await market_service.list_items(
        category=category, search=search, sort=sort,
        min_price=min_price, max_price=max_price, min_rating=min_rating,
        tags=tags, user_id=user_id, mode=mode, page=page, limit=limit,
    )


@router.get("/my-items")
async def my_items(authorization: Optional[str] = Header(None)):
    """Get items listed by the current user."""
    token = _get_token(authorization)
    # Get user profile to find user_id
    profile = await market_service.get_user_profile(token)
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
    result = await market_service.list_items(user_id=user_id, limit=100)
    return result


@router.get("/items/{public_id}")
async def get_item_detail(public_id: str):
    """Get item detail with reviews and seller info."""
    result = await market_service.get_detail(public_id)
    if result.get("status") == "error":
        raise HTTPException(404, "Item not found")
    return result


@router.post("/items")
async def upload_item(req: UploadRequest, authorization: Optional[str] = Header(None)):
    """Upload a new item to the marketplace.
    Enforces unique names: if title already exists, auto-update for same author or block.
    """
    token = _get_token(authorization)

    # Check for duplicate name on market
    name_check = await market_service.check_name_exists(req.title, token)
    if name_check.get("exists"):
        if name_check.get("is_owner"):
            # Same author → auto-update existing item
            existing_id = name_check["public_id"]
            print(f"[Market] Auto-updating existing item '{req.title}' (ID: {existing_id})")
            result = await market_service.update_item(
                token=token, public_id=existing_id,
                title=req.title, description=req.description,
                category=req.category, price=req.price, item_data=req.item_data,
                visibility=req.visibility, tags=req.tags, version=req.version,
                thumbnail_url=req.thumbnail_url, git_url=req.git_url,
            )
            if result.get("error"):
                raise HTTPException(400, result["error"])
            result["auto_updated"] = True
            result["public_id"] = existing_id
            return result
        else:
            # Different author → block
            owner = name_check.get("owner_name", "another user")
            raise HTTPException(
                409,
                f"Extension name '{req.title}' is already taken by {owner}. Please choose a different name."
            )

    # No duplicate → normal upload
    result = await market_service.upload_item(
        token=token, title=req.title, description=req.description,
        category=req.category, price=req.price, item_data=req.item_data,
        visibility=req.visibility, tags=req.tags, version=req.version,
        thumbnail_url=req.thumbnail_url, git_url=req.git_url,
    )
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


class UpdateItemRequest(BaseModel):
    title: str
    description: str = ""
    category: str
    price: float = 0
    item_data: str
    visibility: str = "PUBLIC"
    tags: list = []
    version: str = "1.0.0"
    thumbnail_url: Optional[str] = None
    git_url: Optional[str] = None


@router.put("/items/{public_id}")
async def update_item(public_id: str, req: UpdateItemRequest, authorization: Optional[str] = Header(None)):
    """Update an existing item listing on the marketplace."""
    token = _get_token(authorization)
    result = await market_service.update_item(
        token=token, public_id=public_id, title=req.title, description=req.description,
        category=req.category, price=req.price, item_data=req.item_data,
        visibility=req.visibility, tags=req.tags, version=req.version,
        thumbnail_url=req.thumbnail_url, git_url=req.git_url,
    )
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/items/{public_id}/buy")
async def buy_item(public_id: str, authorization: Optional[str] = Header(None)):
    """Purchase an item."""
    token = _get_token(authorization)
    result = await market_service.buy_item(token=token, item_id=public_id)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Purchase failed"))
    return result


@router.delete("/items/{public_id}")
async def delete_market_item(public_id: str, authorization: Optional[str] = Header(None)):
    """Delete an item from the marketplace (seller only)."""
    token = _get_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized: no token provided")

    result = await market_service.delete_item(item_id=public_id, token=token)
    if result.get("status") == "success":
        return result
    raise HTTPException(
        status_code=400,
        detail=result.get("message", result.get("error", "Failed to delete item"))
    )

# ── Install Extension from Market ──

def _make_install_id(name: str, public_id: str = "") -> str:
    """Create install identifier from extension name.
    No longer appends public_id — names are unique on the market.
    """
    return name.replace(" ", "_").lower()


def _check_item_installed(public_id: str, name: str, category: str) -> dict:
    """Check if an item is already installed locally.
    For extensions: scans all folders by NAME to prevent duplicates (regardless of public_id).
    For other categories: checks by name__public_id.
    """
    import os
    from tubecli.config import EXTENSIONS_EXTERNAL_DIR, DATA_DIR

    def _normalize_name(n: str) -> str:
        return (n or "").replace(" ", "").replace("_", "").replace("-", "").lower()

    install_id = _make_install_id(name, public_id)
    name_clean = name.replace(" ", "_").lower()
    name_norm = _normalize_name(name)
    installed = False
    install_path = ""
    local_version = "0.0.0"

    if category == "extension":
        # Check exact match first (name__public_id)
        ext_dir = str(EXTENSIONS_EXTERNAL_DIR / install_id)
        if os.path.isdir(ext_dir):
            installed = True
            install_path = ext_dir
        else:
            # Scan ALL folders for same extension NAME (prevent duplicate installs)
            ext_base = str(EXTENSIONS_EXTERNAL_DIR)
            if os.path.isdir(ext_base):
                for entry in os.listdir(ext_base):
                    candidate = os.path.join(ext_base, entry)
                    if not os.path.isdir(candidate):
                        continue
                    
                    # 1. Match by normalized folder name prefix
                    entry_norm = _normalize_name(entry)
                    if entry_norm == name_norm or entry_norm.startswith(name_norm + "__") or name_norm.startswith(entry_norm + "__"):
                        installed = True
                        install_path = candidate
                        break
                    
                    # 2. Also check manifest name & display name for ultimate compatibility
                    manifest_file = os.path.join(candidate, "tubecli-extension.json")
                    if os.path.exists(manifest_file):
                        try:
                            import json as _json
                            with open(manifest_file, "r", encoding="utf-8-sig") as f:
                                m = _json.load(f)
                            m_name_norm = _normalize_name(m.get("name"))
                            m_display_norm = _normalize_name(m.get("display_name"))
                            if m_name_norm == name_norm or m_display_norm == name_norm:
                                installed = True
                                install_path = candidate
                                break
                        except Exception:
                            continue
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

    if installed and category == "extension" and install_path:
        manifest_file = os.path.join(install_path, "tubecli-extension.json")
        if os.path.exists(manifest_file):
            try:
                import json as _json
                with open(manifest_file, "r", encoding="utf-8-sig") as f:
                    m = _json.load(f)
                local_version = m.get("version", "0.0.0")
            except:
                pass

    return {"installed": installed, "path": install_path, "install_id": install_id, "local_version": local_version}


@router.get("/items/{public_id}/check-installed")
async def check_installed(public_id: str, item_name: str, category: str):
    """Check if a market item is already installed locally."""
    result = _check_item_installed(public_id, item_name, category)
    return {"status": "success", **result}

class BatchCheckItem(BaseModel):
    public_id: str
    item_name: str
    category: str

@router.post("/items/batch-check-installed")
async def batch_check_installed(items: List[BatchCheckItem]):
    """Check installed status for multiple items at once to speed up UI loading."""
    result = {}
    for item in items:
        status = _check_item_installed(item.public_id, item.item_name, item.category)
        result[item.public_id] = {"status": "success", **status}
    return {"status": "success", "data": result}


@router.post("/items/{public_id}/uninstall")
async def uninstall_from_market(public_id: str, item_name: str, category: str):
    """Uninstall a market-installed extension. Only removes files from extensions_external."""
    import os
    import shutil
    from tubecli.config import EXTENSIONS_EXTERNAL_DIR, DATA_DIR

    install_id = _make_install_id(item_name, public_id)

    if category == "extension":
        ext_dir = str(EXTENSIONS_EXTERNAL_DIR / install_id)
        if not os.path.isdir(ext_dir):
            raise HTTPException(404, "Extension not installed")
        # Safety: only allow removing from extensions_external
        ext_external_str = str(EXTENSIONS_EXTERNAL_DIR)
        real_ext = os.path.realpath(ext_dir)
        real_external = os.path.realpath(ext_external_str)
        if not real_ext.startswith(real_external):
            raise HTTPException(403, "Cannot uninstall: path outside extensions_external")
        shutil.rmtree(ext_dir)
        return {"status": "success", "message": f"'{item_name}' uninstalled successfully"}

    elif category == "skill":
        skill_path = os.path.join(str(DATA_DIR), "skills", f"{install_id}.json")
        if os.path.isfile(skill_path):
            os.remove(skill_path)
            return {"status": "success", "message": f"Skill '{item_name}' uninstalled"}
        raise HTTPException(404, "Skill not installed")

    elif category == "node":
        node_path = os.path.join(str(DATA_DIR), "custom_nodes", f"{install_id}.json")
        if os.path.isfile(node_path):
            os.remove(node_path)
            return {"status": "success", "message": f"Node '{item_name}' uninstalled"}
        raise HTTPException(404, "Node not installed")

    elif category == "model3d":
        wf_path = os.path.join(str(DATA_DIR), "workflows", f"{install_id}.json")
        if os.path.isfile(wf_path):
            os.remove(wf_path)
            return {"status": "success", "message": f"Workflow '{item_name}' uninstalled"}
        raise HTTPException(404, "Workflow not installed")

    raise HTTPException(400, "Unknown category")


class MarketInstallRequest(BaseModel):
    item_data: str   # JSON of the extension package data
    item_name: str   # extension name
    category: str    # extension, node, skill, model3d
    force_update: bool = False

@router.post("/items/{item_name}/update-local")
async def update_local_extension(item_name: str):
    """Trigger local Git update for an installed extension."""
    from tubecli.core.extension_manager import extension_manager
    
    # 1. Try direct lookup (original name)
    ext = extension_manager.get(item_name)
    
    # 2. Try normalized name lookup (e.g., "Video Manager" -> "video_manager")
    if not ext:
        normalized = item_name.replace(" ", "_").lower()
        ext = extension_manager.get(normalized)
        
    # 3. Try case-insensitive comparison on names / display names
    if not ext:
        for e in extension_manager.get_all():
            if e.name.lower() == item_name.lower():
                ext = e
                break
            
            # Check manifest display name/title
            manifest = e.get_manifest()
            if manifest.get("display_name", "").lower() == item_name.lower():
                ext = e
                break
            if manifest.get("name", "").lower() == item_name.lower():
                ext = e
                break

    if not ext:
        raise HTTPException(400, f"Extension '{item_name}' not found locally.")

    result = extension_manager.update_extension(ext.name)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Update failed"))
    return result

@router.post("/items/install-git")
async def install_git_extension(req: GitInstallRequest):
    """Fallback to install from Git."""
    from tubecli.core.extension_manager import extension_manager
    result = extension_manager.install_from_git(req.git_url)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Git install failed"))
    
    # Hot mount if extension was returned
    manifest = result.get("extension")
    if manifest and isinstance(manifest, dict):
        ext_obj = extension_manager.get(manifest.get("name"))
        if ext_obj:
            import sys as _sys
            ext_d = getattr(ext_obj, 'extension_dir', None)
            if ext_d and ext_d not in _sys.path:
                _sys.path.insert(0, ext_d)
            try:
                from tubecli.api.server import app
                ext_router = ext_obj.get_routes()
                if ext_router:
                    app.include_router(ext_router)
                    print(f"[Market/Git] Hot-mounted routes for {ext_obj.name}")
            except Exception as e:
                print(f"[Market/Git] Could not hot-mount routes (restart server to activate): {e}")

            try:
                nodes = ext_obj.get_nodes()
                if nodes:
                    from tubecli.core.workflow_engine import WorkflowEngine
                    WorkflowEngine.NODE_REGISTRY.update(nodes)
                    print(f"[Market/Git] Registered workflow nodes for {ext_obj.name}")
            except Exception:
                pass
                
            try:
                ext_obj.on_install()
            except Exception:
                pass

    return result


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
    if check["installed"] and not req.force_update:
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

        # ── Step 1: Try to get files from item_data ──
        # Sometimes item_data is double-encoded JSON string
        def _unwrap_item_data(data):
            """Recursively unwrap item_data if it's a JSON string."""
            if isinstance(data, str):
                try:
                    data = json_lib.loads(data)
                    return _unwrap_item_data(data)  # recurse in case of double-encoding
                except (json_lib.JSONDecodeError, TypeError):
                    pass
            return data

        item_data = _unwrap_item_data(item_data)

        # ── Step 2: If no files, download from server ──
        if not (isinstance(item_data, dict) and "files" in item_data):
            print(f"[Market] item_data has no 'files' key, trying download-data.php...")
            try:
                dl = await market_service.download_item_data(public_id)
                if dl.get("status") == "success" and dl.get("item_data"):
                    server_data = _unwrap_item_data(dl["item_data"])
                    if isinstance(server_data, dict) and "files" in server_data:
                        item_data = server_data
                        print(f"[Market] Downloaded {len(item_data['files'])} files from server")
                    else:
                        print(f"[Market] Server returned item_data but no 'files' key: {type(server_data)}")
                else:
                    print(f"[Market] download-data.php returned: {dl.get('status')}")
            except Exception as e:
                print(f"[Market] Download item_data failed: {e}")

        # ── Step 3: Write files if available ──
        if isinstance(item_data, dict) and "files" in item_data:
            for file_info in item_data["files"]:
                fpath = os.path.join(ext_dir, file_info["path"])
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(file_info["content"])
            print(f"[Market] Wrote {len(item_data['files'])} files to {ext_dir}")
        else:
            # ── Fallback 1: git_url backup ──
            source_dir = None
            git_url = item_data.get("git_url") if isinstance(item_data, dict) else None
            # Extract git_url from meta tags if API included it there or in top level
            if not git_url and isinstance(item_data, dict) and item_data.get("tags"):
                for tag in item_data.get("tags", []):
                    if isinstance(tag, str) and tag.startswith("git_url:"):
                        git_url = tag.replace("git_url:", "")
                        break
                        
            if git_url:
                print(f"[Market] Fallback to Git Install: {git_url}")
                from tubecli.core.extension_manager import extension_manager
                # Xóa thư mục rỗng chuẩn bị nãy giờ vì git clone cần trống
                shutil.rmtree(ext_dir, ignore_errors=True)
                git_res = extension_manager.install_from_git(git_url)
                if git_res.get("status") == "success":
                    return {"status": "success", "message": git_res.get("message"), "type": "extension", "restart_required": False}
                else:
                    raise HTTPException(500, f"Git fallback install failed: {git_res.get('message')}")
            
            # ── Fallback 2: Local source ──
            # Check extensions_external for a folder matching the extension name
            if os.path.isdir(str(EXTENSIONS_EXTERNAL_DIR)):
                for entry in os.listdir(str(EXTENSIONS_EXTERNAL_DIR)):
                    candidate = os.path.join(str(EXTENSIONS_EXTERNAL_DIR), entry)
                    if not os.path.isdir(candidate) or candidate == ext_dir:
                        continue
                    manifest_file = os.path.join(candidate, "tubecli-extension.json")
                    if os.path.exists(manifest_file):
                        try:
                            with open(manifest_file, "r", encoding="utf-8-sig") as f:
                                m = json.load(f)
                            if m.get("name", "").lower().replace(" ", "_") == name:
                                source_dir = candidate
                                break
                        except Exception:
                            continue

            # Also check built-in extensions
            if not source_dir:
                from tubecli.core.extension_manager import extension_manager
                # Try exact match first, then partial
                ext_obj = extension_manager.get(name)
                if not ext_obj:
                    # Try matching by checking all extensions
                    for ext_name, ext in extension_manager._extensions.items():
                        if name in ext_name.lower().replace(" ", "_"):
                            ext_obj = ext
                            break
                if ext_obj and ext_obj.extension_dir and os.path.isdir(ext_obj.extension_dir):
                    source_dir = ext_obj.extension_dir

            if source_dir:
                print(f"[Market] Copying from local source: {source_dir}")
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
                # No source files available — clean up empty dir and fail
                shutil.rmtree(ext_dir, ignore_errors=True)
                raise HTTPException(
                    500,
                    "Could not install: extension source files not available. "
                    "Please re-upload the extension with full file contents from the seller's machine."
                )

        # Install pip requirements: from requirements.txt first, then manifest.dependencies
        deps_to_install = []

        # 1. requirements.txt takes priority (specific versions)
        req_file = os.path.join(ext_dir, "requirements.txt")
        if os.path.exists(req_file):
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
                    capture_output=True, timeout=180,
                )
            except subprocess.TimeoutExpired:
                print(f"[Market] Warning: pip install -r requirements.txt timed out after 3 minutes. Heavy dependencies might need manual installation.")
            # Read what's in requirements.txt to avoid reinstalling below
            with open(req_file, "r") as f:
                installed_pkgs = {line.strip().split("==")[0].split(">=")[0].split("<=")[0].lower()
                                  for line in f if line.strip() and not line.startswith("#")}
        else:
            installed_pkgs = set()

        # 2. manifest.dependencies — install any not already covered by requirements.txt
        manifest_path = os.path.join(ext_dir, "tubecli-extension.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8-sig") as f:
                    manifest_data = json_lib.load(f)
                for dep in manifest_data.get("dependencies", []):
                    pkg = dep.strip().split("==")[0].split(">=")[0].split("<=")[0].lower()
                    if pkg and pkg not in installed_pkgs:
                        deps_to_install.append(dep.strip())
            except Exception as e:
                print(f"[Market] Could not read manifest for deps: {e}")

        if deps_to_install:
            print(f"[Market] Installing manifest dependencies: {deps_to_install}")
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", *deps_to_install, "--quiet"],
                    capture_output=True, timeout=180,
                )
            except subprocess.TimeoutExpired:
                print(f"[Market] Warning: pip install for manifest dependencies timed out after 3 minutes.")

        # Register with ExtensionManager and auto-enable
        from tubecli.core.extension_manager import extension_manager
        extension_manager.discover_external_extensions()

        # Auto-enable: try by name, install_id, or partial match
        ext_obj = extension_manager.get(name)
        if not ext_obj:
            ext_obj = extension_manager.get(install_id)
        if not ext_obj:
            # Scan all discovered extensions for a match
            for ext_name, ext in extension_manager._extensions.items():
                if name in ext_name.lower().replace(" ", "_") or install_id in ext_name:
                    ext_obj = ext
                    break
        if ext_obj and not ext_obj.enabled:
            extension_manager.enable(ext_obj.name)
            print(f"[Market] Auto-enabled extension: {ext_obj.name}")

        # Hot-mount routes and nodes into running server (no restart needed)
        if ext_obj:
            import sys as _sys

            # IMPORTANT: add extension dir to sys.path BEFORE get_routes()
            # so the extension's local imports (e.g. video_api, video_engine) resolve
            ext_d = getattr(ext_obj, 'extension_dir', None)
            if ext_d and ext_d not in _sys.path:
                _sys.path.insert(0, ext_d)

            try:
                from tubecli.api.server import app
                ext_router = ext_obj.get_routes()
                if ext_router:
                    app.include_router(ext_router)
                    print(f"[Market] Hot-mounted {len(ext_router.routes)} routes for {ext_obj.name}")
                else:
                    print(f"[Market] No routes returned by {ext_obj.name}")
            except Exception as e:
                print(f"[Market] Could not hot-mount routes (restart server to activate): {e}")
                import traceback
                traceback.print_exc()

            try:
                nodes = ext_obj.get_nodes()
                if nodes:
                    from tubecli.core.workflow_engine import WorkflowEngine
                    WorkflowEngine.NODE_REGISTRY.update(nodes)
                    print(f"[Market] Registered {len(nodes)} workflow nodes for {ext_obj.name}")
            except Exception as e:
                print(f"[Market] Could not register nodes: {e}")

            # Trigger on_install to create workspace directories
            try:
                ext_obj.on_install()
            except Exception as e:
                print(f"[Market] on_install warning: {e}")

        return {"status": "success", "message": f"Extension '{req.item_name}' installed and enabled. Refresh page to use.", "type": "extension", "restart_required": False}

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
    return await market_service.get_reviews(public_id)


@router.post("/items/{public_id}/reviews")
async def post_review(public_id: str, req: ReviewRequest, authorization: Optional[str] = Header(None)):
    """Submit a review."""
    token = _get_token(authorization)
    result = await market_service.post_review(token=token, item_id=public_id, rating=req.rating, comment=req.comment)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Review failed"))
    return result


# ── Categories ──

@router.get("/categories")
async def get_categories():
    """Get categories with item counts and popular tags."""
    return await market_service.get_categories()


# ── User Profile ──

@router.get("/user")
async def get_user_profile(authorization: Optional[str] = Header(None)):
    """Get user marketplace profile."""
    token = _get_token(authorization)
    return await market_service.get_user_profile(token)


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
    result = await market_service.link_google(
        token=token, google_id=req.google_id, google_email=req.google_email,
        google_name=req.google_name, google_avatar=req.google_avatar,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error", "Link failed"))
    return result
