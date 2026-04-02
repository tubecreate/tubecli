"""
File Manager API Routes — REST API for file/folder operations.
"""
import os
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/v1/files", tags=["File Manager"])


def _get_service():
    from tubecli.extensions.file_manager.file_service import file_service
    return file_service


# ── Request Models ───────────────────────────────────────────────

class CreateFolderRequest(BaseModel):
    path: str

class CreateFileRequest(BaseModel):
    path: str
    content: str = ""

class MoveRequest(BaseModel):
    src: str
    dst: str

class CopyRequest(BaseModel):
    src: str
    dst: str

class DeleteRequest(BaseModel):
    path: str


# ── Routes ───────────────────────────────────────────────────────

@router.get("/roots")
async def get_roots():
    """Get list of allowed root directories."""
    svc = _get_service()
    return {"success": True, "roots": svc.get_allowed_roots()}


@router.get("/list")
async def list_files(
    path: str = Query(..., description="Directory path"),
    show_hidden: bool = Query(False, description="Show hidden files"),
):
    """List files and folders in a directory."""
    svc = _get_service()
    try:
        result = svc.list_dir(path, show_hidden=show_hidden)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-folder")
async def create_folder(req: CreateFolderRequest):
    """Create a new folder."""
    svc = _get_service()
    try:
        result = svc.create_folder(req.path)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-file")
async def create_file(req: CreateFileRequest):
    """Create a new file with optional content."""
    svc = _get_service()
    try:
        result = svc.create_file(req.path, req.content)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/read")
async def read_file(
    path: str = Query(..., description="File path"),
    max_lines: int = Query(1000, description="Max lines to read"),
):
    """Read text file content."""
    svc = _get_service()
    try:
        result = svc.read_file(path, max_lines=max_lines)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/info")
async def file_info(path: str = Query(..., description="File or folder path")):
    """Get detailed file/folder information."""
    svc = _get_service()
    try:
        result = svc.info(path)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_files(
    path: str = Query(..., description="Directory to search in"),
    pattern: str = Query("*", description="Glob pattern"),
    recursive: bool = Query(True, description="Search recursively"),
):
    """Search files matching a pattern."""
    svc = _get_service()
    try:
        result = svc.search(path, pattern=pattern, recursive=recursive)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/move")
async def move_file(req: MoveRequest):
    """Move or rename a file/folder."""
    svc = _get_service()
    try:
        result = svc.move(req.src, req.dst)
        return {"success": True, **result}
    except (FileNotFoundError, ValueError) as e:
        status = 404 if isinstance(e, FileNotFoundError) else 403
        raise HTTPException(status_code=status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/copy")
async def copy_file(req: CopyRequest):
    """Copy a file/folder."""
    svc = _get_service()
    try:
        result = svc.copy(req.src, req.dst)
        return {"success": True, **result}
    except (FileNotFoundError, ValueError) as e:
        status = 404 if isinstance(e, FileNotFoundError) else 403
        raise HTTPException(status_code=status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete")
async def delete_file(path: str = Query(..., description="Path to delete")):
    """Delete a file or folder."""
    svc = _get_service()
    try:
        result = svc.delete(path)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
