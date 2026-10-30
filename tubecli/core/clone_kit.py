"""Nhân bản (clone) một máy TubeCLI sang máy khác — extension + template, KHÔNG dữ liệu, KHÔNG agent.

User 30/10/2026: «thêm chức năng clone tubecli từ vps này qua vps khác thông qua mcp, copy tất cả qua vps mới chỉ copy
các extension, template không copy data, agent và để mở phần copy data nếu cần phát triển thêm».

Đường đi (cloud chỉ điều phối, KHÔNG chở byte — Worker giới hạn dung lượng và ~100 s mỗi request):
  1. máy NGUỒN  POST /api/v1/clone/export {sections}  → đóng gói zip vào DATA_DIR/clone/out, trả mã tải dùng-giới-hạn
  2. máy ĐÍCH   POST /api/v1/clone/import {url, sections, mode}  → tự tải zip từ tunnel của nguồn
                  (GET <nguồn>/api/v1/clone/bundle/<mã>), nhập ở luồng nền, trả job; GET /api/v1/clone/jobs/<id>
  Trình kết nối claude.ai: công cụ cloud `server_clone` gọi hai bước trên qua kênh ký HMAC; bước 2 LUÔN cần chủ máy
  đích duyệt (cài mã mới = chạy mã với quyền TubeCLI), giống market_install.

MỤC (SECTIONS) — chỗ mở rộng: mỗi mục là một Section(name, label, enabled, export(zf, ctx), import_(zf, ctx)).
  • extensions  — mã extension cài ngoài (DATA_DIR/extensions_external/*) trừ dữ liệu/thư mục chạy/tệp bí mật.
                  Extension có sẵn trong lõi KHÔNG chép (đi theo phiên bản TubeCLI).
  • templates   — kho mẫu của Content Studio qua cặp xuất/nhập zip có sẵn của nó (cả thư viện ảnh; nhập mặc định an
                  toàn: mẫu mới thêm, trùng y hệt bỏ qua, trùng tên khác nội dung giữ cả hai — không ghi đè).
  • data, agents — KHAI SẴN nhưng TẮT (enabled=False). Muốn mở: viết export/import cho mục rồi bật enabled; API,
                  công cụ MCP và báo cáo tự nhận mục mới, không phải sửa chỗ khác.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

FORMAT = "tubecli-clone/1"
BUNDLE_TTL_S = 2 * 3600          # dài hơn hạn link duyệt (30 phút) + thời gian tải
BUNDLE_MAX_DOWNLOADS = 5
MAX_BUNDLE_BYTES = 3 * 1024 ** 3
DOWNLOAD_TIMEOUT_S = 1800
BUNDLE_PATH_RE = re.compile(r"^/api/v1/clone/bundle/([A-Za-z0-9_-]{32,64})$")
MODES = ("newer", "missing", "all")
DEFAULT_SECTIONS = ("extensions", "templates")

# Không chép: dữ liệu chạy, thư viện cài lại được, rác dựng, và tệp mang bí mật.
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "data", "db", "logs", "tmp", ".pytest_cache",
             ".mypy_cache", ".vscode", ".idea", "coverage"}
SKIP_EXTS = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db", ".pid"}
# Đã nén sẵn: ghi STORED (không deflate lại) — cloud chỉ chờ máy ~55 s mỗi lời gọi.
STORED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mp3", ".m4a", ".ogg", ".wav",
               ".zip", ".gz", ".7z", ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".glb", ".onnx", ".bin", ".pt"}
REUSE_EXPORT_S = 15 * 60
SECRET_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "auth.json", "connect.json", "cookies*",
                "*cookie*.json", "credential*", "*credentials*.json", "token*.json", "*_token.json", "secret*",
                "*secrets*", "cloud_api_keys.json", "service_account*.json", "client_secret*.json", "*.kdbx")


def _data_dir() -> Path:
    from tubecli.config import DATA_DIR
    return Path(DATA_DIR)


def _ext_root() -> Path:
    return _data_dir() / "extensions_external"


def _clone_dir(*parts: str) -> Path:
    p = _data_dir().joinpath("clone", *parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now() -> int:
    return int(time.time())


def _version_tuple(v: Any) -> tuple:
    out = []
    for part in re.split(r"[.\-+]", str(v or "")):
        out.append(int(part) if part.isdigit() else -1)
    return tuple(out) or (-1,)


def _is_secret(name: str) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, pat) for pat in SECRET_NAMES)


def _manifest_of(ext_dir: Path) -> Dict[str, Any]:
    try:
        with open(ext_dir / "tubecli-extension.json", encoding="utf-8-sig") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _iter_ext_files(ext_dir: Path, keep_dirs: List[str]):
    """(đường dẫn tương đối, đường dẫn thật) của mọi tệp được chép. Tệp bí mật trả qua `skipped`."""
    keep = {k.strip("/\\") for k in keep_dirs if isinstance(k, str)}
    for root, dirs, files in os.walk(ext_dir):
        rel_root = os.path.relpath(root, ext_dir)
        rel_root = "" if rel_root == "." else rel_root.replace("\\", "/")
        dirs[:] = [d for d in dirs
                   if not (d in SKIP_DIRS and (f"{rel_root}/{d}".strip("/") not in keep))
                   and not os.path.islink(os.path.join(root, d))]
        for fn in files:
            rel = f"{rel_root}/{fn}".strip("/")
            yield rel, os.path.join(root, fn)


# ── Mục ──────────────────────────────────────────────────────────────────────
@dataclass
class Section:
    name: str
    label: str
    enabled: bool
    describe: Callable[[], Dict[str, Any]]
    export: Optional[Callable[[zipfile.ZipFile, Dict[str, Any]], Dict[str, Any]]] = None
    import_: Optional[Callable[[zipfile.ZipFile, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None
    note: str = ""


def _ext_describe() -> Dict[str, Any]:
    items = []
    root = _ext_root()
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            m = _manifest_of(d)
            items.append({"dir": d.name, "name": m.get("name") or d.name, "version": str(m.get("version") or ""),
                          "kind": "extension" if m else "support"})
    try:
        from tubecli.core.extension_manager import extension_manager
        builtin = sorted(e.name for e in extension_manager.get_all() if getattr(e, "extension_type", "") != "external")
    except Exception:  # noqa: BLE001
        builtin = []
    return {"items": items, "builtin_not_copied": builtin}


def _ext_export(zf: zipfile.ZipFile, ctx: Dict[str, Any]) -> Dict[str, Any]:
    out, skipped_secret = [], []
    root = _ext_root()
    if not root.is_dir():
        return {"items": []}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        m = _manifest_of(d)
        n_files, n_bytes = 0, 0
        for rel, real in _iter_ext_files(d, m.get("package_keep_dirs") or []):
            base = os.path.basename(rel)
            if os.path.splitext(base)[1].lower() in SKIP_EXTS:
                continue
            if _is_secret(base):
                skipped_secret.append(f"{d.name}/{rel}")
                continue
            try:
                ctype = zipfile.ZIP_STORED if os.path.splitext(base)[1].lower() in STORED_EXTS else zipfile.ZIP_DEFLATED
                zf.write(real, f"extensions/{d.name}/{rel}", compress_type=ctype)
            except OSError:
                continue
            n_files += 1
            n_bytes += os.path.getsize(real)
            ctx["bytes"] = ctx.get("bytes", 0) + os.path.getsize(real)
            if ctx["bytes"] > MAX_BUNDLE_BYTES:
                raise RuntimeError(f"Bundle would exceed {MAX_BUNDLE_BYTES // 1024 ** 3} GB — stopped at {d.name}")
        out.append({"dir": d.name, "name": m.get("name") or d.name, "version": str(m.get("version") or ""),
                    "kind": "extension" if m else "support", "files": n_files, "bytes": n_bytes,
                    "has_requirements": (d / "requirements.txt").is_file(), "has_package_json": (d / "package.json").is_file()})
    return {"items": out, "skipped_secret_files": skipped_secret[:200]}


def _plan_ext(items: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    root = _ext_root()
    plan = []
    for it in items:
        d = str(it.get("dir") or "")
        if not d or "/" in d or "\\" in d or d.startswith("."):
            continue
        here = root / d
        local = _manifest_of(here) if here.is_dir() else {}
        lv, sv = str(local.get("version") or ""), str(it.get("version") or "")
        if not here.is_dir():
            action = "install"
        elif mode == "all":
            action = "overwrite"
        elif mode == "newer" and sv and _version_tuple(sv) > _version_tuple(lv):
            action = "update"
        else:
            action = "skip"
        plan.append({"dir": d, "name": it.get("name") or d, "source_version": sv, "local_version": lv, "action": action,
                     "kind": it.get("kind") or "extension"})
    return plan


def _run(cmd: List[str], cwd: str, timeout: int) -> str:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                           errors="replace")
        return "ok" if r.returncode == 0 else f"exit {r.returncode}: {(r.stderr or r.stdout or '')[-300:]}"
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout} s"
    except (OSError, ValueError) as e:
        return f"could not run: {e}"


def _ext_import(zf: zipfile.ZipFile, man: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    plan = _plan_ext(((man.get("sections") or {}).get("extensions") or {}).get("items") or [], ctx.get("mode", "newer"))
    root = _ext_root()
    root.mkdir(parents=True, exist_ok=True)
    names = zf.namelist()
    done = []
    for p in plan:
        if p["action"] == "skip":
            done.append({**p, "result": "skipped"})
            continue
        prefix = f"extensions/{p['dir']}/"
        dest = root / p["dir"]
        dest_real = os.path.realpath(dest)
        written = 0
        for n in names:
            if not n.startswith(prefix) or n.endswith("/"):
                continue
            rel = n[len(prefix):]
            parts = rel.split("/")
            if not rel or ".." in parts or parts[0] in SKIP_DIRS or _is_secret(parts[-1]):
                continue
            target = os.path.realpath(dest / rel)
            if not target.startswith(dest_real + os.sep):
                continue                                    # chống zip-slip
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(n) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            written += 1
        row = {**p, "files": written, "result": "installed" if p["action"] == "install" else "updated"}
        if (dest / "requirements.txt").is_file():
            row["pip"] = _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"], str(dest), 600)
        if (dest / "package.json").is_file() and not (dest / "node_modules").is_dir() and shutil.which("npm"):
            row["npm"] = _run([shutil.which("npm"), "install", "--omit=dev", "--no-audit", "--no-fund"], str(dest), 900)
        done.append(row)
    return {"items": done}


# ── template (Content Studio) ────────────────────────────────────────────────
def _asgi(app, method: str, path: str, **kw):
    import httpx
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    with_timeout = httpx.Timeout(600.0)

    async def go():
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1", timeout=with_timeout,
                                     headers={"X-TubeCLI-Agent": "clone"}) as c:
            return await c.request(method, path, **kw)
    return go()


def _run_async(coro, loop):
    import asyncio
    if loop is not None and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result(900)
    return asyncio.run(coro)


def _tpl_describe() -> Dict[str, Any]:
    n = 0
    try:
        with open(_data_dir() / "templates" / "templates.json", encoding="utf-8") as f:
            st = json.load(f)
        for sec in (st or {}).values():
            if isinstance(sec, dict):
                n += len(sec)
            elif isinstance(sec, list):
                n += len(sec)
    except (OSError, ValueError, AttributeError):
        pass
    return {"content_studio_templates": n, "not_yet": ["pod_studio presets", "canvas template_packs", "edu_video_studio"]}


def _tpl_export(zf: zipfile.ZipFile, ctx: Dict[str, Any]) -> Dict[str, Any]:
    app = ctx.get("app")
    if app is None:
        return {"content_studio": "skipped: no running server"}
    r = _run_async(_asgi(app, "POST", "/api/v1/studio/preset-bundle/export-zip", json={}), ctx.get("loop"))
    if r.status_code == 404:
        return {"content_studio": "skipped: Content Studio is not installed here"}
    if r.status_code >= 400:
        raise RuntimeError(f"Content Studio template export failed: HTTP {r.status_code} {r.text[:200]}")
    zf.writestr("templates/content_studio.zip", r.content)
    ctx["bytes"] = ctx.get("bytes", 0) + len(r.content)
    return {"content_studio": "exported", "bytes": len(r.content)}


def _tpl_import_bytes(app, loop, data: bytes) -> Dict[str, Any]:
    r = _run_async(_asgi(app, "POST", "/api/v1/studio/preset-bundle/import-zip",
                         files={"file": ("templates.zip", data, "application/zip")}), loop)
    if r.status_code == 404:
        return {"result": "pending", "reason": "Content Studio is not loaded yet"}
    if r.status_code >= 400:
        return {"result": "failed", "reason": f"HTTP {r.status_code} {r.text[:200]}"}
    uid = (r.json() or {}).get("upload_id")
    r2 = _run_async(_asgi(app, "POST", "/api/v1/studio/preset-bundle/import", json={"upload_id": uid, "apply": True}), loop)
    if r2.status_code >= 400:
        return {"result": "failed", "reason": f"HTTP {r2.status_code} {r2.text[:200]}"}
    js = r2.json() if r2.headers.get("content-type", "").startswith("application/json") else {}
    return {"result": "imported", "summary": {k: js.get(k) for k in ("added", "skipped", "renamed", "written", "count")
                                              if isinstance(js, dict) and k in js}}


def _tpl_import(zf: zipfile.ZipFile, man: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if "templates/content_studio.zip" not in zf.namelist():
        return {"content_studio": "nothing in the bundle"}
    data = zf.read("templates/content_studio.zip")
    res = _tpl_import_bytes(ctx.get("app"), ctx.get("loop"), data) if ctx.get("app") is not None else \
        {"result": "pending", "reason": "no running server"}
    if res.get("result") == "pending":
        # Content Studio vừa được chép sang nhưng chưa nạp (extension MỚI cần khởi động lại): giữ gói, nhập lúc khởi động.
        p = _clone_dir("pending") / f"templates-{secrets.token_hex(4)}.zip"
        p.write_bytes(data)
        res["staged"] = p.name
        res["note"] = "Templates will be imported automatically after TubeCLI restarts."
    return {"content_studio": res}


def apply_pending(app, loop=None) -> List[Dict[str, Any]]:
    """Gọi sau khi server khởi động: nhập các gói template đã xếp chờ (Content Studio lúc đó mới nạp)."""
    out = []
    pend = _data_dir() / "clone" / "pending"
    if not pend.is_dir():
        return out
    for p in sorted(pend.glob("templates-*.zip")):
        res = _tpl_import_bytes(app, loop, p.read_bytes())
        out.append({"file": p.name, **res})
        if res.get("result") in ("imported", "failed"):
            try:
                p.unlink()
            except OSError:
                pass
    return out


def _off(name: str) -> Dict[str, Any]:
    return {"enabled": False, "note": f"'{name}' is not cloned yet — see SECTIONS in tubecli/core/clone_kit.py"}


SECTIONS: Dict[str, Section] = {
    "extensions": Section("extensions", "Extensions (code)", True, _ext_describe, _ext_export, _ext_import),
    "templates": Section("templates", "Templates (Content Studio)", True, _tpl_describe, _tpl_export, _tpl_import),
    # CHỖ MỞ RỘNG — chưa làm theo yêu cầu (không chép data, agent). Bật = viết export/import + enabled=True.
    "data": Section("data", "Data (projects, media, browser profiles, keys)", False, lambda: _off("data"),
                    note="Off by design: data can hold accounts, cookies and API keys."),
    "agents": Section("agents", "Agents and schedules", False, lambda: _off("agents"),
                      note="Off by design."),
}


def sections_public() -> List[Dict[str, Any]]:
    return [{"name": s.name, "label": s.label, "enabled": s.enabled, "note": s.note} for s in SECTIONS.values()]


def _pick_sections(sections) -> List[str]:
    names = [str(s).strip().lower() for s in (sections or DEFAULT_SECTIONS) if str(s).strip()]
    bad = [n for n in names if n not in SECTIONS]
    if bad:
        raise ValueError(f"Unknown section(s): {', '.join(bad)}. Known: {', '.join(SECTIONS)}")
    off = [n for n in names if not SECTIONS[n].enabled]
    if off:
        raise ValueError(f"Section(s) not available yet: {', '.join(off)} — only {', '.join(n for n, s in SECTIONS.items() if s.enabled)} "
                         "can be cloned. Data and agents are left out on purpose.")
    return list(dict.fromkeys(names))


def local_manifest() -> Dict[str, Any]:
    from tubecli import __version__
    return {"format": FORMAT, "tubecli_version": __version__, "sections_available": sections_public(),
            "sections": {n: s.describe() for n, s in SECTIONS.items() if s.enabled}}


# ── xuất (máy nguồn) ─────────────────────────────────────────────────────────
_lock = threading.RLock()


def _tokens_path() -> Path:
    return _clone_dir() / "tokens.json"


def _load_tokens() -> Dict[str, Any]:
    try:
        with open(_tokens_path(), encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_tokens(t: Dict[str, Any]) -> None:
    tmp = str(_tokens_path()) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(t, f)
    os.replace(tmp, _tokens_path())


def _sweep(t: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    keep = {}
    for k, v in t.items():
        if int(v.get("expires_at") or 0) > now:
            keep[k] = v
        else:
            try:
                os.remove(_clone_dir("out") / v.get("file", ""))
            except OSError:
                pass
    return keep


_export_lock = threading.Lock()


def _recent_export(names: List[str]) -> Optional[Dict[str, Any]]:
    with _lock:
        t = _sweep(_load_tokens())
    best = None
    for tok, v in t.items():
        m = v.get("manifest") or {}
        if sorted((m.get("sections") or {}).keys()) != sorted(names) or int(v.get("downloads") or 0):
            continue
        if _now() - int(m.get("created_at") or 0) > REUSE_EXPORT_S:
            continue
        if best is None or int(m.get("created_at") or 0) > int(best[1]["manifest"].get("created_at") or 0):
            best = (tok, v)
    if best is None:
        return None
    tok, v = best
    p = _clone_dir("out") / v["file"]
    if not p.is_file():
        return None
    return {"token": tok, "path": f"/api/v1/clone/bundle/{tok}", "manifest_path": f"/api/v1/clone/bundle/{tok}/manifest",
            "bytes": p.stat().st_size, "expires_at": v["expires_at"], "sections": names, "manifest": v["manifest"],
            "reused": True}


def export_bundle(sections=None, app=None, loop=None, fresh: bool = False) -> Dict[str, Any]:
    """Đóng gói. Gói cùng mục vừa làm (< 15 phút, chưa ai tải) được dùng lại — lời gọi quá giờ ở cloud gọi lại là
    nhận ngay gói đã xong; hai lời gọi trùng nhau thì lời sau chờ lời trước (khoá) rồi nhận chính gói đó."""
    names = _pick_sections(sections)
    with _export_lock:
        if not fresh:
            got = _recent_export(names)
            if got:
                return got
        return _export_bundle_locked(names, app, loop)


def _export_bundle_locked(names: List[str], app=None, loop=None) -> Dict[str, Any]:
    from tubecli import __version__
    token = secrets.token_urlsafe(32)
    fname = f"clone-{_now()}-{secrets.token_hex(4)}.zip"
    path = _clone_dir("out") / fname
    ctx: Dict[str, Any] = {"app": app, "loop": loop, "bytes": 0}
    man: Dict[str, Any] = {"format": FORMAT, "tubecli_version": __version__, "created_at": _now(), "sections": {}}
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for n in names:
                man["sections"][n] = SECTIONS[n].export(zf, ctx)
            zf.writestr("manifest.json", json.dumps(man, ensure_ascii=False, indent=1))
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    size = path.stat().st_size
    with _lock:
        t = _sweep(_load_tokens())
        t[token] = {"file": fname, "expires_at": _now() + BUNDLE_TTL_S, "downloads": 0, "manifest": man}
        _save_tokens(t)
    return {"token": token, "path": f"/api/v1/clone/bundle/{token}", "manifest_path": f"/api/v1/clone/bundle/{token}/manifest",
            "bytes": size, "expires_at": _now() + BUNDLE_TTL_S, "sections": names, "manifest": man}


def bundle_for(token: str, count: bool = True) -> Optional[Dict[str, Any]]:
    """Gói ứng với mã (còn hạn, còn lượt tải) — đếm lượt khi count=True. None = không có / hết hạn / hết lượt."""
    with _lock:
        t = _sweep(_load_tokens())
        v = t.get(str(token or ""))
        if not v or int(v.get("downloads") or 0) >= BUNDLE_MAX_DOWNLOADS:
            _save_tokens(t)
            return None
        if count:
            v["downloads"] = int(v.get("downloads") or 0) + 1
        _save_tokens(t)
        return {**v, "file_path": str(_clone_dir("out") / v["file"])}


# ── nhập (máy đích) ──────────────────────────────────────────────────────────
JOBS: Dict[str, Dict[str, Any]] = {}


def check_bundle_url(url: str) -> str:
    """Chỉ nhận https://<máy>/api/v1/clone/bundle/<mã> — không cho trỏ tải bất kỳ địa chỉ nào (SSRF / mã lạ)."""
    u = urllib.parse.urlsplit(str(url or "").strip())
    if u.scheme != "https" or not u.hostname or u.query or u.fragment or not BUNDLE_PATH_RE.match(u.path or ""):
        raise ValueError("url must be https://<server>/api/v1/clone/bundle/<token> (from the source machine's export)")
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))


