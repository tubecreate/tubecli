"""
Project Manager — Manages video editing projects and timeline JSON.
Each project stores its media files, timeline structure, and export settings.
"""
import os
import json
import uuid
import shutil
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger("video_editor.project_manager")


def _get_base_dir() -> str:
    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    return os.path.join(data_dir, "video_editor")


def _get_projects_dir() -> str:
    d = os.path.join(_get_base_dir(), "projects")
    os.makedirs(d, exist_ok=True)
    return d


def _get_uploads_dir() -> str:
    d = os.path.join(_get_base_dir(), "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def _get_exports_dir() -> str:
    d = os.path.join(_get_base_dir(), "exports")
    os.makedirs(d, exist_ok=True)
    return d


def _get_thumbnails_dir() -> str:
    d = os.path.join(_get_base_dir(), "thumbnails")
    os.makedirs(d, exist_ok=True)
    return d


# ── Timeline Template ────────────────────────────────────────────────

def _new_timeline() -> Dict[str, Any]:
    """Create an empty timeline structure."""
    return {
        "tracks": [
            {"id": "video-1", "type": "video", "label": "Video 1", "clips": []},
            {"id": "audio-1", "type": "audio", "label": "Audio 1", "clips": []},
            {"id": "text-1",  "type": "text",  "label": "Text 1",  "clips": []},
        ],
        "duration": 0,
        "playhead": 0,
    }


def _new_clip(
    media_id: str, track_id: str,
    start: float = 0, end: float = 0,
    offset: float = 0, label: str = ""
) -> Dict[str, Any]:
    """Create a new clip for the timeline."""
    return {
        "id": f"clip_{uuid.uuid4().hex[:8]}",
        "media_id": media_id,
        "track_id": track_id,
        "start": start,        # Start time in source media (seconds)
        "end": end,            # End time in source media (seconds)
        "offset": offset,      # Position on the timeline (seconds)
        "label": label,
        "effects": [],
        "volume": 1.0,
        "opacity": 1.0,
    }


# ── Project CRUD ─────────────────────────────────────────────────────

def create_project(name: str, description: str = "") -> Dict[str, Any]:
    """Create a new editing project."""
    project_id = uuid.uuid4().hex[:12]
    project_dir = os.path.join(_get_projects_dir(), project_id)
    os.makedirs(project_dir, exist_ok=True)
    media_dir = os.path.join(project_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    project = {
        "id": project_id,
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "media": [],           # List of media files
        "timeline": _new_timeline(),
        "export_settings": {
            "format": "mp4",
            "quality": "high",
            "resolution": "1080p",
            "fps": 30,
        },
    }

    _save_project(project_id, project)
    logger.info(f"Created project: {project_id} ({name})")
    return project


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    """Load a project by ID."""
    project_file = os.path.join(_get_projects_dir(), project_id, "project.json")
    if not os.path.exists(project_file):
        return None
    try:
        with open(project_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading project {project_id}: {e}")
        return None


def list_projects() -> List[Dict[str, Any]]:
    """List all projects (summary only)."""
    projects = []
    projects_dir = _get_projects_dir()
    if not os.path.isdir(projects_dir):
        return []

    for entry in os.listdir(projects_dir):
        project_file = os.path.join(projects_dir, entry, "project.json")
        if os.path.exists(project_file):
            try:
                with open(project_file, "r", encoding="utf-8") as f:
                    p = json.load(f)
                projects.append({
                    "id": p["id"],
                    "name": p["name"],
                    "description": p.get("description", ""),
                    "created_at": p.get("created_at", ""),
                    "updated_at": p.get("updated_at", ""),
                    "media_count": len(p.get("media", [])),
                    "tracks_count": len(p.get("timeline", {}).get("tracks", [])),
                })
            except Exception:
                continue

    projects.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return projects


def update_project(project_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a project's fields (name, timeline, export_settings, etc.)."""
    project = get_project(project_id)
    if not project:
        return None

    # Allow updating specific fields
    for key in ["name", "description", "timeline", "export_settings"]:
        if key in updates:
            project[key] = updates[key]

    project["updated_at"] = datetime.now().isoformat()
    _save_project(project_id, project)
    return project


def delete_project(project_id: str) -> bool:
    """Delete a project and all its files."""
    project_dir = os.path.join(_get_projects_dir(), project_id)
    if os.path.isdir(project_dir):
        shutil.rmtree(project_dir, ignore_errors=True)
        logger.info(f"Deleted project: {project_id}")
        return True
    return False


# ── Media Management ─────────────────────────────────────────────────

def add_media_to_project(
    project_id: str, filename: str, file_path: str,
    media_type: str = "video", duration: float = 0,
    width: int = 0, height: int = 0
) -> Optional[Dict[str, Any]]:
    """Register a media file with a project."""
    project = get_project(project_id)
    if not project:
        return None

    media_id = uuid.uuid4().hex[:8]

    # Copy file to project media folder
    project_media_dir = os.path.join(_get_projects_dir(), project_id, "media")
    os.makedirs(project_media_dir, exist_ok=True)
    dest_path = os.path.join(project_media_dir, filename)

    if os.path.abspath(file_path) != os.path.abspath(dest_path):
        shutil.copy2(file_path, dest_path)

    media_entry = {
        "id": media_id,
        "filename": filename,
        "path": dest_path,
        "type": media_type,  # video, audio, image
        "duration": duration,
        "width": width,
        "height": height,
        "added_at": datetime.now().isoformat(),
    }

    project["media"].append(media_entry)
    project["updated_at"] = datetime.now().isoformat()
    _save_project(project_id, project)

    return media_entry


def remove_media_from_project(project_id: str, media_id: str) -> bool:
    """Remove a media file from a project."""
    project = get_project(project_id)
    if not project:
        return False

    media_entry = next((m for m in project["media"] if m["id"] == media_id), None)
    if not media_entry:
        return False

    # Remove file
    if os.path.exists(media_entry.get("path", "")):
        try:
            os.remove(media_entry["path"])
        except Exception:
            pass

    # Remove from project
    project["media"] = [m for m in project["media"] if m["id"] != media_id]

    # Remove clips referencing this media
    for track in project.get("timeline", {}).get("tracks", []):
        track["clips"] = [c for c in track["clips"] if c.get("media_id") != media_id]

    project["updated_at"] = datetime.now().isoformat()
    _save_project(project_id, project)
    return True


# ── Internal Helpers ─────────────────────────────────────────────────

def _save_project(project_id: str, project: Dict[str, Any]):
    """Persist project data to disk."""
    project_dir = os.path.join(_get_projects_dir(), project_id)
    os.makedirs(project_dir, exist_ok=True)
    project_file = os.path.join(project_dir, "project.json")
    with open(project_file, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)
