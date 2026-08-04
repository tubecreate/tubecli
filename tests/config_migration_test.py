"""The boot migration must not invent data it was never given.

Run:  python tests/config_migration_test.py     (exit 0 = pass)

Why this file exists. migrate_and_link_extensions_data() moves extension data
under extensions_data/ and leaves a junction or hardlink at the old location so
code that still names the old path keeps working. For every entry in its
file_mapping it also CREATED the file when it was absent — including with
touch() for non-JSON.

content_studio migrates its SQLite database into JSON, renames
content_studio.db to .migrated, and is finished with it. Because the name is in
file_mapping, the next boot found it "missing" and touch()'d a 0-byte database
back into place; the extension then saw an old DB next to a completed index,
tried to rename it again, and hit FileExistsError because .migrated was already
there. The result was "Could not rename old DB — migration already complete,
ignoring." on every single start, forever, and a 0-byte content_studio.db
hardlinked into data/ that no code ever wanted.

The distinction this locks in: an ABSENT non-JSON file stays absent, while the
JSON pre-creation several extensions may lean on is unchanged.

Everything runs against a temporary data directory. The real one is untouched.
"""
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="tubecli_migration_test_"))
    saved = (cfg.DATA_DIR, cfg.EXTENSIONS_DATA_DIR, cfg.EXTENSIONS_EXTERNAL_DIR)
    cfg.DATA_DIR = tmp / "data"
    cfg.EXTENSIONS_DATA_DIR = cfg.DATA_DIR / "extensions_data"
    cfg.EXTENSIONS_EXTERNAL_DIR = cfg.DATA_DIR / "extensions_external"
    for d in (cfg.DATA_DIR, cfg.EXTENSIONS_DATA_DIR, cfg.EXTENSIONS_EXTERNAL_DIR):
        d.mkdir(parents=True, exist_ok=True)

    try:
        # content_studio's finished state: the DB was renamed away and the JSON
        # index it migrated into is present.
        cs = cfg.EXTENSIONS_DATA_DIR / "content_studio"
        cs.mkdir(parents=True, exist_ok=True)
        (cs / "content_studio.db.migrated").write_bytes(b"sqlite-ish" * 100)
        (cs / "dramas_index.json").write_text("{}", encoding="utf-8")
        db = cs / "content_studio.db"

        cfg.migrate_and_link_extensions_data()

        check("DB da di tru KHONG bi dung lai", not db.exists(),
              f"ton tai, {db.stat().st_size if db.exists() else 0} B")
        check("va khong co ban hardlink o data/", not (cfg.DATA_DIR / "content_studio.db").exists())

        # This is the branch that printed the warning on every boot.
        entered_warning_branch = db.exists() and (cs / "dramas_index.json").exists()
        check("content_studio khong vao nhanh 'rename lai'", not entered_warning_branch)

        # Non-JSON entries stay absent. ytdl_cookies.txt is WRITTEN by
        # video_downloader when it converts a cookie string; an empty one was
        # never read by anything.
        cookies = cfg.EXTENSIONS_DATA_DIR / "video_downloader" / "ytdl_cookies.txt"
        check("file non-JSON vang mat thi de nguyen vang", not cookies.exists(),
              str(cookies))

        # JSON pre-creation is deliberately unchanged.
        for ext, fn in (("web_crawler", "watches.json"),
                        ("studio3d", "studio3d_scenes.json"),
                        ("auth_manager", "auth_manager.json")):
            p = cfg.EXTENSIONS_DATA_DIR / ext / fn
            ok = p.exists() and p.read_text(encoding="utf-8").strip() == "{}"
            check(f"{ext}/{fn} van duoc tao san voi {{}}", ok,
                  f"ton tai={p.exists()}")
            if p.exists():
                check(f"  va van duoc lien ket ra data/{fn}",
                      (cfg.DATA_DIR / fn).exists())

        # A file that really is there must still be moved and linked — the whole
        # point of the shim.
        stray = cfg.DATA_DIR / "calendar_manager.json"
        stray.write_text('{"kept": true}', encoding="utf-8")
        cfg.migrate_and_link_extensions_data()
        moved = cfg.EXTENSIONS_DATA_DIR / "calendar_manager" / "calendar_manager.json"
        check("file co that van duoc chuyen sang extensions_data",
              moved.exists() and "kept" in moved.read_text(encoding="utf-8"),
              moved.read_text(encoding="utf-8") if moved.exists() else "vang")
        if moved.exists() and stray.exists():
            try:
                check("  va hai ten van la mot file (hardlink)",
                      os.path.samefile(str(moved), str(stray)))
            except OSError as e:
                check("  samefile", False, str(e))

        # Idempotent: a second run must not add or change anything.
        before = sorted((str(q.relative_to(tmp)), q.stat().st_size if q.is_file() else -1)
                        for q in tmp.rglob("*"))
        cfg.migrate_and_link_extensions_data()
        after = sorted((str(q.relative_to(tmp)), q.stat().st_size if q.is_file() else -1)
                       for q in tmp.rglob("*"))
        check("chay lai khong doi gi", before == after,
              f"khac {len(set(after) ^ set(before))} muc")
    finally:
        cfg.DATA_DIR, cfg.EXTENSIONS_DATA_DIR, cfg.EXTENSIONS_EXTERNAL_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
