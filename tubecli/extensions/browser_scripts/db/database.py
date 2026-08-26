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


# ── Credentials never reach this table ───────────────────────────────
#
# `variables` is the bag of inputs a script RUN was given, and
# POST /api/v1/scripts/{id}/run fills it from the profile's saved account:
# {service}_password, {service}_recovery, {service}_2fa. Written through
# verbatim, this table became a plaintext password store — one that
# GET /api/v1/scripts/executions/history then served back over HTTP.
#
# Masked in three places, because there are three ways in: on the way IN
# (create_execution / update_execution), on the way OUT (_exec_row, for rows
# older than this code and for a database file restored from a backup), and
# once over the whole table at startup (scrub_stored_variables).
#
# The names come from tubecli.core.secret_names — the same list group_log
# redacts agent replies with. A copy here would be the one that forgets.
try:
    from tubecli.core.secret_names import scrub_mapping as _scrub_mapping
except Exception as _secret_names_err:  # pragma: no cover - only on an old core
    _scrub_mapping = None
    logger.warning(
        "Script Studio: shared secret-name list unavailable (%s) — execution "
        "variables will be stored empty until TubeCLI itself is updated",
        _secret_names_err)


def scrub_variables(value):
    """The variables of a run, minus everything that looks like a credential.

    FAILS CLOSED, three times over:
      * no shared name list (an extension hot-patched onto an older core, which
        is a real deployment here) -> nothing is kept;
      * a column that does not parse as JSON -> there are no keys to judge, so
        nothing about it can be trusted;
      * the filter itself raising -> the whole bag is dropped.
    "We could not check it" must never come out as "so we stored the password".
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    if value is None:
        return {}
    if not isinstance(value, (dict, list)):
        return {}
    if _scrub_mapping is None:
        return {}
    try:
        return _scrub_mapping(value)
    except Exception as e:
        logger.warning(f"scrub_variables failed ({e}) — dropping the whole bag")
        return {}


def _variables_column(value):
    """scrub_variables(), serialised the way this column stores it."""
    return json.dumps(scrub_variables(value), ensure_ascii=False)


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
        # Rows written before create_execution learned to scrub still hold the
        # password. Closing the door does not empty the room.
        try:
            self.scrub_stored_variables()
        except Exception as e:
            logger.warning(f"Script Studio: could not sweep old execution variables: {e}")

    # Bumped when a new one-off pass over existing rows is needed.
    #   1 = executions.variables swept of credentials.
    SWEEP_VERSION = 1

    def scrub_stored_variables(self, force=False):
        """One pass over the executions rows written before the door was shut.

        Only the COLUMN is rewritten. The row itself is the owner's record of
        what ran and when; deleting it to remove a password would be answering
        a leak with data loss. Returns how many rows changed.

        Skipped entirely when the shared name list is missing: there the filter
        would mask nothing and empty every row, which is the same data loss by
        another route. New rows still fail closed (scrub_variables), and the
        read path still refuses to serve what is down there.
        """
        if _scrub_mapping is None:
            logger.warning("Script Studio: no secret-name list — old execution "
                           "variables left on disk (they are no longer served)")
            return 0
        conn = self._conn()
        try:
            done = 0
            try:
                done = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
            except Exception:
                done = 0
            if done >= self.SWEEP_VERSION and not force:
                return 0
            cleaned = 0
            for row in conn.execute("SELECT id, variables FROM executions").fetchall():
                raw = row["variables"]
                if not raw or raw in ("{}", "[]"):
                    continue
                safe = _variables_column(raw)
                if safe != raw:
                    conn.execute("UPDATE executions SET variables = ? WHERE id = ?",
                                 (safe, row["id"]))
                    cleaned += 1
            conn.execute(f"PRAGMA user_version = {int(self.SWEEP_VERSION)}")
            conn.commit()
            if cleaned:
                logger.warning("Script Studio: scrubbed credentials out of %d old "
                               "execution row(s) in %s", cleaned, self.db_path)
            return cleaned
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
                # _variables_column, not json.dumps: the caller's dict carries the
                # profile's real password/2FA when the run was started from the UI.
                (script_id, profile_name, _variables_column(variables or {}),
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
                if k == "variables":
                    # The same door as create_execution. No caller updates this
                    # column today, which is exactly why it has to be shut now:
                    # the first one that does would otherwise bypass the filter.
                    v = _variables_column(v)
                elif k in json_fields and not isinstance(v, str):
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
            return [self._exec_row(r) for r in rows]
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

    def _exec_row(self, row):
        """An executions row on its way out, with `variables` masked again.

        Not merely belt-and-braces: rows written before this file learned to
        scrub are still on disk, the startup pass only ever sweeps the database
        files it is actually run against (an owner who restores an old
        scripts.db has one that was never swept), and this is the single read
        path both HTTP endpoints and any in-process caller go through. Scrubbing
        at the endpoint alone would leave that in-process door open.

        Only the executions table gets this. scripts.variables is the author's
        DECLARED input list, defaults included — masking those would write
        "***" back into the script the next time Script Studio saved it.
        """
        d = self._row_to_dict(row)
        if isinstance(d, dict) and "variables" in d:
            d["variables"] = scrub_variables(d["variables"])
        # `result` is the runner's variable bag too — run_script_sync reads
        # result_data["variables"] out of that file, and a script that saves
        # what it typed into a login form puts the password in there. Nothing
        # writes this column today, which is the cheapest possible moment to
        # shut it. Only a MAPPING is masked, so a caller that one day stores a
        # plain string there still gets its string back.
        if isinstance(d, dict) and isinstance(d.get("result"), (dict, list)):
            d["result"] = scrub_variables(d["result"])
        return d

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
