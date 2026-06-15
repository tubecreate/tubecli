"""
Script Studio — SQLite Database.
"""
import sqlite3
import json
import os
import logging
import threading
from datetime import datetime

logger = logging.getLogger("ScriptStudio.DB")

_instance = None
_lock = threading.Lock()


class ScriptDatabase:
    """Thread-safe SQLite database for Script Studio."""

    @classmethod
    def get_instance(cls, db_path=None):
        global _instance
        if _instance is None and db_path:
            with _lock:
                if _instance is None:
                    _instance = cls(db_path)
        return _instance

    def __init__(self, db_path):
        self.db_path = db_path
        self._init_schema()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        conn = self._conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE,
                    description TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    target_url TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    steps TEXT DEFAULT '[]',
                    variables TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    is_template BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    script_id TEXT DEFAULT '',
                    profile_name TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    variables TEXT DEFAULT '{}',
                    result TEXT DEFAULT '{}',
                    log TEXT DEFAULT '',
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS elements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    script_id INTEGER,
                    step_index INTEGER DEFAULT 0,
                    name TEXT DEFAULT '',
                    selector TEXT DEFAULT '',
                    xpath TEXT DEFAULT '',
                    screenshot TEXT DEFAULT '',
                    attributes TEXT DEFAULT '{}',
                    page_url TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_scripts_slug ON scripts(slug);
                CREATE INDEX IF NOT EXISTS idx_scripts_category ON scripts(category);
                CREATE INDEX IF NOT EXISTS idx_executions_script ON executions(script_id);
                CREATE INDEX IF NOT EXISTS idx_elements_script ON elements(script_id);
            """)
            conn.commit()
            logger.info(f"Script Studio DB schema initialized: {self.db_path}")
        finally:
            conn.close()

    # ── Scripts CRUD ──

    def list_scripts(self, category=None):
        conn = self._conn()
        try:
            if category:
                rows = conn.execute(
                    "SELECT * FROM scripts WHERE category = ? ORDER BY updated_at DESC", (category,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM scripts ORDER BY updated_at DESC").fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_script(self, script_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def get_script_by_slug(self, slug):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM scripts WHERE slug = ?", (slug,)).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def create_script(self, name, slug=None, description="", category="general",
                      target_url="", tags=None, steps=None, variables=None,
                      metadata=None, is_template=False):
        if not slug:
            slug = name.lower().replace(" ", "_").replace("-", "_")
            # Remove non-alphanumeric except underscore
            slug = "".join(c for c in slug if c.isalnum() or c == "_")

        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO scripts (name, slug, description, category, target_url,
                   tags, steps, variables, metadata, is_template)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name, slug, description, category, target_url,
                    json.dumps(tags or [], ensure_ascii=False),
                    json.dumps(steps or [], ensure_ascii=False),
                    json.dumps(variables or [], ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    is_template,
                )
            )
            conn.commit()
            return self.get_script(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        finally:
            conn.close()

    def update_script(self, script_id, **kwargs):
        conn = self._conn()
        try:
            sets = []
            vals = []
            json_fields = {"tags", "steps", "variables", "metadata"}
            for k, v in kwargs.items():
                if k in json_fields and not isinstance(v, str):
                    v = json.dumps(v, ensure_ascii=False)
                sets.append(f"{k} = ?")
                vals.append(v)
            sets.append("updated_at = ?")
            vals.append(datetime.utcnow().isoformat())
            vals.append(script_id)
            conn.execute(f"UPDATE scripts SET {', '.join(sets)} WHERE id = ?", vals)
            conn.commit()
            return self.get_script(script_id)
        finally:
            conn.close()

    def delete_script(self, script_id):
        conn = self._conn()
        try:
            conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def duplicate_script(self, script_id):
        original = self.get_script(script_id)
        if not original:
            return None
        new_name = f"{original['name']} (Copy)"
        new_slug = f"{original['slug']}_copy_{int(datetime.utcnow().timestamp())}"
        return self.create_script(
            name=new_name,
            slug=new_slug,
            description=original.get("description", ""),
            category=original.get("category", "general"),
            target_url=original.get("target_url", ""),
            tags=original.get("tags", []),
            steps=original.get("steps", []),
            variables=original.get("variables", []),
            metadata=original.get("metadata", {}),
        )

    # ── Executions ──

    def create_execution(self, script_id, profile_name="", variables=None):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO executions (script_id, profile_name, status, variables, started_at)
                   VALUES (?, ?, 'running', ?, ?)""",
                (script_id, profile_name, json.dumps(variables or {}, ensure_ascii=False),
                 datetime.utcnow().isoformat())
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()

    def update_execution(self, exec_id, **kwargs):
        conn = self._conn()
        try:
            sets = []
            vals = []
            json_fields = {"variables", "result"}
            for k, v in kwargs.items():
                if k in json_fields and not isinstance(v, str):
                    v = json.dumps(v, ensure_ascii=False)
                sets.append(f"{k} = ?")
                vals.append(v)
            vals.append(exec_id)
            conn.execute(f"UPDATE executions SET {', '.join(sets)} WHERE id = ?", vals)
            conn.commit()
        finally:
            conn.close()

    def list_executions(self, script_id=None, limit=50):
        conn = self._conn()
        try:
            if script_id:
                rows = conn.execute(
                    "SELECT * FROM executions WHERE script_id = ? ORDER BY id DESC LIMIT ?",
                    (script_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM executions ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # ── Elements ──

    def save_element(self, script_id, step_index, name, selector, xpath="",
                     screenshot="", attributes=None, page_url=""):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO elements (script_id, step_index, name, selector, xpath,
                   screenshot, attributes, page_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (script_id, step_index, name, selector, xpath, screenshot,
                 json.dumps(attributes or {}, ensure_ascii=False), page_url)
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()

    def list_elements(self, script_id):
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM elements WHERE script_id = ? ORDER BY step_index", (script_id,)
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # ── Helpers ──

    def _row_to_dict(self, row):
        if not row:
            return None
        d = dict(row)
        # Parse JSON fields
        for field in ("tags", "steps", "variables", "metadata", "result", "attributes"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
