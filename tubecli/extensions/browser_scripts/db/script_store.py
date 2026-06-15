"""
Script Studio — JSON File Store.
Replaces SQLite with simple JSON files: one file per script.

Structure:
    scripts/
    ├── gmail_login.json        ← function
    ├── get_api_key.json        ← script
    └── ...
"""
import os
import json
import logging
import threading
from datetime import datetime

logger = logging.getLogger("ScriptStudio.Store")

_instance = None
_lock = threading.Lock()


class ScriptStore:
    """Thread-safe JSON file-based script store."""

    @classmethod
    def get_instance(cls, scripts_dir=None):
        global _instance
        if _instance is None and scripts_dir:
            with _lock:
                if _instance is None:
                    _instance = cls(scripts_dir)
        return _instance

    def __init__(self, scripts_dir):
        self.scripts_dir = scripts_dir
        os.makedirs(scripts_dir, exist_ok=True)
        logger.info(f"ScriptStore initialized: {scripts_dir}")

    # ── Read ──

    def _read_script(self, filepath):
        """Read a single script JSON file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Ensure required fields
            data.setdefault("slug", os.path.splitext(os.path.basename(filepath))[0])
            data.setdefault("name", data["slug"])
            data.setdefault("steps", [])
            data.setdefault("variables", [])
            data.setdefault("tags", [])
            data.setdefault("category", "general")
            data.setdefault("is_function", False)
            data.setdefault("function_inputs", [])
            data.setdefault("function_outputs", [])
            return data
        except Exception as e:
            logger.warning(f"Failed to read {filepath}: {e}")
            return None

    def list_scripts(self, category=None):
        """List all scripts, optionally filtered by category."""
        scripts = []
        for fname in sorted(os.listdir(self.scripts_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(self.scripts_dir, fname)
            data = self._read_script(fpath)
            if data:
                if category and data.get("category") != category:
                    continue
                scripts.append(data)
        # Sort by updated_at desc
        scripts.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return scripts

    def list_functions(self):
        """List scripts marked as functions."""
        return [s for s in self.list_scripts() if s.get("is_function")]

    def get_script(self, slug):
        """Get a single script by slug."""
        fpath = os.path.join(self.scripts_dir, f"{slug}.json")
        if os.path.isfile(fpath):
            return self._read_script(fpath)
        # Fallback: scan all files for matching slug
        for fname in os.listdir(self.scripts_dir):
            if not fname.endswith(".json"):
                continue
            data = self._read_script(os.path.join(self.scripts_dir, fname))
            if data and data.get("slug") == slug:
                return data
        return None

    def get_script_by_id(self, script_id):
        """Compatibility: get by numeric ID (uses slug internally)."""
        # Try as slug first
        result = self.get_script(str(script_id))
        if result:
            return result
        # Scan all for matching id field
        for fname in sorted(os.listdir(self.scripts_dir)):
            if not fname.endswith(".json"):
                continue
            data = self._read_script(os.path.join(self.scripts_dir, fname))
            if data and data.get("id") == script_id:
                return data
        return None

    def _sync_to_skill_manager(self, data):
        """Sync script to global skill manager if it's a function."""
        if not data.get("is_function"):
            return
            
        try:
            from tubecli.core.skill import skill_manager
            
            slug = data.get("slug")
            name = data.get("name")
            desc = data.get("description", "")
            
            workflow_data = {
                "extension": "browser_scripts",
                "script_id": slug,
                "action": "execute_script_sync"
            }
            
            existing = None
            for s in skill_manager.get_all():
                if isinstance(s.workflow_data, dict) and s.workflow_data.get("extension") == "browser_scripts" and s.workflow_data.get("script_id") == slug:
                    existing = s
                    break
                    
            if existing:
                skill_manager.update(
                    existing.id,
                    name=name,
                    description=desc,
                    workflow_data=workflow_data
                )
            else:
                skill_manager.create(
                    name=name,
                    description=desc,
                    skill_type="Browser Automation",
                    skill_format="browser_script",
                    workflow_data=workflow_data,
                    commands=[name.lower(), slug]
                )
        except Exception as e:
            logger.error(f"Failed to sync script {data.get('slug')} to skill manager: {e}")

    # ── Write ──

    def _save_script(self, data):
        """Save script to JSON file."""
        slug = data.get("slug", "").strip()
        if not slug:
            slug = data.get("name", "untitled").lower().replace(" ", "_")
            slug = "".join(c for c in slug if c.isalnum() or c == "_")
            data["slug"] = slug

        data["updated_at"] = datetime.utcnow().isoformat()
        if not data.get("created_at"):
            data["created_at"] = data["updated_at"]

        fpath = os.path.join(self.scripts_dir, f"{slug}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved script: {slug}")
        
        self._sync_to_skill_manager(data)
        
        return data

    def create_script(self, name, slug=None, description="", category="general",
                      target_url="", tags=None, steps=None, variables=None,
                      metadata=None, is_template=False, is_function=False,
                      function_inputs=None, function_outputs=None):
        """Create a new script."""
        if not slug:
            slug = name.lower().replace(" ", "_").replace("-", "_")
            slug = "".join(c for c in slug if c.isalnum() or c == "_")

        # Ensure unique slug
        base_slug = slug
        counter = 1
        while os.path.isfile(os.path.join(self.scripts_dir, f"{slug}.json")):
            slug = f"{base_slug}_{counter}"
            counter += 1

        data = {
            "name": name,
            "slug": slug,
            "description": description,
            "category": category,
            "target_url": target_url,
            "tags": tags or [],
            "steps": steps or [],
            "variables": variables or [],
            "is_function": is_function,
            "function_inputs": function_inputs or [],
            "function_outputs": function_outputs or [],
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        return self._save_script(data)

    def update_script(self, original_slug, **kwargs):
        """Update an existing script."""
        data = self.get_script(original_slug)
        if not data:
            return None

        old_slug = data.get("slug", original_slug)

        for k, v in kwargs.items():
            if v is not None:
                data[k] = v

        new_slug = data.get("slug", old_slug)

        # If slug changed, rename file
        if new_slug != old_slug:
            old_path = os.path.join(self.scripts_dir, f"{old_slug}.json")
            if os.path.isfile(old_path):
                os.remove(old_path)

        return self._save_script(data)

    def delete_script(self, slug):
        """Delete a script."""
        fpath = os.path.join(self.scripts_dir, f"{slug}.json")
        if os.path.isfile(fpath):
            os.remove(fpath)
            logger.info(f"Deleted script: {slug}")
            return True
        return False

    def duplicate_script(self, slug):
        """Duplicate a script with a new slug."""
        original = self.get_script(slug)
        if not original:
            return None
        return self.create_script(
            name=f"{original['name']} (Copy)",
            description=original.get("description", ""),
            category=original.get("category", "general"),
            target_url=original.get("target_url", ""),
            tags=original.get("tags", []),
            steps=original.get("steps", []),
            variables=original.get("variables", []),
            is_function=original.get("is_function", False),
            function_inputs=original.get("function_inputs", []),
            function_outputs=original.get("function_outputs", []),
        )