def fetch_remote_manifest(url: str, timeout: int = 30) -> Dict[str, Any]:
    url = check_bundle_url(url)
    req = urllib.request.Request(url + "/manifest", headers={"User-Agent": "TubeCLI-Clone/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def plan_import(man: Dict[str, Any], sections=None, mode: str = "newer") -> Dict[str, Any]:
    names = _pick_sections(sections)
    mode = mode if mode in MODES else "newer"
    out: Dict[str, Any] = {"mode": mode, "sections": names, "source_version": man.get("tubecli_version")}
    if "extensions" in names:
        out["extensions"] = _plan_ext(((man.get("sections") or {}).get("extensions") or {}).get("items") or [], mode)
    if "templates" in names:
        out["templates"] = (man.get("sections") or {}).get("templates") or {}
    return out


def plan_summary(plan: Dict[str, Any]) -> str:
    lines = []
    ex = plan.get("extensions") or []
    by = {}
    for p in ex:
        by.setdefault(p["action"], []).append(p)
    for act, label in (("install", "install"), ("update", "update"), ("overwrite", "overwrite"), ("skip", "skip")):
        rows = by.get(act) or []
        if rows:
            shown = ", ".join(f"{r['name']} {r['source_version']}".strip() + (f" (has {r['local_version']})" if r["local_version"] else "")
                              for r in rows[:12])
            lines.append(f"{label} {len(rows)} extension(s): {shown}{' …' if len(rows) > 12 else ''}")
    if "templates" in plan.get("sections", []):
        t = plan.get("templates") or {}
        lines.append("import Content Studio templates (new ones added, identical skipped, same-name kept as a copy — "
                     "nothing overwritten)" if t.get("content_studio") == "exported" else
                     f"templates: {t.get('content_studio') or 'none in the bundle'}")
    lines.append(f"mode: {plan.get('mode')}; data and agents are NOT copied")
    return "\n".join(lines)


def _download(url: str, dest: Path, job: Dict[str, Any]) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "TubeCLI-Clone/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        got, t0 = 0, time.time()
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if got > MAX_BUNDLE_BYTES:
                raise RuntimeError("bundle is larger than allowed")
            if time.time() - t0 > DOWNLOAD_TIMEOUT_S:
                raise RuntimeError("download took too long")
            job.update(stage="downloading", downloaded=got, total=total)


def start_import(url: str, sections=None, mode: str = "newer", app=None, loop=None) -> Dict[str, Any]:
    url = check_bundle_url(url)
    names = _pick_sections(sections)
    jid = secrets.token_hex(6)
    job = {"id": jid, "status": "running", "stage": "starting", "started_at": _now(), "sections": names, "mode": mode,
           "source": urllib.parse.urlsplit(url).hostname, "report": {}}
    JOBS[jid] = job

    def work():
        tmp = Path(tempfile.mkdtemp(prefix="tubecli_clone_"))
        try:
            zpath = tmp / "bundle.zip"
            _download(url, zpath, job)
            job["stage"] = "importing"
            with zipfile.ZipFile(zpath) as zf:
                man = json.loads(zf.read("manifest.json").decode("utf-8"))
                if man.get("format") != FORMAT:
                    raise RuntimeError(f"unknown bundle format {man.get('format')!r}")
                ctx = {"app": app, "loop": loop, "mode": mode if mode in MODES else "newer"}
                for n in names:
                    sec = SECTIONS[n]
                    if n not in (man.get("sections") or {}):
                        job["report"][n] = {"result": "not in the bundle"}
                        continue
                    job["stage"] = f"importing {n}"
                    job["report"][n] = sec.import_(zf, man, ctx)
            ext_rows = (job["report"].get("extensions") or {}).get("items") or []
            # Extension CẬP NHẬT: nạp nóng tại chỗ (POST /api/v1/extensions/<tên>/reload). Extension MỚI chỉ nạp được
            # khi khởi động lại — báo rõ thay vì tự khởi động lại (cắt ngang việc đang chạy trên máy đích).
            if app is not None:
                for r in ext_rows:
                    if r.get("result") == "updated" and r.get("kind") == "extension":
                        try:
                            rr = _run_async(_asgi(app, "POST", "/api/v1/extensions/"
                                                  + urllib.parse.quote(str(r.get("name") or r["dir"]), safe="") + "/reload"), loop)
                            r["reloaded"] = rr.status_code < 400
                        except Exception:  # noqa: BLE001
                            r["reloaded"] = False
            tpl = (job["report"].get("templates") or {}).get("content_studio")
            job["restart_required"] = any(
                r.get("result") == "installed" or (r.get("result") == "updated" and not r.get("reloaded"))
                for r in ext_rows) or (isinstance(tpl, dict) and tpl.get("result") == "pending")
            job.update(status="done", stage="done", finished_at=_now())
        except Exception as e:  # noqa: BLE001
            job.update(status="failed", error=str(e)[:500], finished_at=_now())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            _save_job(job)

    threading.Thread(target=work, daemon=True, name=f"clone-{jid}").start()
    return {"job_id": jid, "status": "running", "status_path": f"/api/v1/clone/jobs/{jid}"}


def _save_job(job: Dict[str, Any]) -> None:
    try:
        p = _clone_dir("jobs") / f"{job['id']}.json"
        p.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def job_status(jid: str) -> Optional[Dict[str, Any]]:
    j = JOBS.get(str(jid or ""))
    if j is not None:
        return j
    p = _data_dir() / "clone" / "jobs" / f"{str(jid or '')}.json"
    if re.fullmatch(r"[0-9a-f]{12}", str(jid or "")) and p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None
