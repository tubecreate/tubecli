"""
TubeCLI REST API Server
FastAPI-based REST API for agents, skills, and workflows.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os, sys
import mimetypes
import random  # module-level for the schedule behavior helpers below

_BUILD_ETAG = "306d3aa214be205cb2f9d9e3ee8dae2f"  # release build etag

# Fix Windows registry MIME type bug for CSS/JS/SVG files
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/json", ".json")


app = FastAPI(
    title="TubeCLI API",
    description="REST API for TubeCLI — AI Agent management, skills, and workflows.",
    version="0.1.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Cross-origin guard for the whole API surface ─────────────────────────
# CORS above is deliberately permissive so any local tool can call the API. That
# alone would let ANY web page the user happens to have open drive this server
# through their own browser: it binds to loopback, but the attacker's JavaScript
# runs inside the victim's browser, which is already on loopback. The dangerous
# reach is not only credential endpoints — POST /api/v1/extensions/install does
# git clone + pip install + npm install, i.e. arbitrary code execution.
#
# Guarding router-by-router missed that: only two extension routers carried the
# dependency, leaving every route defined here unprotected. A middleware covers
# the entire surface at once and cannot be forgotten when a route is added.
#
# Requests with no Origin header (curl, the CLI itself, Telegram, any
# server-side client) are untouched. Browser requests are allowed only from
# loopback, or from a host listed in TUBECLI_ALLOWED_ORIGIN_HOSTS for people who
# deliberately serve the dashboard on a LAN address.
# Paths that must answer before anyone is logged in, or nobody could ever log
# in. Deliberately short, and matched by exact path or prefix — never by
# substring, so a crafted URL like /api/v1/files/read?x=/login cannot slip past.
_AUTH_EXEMPT_EXACT = {"/login", "/api/v1/auth/login", "/api/v1/auth/status",
                      # Sharee đổi guest token lấy cookie tubecli_guest — phải gọi
                      # được TRƯỚC khi có session (như /auth/login). Mint token thì
                      # KHÔNG exempt (chủ-authed).
                      "/api/v1/auth/guest-login",
                      "/api/v1/auth/banner.js", "/favicon.ico",
                      # Health is exempt so "curl http://<ip>:5295/api/v1/health"
                      # works from the user's laptop as the install-check the
                      # summary screen advertises. It returns strictly less than
                      # the already-exempt /auth/status.
                      "/api/v1/health"}
_AUTH_EXEMPT_PREFIX = ("/webui/static/", "/static/")


def _auth_exempt(path: str) -> bool:
    return path in _AUTH_EXEMPT_EXACT or path.startswith(_AUTH_EXEMPT_PREFIX)


# Paths the read-only scraped key may reach. Everything else — including
# /scraped-guide, which would just hand back the key that opened it — stays
# session-only. The pattern is anchored at both ends so a path that merely
# CONTAINS one of these names cannot slip in.
import re as _re

_READ_KEY_PATHS = _re.compile(
    r"^/api/v1/(?:scraped/(?:articles|article|stats|export|profiles|image)"
    r"|agents/[^/]+/scraped)$"
)


def _read_key_from(request: Request) -> Optional[str]:
    """The key, from wherever a one-shot client can put it.

    Three carriers because the tools differ: a header is correct, Bearer is
    what most HTTP clients offer by default, and the query string is the only
    option left for a cloud AI that can do nothing but fetch a URL. That last
    one lands in access logs and Referer headers, which is a real cost — and
    the reason this key is scoped to reading articles rather than being the
    password.
    """
    value = request.headers.get("x-tubecli-token")
    if not value:
        authz = request.headers.get("authorization") or ""
        if authz.lower().startswith("bearer "):
            value = authz[7:]
    if not value:
        value = request.query_params.get("token")
    return (value or "").strip() or None


def _read_key_authorised(request: Request) -> bool:
    """GET-only, on the data paths only, with a valid key."""
    if request.method != "GET" or not _READ_KEY_PATHS.match(request.url.path):
        return False
    from tubecli.core import auth

    return auth.scraped_read_token_valid(_read_key_from(request))


async def _guest_allowed(request: Request, scope: dict) -> bool:
    """Guest (workspace được chia sẻ có phạm vi) có được chạm path này không?

    DENY MẶC ĐỊNH. G1: chỉ BROWSER preview scoped theo profile — enforce TRỌN ở đây
    (1 điểm, ít lỗ hổng). launch/stop kiểm profile trong body (Starlette cache body
    nên route vẫn đọc lại được); screenshot theo port→profile; status/profiles read-
    only cho qua. WS enforce RIÊNG ở /preview/ws. Terminal/file/credentials/agent/
    extension/profile-CRUD... → False. G2/G3 mở thêm chat + extension. Xem
    docs/guest-scoped-workspace-design.md.
    """
    p = request.url.path
    m = request.method
    profiles = set(str(x) for x in (scope.get("profiles") or []))
    # Ba mức quyền của share: view (chỉ nhìn) < control (điều khiển browser,
    # chat agent — mặc định, đúng hành vi trước giờ) < full (control + ghi/sửa
    # dữ liệu của nhóm). Nhánh CHỈ-ĐỌC đi qua cho mọi mức; nhánh THAO TÁC đòi
    # access != "view"; nhánh GHI đòi "full".
    access = str(scope.get("access") or "control")

    if m == "GET" and p in ("/api/v1/browser/status", "/api/v1/browser/profiles"):
        return True

    if m == "POST" and access != "view" and p in ("/api/v1/browser/preview/launch",
                                                  "/api/v1/browser/preview/stop",
                                                  "/api/v1/browser/stop"):
        try:
            body = await request.json()
        except Exception:
            return False
        return str((body or {}).get("profile") or "") in profiles

    mo = _re.match(r"^/api/v1/browser/preview/screenshot/(\d+)$", p)
    if mo and m == "GET":
        try:
            from tubecli.extensions.browser.routes import _resolve_profile_for_port
            return (_resolve_profile_for_port(int(mo.group(1))) or "") in profiles
        except Exception:
            return False

    # Upload file TỪ MÁY SHAREE vào browser trong nhóm (không đọc VPS) — chỉ port∈profiles.
    mo = _re.match(r"^/api/v1/browser/preview/(?:upload|upload-chunk|upload-finalize)/(\d+)$", p)
    if mo and m == "POST" and access != "view":
        try:
            from tubecli.extensions.browser.routes import _resolve_profile_for_port
            return (_resolve_profile_for_port(int(mo.group(1))) or "") in profiles
        except Exception:
            return False

    # Gắn file VPS (∈ folder/file được chia sẻ) vào browser theo PROFILE — profile∈scope + path∈scope.
    if m == "POST" and access != "view" and p == "/api/v1/browser/preview/attach-file":
        try:
            from tubecli.core import auth
            body = await request.json()
        except Exception:
            return False
        if str((body or {}).get("profile") or "") not in profiles:
            return False
        path = (body or {}).get("path")
        return bool(path) and (auth.path_in_folders(path, scope.get("folders") or [])
                               or auth.path_is_shared_file(path, scope.get("files") or []))

    # ── File được chia sẻ: FOLDER node (prefix) + FILE node lẻ (exact) ──
    # list/read/raw CHỈ đọc (GET/HEAD), realpath+prefix/exact chặn traversal/symlink
    # (xem auth._canon_fs). list chỉ trong folders (file không phải thư mục để liệt kê);
    # read/raw cho path ∈ folder HOẶC == file chia sẻ. Deny-default lo search/download/write/…
    folders = scope.get("folders") or []
    files = scope.get("files") or []
    if (folders or files) and m in ("GET", "HEAD") and p in (
        "/api/v1/file-manager/list",
        "/api/v1/file-manager/read",
        "/api/v1/file-manager/raw",
        "/api/v1/file-manager/read-sheet",
        "/api/v1/file-manager/xlsx/grid",
    ):
        # getlist (KHÔNG .get): nếu client nhồi ?path=/an-toàn&path=/etc/shadow thì
        # route có thể đọc giá trị route chọn ≠ giá trị ta kiểm — bắt MỌI giá trị hợp lệ.
        from tubecli.core import auth
        vals = request.query_params.getlist("path")
        if not vals:
            return False
        if p == "/api/v1/file-manager/list":
            return bool(folders) and all(auth.path_in_folders(v, folders) for v in vals)
        return all(auth.path_in_folders(v, folders) or auth.path_is_shared_file(v, files) for v in vals)

    # Ghi xlsx của nhóm (lưới SheetEditor): chỉ share TOÀN QUYỀN, path phải
    # thuộc folder/file đã chia sẻ — cùng phép realpath/prefix với read.
    if (folders or files) and access == "full" and m == "POST" and p in (
        "/api/v1/file-manager/write-sheet",
        "/api/v1/file-manager/xlsx/cells",
        "/api/v1/file-manager/xlsx/format",
        "/api/v1/file-manager/xlsx/merge",
    ):
        try:
            from tubecli.core import auth
            body = await request.json()
        except Exception:
            return False
        _wp = (body or {}).get("path")
        return bool(_wp) and (auth.path_in_folders(_wp, folders)
                              or auth.path_is_shared_file(_wp, files))

    # ── File Manager / Drive (G3): CHỈ khi scope.file_manager.drive bật ──
    # Cho: liệt kê account (lộ email — chấp nhận, siết sau), duyệt Drive (cred_id∈scope,
    # CHẶN ?q= search toàn Drive), và GẮN file Drive vào browser (endpoint hợp nhất, không
    # path). CHẶN: drive/download|fetch|upload|write, upload-local, mọi file cục bộ.
    fm = scope.get("file_manager") or {}
    if fm.get("drive"):
        creds = set(str(x) for x in (fm.get("drive_cred_ids") or []))
        if m == "GET" and p == "/api/v1/file-manager/drive/accounts":
            return True
        if m == "GET" and p == "/api/v1/file-manager/drive/list":
            q = request.query_params
            if q.get("q"):
                return False
            return str(q.get("cred_id") or "") in creds
        mo = _re.match(r"^/api/v1/browser/preview/drive-attach/(\d+)$", p)
        if mo and m == "POST" and access != "view":
            try:
                from tubecli.extensions.browser.routes import _resolve_profile_for_port
                if (_resolve_profile_for_port(int(mo.group(1))) or "") not in profiles:
                    return False
                body = await request.json()
                cid = (body or {}).get("cred_id")
                return cid is None or str(cid) in creds
            except Exception:
                return False

    # ── THƯ MỤC DRIVE chia sẻ qua bàn làm việc ──────────────────────────────
    # Chủ kéo một thư mục Drive ra canvas → nó là "khu vực" của người nhận:
    # duyệt, tải về máy, tải lên, tạo thư mục con, và gắn file vào browser
    # (đường đi để đăng YouTube) — TẤT CẢ chỉ trong thư mục đó và các thư mục
    # con, kiểm bằng drive.is_within (leo `parents`, fail-closed).
    #
    # KHÔNG mở /drive/upload và /drive/download: hai route đó đọc/ghi ĐĨA MÁY
    # CHỦ sau sandbox nghiêm ngặt của AI. Người nhận lấy file bằng /fetch (đi
    # thẳng về máy họ) và đưa file lên bằng /upload-content (byte từ trình
    # duyệt) — không route nào chạm tới đường dẫn trên server.
    dfolders = scope.get("drive_folders") or []
    if dfolders and access != "view":
        def _roots(cid):
            return [str(x.get("folder_id")) for x in dfolders
                    if isinstance(x, dict) and str(x.get("cred_id") or "") == str(cid or "")
                    and x.get("folder_id")]

        try:
            from tubecli.extensions.file_manager import drive as _drv
        except Exception:
            _drv = None

        if _drv is not None:
            _q = request.query_params
            _cid = str(_q.get("cred_id") or "")
            if m == "GET" and p == "/api/v1/file-manager/drive/list":
                # Tìm-toàn-Drive (?q=) bị chặn: nó nhìn ra ngoài khu vực.
                if _q.get("q"):
                    return False
                return _drv.is_within(_cid, str(_q.get("folder_id") or ""), _roots(_cid))
            if m == "GET" and p == "/api/v1/file-manager/drive/fetch":
                return _drv.is_within(_cid, str(_q.get("file_id") or ""), _roots(_cid))
            # Xin quyền Google cho CHÍNH email đăng nhập (để mở file bằng
            # Sheets/Docs thật). Route tự lấy email từ scope, tự kiểm khu vực —
            # ở đây chỉ cần chắc file thuộc khu vực đã chia sẻ.
            if m == "POST" and p == "/api/v1/file-manager/drive/share-self":
                try:
                    _b = await request.json()
                except Exception:
                    return False
                _bc = str((_b or {}).get("cred_id") or "")
                return _drv.is_within(_bc, str((_b or {}).get("file_id") or ""), _roots(_bc))
            if m == "POST" and p == "/api/v1/file-manager/drive/upload-content":
                return _drv.is_within(_cid, str(_q.get("folder_id") or ""), _roots(_cid))
            if m == "POST" and p == "/api/v1/file-manager/drive/mkdir":
                try:
                    _b = await request.json()
                except Exception:
                    return False
                _bc = str((_b or {}).get("cred_id") or "")
                return _drv.is_within(_bc, str((_b or {}).get("parent_id") or ""), _roots(_bc))
            # Gắn file Drive vào browser đang chiếu (đường "đăng lên YouTube"):
            # cổng phải thuộc hồ sơ trong nhóm VÀ file phải nằm trong khu vực.
            _mo = _re.match(r"^/api/v1/browser/preview/drive-attach/(\d+)$", p)
            if _mo and m == "POST":
                try:
                    from tubecli.extensions.browser.routes import _resolve_profile_for_port
                    if (_resolve_profile_for_port(int(_mo.group(1))) or "") not in profiles:
                        return False
                    _b = await request.json()
                except Exception:
                    return False
                _bc = str((_b or {}).get("cred_id") or "")
                _fid = str((_b or {}).get("file_id") or (_b or {}).get("drive_id") or "")
                return bool(_fid) and _drv.is_within(_bc, _fid, _roots(_bc))

    # ── G2: sharee CHAT với agent của nhóm (scope.agent_ids) ────────────────
    # Gate này chỉ MỞ CỬA vào các route chat; kiểm tra chi tiết nằm TRONG
    # chat/routes.py — nơi có store trong tay: agent ∈ agent_ids, phiên phải
    # mang đúng nhãn workspace (cô lập — không mở được phiên của chủ/sharee
    # khác), group_id + auto_route bị ÉP theo scope.
    if scope.get("agent_ids"):
        if p == "/api/v1/chat/sessions":
            return m == "GET" or (m == "POST" and access != "view")
        if _re.match(r"^/api/v1/chat/sessions/[A-Za-z0-9_-]+$", p):
            return m == "GET" or (m in ("PUT", "DELETE") and access != "view")
        if _re.match(r"^/api/v1/chat/sessions/[A-Za-z0-9_-]+/messages$", p):
            return m == "GET" or (m == "POST" and access != "view")
        if _re.match(r"^/api/v1/chat/sessions/[A-Za-z0-9_-]+/clear$", p):
            return m == "POST" and access != "view"

    # ── Sheet của nhóm: ĐỌC cho mọi mức; GHI chỉ khi share Toàn quyền VÀ chính
    # entry sheet trong nhóm cho phép mức đó (append/write/manage — cùng thang
    # group_context.allows của chủ). Sharee chưa có UI gọi các đường này (thiếu
    # cred_id — bị lột khỏi data khi chia sẻ); gate dựng sẵn cho lô UI kế.
    _sheets = {str(x.get("sheet_id")): str(x.get("access") or "append")
               for x in (scope.get("sheets") or [])
               if isinstance(x, dict) and x.get("sheet_id")}
    if _sheets:
        mo = _re.match(r"^/api/v1/auth-manager/gsheets/([A-Za-z0-9_-]+)/(values|grid)$", p)
        if mo and m == "GET":
            return mo.group(1) in _sheets
        mo = _re.match(r"^/api/v1/auth-manager/gsheets/([A-Za-z0-9_-]+)/(update|append|format|merge)$", p)
        if mo and m == "POST" and access == "full":
            from tubecli.core import group_context
            have = _sheets.get(mo.group(1), "")
            need = "append" if mo.group(2) == "append" else "write"
            return bool(have) and group_context.allows(have, need)

    return False


def _cors_error_headers(request):
    """Header CORS cho response lỗi của gate (401/403).

    Hai gate dưới nằm NGOÀI CORSMiddleware nên response 401/403 của chúng không có
    header CORS → trình duyệt chặn luôn, client không đọc được status mà báo nhầm
    'CORS error'. Echo lại Origin (kèm credentials) để trình duyệt giao được response
    lỗi cho client — client thấy 401 thật thì tự đăng nhập lại được. An toàn: body chỉ
    là thông báo lỗi, echo origin trên response lỗi không lộ gì.
    """
    origin = request.headers.get("origin")
    if not origin:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


@app.middleware("http")
async def _require_login(request: Request, call_next):
    """Gate everything that is not loopback behind a session cookie.

    Sits OUTSIDE the origin guard below, so the two are independent: this one
    answers "do we know who this is", the origin guard answers "may this page
    talk to us at all". Neither replaces the other — a session cookie would
    otherwise be replayable by any site the user visits, which is exactly the
    CSRF the origin guard exists to stop.
    """
    if request.method == "OPTIONS" or _auth_exempt(request.url.path):
        return await call_next(request)
    # A one-shot client with the read key. Checked before the cookie because a
    # cloud AI has neither a cookie nor a way to obtain one — see
    # auth.scraped_read_token. Narrow by construction: GET, data paths only.
    try:
        if _read_key_authorised(request):
            return await call_next(request)
    except Exception:
        pass  # a broken key check must refuse, not crash — fall through
    try:
        from tubecli.core import auth

        refusal = auth.check_request(
            request.client.host if request.client else "",
            request.cookies.get(auth.SESSION_COOKIE),
            request.headers,
        )
        if refusal is not None:
            from fastapi.responses import JSONResponse, RedirectResponse

            # Không phải chủ → thử GUEST (workspace chia sẻ có phạm vi). FAIL-CLOSED:
            # mỗi bước bọc try riêng, bất kỳ lỗi nào → coi như không phải guest (giữ
            # refusal của chủ). Guest hợp lệ nhưng NGOÀI scope → 403 (khác 401 của chủ).
            gscope = None
            try:
                gscope = auth.guest_scope_for(request.cookies.get(auth.GUEST_COOKIE))
            except Exception:
                gscope = None
            if gscope is not None:
                allowed = False
                try:
                    allowed = await _guest_allowed(request, gscope)
                except Exception:
                    allowed = False
                if allowed:
                    request.state.guest_scope = gscope
                    return await call_next(request)
                # code ổn định để giao diện tự dịch — câu detail chỉ là dự
                # phòng khi client chưa biết mã này (xem tubecliClient.js).
                return JSONResponse(status_code=403,
                                    content={"detail": "Outside the shared scope.",
                                             "code": "guest_out_of_scope"},
                                    headers=_cors_error_headers(request))

            # A browser asking for a page gets the login screen; anything else
            # gets JSON it can act on. Sending HTML to a fetch() is how the
            # dashboard ended up showing a bare "Failed." for everything.
            accepts_html = "text/html" in (request.headers.get("accept") or "")
            if accepts_html and request.method == "GET":
                return RedirectResponse(f"/login?next={request.url.path}", status_code=302)
            return JSONResponse(status_code=401, content=refusal, headers=_cors_error_headers(request))
    except Exception:
        pass  # never let the gate itself take the server down
    return await call_next(request)


@app.middleware("http")
async def _guard_cross_origin(request: Request, call_next):
    # The login surface is exempt here as well as from the gate above, and that
    # costs nothing: this guard has never protected those paths, because a
    # request with no Origin header — curl, from anywhere on the internet — has
    # always been let through. Refusing them only stopped the real browser on a
    # public address from reaching its own login form, which is precisely the
    # case the dashboard has to serve.
    if request.method != "OPTIONS" and not _auth_exempt(request.url.path):
        try:
            from tubecli.core.origin_guard import is_origin_allowed
            if not is_origin_allowed(request.headers.get("origin"),
                                     request.headers.get("host", "")):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request refused. Open the dashboard "
                                       "from this machine, or set TUBECLI_ALLOWED_ORIGIN_HOSTS."},
                    headers=_cors_error_headers(request),
                )
        except Exception:
            pass  # never let the guard itself take the server down
    return await call_next(request)


def check_and_generate_daily_keywords(agent, now_dt):
    """Checks if daily evolved keywords exist for the current date. Generates them via LLM if not."""
    import json
    from pathlib import Path
    from tubecli.core.agent import agent_manager
    from tubecli.core.brain import AgentBrain
    from tubecli.core.ai_generator import extract_json

    date_str = now_dt.strftime("%Y-%m-%d")
    routine = agent.routine or {}
    daily_keywords = routine.get("daily_keywords") or {}

    if daily_keywords.get("date") == date_str:
        return daily_keywords

    print(f"[Scheduler Callback] Daily keywords stale or missing for {date_str}. Generating evolved keywords via AI...")

    # 1. Retrieve recent history titles
    from tubecli.core import scraped_store

    recent_history_titles = []
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []
    for profile in scraped_store.resolve_profiles(allowed_profiles):
        owned = [a for a in scraped_store.raw_history(profile)
                 if scraped_store.owns(a, agent.id, allowed_profiles, profile)]
        for a in owned[:15]:
            if a.get("title") and a.get("title") != "Untitled":
                recent_history_titles.append(f"- {a.get('title')} ({a.get('url', '')})")

    # 2. Build interests list
    persona = agent.persona or {}
    interests = persona.get("interests", []) or routine.get("interests", []) or []
    work_habits = routine.get("workHabits") or persona.get("workHabits") or {}
    focus_areas = work_habits.get("focusAreas", []) or []
    combined_topics = list(dict.fromkeys([str(t) for t in interests + focus_areas if t]))

    history_text = "\n".join(recent_history_titles[:15]) if recent_history_titles else "No history yet (First day running)."

    # Language instruction for keyword generation
    agent_language = getattr(agent, "language", "auto") or "auto"
    _LANGUAGE_NAMES = {
        "auto": None,
        "vi": "Vietnamese",
        "en": "English",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "es": "Spanish",
        "tr": "Turkish",
        "ru": "Russian",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ar": "Arabic",
        "th": "Thai",
        "id": "Indonesian",
    }
    lang_name = _LANGUAGE_NAMES.get(agent_language)
    lang_instruction = (
        f"\nIMPORTANT: Write ALL search queries in {lang_name}. The queries must be in {lang_name} language."
        if lang_name else ""
    )

    prompt = f"""You are the core intelligence of the agent '{agent.name}'.
Description / Profession of the agent:
"{agent.description}"

Agent's interests and focus topics:
{json.dumps(combined_topics, ensure_ascii=False)}

Here is the agent's recent web browsing history (last visited pages):
{history_text}

Your task is to generate a progressive and evolved set of search queries/keywords for today: {date_str}.{lang_instruction}
Rules for evolution and progression:
1. Progress from basic/foundational concepts to more advanced, specific, and deeper concepts based on what has been browsed.
2. Avoid repeating exactly the same queries or topics already found in the recent history.
3. Align the topics with the agent's profession and specific interest areas.
4. Provide exactly 5 distinct search queries for each of the following time periods: "morning", "afternoon", "evening", "night".
5. Return the result in raw JSON format matching this EXACT structure (output ONLY the JSON block, no explanations):
{{
  "morning": ["query 1", "query 2", "query 3", "query 4", "query 5"],
  "afternoon": ["query 1", "query 2", "query 3", "query 4", "query 5"],
  "evening": ["query 1", "query 2", "query 3", "query 4", "query 5"],
  "night": ["query 1", "query 2", "query 3", "query 4", "query 5"]
}}
"""
    messages = [
        {"role": "system", "content": "You are a precise JSON keyword generator. Output only valid JSON."},
        {"role": "user", "content": prompt}
    ]

    try:
        raw_response = AgentBrain._call_llm(agent.to_dict(), messages, temperature=0.7)
        json_str = extract_json(raw_response)
        evolved_data = json.loads(json_str)
        if all(k in evolved_data for k in ["morning", "afternoon", "evening", "night"]):
            new_keywords = {
                "date": date_str,
                "morning": evolved_data["morning"],
                "afternoon": evolved_data["afternoon"],
                "evening": evolved_data["evening"],
                "night": evolved_data["night"]
            }
            # Deep-reload routine from agent to avoid overwriting updates
            agent = agent_manager.get(agent.id)
            routine = agent.routine or {}
            routine["daily_keywords"] = new_keywords
            agent_manager.update(agent.id, routine=routine)
            print(f"[Scheduler Callback] Successfully saved daily evolved keywords: {new_keywords}")
            return new_keywords
    except Exception as e:
        print(f"[Scheduler Callback] Evolved daily keywords generation failed: {e}. Falling back to default interests.")

    return {}


def _group_browser_profiles(groups) -> List[tuple]:
    """(profile name, group label) for every browser profile the agent's Flow
    groups share with it.

    The `profiles` kind is registered by the browser extension; with that
    extension disabled the merged group view has no such key and this list is
    empty — which is exactly what "the group shares no profile" should mean.
    Access is checked, not assumed: an entry shared below `use` is listed to
    the agent but never driven on a schedule.
    """
    from tubecli.core import group_context

    out = []
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        label = g.get("label") or g.get("group_id") or ""
        for p in g.get("profiles") or []:
            if not isinstance(p, dict):
                continue
            name = str(p.get("profile") or "").strip()
            if name and group_context.allows(p.get("access") or "use", "use"):
                out.append((name, label))
    return out


def _group_log_routine(groups, agent, title: str, detail: str = "", ok: bool = True) -> None:
    """One "schedule" line on the log panel of every group this agent is in.

    A scheduled run is the only thing an agent does with nobody watching, and
    it was also the only thing the canvas could not see: run_log records it for
    the owner's dashboard, keyed by agent, while the panel beside the group is
    keyed by group. Two lines per run — one when the routine is decided, one
    when the browser either came up or did not — is what turns "the group looks
    idle" into "it ran at 03:00 and the profile was busy".

    Best effort, like every other logging call in this file: a run must never
    fail because of its own log.
    """
    if not groups:
        return
    try:
        from tubecli.core import group_log

        for g in groups:
            gid = (g or {}).get("group_id") if isinstance(g, dict) else ""
            if not gid:
                continue
            group_log.append(gid, getattr(agent, "id", ""), getattr(agent, "name", ""),
                             kind="schedule", title=title, detail=detail, ok=ok)
    except Exception as e:
        print(f"[Scheduler Callback] Group log skipped: {e}")


# ── Per-period BEHAVIOR resolution for scheduled agents ──────────────────
# The Schedule tab (per agent) writes dailyRoutine[period] = {behaviorKey: true}.
# The owner asked for EXPLICIT keys, not fuzzy free text, so a period's intent is
# robust and per-agent. These keys map straight to an internal behavior string —
# the same strings the prompt templates below already key on. The old fuzzy
# keyword matching stays as a fallback so pre-existing free-text configs (which
# had no UI, only whatever a persona generator wrote) still resolve.
EXPLICIT_BEHAVIOR_MAP = {
    "browse_topic": "work",       # lướt chủ đề — search + read
    "news": "morningCheck",       # lướt tin — headlines
    "watch_video": "watchVideos", # xem video
    "study": "study",             # học / nghiên cứu
    "check_email": "checkEmails", # đọc email (chỉ đọc)
    "reply_email": "replyEmail",  # trả lời email chưa đọc mới nhất
    "send_report": "sendReport",  # soạn & gửi báo cáo cho đồng nghiệp
}

# ── Hành vi phải KHỚP chip đăng nhập của hồ sơ ───────────────────────────
# profile_manager.detect_logins đọc kho cookie thật của hồ sơ và trả các chip
# ['google','youtube','facebook','tiktok','instagram','x'] — đúng dữ liệu đang
# vẽ huy hiệu trên thẻ hồ sơ. Hành vi nào cần dịch vụ nào thì chỉ chạy khi có
# một hồ sơ ứng viên mang chip đó: không có Google thì không đọc/soạn mail,
# không có YouTube thì không "xem video" (trước đây vẫn chạy và ra Google
# search "gmail"). Hành vi lướt/đọc tự do không cần chip nào.
BEHAVIOR_LOGIN_NEEDS = {
    "checkEmails": {"google"},
    "replyEmail": {"google"},
    "sendReport": {"google"},
    "watchVideos": {"youtube"},   # detect_logins: có google là tự có youtube
}

# Trang báo theo ngôn ngữ agent — hành vi "news" vào THẲNG trang báo rồi bấm
# bài, thay vì Google search "X news today" (nguồn của cảnh "toàn search").
NEWS_SITES = {
    "vi": ["vnexpress.net", "tuoitre.vn", "thanhnien.vn"],
    "en": ["reuters.com", "bbc.com", "apnews.com"],
    "ja": ["nhk.or.jp/news", "asahi.com"],
    "ko": ["yna.co.kr", "news.naver.com"],
    "zh": ["news.sina.com.cn", "news.163.com"],
    "es": ["elpais.com", "bbc.com/mundo"],
    "tr": ["hurriyet.com.tr", "ntv.com.tr"],
    "ru": ["ria.ru", "lenta.ru"],
}


# ── Sinh dailyRoutine theo VAI TRÒ khi tạo agent ─────────────────────────
# WHY: chip 7 hành vi/buổi vẫn giữ NGUYÊN và người dùng vẫn tự bật/tắt được.
# Cái thêm vào: lúc tạo agent, thay vì để trống giống hệt nhau, ta để LLM
# CHỌN SẴN tập con phù hợp với persona (giáo viên -> study/browse chứ không
# "check email mỗi sáng"). Tuyệt đối KHÔNG đẻ key mới: scheduler chỉ hiểu đúng
# 7 key trong EXPLICIT_BEHAVIOR_MAP; độ cụ thể chủ đề ("giáo án") đến từ
# interests của agent (thứ đã lái câu tìm kiếm ở chỗ khác), không phải từ đây.
PERIODS = ("morning", "afternoon", "evening", "night")

# Nghĩa "người thường" của từng key — đưa vào prompt để LLM chọn đúng vai trò.
# Key PHẢI trùng khít EXPLICIT_BEHAVIOR_MAP (một nguồn sự thật cho 7 key hợp lệ).
BEHAVIOR_MEANINGS = {
    "browse_topic": "search the web and read about its topics of interest",
    "news": "skim the day's headlines / news",
    "watch_video": "watch videos (e.g. YouTube) related to its interests",
    "study": "study, take an online course, deep-read to learn",
    "check_email": "open and read incoming email (read only)",
    "reply_email": "reply to the newest unread email",
    "send_report": "compose and send a summary report to colleagues",
}


def _default_daily_routine():
    """Fallback chung, trung tính khi LLM lỗi/trả rác.

    Là factory (không phải hằng dùng chung) để mỗi caller có bản sao riêng đem
    lưu — tránh hai agent vô tình dùng chung một dict rồi sửa lẫn nhau.
    """
    return {
        "morning": {"news": True, "check_email": True},
        "afternoon": {"browse_topic": True, "study": True},
        "evening": {"watch_video": True},
        "night": {"study": True},
    }


def _routine_flag_on(v) -> bool:
    """LLM có thể trả bool thật, số, hoặc CHUỖI 'false'/'true'.

    WHY: chuỗi "false" là truthy trong Python — nếu chỉ `if v:` thì một buổi
    LLM ghi "false" vẫn bị bật. Ép về bool đúng nghĩa ở đây.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "on", "y")
    return False


def _sanitize_daily_routine(data):
    """Chỉ giữ đúng 7 key hợp lệ, dạng {period: {validKey: True}}.

    Trả dict khi reply có ÍT NHẤT một hành vi hợp lệ + được bật; trả None khi
    không có gì dùng được (không phải dict, hoặc mọi buổi rỗng sau khi loại rác)
    để caller rơi về _default_daily_routine(). Đây là chốt kiểm bắt buộc chủ
    dự án yêu cầu: một key ảo (hallucinated) KHÔNG BAO GIỜ lọt vào
    persona.dailyRoutine, vì scheduler sẽ không hiểu nó.
    """
    if not isinstance(data, dict):
        return None
    out = {}
    total = 0
    for period in PERIODS:
        pt = data.get(period)
        cleaned = {}
        if isinstance(pt, dict):
            for key, enabled in pt.items():
                # Loại thẳng mọi key ngoài 7 key; chỉ lưu key được bật.
                if key in BEHAVIOR_MEANINGS and _routine_flag_on(enabled):
                    cleaned[key] = True
                    total += 1
        out[period] = cleaned
    if total == 0:
        return None
    return out


def generate_daily_routine(agent):
    """Suy ra dailyRoutine theo buổi TỪ CHÍNH persona của agent.

    Dùng lại y hệt "đường ống" của check_and_generate_daily_keywords: dựng prompt
    từ description + interests, gọi AgentBrain._call_llm, extract_json, rồi VALIDATE.
    LLM chỉ CHỌN SẴN tập con trong 7 hành vi cố định cho mỗi buổi — không đẻ key
    mới. Luôn trả {period: {validKey: True}}: hoặc là lựa chọn đã làm sạch của
    LLM, hoặc default chung nếu gọi lỗi/reply rác. KHÔNG BAO GIỜ raise.
    """
    import json
    from tubecli.core.brain import AgentBrain
    from tubecli.core.ai_generator import extract_json

    persona = agent.persona or {}
    routine = agent.routine or {}
    interests = persona.get("interests", []) or routine.get("interests", []) or []
    work_habits = routine.get("workHabits") or persona.get("workHabits") or {}
    focus_areas = work_habits.get("focusAreas", []) or []
    combined = list(dict.fromkeys(str(t) for t in list(interests) + list(focus_areas) if t))

    behavior_lines = "\n".join(f"- {k}: {v}" for k, v in BEHAVIOR_MEANINGS.items())
    all_keys_example = ", ".join(f'"{k}": false' for k in BEHAVIOR_MEANINGS)
    prompt = f"""You set the daily routine of the agent '{agent.name}'.
Description / profession:
"{agent.description}"
Interests / focus topics: {json.dumps(combined, ensure_ascii=False)}

There are EXACTLY 7 behaviors it can perform, and ONLY these:
{behavior_lines}

Decide which behaviors fit THIS agent's role in each period of the day
(morning, afternoon, evening, night). Reason about the role: a teacher studies
and browses teaching material and does NOT run an email desk; a sales manager
checks and replies to email and sends reports; a researcher studies and reads
news. Enable 1-3 behaviors per period that genuinely fit; set the rest false.
Do NOT invent any behavior outside the 7 keys above.

Return ONLY raw JSON (no prose), this EXACT structure, with every one of the 7
keys present as a boolean in each period:
{{
  "morning":   {{ {all_keys_example} }},
  "afternoon": {{ {all_keys_example} }},
  "evening":   {{ {all_keys_example} }},
  "night":     {{ {all_keys_example} }}
}}"""
    messages = [
        {"role": "system", "content": "You are a precise JSON generator. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ]

    try:
        raw_response = AgentBrain._call_llm(agent.to_dict(), messages, temperature=0.4)
        data = json.loads(extract_json(raw_response))
        sanitized = _sanitize_daily_routine(data)
        if sanitized is not None:
            return sanitized
        print("[RoutineGen] LLM reply carried no valid behaviors; using default routine.")
    except Exception as e:
        print(f"[RoutineGen] Routine generation failed: {e}. Using default routine.")
    return _default_daily_routine()


def _seed_agent_routine(agent_id):
    """Best-effort: sinh + lưu dailyRoutine hợp vai trò vào persona.

    Đồng bộ và bọc kín lỗi — an toàn để gọi từ daemon thread (lúc tạo agent)
    hoặc gọi trực tiếp (endpoint generate_routine / test). KHÔNG BAO GIỜ raise;
    trả về routine đã lưu, hoặc None nếu agent biến mất giữa chừng.

    WHY lưu vào persona.dailyRoutine: tab Schedule đọc/ghi ở đúng chỗ này
    (scheduler đọc routine.dailyRoutine trước rồi mới persona.dailyRoutine), nên
    ghi vào persona khớp "home of record" của UI và không đụng các key khác.
    """
    try:
        from tubecli.core.agent import agent_manager
        agent = agent_manager.get(agent_id)
        if not agent:
            return None
        routine_map = generate_daily_routine(agent)
        persona = dict(agent.persona or {})
        persona["dailyRoutine"] = routine_map
        agent_manager.update(agent_id, persona=persona)
        return routine_map
    except Exception as e:
        print(f"[RoutineSeed] Could not seed routine for agent {agent_id}: {e}")
        return None


def resolve_task_behavior(chosen_task: str) -> str:
    """Map one chosen task label from dailyRoutine[period] to an internal behavior.

    Explicit keys (browse_topic, news, watch_video, study, check_email,
    reply_email, send_report) win — an exact, case-insensitive match against
    EXPLICIT_BEHAVIOR_MAP. Anything else falls through to the old fuzzy keyword
    matching so free-text labels ("check morning email", "read the news") keep
    working exactly as before.
    """
    key = str(chosen_task).strip()
    if key in EXPLICIT_BEHAVIOR_MAP:
        return EXPLICIT_BEHAVIOR_MAP[key]
    if key.lower() in EXPLICIT_BEHAVIOR_MAP:
        return EXPLICIT_BEHAVIOR_MAP[key.lower()]
    # --- backward-compatible fuzzy fallback (unchanged behavior) ---
    task_lower = key.lower()
    if any(x in task_lower for x in ["email", "mail"]):
        return "checkEmails"
    elif any(x in task_lower for x in ["news", "headline", "calendar"]):
        return "morningCheck"
    elif any(x in task_lower for x in ["video", "youtube"]):
        return "watchVideos"
    elif any(x in task_lower for x in ["study", "learn", "course", "read"]):
        return "study"
    elif any(x in task_lower for x in ["analyze", "research", "stock", "chart", "company"]):
        return "work"
    else:
        return "work"


# With no enabled task for the period (the common case before the Schedule tab
# UI existed — dailyRoutine was always empty), behavior stays random so every
# run isn't identical. Unchanged from the original callback.
FALLBACK_BEHAVIORS = ["work", "research", "study", "morningCheck"]


def select_period_behavior(daily_routine, time_period, rng=None, runnable=None):
    """Resolve the internal behavior for one period from dailyRoutine.

    dailyRoutine may be {period: {behaviorKey: enabled}} (the shape the Schedule
    tab writes), {period: [labels]}, or a flat list. Picks one enabled task at
    random and resolves it via resolve_task_behavior (explicit keys win, then
    fuzzy). With nothing enabled, returns the old random fallback so pre-UI
    configs behave exactly as before.

    runnable (optional): predicate on the RESOLVED behavior string. Tasks whose
    behavior it rejects are dropped from the draw — the caller uses this to
    exclude behaviors no candidate profile is logged in for (no Google chip ->
    no email behaviors). If everything enabled is rejected, fall through to the
    login-free fallback pool rather than run an impossible task.

    Returns (behavior, period_tasks, chosen_task) — period_tasks is handed back
    so the caller can keep recording it in the run context.
    """
    _rng = rng or random
    period_tasks = {}
    if isinstance(daily_routine, dict):
        pt = daily_routine.get(time_period, {})
        if isinstance(pt, dict):
            period_tasks = pt
        elif isinstance(pt, list):
            period_tasks = {str(task): True for task in pt if task}
    elif isinstance(daily_routine, list):
        period_tasks = {str(task): True for task in daily_routine if task}

    active_tasks = [task for task, enabled in period_tasks.items() if enabled]
    if active_tasks and callable(runnable):
        ok_tasks = [t for t in active_tasks if runnable(resolve_task_behavior(t))]
        dropped = [t for t in active_tasks if t not in ok_tasks]
        if dropped:
            print(f"[Scheduler Callback] Tasks dropped (no logged-in profile for them): {dropped}")
        active_tasks = ok_tasks
    if active_tasks:
        chosen = _rng.choice(active_tasks)
        return resolve_task_behavior(chosen), period_tasks, chosen
    return _rng.choice(FALLBACK_BEHAVIORS), period_tasks, None


def _extract_account_email(acc) -> str:
    """Email của một tài khoản profile — google_account là str hoặc dict.
    str có thể là 'email|password|...' (routes.py tách bằng pipe/tab)."""
    if isinstance(acc, dict):
        e = acc.get("email") or ""
    elif isinstance(acc, str):
        e = acc.replace("\t", "|").split("|")[0]
    else:
        e = ""
    e = str(e).strip()
    return e if "@" in e else ""


def _system_report_emails(exclude_profile="") -> list:
    """Email Google đã nhập vào các profile KHÁC trong hệ thống — pool người nhận
    ngẫu nhiên cho send_report. Loại MỌI profile có thể chạy lượt này (str hoặc
    tập tên — vòng thử ứng viên có thể spawn hồ sơ #2/#3) để agent không tự gửi
    cho chính nó. Best effort tuyệt đối: không bao giờ ném vào vòng lập lịch."""
    if isinstance(exclude_profile, str):
        _excl = {exclude_profile} if exclude_profile else set()
    else:
        _excl = {str(x) for x in (exclude_profile or [])}
    uniq, seen = [], set()
    try:
        from tubecli.extensions.browser.profile_manager import list_profiles
        for p in list_profiles():
            if not isinstance(p, dict):
                continue
            if p.get("name") in _excl:
                continue
            e = _extract_account_email(p.get("google_account"))
            if e and e.lower() not in seen:
                seen.add(e.lower())
                uniq.append(e)
    except Exception:
        pass
    return uniq


def normalize_report_recipients(routine, persona) -> list:
    """Read the agent's report recipients — "colleagues in the same system".

    Home of record is routine.reportRecipients (the scheduler reads routine
    first everywhere else); persona.reportRecipients is a fallback so the UI can
    save to either. Accepts a list or a comma/semicolon-separated string, trims
    blanks, and returns a clean list of address strings (possibly empty).
    """
    raw = None
    if isinstance(routine, dict):
        raw = routine.get("reportRecipients")
    if not raw and isinstance(persona, dict):
        raw = persona.get("reportRecipients")
    if isinstance(raw, str):
        raw = raw.replace(";", ",").split(",")
    if not isinstance(raw, list):
        raw = []
    return [str(r).strip() for r in raw if str(r).strip()]


def build_email_prompt(behavior, time_period, topics, recipients):
    """Build the single natural-language gmail instruction open.js will execute.

    Returns (prompt, skip_reason):
      * replyEmail -> open gmail, read the newest UNREAD, compose a short
        on-topic reply, send. If the inbox has nothing unread the instruction
        tells the browser to stop rather than invent a message.
      * sendReport -> compose a NEW email to `recipients` with a subject + a
        short body summarizing the period's topics/activity, then send. With NO
        recipients, prompt is None and skip_reason explains the honest skip —
        we never email nobody.
    Attachments are out of scope in this version: the summary rides in the body
    text, and the prompt says so.
    Any non-email behavior returns (None, None) — the caller keeps its search
    prompt untouched.
    """
    clean_topics = [str(t).strip() for t in (topics or []) if str(t).strip()]
    topic_summary = ", ".join(clean_topics[:4]) if clean_topics else "its assigned topics"

    if behavior == "replyEmail":
        prompt = (
            "Go to gmail.com. Open the newest UNREAD email in the inbox and read it. "
            "Then click Reply, write a brief, polite, on-topic reply of a few sentences "
            f"relevant to {topic_summary}, and click Send. "
            "If there is no unread email, do nothing and stop — do not compose a new message. "
            "Do not add any attachment; keep the reply as body text."
        )
        return prompt, None

    if behavior == "sendReport":
        clean = [str(r).strip() for r in (recipients or []) if str(r).strip()]
        if not clean:
            # Không có người nhận thì KHÔNG gửi cho hư không — bỏ qua lượt này,
            # ghi một dòng log trung thực thay vì soạn một email không có To.
            return None, (
                "send_report scheduled but this agent has no reportRecipients configured "
                "— skipping this run (never emails nobody)."
            )
        to_line = ", ".join(clean)
        prompt = (
            "Go to gmail.com and click Compose to start a new email. "
            f"In the To field enter exactly: {to_line}. "
            f"Set the Subject to a short line summarizing today's {time_period} work on {topic_summary}. "
            f"In the body, write a brief report of a few sentences about what was worked on this "
            f"{time_period}: the topics {topic_summary} and any activity collected today. "
            "Then click Send. Do not add any attachment — the whole summary goes in the body text."
        )
        return prompt, None

    return None, None


def run_agent_routine(agent_id: str, run_id: str = None, trigger: str = "schedule"):
    """Callback for running an agent's daily behavior routine on schedule.

    run_id ties this run to the row the scheduler already wrote. A caller that
    passes none (the manual "test routine" button) gets one minted here, so a
    hand-triggered run is recorded the same way a scheduled one is.
    """
    import random
    import datetime
    from tubecli.core.agent import agent_manager
    from tubecli.core import run_log

    agent = agent_manager.get(agent_id)
    if not agent:
        print(f"[Scheduler Callback] Agent {agent_id} not found")
        return

    if not run_id:
        try:
            run_id = run_log.new_run_id()
            run_log.start(run_id, agent.id, getattr(agent, "name", ""), trigger=trigger)
        except Exception:
            run_id = None
        
    print(f"\n[Scheduler Callback] >>> Executing scheduled behavior routine for agent '{agent.name}' ({agent.id}) <<<")
    
    # 1. Resolve Profile Name
    # A Browser node the owner dropped into one of the agent's Flow groups is
    # the owner's word on which profile this agent drives, so it outranks
    # allowed_profiles (the older per-agent setting) and certainly outranks
    # "any profile on this machine". The groups are loaded once here and
    # reused for the context block further down; a failure never blocks the
    # run, it only falls back to the old behaviour.
    profile_name = "default"
    group_ctxs = []
    group_profiles = []
    _gc = None
    try:
        from tubecli.core import group_context as _gc
        group_ctxs = _gc.effective_groups(agent.id)
        group_profiles = _group_browser_profiles(group_ctxs)
    except Exception as _ge:
        print(f"[Scheduler Callback] Group context skipped: {_ge}")

    # GIỮ CẢ DANH SÁCH ứng viên theo đúng 3 bậc cũ (nhóm > allowed_profiles >
    # hồ sơ local) thay vì random.choice một phát rồi vứt: hành vi sẽ được lọc
    # theo chip đăng nhập của các ứng viên, hồ sơ được xếp hạng theo hành vi đã
    # chọn, và khi hồ sơ đầu bận thì lượt thử hồ sơ kế thay vì bỏ cả lượt.
    candidate_profiles = []
    if group_profiles:
        candidate_profiles = [str(name) for name, _lbl in group_profiles if name]
        print(f"[Scheduler Callback] {len(candidate_profiles)} candidate profile(s) shared via groups")
    elif agent.allowed_profiles:
        candidate_profiles = [
            (p.get("name", "default") if isinstance(p, dict) else str(p))
            for p in agent.allowed_profiles]
        print(f"[Scheduler Callback] {len(candidate_profiles)} candidate profile(s) from allowed_profiles")
    else:
        try:
            from tubecli.extensions.browser.profile_manager import list_profiles
            profiles = list_profiles()
            candidate_profiles = [
                (p.get("name") if isinstance(p, dict) else str(p))
                for p in profiles
                if (p.get("name") if isinstance(p, dict) else str(p)) != "default"]
            print(f"[Scheduler Callback] No profile assigned — {len(candidate_profiles)} local profile(s) as candidates")
        except Exception as e:
            print(f"[Scheduler Callback] Profile check warning: {e}")
    # Tài khoản Keychain agent được chỉ định để ĐĂNG NHẬP: đảm bảo mỗi cái có
    # một profile (tự TẠO nếu chưa có nhà) rồi đẩy các profile đó lên đầu danh
    # sách ứng viên. Đây là chỗ "profile chưa có thì tự tạo" của người dùng —
    # xảy ra ngay trước khi chọn hồ sơ, không phải để agent LLM tự quyết.
    login_accounts = getattr(agent, "login_accounts", []) or []
    if login_accounts:
        try:
            from tubecli.extensions.keychain.routes import ensure_profile_for_account
            forced = []
            for _aid in login_accounts:
                try:
                    _r = ensure_profile_for_account(str(_aid))
                    if _r.get("profile"):
                        forced.append(_r["profile"])
                        if _r.get("created"):
                            print(f"[Scheduler Callback] Keychain: tạo profile '{_r['profile']}' cho tài khoản {_aid}")
                except Exception as _e:
                    print(f"[Scheduler Callback] Keychain ensure_profile {_aid}: {_e}")
            candidate_profiles = forced + candidate_profiles
        except Exception as _e:
            print(f"[Scheduler Callback] Keychain không sẵn sàng: {_e}")

    candidate_profiles = list(dict.fromkeys([p for p in candidate_profiles if p])) or ["default"]
    # Nền ngẫu nhiên như cũ; sort ỔN ĐỊNH phía dưới chỉ kéo hồ sơ khớp lên trước
    # nên trong cùng một hạng các hồ sơ vẫn xoay vòng chứ không mòn một cái.
    random.shuffle(candidate_profiles)

    # Chip đăng nhập từng ứng viên — list_profiles() đọc kho cookie thật
    # (mode=ro&immutable=1, cache theo mtime) nên gọi đồng bộ ở đây rẻ và không
    # đụng khoá SQLite dù trình duyệt đang chạy. Credential auto-login
    # (google_account/...) cũng tính là "có cửa vào": hồ sơ mới chưa có cookie
    # nhưng autoLoginIfNeeded tự đăng nhập đầu phiên. logins_known=False
    # (extension cũ chưa có trường logins / import hỏng — kịch bản hot-patch
    # server.py lệch extension) thì TẮT gating: chạy như cũ, không âm thầm lọc
    # sạch mọi hành vi email/video.
    profile_logins = {}
    profile_emails = {}
    logins_known = False
    try:
        from tubecli.extensions.browser.profile_manager import list_profiles as _list_profiles
        _cand = set(candidate_profiles)
        _rows = [r for r in _list_profiles()
                 if isinstance(r, dict) and r.get("name") in _cand]
        for _pr in _rows:
            chips = set(_pr.get("logins") or [])
            if _pr.get("google_account"):
                chips |= {"google", "youtube"}
            for _fk, _fc in (("facebook_account", "facebook"),
                             ("tiktok_account", "tiktok"), ("x_account", "x")):
                if _pr.get(_fk):
                    chips.add(_fc)
            profile_logins[_pr["name"]] = chips
            profile_emails[_pr["name"]] = _extract_account_email(_pr.get("google_account"))
        logins_known = any("logins" in r for r in _rows)
    except Exception as _le:
        print(f"[Scheduler Callback] Login detection unavailable — gating disabled: {_le}")
            
    # 2. Determine Time of Day in Agent's Timezone
    tz_str = getattr(agent, "timezone", None)
    now = datetime.datetime.now()
    if tz_str and isinstance(tz_str, str) and tz_str.strip():
        tz_clean = tz_str.strip()
        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(ZoneInfo(tz_clean))
        except Exception:
            try:
                import pytz
                now = datetime.datetime.now(pytz.timezone(tz_clean))
            except Exception:
                pass
                
    hour = now.hour
    time_period = "night"
    if 5 <= hour < 12:
        time_period = "morning"
    elif 12 <= hour < 17:
        time_period = "afternoon"
    elif 17 <= hour < 22:
        time_period = "evening"
        
    print(f"[Scheduler Callback] Period: {time_period} (hour: {hour}, timezone: {tz_str or 'local'})")
    
    # Check and generate daily keywords via AI
    daily_keywords = check_and_generate_daily_keywords(agent, now)
    if daily_keywords:
        agent = agent_manager.get(agent_id)
        
    # 3. Resolve Persona / Routine behavior configurations
    routine = agent.routine or {}
    persona = agent.persona or {}
    
    daily_routine = routine.get("dailyRoutine") or persona.get("dailyRoutine") or {}
    work_habits = routine.get("workHabits") or persona.get("workHabits") or {}
    
    # Explicit keys (browse_topic/news/watch_video/study/check_email/
    # reply_email/send_report) win; free text still fuzzy-maps; empty period ->
    # old random fallback. One source of truth in select_period_behavior.
    # Chip nào cần dịch vụ mà KHÔNG ứng viên nào đăng nhập thì loại khỏi vòng
    # bốc — không có Google thì đừng bốc email, không có YouTube thì đừng bốc
    # xem video (trước đây vẫn bốc rồi chạy thành Google search).
    def _behavior_runnable(b):
        if not logins_known:
            return True   # không có dữ liệu login = không phán, chạy như cũ
        need = BEHAVIOR_LOGIN_NEEDS.get(b, set())
        return (not need) or any(
            need <= profile_logins.get(p, set()) for p in candidate_profiles)

    behavior, period_tasks, chosen_task = select_period_behavior(
        daily_routine, time_period, runnable=_behavior_runnable)
    if chosen_task is not None:
        print(f"[Scheduler Callback] Selected task '{chosen_task}' -> behavior '{behavior}'")
    else:
        print(f"[Scheduler Callback] No active tasks. Using fallback behavior: {behavior}")

    # 3b. Chọn hồ sơ THEO hành vi: hành vi cần dịch vụ nào thì chỉ hồ sơ mang
    # chip đó được lái; hành vi tự do thì ưu tiên hồ sơ ĐÃ đăng nhập (có chip
    # nào đó) trước hồ sơ trắng. candidate_profiles đã shuffle nên trong cùng
    # một hạng các hồ sơ vẫn xoay vòng.
    login_need = BEHAVIOR_LOGIN_NEEDS.get(behavior, set()) if logins_known else set()
    if not logins_known:
        launch_candidates = list(candidate_profiles)
    else:
        ranked = sorted(candidate_profiles, key=lambda p: (
            0 if (login_need and login_need <= profile_logins.get(p, set())) else 1,
            0 if profile_logins.get(p) else 1))
        if login_need:
            eligible = [p for p in ranked if login_need <= profile_logins.get(p, set())]
            # _behavior_runnable ở trên bảo đảm thường không rỗng; rỗng chỉ khi
            # behavior đến từ fuzzy/fallback — khi đó đành chạy như cũ.
            launch_candidates = eligible or ranked
        elif random.random() < 0.3:
            # "Ưu tiên đã đăng nhập" là THIÊN VỊ, không phải loại trừ: 30% lượt
            # hành vi tự do chạy thuần ngẫu nhiên để hồ sơ trắng vẫn có lượt
            # ấm máy/tích cookie, hoạt động không dồn hết vào một identity.
            launch_candidates = list(candidate_profiles)
        else:
            launch_candidates = ranked
    profile_name = launch_candidates[0]
    print(f"[Scheduler Callback] Profile ranking for '{behavior}'"
          f" (needs {sorted(login_need) if login_need else 'nothing'}): "
          + ", ".join(
              f"{p}[{'+'.join(sorted(profile_logins.get(p, set()))) or 'no logins'}]"
              for p in launch_candidates[:5]))

    # 4. Generate Diverse Prompt
    import hashlib
    interests = persona.get("interests") or routine.get("interests") or []
    if not isinstance(interests, list):
        interests = [interests] if interests else []
    focus_areas = work_habits.get("focusAreas") or []
    if not isinstance(focus_areas, list):
        focus_areas = [focus_areas] if focus_areas else []
    combined_topics = list(dict.fromkeys([str(t) for t in interests + focus_areas if t]))
    
    hour_slot = now.strftime('%Y%m%d%H')
    seed_str = f"{profile_name}|{agent.name}|{hour_slot}"
    seed_int = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    rng = random.Random(seed_int)
    
    # Occasionally add a natural time marker (not a forced year number)
    _time_hints = ["", "", "", "latest", "recently", "this year", "new", "trending"]
    _time_hint = rng.choice(_time_hints).strip()

    def _with_hint(template: str) -> str:
        """Randomly sprinkle a natural time hint into a template, or leave as-is."""
        if _time_hint and "{topic}" in template and rng.random() < 0.35:
            return template.replace("{topic}", f"{_time_hint} {{topic}}")
        return template

    fmt_templates = {
        "work": [
            "how to {topic}",
            "{topic} best practices",
            "latest {topic} news",
            "{topic} tutorial for professionals",
            "{topic} tips and tricks",
            "top {topic} tools",
            "{topic} case study",
        ],
        "research": [
            "latest research on {topic}",
            "{topic} future trends",
            "what is {topic} explained",
            "{topic} in-depth analysis",
            "breakthroughs in {topic}",
        ],
        "study": [
            "learn {topic} from scratch",
            "{topic} for beginners",
            "{topic} complete guide",
            "{topic} online course free",
            "how to master {topic}",
        ],
        "morningCheck": [
            "{topic} news today",
            "breaking {topic} updates",
            "latest {topic} headlines",
        ],
        "entertainment": [
            "top {topic}",
            "{topic} highlights",
            "best {topic} videos",
        ],
        "watchVideos": [
            # Gõ trong ô tìm kiếm CỦA YouTube (prompt vào thẳng youtube.com)
            # nên không cần đuôi "youtube" nữa.
            "best {topic}",
            "{topic} video review",
            "{topic} documentary",
        ],
        "relax": [
            "{topic} life style tips",
            "{topic} wellness guide",
        ],
        "checkEmails": [
            "gmail", "outlook mail", "email inbox",
        ],
    }
    # Apply natural time hints to templates
    fmt_templates = {
        k: [_with_hint(t) for t in v]
        for k, v in fmt_templates.items()
    }
    
    fmts = fmt_templates.get(behavior, ["{topic} news", "about {topic}"])
    
    base_query = ""
    today_keywords = daily_keywords.get(time_period, []) if isinstance(daily_keywords, dict) else []
    if not isinstance(today_keywords, list):
        today_keywords = [today_keywords] if today_keywords else []

    if today_keywords:
        # --- Used-keyword tracking: pick next unused keyword, reset daily ---
        today_date = now.strftime('%Y-%m-%d')
        routine_data = agent.routine or {}
        used_meta = routine_data.get("used_keywords_today", {})
        if not isinstance(used_meta, dict):
            used_meta = {}

        # Reset if it's a new day
        if used_meta.get("date") != today_date:
            used_meta = {"date": today_date, "used": {}}

        used_dict = used_meta.get("used")
        if not isinstance(used_dict, dict):
            used_dict = {}
        period_used = used_dict.get(time_period, [])
        if not isinstance(period_used, list):
            period_used = []

        # Find first unused keyword (cycle back when all used)
        available = [kw for kw in today_keywords if kw not in period_used]
        if not available:
            print(f"[Scheduler Callback] All keywords used for '{time_period}' today. Resetting cycle.")
            period_used = []
            available = list(today_keywords)

        base_query = available[0] if available else ""
        print(f"[Scheduler Callback] Selected evolved query for period '{time_period}': '{base_query}'")

        # Mark as used and persist — CHỈ cho hành vi thật sự SEARCH từ khoá.
        # morningCheck/email giờ vào thẳng trang đích, không gõ base_query;
        # đốt keyword ở đó là mất lượt của các hành vi search thật.
        if base_query and behavior not in ("morningCheck", "checkEmails",
                                           "replyEmail", "sendReport"):
            period_used.append(base_query)
            if "used" not in used_meta:
                used_meta["used"] = {}
            used_meta["used"][time_period] = period_used
            routine_data["used_keywords_today"] = used_meta
            try:
                from tubecli.core.agent import agent_manager
                agent.routine = routine_data
                agent_manager.update(agent.id, routine=routine_data)
                print(f"[Scheduler Callback] Marked '{base_query}' as used for '{time_period}'. "
                      f"Remaining: {[kw for kw in today_keywords if kw not in period_used]}")
            except Exception as _e:
                print(f"[Scheduler Callback] Warning: could not persist used_keywords_today: {_e}")

    elif combined_topics:
        topic_idx = seed_int % len(combined_topics)
        topic = combined_topics[topic_idx]
        if len(combined_topics) > 1 and rng.random() < 0.3:
            topic2_idx = (topic_idx + 1) % len(combined_topics)
            topic2 = combined_topics[topic2_idx]
            combiner = rng.choice([f"{topic} vs {topic2}", f"{topic} and {topic2}", f"{topic} {topic2}"])
            base_query = rng.choice(fmts).replace("{topic}", combiner)
        else:
            base_query = rng.choice(fmts).replace("{topic}", topic)
    else:
        fallbacks = {
            "checkEmails": ["gmail", "outlook"],
            "morningCheck": ["breaking news today", "world news"],
            "work": ["github trending", "technology news"],
            "research": ["AI advancements", "science news", "latest research"],
            "study": ["free coding tutorials", "learning resources"],
            "watchVideos": ["youtube trending", "interesting tech videos"],
        }
        choices = fallbacks.get(behavior, ["latest news", "technology trends"])
        base_query = choices[seed_int % len(choices)]
        
    # Estimate browsing time based on keywords
    import random
    query_lower = base_query.lower()
    is_deep_topic = any(w in query_lower for w in ["tutorial", "guide", "learn", "how", "analysis", "study", "research", "documentation", "course", "master", "practice"])
    is_quick_topic = any(w in query_lower for w in ["weather", "price", "stock", "today", "news", "headline", "breaking"])
    
    if is_deep_topic:
        read_time = random.randint(180, 360)
    elif is_quick_topic:
        read_time = random.randint(45, 90)
    else:
        read_time = random.randint(90, 180)
        
    # Suffix templates — single-flow, NO going back to search.
    # MỖI BƯỚC MỘT ĐỘNG TỪ, nối bằng ", then ": parser open.js tách bước theo
    # ", then " — câu ghép kiểu "click X, and read for N seconds" từng làm RƠI
    # nửa sau của bước (chỉ click, phần đọc bị vứt), vì vậy toàn search-rồi-đứng.
    suffix_options = [
        # Pattern 1: Click result → read page
        f", then click the most relevant result, then browse for {read_time} seconds. Do NOT search again.",

        # Pattern 2: Click result → read → click an internal link on the same site
        f", then click a result, then browse for {read_time // 2} seconds, then click an internal link within the SAME site, then browse for another {read_time // 2} seconds. Do NOT return to search.",

        # Pattern 3: Click result → stay and read/watch media on the page
        f", then click a result, then browse for {read_time} seconds. Stay on the page. Do NOT search again.",
    ]

    # ĐÍCH ĐẾN TRƯỚC: hành vi có "nhà" riêng thì vào thẳng nhà đó thay vì đi
    # vòng qua Google — search.js tự dùng ô tìm kiếm CỦA site khi đã ở trong
    # site (YouTube search chứ không phải Google search). Các hành vi này chỉ
    # được chọn khi hồ sơ có chip đăng nhập tương ứng (BEHAVIOR_LOGIN_NEEDS).
    if behavior in ["watchVideos", "entertainment"]:
        watch_secs = random.randint(120, max(120, min(read_time, 300)))
        prompt = (f"Navigate to youtube.com, then search for '{base_query}', "
                  f"then click a video result, then watch for {watch_secs} seconds. "
                  f"Do NOT search again.")
    elif behavior == "checkEmails":
        prompt = (f"Navigate to mail.google.com, then read gmail unread, "
                  f"then browse for {random.randint(60, 120)} seconds. Do NOT search.")
    elif behavior == "morningCheck":
        _lang = (str(getattr(agent, "language", "") or "").split("-")[0].lower())
        _sites = NEWS_SITES.get(_lang) or NEWS_SITES["en"]
        news_site = rng.choice(_sites)
        prompt = (f"Navigate to {news_site}, then click a result, "
                  f"then browse for {read_time} seconds, "
                  f"then click an internal link within the SAME site, "
                  f"then browse for {read_time // 2} seconds. Do NOT search.")
    else:
        prompt = f"Search for '{base_query}'" + random.choice(suffix_options)
    print(f"[Scheduler Callback] Generated prompt: \"{prompt}\"")

    # --- REAL email actions: reply_email / send_report ---
    # These are not a "Search for X" flow — they are a single gmail
    # compose/reply instruction for the SAME open.js engine (behaviors are
    # prompts, no new skill). Overrides the search prompt above. If a
    # send_report has no recipients, email_skip_reason is set and the run is
    # skipped below the same way a refused spawn is — we never email nobody.
    email_skip_reason = None
    if behavior in ("replyEmail", "sendReport"):
        recipients = normalize_report_recipients(routine, persona)
        # Không tự điền người nhận + chủ máy BẬT allowRandomRecipient → gửi ngẫu
        # nhiên tới một email trong hệ thống (tài khoản Google của profile khác).
        # Chốt an toàn opt-in: không bật thì vẫn bỏ qua như cũ (never email nobody).
        allow_random = bool((isinstance(routine, dict) and routine.get("allowRandomRecipient"))
                            or (isinstance(persona, dict) and persona.get("allowRandomRecipient")))
        if behavior == "sendReport" and not recipients and allow_random:
            # Loại email của MỌI ứng viên có thể spawn — hồ sơ #1 bận thì lượt
            # chạy trên #2/#3, mà người nhận đã nướng cứng vào prompt từ đây.
            pool = _system_report_emails(exclude_profile=launch_candidates[:3])
            if pool:
                recipients = [random.choice(pool)]
                print(f"[Scheduler Callback] send_report: khong dien nguoi nhan, "
                      f"allow_random BAT -> chon {recipients[0]} tu {len(pool)} email he thong")
        email_prompt, email_skip_reason = build_email_prompt(
            behavior, time_period, combined_topics, recipients)
        if email_prompt:
            prompt = email_prompt
            base_query = "gmail"  # run log reads a query; the flow is gmail-driven
            print(f"[Scheduler Callback] Email behavior '{behavior}' prompt: \"{prompt}\"")

    context = {
        # run_id đi kèm để phiên node ghi NHẬT KÝ DIỄN BIẾN (run_trail) theo
        # đúng lượt — bảng Hoạt động mở rộng lượt là đọc được từng hành động.
        "run_id": run_id or "",
        "agent_id": agent.id,
        "agent_name": agent.name,
        "time_period": time_period,
        "current_activity": behavior,
        "interests": combined_topics,
        "routine_tasks": period_tasks,
        "schedule_name": f"Scheduled Routine ({time_period})",
        "proxy_provider": getattr(agent, "proxy_provider", {"mode": "none"}),
        "avatar_type": getattr(agent, "avatar_type", "bot"),
        "avatar_color": getattr(agent, "avatar_color", "blue"),
        "enable_scraping": getattr(agent, "enable_scraping", False),
        "scraper_text_limit": getattr(agent, "scraper_text_limit", 10000),
        "language": getattr(agent, "language", "auto") or "auto",
    }
    
    if agent.auth:
        context["auth"] = agent.auth

    # Flow Builder groups the agent belongs to — the same ones the profile
    # step above already loaded. The routine has no system prompt — `prompt`
    # above is a browsing instruction for open.js — so the GROUP WORKSPACE
    # block rides along in the context file for whatever the browser agent
    # chooses to do with it. Best-effort: never blocks the run.
    try:
        if group_ctxs and _gc is not None:
            context["group_ids"] = [g.get("group_id", "") for g in group_ctxs if g.get("group_id")]
            context["group_workspace"] = _gc.prompt_block(group_ctxs)
    except Exception as _ge:
        print(f"[Scheduler Callback] Group workspace skipped: {_ge}")
        
    # The canvas log panel gets the same two beats run_log gives the dashboard:
    # what this run decided to do, and (below, once the browser answered) how it
    # went. Written here, after the profile and query are chosen, so the line
    # already says which browser is about to move.
    _group_log_routine(group_ctxs, agent,
                       f"schedule {profile_name} → {base_query}"
                       if profile_name else f"schedule → {base_query}",
                       detail=prompt)

    # Session time: average 5 min, max 10 min. Clamp read_time to 120-480s.
    read_time = max(120, min(480, read_time))   # 2-8 min
    # session_minutes = ceil(read_time / 60), capped to 10, floors at 2
    import math
    session_minutes = max(2, min(10, math.ceil(read_time / 60)))
    # NGÂN SÁCH THẬT của một lượt = mở trình duyệt trên VPS (~90s cả vòng
    # fingerprint/ShardX) + chuỗi mở màn (ăn cỡ read_time — watch/browse theo
    # đúng số giây ghi trong prompt) + phiên tối thiểu session_minutes + 60s ân
    # hạn. Watchdog cũ chỉ cấp session_minutes*60+60 — đúng MỘT NỬA nhu cầu —
    # nên watchVideos/browse dài gần như chắc chắn bị giết giữa chừng và vào sổ
    # timeout_killed: "chạy cả ngày được 2 lượt thành công". Trần 900s để một
    # lượt không bao giờ chiếm hồ sơ quá 15 phút.
    max_session_seconds = min(900, 90 + read_time + session_minutes * 60 + 60)
    print(f"[Scheduler Callback] Session timing: read_time={read_time}s, "
          f"session_minutes={session_minutes}min, max_watchdog={max_session_seconds}s")

    # A send_report with no recipients configured: do not spawn a browser to
    # write an email to nobody. Log it honestly and close the run — same
    # launch+end shape the refused-spawn path uses so the row never hangs
    # "running", but with an explicit "skipped" outcome.
    if email_skip_reason:
        print(f"[Scheduler Callback] {email_skip_reason}")
        _group_log_routine(group_ctxs, agent,
                           f"schedule {profile_name} — {behavior} skipped",
                           detail=email_skip_reason, ok=False)
        if run_id:
            run_log.launch(
                run_id, agent.id,
                profile=profile_name,
                time_period=time_period,
                behavior=behavior,
                query=base_query,
                session_minutes=session_minutes,
                max_duration_sec=max_session_seconds,
                spawn_status="skipped",
                error=email_skip_reason,
            )
            run_log.end(run_id, agent.id, "skipped", log_tail=email_skip_reason)
        return

    def _do_launch():
        try:
            from tubecli.extensions.browser.process_manager import browser_process_manager

            # Resolved once for the whole launch so the browser and the run log
            # agree: the log used to record the agent's raw (usually empty) field
            # while the browser was handed "qwen:latest".
            from tubecli.config import resolve_browser_ai
            browser_ai = resolve_browser_ai(agent)

            # Thử LẦN LƯỢT các hồ sơ đủ điều kiện (tối đa 3): hồ sơ đầu bị
            # preflight chặn hay đang bận thì sang hồ sơ kế — trước đây bận là
            # bỏ cả lượt dù agent còn hồ sơ khác dùng được.
            result = {}
            spawn_status = "error"
            profile_busy = False
            spawned = False
            refusal_reason = None
            instance_id = ""
            used_profile = launch_candidates[0]
            _tries = launch_candidates[:3]
            for _attempt, _prof in enumerate(_tries):
                # LIVE VIEW đang giữ hồ sơ? — hỏi TRƯỚC khi làm bất cứ gì. Kẻ
                # giữ này không nằm trong list_running() (nó là phiên preview
                # của canvas) nên vòng cũ không thấy, spawn thẳng vào khoá
                # Chromium và ăn "already open in another process (pid …)" ở
                # giây ~10 → lượt vào sổ Failed đỏ. Không bao giờ giết live
                # view của người dùng: coi là bận, thử ứng viên kế.
                try:
                    from tubecli.extensions.browser.routes import preview_holds_profile
                    if preview_holds_profile(_prof):
                        if trigger != "schedule":
                            # Bấm Run TAY là ý định tường minh — nhường chỗ:
                            # dừng live view của chính chủ rồi chạy; khung trên
                            # canvas tự chuyển sang xem phiên agent (attach
                            # offer). Lịch tự động thì ngược lại: không bao giờ
                            # giật khung người dùng đang xem — skip như dưới.
                            from tubecli.extensions.browser.routes import stop_preview_for_profile
                            print(f"[Scheduler Callback] Manual run — stopping the live view holding '{_prof}'")
                            stop_preview_for_profile(_prof)
                            import time as _time
                            _time.sleep(1.5)   # chờ khoá Singleton của Chromium nhả
                        else:
                            profile_busy = True
                            print(f"[Scheduler Callback] '{_prof}' is held by a live view — busy, trying next candidate")
                            continue
                except Exception as _pv:
                    print(f"[Scheduler Callback] Preview-busy preflight skipped: {_pv}")

                # Ứng viên #1 giữ nếp cũ: phiên đang đứng tên hồ sơ này là rác
                # của lượt trước — dọn rồi chiếm. Ứng viên KẾ TIẾP thì ngược
                # lại: có phiên đang chạy nghĩa là hồ sơ BẬN THẬT (thường là
                # lượt hợp lệ của agent khác dùng chung hồ sơ) — coi là bận và
                # thử tiếp, tuyệt đối không giết.
                running = browser_process_manager.list_running()
                _live = [inst for inst in running if inst.get("profile") == _prof]
                if _attempt == 0:
                    for inst in _live:
                        print(
                            f"[Scheduler Callback] Killing stale session {inst['instance_id']} "
                            f"for profile '{_prof}' before spawning new one."
                        )
                        browser_process_manager.terminate(inst["instance_id"])
                elif _live:
                    profile_busy = True
                    print(f"[Scheduler Callback] Candidate '{_prof}' has a live session — busy, trying next")
                    continue

                # Hỏi TRƯỚC khi spawn: hồ sơ này có cửa nào mở được không. spawn()
                # báo "running" ngay khi tiến trình node lên, nên một lượt chết sau
                # một giây vẫn vào sổ như một lần mở thành công. Cùng một câu từ
                # chối mà /launch và live view đang dùng, chỉ đọc đĩa nên rẻ.
                refusal = None
                try:
                    from tubecli.extensions.browser.routes import launch_refusal
                    refusal = launch_refusal(_prof)
                except Exception as _pe:
                    print(f"[Scheduler Callback] Preflight skipped: {_pe}")
                if refusal:
                    refusal_reason = f"{refusal['code']}: {refusal['message']}"
                    print(f"[Scheduler Callback] Refusing to spawn '{_prof}' — {refusal_reason}"
                          + (" — trying next candidate" if _attempt + 1 < len(_tries) else ""))
                    continue

                used_profile = _prof
                # Phiên biết hồ sơ mình đang lái đã đăng nhập gì — để AI phiên
                # không mò vào mạng xã hội mà hồ sơ này chưa có tài khoản.
                context["profile_logins"] = sorted(profile_logins.get(_prof, set()))
                print(
                    f"[Scheduler Callback] Spawning browser profile '{_prof}' "
                    f"for agent '{agent.name}' (max {max_session_seconds}s) "
                    f"using AI {browser_ai['model']} (from {browser_ai['source']})..."
                )
                result = browser_process_manager.spawn(
                    profile=_prof,
                    prompt=prompt,
                    headless=False,
                    manual=False,
                    ai_model=browser_ai["model"],
                    context=context,
                    max_duration=max_session_seconds,
                    session_minutes=session_minutes,
                    run_id=run_id,
                    agent_id=agent.id,
                )
                spawned = True
                instance_id = result.get("instance_id", "")
                spawn_status = result.get("status", "unknown")
                print(
                    f"[Scheduler Callback] Spawn result: {spawn_status} "
                    f"(PID: {result.get('pid')}, instance: {instance_id})"
                )
                # Hồ sơ đang bị MỘT phiên khác/live view giữ (browser_manager ném
                # PROFILE_IN_USE) KHÔNG phải lỗi thực thi — chỉ là "bận". Còn ứng
                # viên thì thử tiếp, hết mới ghi BỎ QUA (xám) thay vì Failed (đỏ).
                _busy_txt = (str(result.get("error") or "") + " "
                             + str(result.get("log_output") or "")).lower()
                profile_busy = spawn_status == "error" and (
                    "already open in another process" in _busy_txt
                    or "profile_in_use" in _busy_txt)
                if profile_busy and _attempt + 1 < len(_tries):
                    print(f"[Scheduler Callback] Profile '{_prof}' busy — trying next candidate")
                    continue
                break

            if not spawned:
                if profile_busy:
                    # Mọi ứng viên khả dụng đều đang có phiên sống — BỎ QUA xám
                    # đúng như đường busy sau spawn, không phải lỗi.
                    busy_reason = ("Skipped: all candidate profiles are in use. "
                                   "Will run at the next scheduled slot.")
                    _group_log_routine(group_ctxs, agent,
                                       f"schedule {used_profile} — browser busy (skip)",
                                       detail=busy_reason, ok=True)
                    if run_id:
                        run_log.launch(
                            run_id, agent.id,
                            profile=used_profile,
                            time_period=time_period,
                            behavior=behavior,
                            query=base_query,
                            prompt=prompt,
                            session_minutes=session_minutes,
                            max_duration_sec=max_session_seconds,
                            ai_model=browser_ai["model"],
                            spawn_status="skipped",
                            error=busy_reason,
                        )
                        run_log.end(run_id, agent.id, "skipped", log_tail=busy_reason)
                    return
                # Mọi ứng viên đều bị preflight chặn — giữ nguyên đường 'refused'
                # cũ: `launch` giữ lý do thật, `end` đóng lượt để khỏi treo
                # "running" vĩnh viễn (không có tiến trình thì không có monitor).
                reason = refusal_reason or "no launchable profile"
                _group_log_routine(
                    group_ctxs, agent,
                    f"schedule {used_profile} — browser refused",
                    detail=reason[:400], ok=False)
                if run_id:
                    run_log.launch(
                        run_id, agent.id,
                        profile=used_profile,
                        time_period=time_period,
                        behavior=behavior,
                        query=base_query,
                        prompt=prompt,
                        session_minutes=session_minutes,
                        max_duration_sec=max_session_seconds,
                        ai_model=browser_ai["model"],
                        spawn_status="refused",
                        error=reason,
                    )
                    run_log.end(run_id, agent.id, "refused", log_tail=reason)
                return
            if spawn_status == "error":
                print(f"[Scheduler Callback] Spawn error detail: {result.get('error')}")
                # Tiến trình chết trong vòng 1 giây thì spawn() đã kèm log về đây.
                # Nếu log nói khoá BAS hỏng, ghi lại ngay: đó là thứ duy nhất biến
                # kiểm kê từ "chưa biết khoá còn sống không" thành "khoá đã chết",
                # và nhờ đó lượt SAU bị preflight chặn thẳng thay vì lại spawn rồi
                # lại ghi "running". Lưu ý cửa sổ 1 giây của process_manager.spawn:
                # lỗi khoá thường nổ ở giây thứ ~10, lúc đó tiến trình đã được coi
                # là "running" và log không đi qua đây nữa (xem tóm tắt).
                try:
                    from tubecli.extensions.browser.routes import note_launch_output
                    note_launch_output(
                        str(result.get("error") or "")
                        + " " + str(result.get("log_output") or ""))
                except Exception as _ke:
                    print(f"[Scheduler Callback] Could not record BAS key verdict: {_ke}")

            # Kết thúc phần việc chạy được TRONG hàm này: trình duyệt lên hay
            # không. Phiên duyệt web sau đó do process_manager theo dõi và ghi
            # vào run_log — bảng nhóm chỉ cần biết lượt chạy đã khởi động được.
            _group_log_routine(
                group_ctxs, agent,
                f"schedule {used_profile} — browser {'busy (skip)' if profile_busy else spawn_status}",
                detail=str(result.get("error") or "")[:400],
                ok=(spawn_status != "error") or profile_busy)

            # Everything above was print-only until now. On success the monitor
            # thread writes the matching `end` row when the process exits; on a
            # failed spawn there will be no monitor, so this row is the whole story.
            if run_id:
                busy_reason = (f"Skipped: {len(_tries)} candidate profile(s) in use — a live "
                               "view or another session is open. Will run at the next scheduled slot.")
                run_log.launch(
                    run_id, agent.id,
                    profile=used_profile,
                    time_period=time_period,
                    behavior=behavior,   # checkEmails/replyEmail/sendReport… — bảng đọc để hiện nhãn thay 'gmail'
                    query=base_query,
                    prompt=prompt,
                    session_minutes=session_minutes,
                    max_duration_sec=max_session_seconds,
                    ai_model=browser_ai["model"],
                    spawn_status=("skipped" if profile_busy else spawn_status),
                    instance_id=instance_id or None,
                    pid=result.get("pid"),
                    log_file=result.get("log_file"),
                    error=(busy_reason if profile_busy else result.get("error")),
                    log_tail=result.get("log_output"),
                )
                # Không có monitor cho lượt không mở được browser → tự đóng lượt bằng
                # 'skipped' (xám), nếu không nó treo "running" tới khi quá giờ.
                if profile_busy:
                    run_log.end(run_id, agent.id, "skipped", log_tail=busy_reason)
        except Exception as e:
            print(f"[Scheduler Callback] Error launching browser: {e}")
            _group_log_routine(group_ctxs, agent,
                               f"schedule {profile_name} — launch failed",
                               detail=str(e)[:400], ok=False)
            # A run that dies here would otherwise show as "running" forever,
            # since no browser was spawned and so no monitor will ever close it.
            if run_id:
                import traceback
                run_log.end(run_id, agent.id, "failed",
                            log_tail=traceback.format_exc()[-2000:])

    import threading
    threading.Thread(target=_do_launch, daemon=True).start()


@app.on_event("startup")
async def startup_event():
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    from tubecli.core.telegram_listener import telegram_listener
    telegram_listener.start()

    # Pre-fetch Core update in background once on server startup
    import asyncio
    asyncio.create_task(check_for_updates())

    # Start PageWatcher scheduler (if web_crawler extension has watches)
    try:
        import sys
        from tubecli.config import EXTENSIONS_EXTERNAL_DIR
        wc_dir = os.path.join(str(EXTENSIONS_EXTERNAL_DIR), "web_crawler")
        if os.path.isdir(wc_dir) and wc_dir not in sys.path:
            sys.path.insert(0, wc_dir)
        from watcher import page_watcher
        if page_watcher.list_watches():
            page_watcher.start_scheduler()
            print("[Startup] PageWatcher scheduler started")
    except Exception as e:
        print(f"[Startup] PageWatcher not available: {e}")

    # Start the core background scheduler daemon
    try:
        from tubecli.core.scheduler import scheduler
        scheduler.set_agent_runner(run_agent_routine)
        
        def _run_skill_bg(skill_id):
            import asyncio
            async def _run():
                try:
                    print(f"[Scheduler] Executing scheduled skill {skill_id}...")
                    # run_skill nhận `request` để biết AI đang gọi hay người
                    # đang gọi. Ở đây không có request nào — lượt này là lịch
                    # của chủ — nên nói thẳng ra thay vì để nó rơi vào nhánh
                    # mặc định (model) hoặc nổ TypeError vì thiếu tham số.
                    await run_skill(skill_id, _OwnerInProcessCall("scheduler"))
                except Exception as e:
                    print(f"[Scheduler] Error running scheduled skill {skill_id}: {e}")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_run())
            except RuntimeError:
                asyncio.run(_run())
                
        scheduler.set_runner(_run_skill_bg)
        scheduler.start(interval_sec=30)
        print("[Startup] Core background scheduler daemon started successfully")
    except Exception as e:
        print(f"[Startup] Failed to start Core background scheduler: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    try:
        from tubecli.core.scheduler import scheduler
        scheduler.stop()
        print("[Shutdown] Core background scheduler daemon stopped")
    except Exception:
        pass
    from tubecli.core.telegram_listener import telegram_listener
    await telegram_listener.stop()

@app.post("/api/v1/system/shutdown")
async def shutdown_server():
    """Trigger a graceful shutdown of the TubeCLI server."""
    import threading
    import time
    def _shutdown():
        time.sleep(1)
        cli_pid = os.environ.get("TUBECLI_CLI_PID")
        if cli_pid:
            try:
                import signal
                if os.name == 'nt':
                    os.system(f"taskkill /F /PID {cli_pid}")
                else:
                    os.kill(int(cli_pid), signal.SIGTERM)
            except Exception:
                pass
        os._exit(0)
    threading.Thread(target=_shutdown).start()
    return {"status": "success", "message": "Server is shutting down..."}

# ── Pydantic Models ──────────────────────────────────────────────

class AgentCreateRequest(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = "You are a helpful AI assistant."
    model: Optional[str] = None
    
    # New Fields
    allowed_skills: Optional[List[str]] = None
    avatar_icon: Optional[str] = "SMART_TOY"
    avatar_type: Optional[str] = "bot"
    avatar_color: Optional[str] = "blue"
    # "" = not chosen; resolve_browser_ai() answers instead.
    browser_ai_model: Optional[str] = ""
    telegram_token: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    messenger_token: Optional[str] = ""
    messenger_page_id: Optional[str] = ""
    messenger_php_url: Optional[str] = ""
    direct_trigger_skill_id: Optional[str] = ""
    persona: Optional[Dict] = {}
    routine: Optional[Dict] = {}
    thinking_map: Optional[Dict] = {}
    allowed_profiles: Optional[List[str]] = []
    login_accounts: Optional[List[str]] = []
    proxy_config: Optional[str] = ""
    proxy_provider: Optional[Dict] = {"mode": "static"}
    timezone: Optional[str] = None
    language: Optional[str] = "auto"
    auth: Optional[Dict] = {}
    cloud_api_keys: Optional[Dict] = {}
    enable_scraping: Optional[bool] = False
    scraper_text_limit: Optional[int] = 10000
    script_output_format: Optional[str] = "json"
    routine_in_chat: Optional[bool] = True
    schedule_enabled: Optional[bool] = False
    schedule_repeat: Optional[str] = "Daily"
    schedule_interval: Optional[int] = 60
    schedule_active_days: Optional[List[str]] = []
    schedule_start_time: Optional[str] = "08:00"
    schedule_end_time: Optional[str] = "22:00"
    schedule_max_runs: Optional[int] = 10
    schedule_next_run: Optional[str] = None
    schedule_last_run: Optional[str] = None
    schedule_runs_today: Optional[int] = 0

class AgentGenerateRequest(BaseModel):
    name: str = ""
    description: str = ""
    # Written by the user, optional. When present it becomes the agent's system
    # prompt verbatim and the generator is told to build the persona AROUND it,
    # so interests and focus areas agree with the instructions instead of
    # describing a different agent.
    system_prompt: str = ""
    provider: str = "ollama"
    model: str = "qwen:latest"
    api_key: Optional[str] = None
    output_target_prefix: str = "ai"

class ExtensionUpdateRequest(BaseModel):
    port: Optional[int] = None

class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    allowed_skills: Optional[List[str]] = None
    avatar_icon: Optional[str] = None
    avatar_type: Optional[str] = None
    avatar_color: Optional[str] = None
    browser_ai_model: Optional[str] = None
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    messenger_token: Optional[str] = None
    messenger_page_id: Optional[str] = None
    messenger_php_url: Optional[str] = None
    direct_trigger_skill_id: Optional[str] = None
    persona: Optional[Dict] = None
    routine: Optional[Dict] = None
    thinking_map: Optional[Dict] = None
    allowed_profiles: Optional[List[str]] = None
    login_accounts: Optional[List[str]] = None
    proxy_config: Optional[str] = None
    proxy_provider: Optional[Dict] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    auth: Optional[Dict] = None
    cloud_api_keys: Optional[Dict] = None
    enable_scraping: Optional[bool] = None
    scraper_text_limit: Optional[int] = None
    script_output_format: Optional[str] = None
    routine_in_chat: Optional[bool] = None
    schedule_enabled: Optional[bool] = None
    schedule_repeat: Optional[str] = None
    schedule_interval: Optional[int] = None
    schedule_active_days: Optional[List[str]] = None
    schedule_start_time: Optional[str] = None
    schedule_end_time: Optional[str] = None
    schedule_max_runs: Optional[int] = None
    schedule_next_run: Optional[str] = None
    schedule_last_run: Optional[str] = None
    schedule_runs_today: Optional[int] = None

class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    workflow_data: Dict = {}
    skill_type: str = "Skill"
    skill_format: Optional[str] = None
    commands: Optional[List[str]] = []
    trigger: Optional[str] = ""
    # Tool contract for LLM agents
    input_hint: Optional[str] = None
    when_to_use: Optional[str] = None
    examples: Optional[List[str]] = None

class SkillGenerateRequest(BaseModel):
    prompt: str
    provider: str = "ollama"
    model: str = ""
    api_key: str = ""

class WorkflowGenerateRequest(BaseModel):
    prompt: str
    provider: str = "ollama"
    model: str = ""
    api_key: str = ""

class WorkflowRunRequest(BaseModel):
    workflow_data: Dict
    input_text: str = ""

class WorkflowSaveRequest(BaseModel):
    name: str
    workflow_data: Dict


# ── Root ─────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Send the bare origin to the dashboard.

    There was no route here, so http://127.0.0.1:5295 — the address printed by the
    installers, the CLI banner and the "no API key" message — answered
    {"detail":"Not Found"}. That is the first thing a new user sees after a
    successful install, and it reads as a broken program.
    """
    from fastapi.responses import RedirectResponse
    # Carry the query string across. /?theme=glass is how the Flow canvas (and
    # anything embedding the dashboard) asks for the light palette, and it is
    # read by an inline script BEFORE first paint — a redirect that drops it
    # leaves the reader with nothing and the page falls back to the OS setting.
    query = request.url.query
    return RedirectResponse(url="/dashboard" + (f"?{query}" if query else ""))


# ── Health ───────────────────────────────────────────────────────

@app.get("/api/v1/health")
async def health():
    from tubecli.config import get_api_port
    return {"status": "ok", "message": "TubeCLI API is running", "port": get_api_port()}


# ── Version & Update ──────────────────────────────────────────────

@app.get("/api/v1/version")
async def get_version_info():
    import subprocess
    from tubecli import __version__, __build__
    info = {"version": __version__, "build": __build__, "pip_version": __version__, "git_hash": None, "git_branch": None}
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=repo, timeout=3)
        b = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=repo, timeout=3)
        if h.returncode == 0: info["git_hash"] = h.stdout.strip()
        if b.returncode == 0: info["git_branch"] = b.stdout.strip()
    except Exception:
        pass
    return info


def _git_pull_safe(repo: str, pull_args=("git", "pull")) -> dict:
    """git pull that survives local modifications and reports WHY it failed.

    The dashboard's Update button used to call `git pull` bare and then show
    `stdout or stderr`. On a blocked pull git prints "Updating <old>..<new>" to
    STDOUT and the actual reason ("Your local changes to the following files
    would be overwritten by merge: …") to STDERR — so the user saw only
    "git pull failed: Updating 25a1" and nothing about what to do.

    Now: tracked local changes are stashed first, the pull runs, and the stash
    is popped back. If the pop conflicts with the new code, the working tree is
    reset to the fresh HEAD (so the app runs the new version) and the user's
    changes stay safe in `git stash list` — the message says so, by file.
    """
    import subprocess
    import time as _time

    def run(cmd, timeout=60):
        return subprocess.run(cmd, capture_output=True, text=True, cwd=repo, timeout=timeout)

    notes = []
    st = run(["git", "status", "--porcelain", "--untracked-files=no"], 15)
    dirty = [l[3:].strip() for l in st.stdout.splitlines() if l.strip()] if st.returncode == 0 else []
    stashed = False
    if dirty:
        s = run(["git", "stash", "push", "-m",
                 f"tubecli-auto-update {_time.strftime('%Y-%m-%d %H:%M:%S')}"], 30)
        if s.returncode != 0:
            return {"ok": False, "dirty": dirty, "notes": notes,
                    "message": "Có thay đổi cục bộ chưa commit và không cất tạm được: "
                               + (s.stderr.strip() or s.stdout.strip())
                               + " — file: " + ", ".join(dirty)}
        stashed = True
        notes.append(f"Đã cất tạm {len(dirty)} file sửa cục bộ (git stash): " + ", ".join(dirty))

    r = run(list(pull_args), 120)
    if r.returncode != 0:
        reason = r.stderr.strip() or r.stdout.strip()
        if stashed:
            pop = run(["git", "stash", "pop"], 30)
            notes.append("Đã khôi phục thay đổi cục bộ." if pop.returncode == 0
                         else "Thay đổi cục bộ vẫn nằm trong `git stash list`.")
        return {"ok": False, "dirty": dirty, "notes": notes,
                "message": f"git pull failed: {reason}", "output": r.stdout.strip()}

    out = r.stdout.strip()
    if stashed:
        pop = run(["git", "stash", "pop"], 30)
        if pop.returncode == 0:
            notes.append("Đã khôi phục thay đổi cục bộ sau khi cập nhật.")
        else:
            # A conflicting pop leaves conflict markers in the tree; the app
            # must not run that. Reset to the new HEAD — the stash is kept.
            run(["git", "reset", "--hard", "HEAD"], 30)
            notes.append("Thay đổi cục bộ XUNG ĐỘT với bản mới nên được giữ nguyên trong "
                         "`git stash list` (chạy `git stash pop` để xử lý tay). File: " + ", ".join(dirty))
    return {"ok": True, "dirty": dirty, "notes": notes, "message": out, "output": out}

@app.post("/api/v1/version/update")
async def perform_git_update():
    """Safe update: git pull + install only missing deps + restart.
    Mirrors the init_cmd.py option-9 logic. Never runs 'pip install -e .'
    which would break the running installation.
    """
    import subprocess, re, threading, time
    from tubecli import __build__
    from tubecli.config import BASE_DIR
    try:
        repo = str(BASE_DIR)

        # Step 1: git pull — stash-aware, and the failure message carries the
        # real reason (stderr) plus the files involved, not just "Updating abc".
        pr = _git_pull_safe(repo, ("git", "pull"))
        pull_output = pr["message"] + ("\n" + "\n".join(pr["notes"]) if pr["notes"] else "")
        if not pr["ok"]:
            return {"status": "error", "output": pull_output, "dirty_files": pr["dirty"]}

        # Step 2: Check which files changed to determine if deps need updating
        changed_files = []
        try:
            r_diff = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1..HEAD"],
                capture_output=True, text=True, cwd=repo, timeout=10,
            )
            if r_diff.returncode == 0:
                changed_files = [f.strip() for f in r_diff.stdout.strip().split("\n") if f.strip()]
        except Exception:
            pass

        deps_changed = any(f in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg") for f in changed_files)
        pip_output = ""

        # Step 3: Smart dependency check — only if pyproject.toml or requirements.txt changed
        if deps_changed:
            required_packages = set()
            # From pyproject.toml
            pyproject_path = os.path.join(repo, "pyproject.toml")
            if os.path.exists(pyproject_path):
                try:
                    with open(pyproject_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    in_deps = False
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("dependencies"):
                            in_deps = True
                            continue
                        if in_deps:
                            if stripped == "]":
                                break
                            match = re.match(r'^\s*"([a-zA-Z0-9_-]+)', stripped)
                            if match:
                                required_packages.add(match.group(1).lower().replace("-", "_"))
                except Exception:
                    pass

            # From requirements.txt
            req_path = os.path.join(repo, "requirements.txt")
            if os.path.exists(req_path):
                try:
                    with open(req_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                pkg = re.split(r"[>=<!\[\];]", line)[0].strip().lower().replace("-", "_")
                                if pkg:
                                    required_packages.add(pkg)
                except Exception:
                    pass

            if required_packages:
                # Get installed packages
                installed = set()
                try:
                    r_pip = subprocess.run(
                        [sys.executable, "-m", "pip", "list", "--format=columns"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if r_pip.returncode == 0:
                        for line in r_pip.stdout.splitlines()[2:]:
                            parts = line.split()
                            if parts:
                                installed.add(parts[0].lower().replace("-", "_"))
                except Exception:
                    pass

                missing = required_packages - installed
                if missing:
                    pip_r = subprocess.run(
                        [sys.executable, "-m", "pip", "install", *sorted(missing), "--quiet"],
                        capture_output=True, text=True, timeout=120,
                    )
                    pip_output = f"Installed {len(missing)} new package(s): {', '.join(sorted(missing))}"
                else:
                    pip_output = "All dependencies already satisfied."
            else:
                pip_output = "No dependencies to check."
        else:
            pip_output = "No dependency files changed, skipping pip."

        # Step 4: Read updated version from file
        new_version = __build__
        try:
            init_file = os.path.join(repo, "tubecli", "__init__.py")
            with open(init_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("__version__"):
                        new_version = line.split("=")[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

        # Step 5: Schedule restart — kill CLI parent process after response is sent
        # The CLI init_cmd.py menu loop will detect termination and the user
        # double-clicks the shortcut or runs 'tubecli init' again.
        restart_flag = os.path.join(repo, ".restarted")
        try:
            with open(restart_flag, "w") as f:
                f.write("1")
        except Exception:
            pass

        def _delayed_restart():
            time.sleep(2)
            cli_pid = os.environ.get("TUBECLI_CLI_PID")
            if cli_pid:
                try:
                    if os.name == 'nt':
                        os.system(f"taskkill /F /PID {cli_pid}")
                    else:
                        import signal
                        os.kill(int(cli_pid), signal.SIGTERM)
                except Exception:
                    pass
            # Restart CLI in a new process
            try:
                if os.name == 'nt':
                    CREATE_NO_WINDOW = 0x08000000
                    subprocess.Popen(
                        f'start "TubeCLI" cmd /k "cd /d {repo} && python -m tubecli.main init"',
                        shell=True, cwd=repo,
                    )
                else:
                    # `init` opens the interactive control panel, a loop that reads
                    # from stdin. Restarted detached on a headless host it hits EOF
                    # on the first prompt and aborts — so updating from the web
                    # killed this server (os._exit below) and replaced it with a
                    # process that died immediately, leaving no API at all.
                    # Restart what was actually running: the API server. The control
                    # panel is only restarted when a terminal is attached to it.
                    if os.environ.get("TUBECLI_CLI_PID") and sys.stdin and sys.stdin.isatty():
                        args = [sys.executable, "-m", "tubecli.main", "init"]
                    else:
                        args = [sys.executable, "-m", "tubecli.main", "api", "start"]
                        port_env = os.environ.get("TUBECLI_PORT")
                        if port_env:
                            args += ["--port", port_env]
                    subprocess.Popen(args, cwd=repo, start_new_session=True)
            except Exception:
                pass
            time.sleep(1)
            os._exit(0)

        threading.Thread(target=_delayed_restart, daemon=True).start()

        return {
            "status": "success",
            "output": pull_output,
            "pip_output": pip_output,
            "version": new_version,
            "restarting": True,
        }
    except Exception as e:
        return {"status": "error", "output": str(e)}

VERSION_CHECK_CACHE = {"data": None, "last_check": 0.0}
# The cache had no expiry: any result was kept for the life of the process, and
# `last_check` was written but never read. A release published while the server ran
# stayed invisible until someone restarted it — which is precisely the situation an
# update check exists for.
VERSION_CHECK_TTL = 1800  # 30 minutes

@app.get("/api/v1/version/check")
async def check_for_updates(force: bool = False):
    """Check GitHub for a newer version by reading pyproject.toml on main.

    Cached for VERSION_CHECK_TTL; pass ?force=true to bypass, which is what a
    "check now" button should do.
    """
    global VERSION_CHECK_CACHE
    import httpx, re, time
    now = time.time()
    if (VERSION_CHECK_CACHE["data"] is not None
            and not force
            and now - VERSION_CHECK_CACHE.get("last_check", 0) < VERSION_CHECK_TTL):
        return VERSION_CHECK_CACHE["data"]
    from tubecli import __version__
    print(f"[VersionCheck] Local version: {__version__}")
    try:
        raw_url = "https://raw.githubusercontent.com/tubecreate/tubecli/main/pyproject.toml"
        # Our own 30-minute cache is not the only one in the way: raw.github
        # serves through a CDN with its own max-age, so a release published a
        # minute ago can still read as "up to date". On an explicit check, ask
        # both to revalidate and vary the URL so no intermediary can match it.
        headers = {}
        if force:
            headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
            raw_url += f"?t={int(now)}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(raw_url, headers=headers)
            if resp.status_code != 200:
                print(f"[VersionCheck] GitHub returned {resp.status_code}")
                res = {"has_update": False, "error": f"GitHub returned {resp.status_code}"}
                VERSION_CHECK_CACHE["data"] = res
                VERSION_CHECK_CACHE["last_check"] = now
                return res
            text = resp.text
            # Match version specifically under [project] section to avoid false matches
            m = re.search(r'^\[project\].*?^version\s*=\s*"([^"]+)"', text, re.MULTILINE | re.DOTALL)
            if not m:
                # Fallback: match first version = "..." in file
                m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if not m:
                print("[VersionCheck] Could not parse version from GitHub pyproject.toml")
                res = {"has_update": False, "error": "Could not parse version"}
                VERSION_CHECK_CACHE["data"] = res
                VERSION_CHECK_CACHE["last_check"] = now
                return res
            remote_version = m.group(1)
            print(f"[VersionCheck] Remote version: {remote_version}")
            # Version comparison (supports N-part dotted versions like 2026.05.18.151200)
            try:
                local_parts = [int(x) for x in __version__.split(".")]
                remote_parts = [int(x) for x in remote_version.split(".")]
                has_update = remote_parts > local_parts
            except ValueError:
                # Fallback string comparison if parts are non-numeric
                has_update = remote_version != __version__
            print(f"[VersionCheck] has_update={has_update}")
            res = {
                "has_update": has_update,
                "current_version": __version__,
                "remote_version": remote_version,
            }
            VERSION_CHECK_CACHE["data"] = res
            VERSION_CHECK_CACHE["last_check"] = now
            return res
    except Exception as e:
        print(f"[VersionCheck] Error: {e}")
        res = {"has_update": False, "error": str(e)}
        VERSION_CHECK_CACHE["data"] = res
        VERSION_CHECK_CACHE["last_check"] = now
        return res


# ── Browser AI ───────────────────────────────────────────────────

def browser_ai_payload(agent=None) -> dict:
    """resolve_browser_ai() plus a sentence a UI can print unmodified.

    A UI that only had the agent's raw browser_ai_model showed an empty box
    whenever the agent had not picked one, which reads as "broken" rather than
    "inherited". source_label is the same answer in words — "Using your default
    AI (deepseek-v4-flash)" — and `source` is there for anything that would
    rather style it itself.
    """
    from tubecli.config import resolve_browser_ai, get_language
    from tubecli.i18n import t, load_language

    info = resolve_browser_ai(agent)
    key = f"browser_ai.source.{info['source']}"
    label = t(key, model=info["model"])
    if label == key:
        # Catalogue not loaded in this process yet (t() returns the key).
        load_language(get_language())
        label = t(key, model=info["model"])
    info["source_label"] = label
    return info


@app.get("/api/v1/browser-ai/resolve")
async def resolve_browser_ai_endpoint(agent_id: str = ""):
    """Which AI will drive the browser, for an agent or for the defaults alone.

    Called by the agent editor and by the Flow canvas to fill in the "inherited"
    line under an unset browser-AI picker. Without agent_id it answers for the
    settings alone, which is what the settings page needs to preview its own
    fallback.
    """
    agent = None
    if agent_id:
        from tubecli.core.agent import agent_manager
        agent = agent_manager.get(agent_id)
        if not agent:
            raise HTTPException(404, f"Agent {agent_id} not found")
    payload = browser_ai_payload(agent)
    payload["agent_id"] = agent_id
    return payload


# ── Agents ───────────────────────────────────────────────────────

@app.get("/api/v1/agents")
async def list_agents():
    from tubecli.core.agent import agent_manager
    agents = agent_manager.get_all()
    return {"agents": [a.to_dict() for a in agents], "count": len(agents)}

@app.post("/api/v1/agents/generate")
async def generate_agent_with_ai(req: AgentGenerateRequest):
    from tubecli.core.ai_generator import generate_agent_json
    try:
        data = generate_agent_json(
            name=req.name,
            description=req.description,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key or "",
            system_prompt=req.system_prompt or "",
        )
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/agents/{agent_id}")
async def get_agent(agent_id: str):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    data = agent.to_dict()
    # browser_ai_model is the agent's raw choice and is empty when it has none.
    # This is what will actually run, and where it came from, so the editor can
    # label the empty picker instead of leaving it blank.
    data["browser_ai_resolved"] = browser_ai_payload(agent)
    return data

@app.post("/api/v1/agents")
async def create_agent(req: AgentCreateRequest):
    from tubecli.core.agent import agent_manager
    import threading
    agent = agent_manager.create(**req.model_dump(exclude_none=True))

    # WHY chạy nền: sinh dailyRoutine theo vai trò phải KHÔNG làm hỏng/treo phản
    # hồi tạo agent. Gọi LLM có thể chậm hoặc lỗi, nên đẩy sang daemon thread —
    # create trả về ngay lập tức. Nếu agent chưa tự đặt dailyRoutine, trong lúc
    # routine chưa kịp về thì scheduler đã có sẵn fallback ngẫu nhiên che chỗ
    # trống, nên không có "khoảng chết". _seed_agent_routine tự bọc kín lỗi.
    persona = agent.persona or {}
    has_routine = bool((persona.get("dailyRoutine") if isinstance(persona, dict) else None)
                       or (agent.routine or {}).get("dailyRoutine"))
    if not has_routine:
        threading.Thread(target=_seed_agent_routine, args=(agent.id,), daemon=True).start()

    return {"status": "created", "agent": agent.to_dict()}

@app.put("/api/v1/agents/{agent_id}")
async def update_agent(agent_id: str, req: AgentUpdateRequest):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.update(agent_id, **req.model_dump(exclude_none=True))
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return {"status": "updated", "agent": agent.to_dict()}

@app.delete("/api/v1/agents/{agent_id}")
async def delete_agent(agent_id: str):
    from tubecli.core.agent import agent_manager
    if not agent_manager.delete(agent_id):
        raise HTTPException(404, f"Agent {agent_id} not found")
    return {"status": "deleted", "agent_id": agent_id}

@app.post("/api/v1/agents/{agent_id}/test_routine")
async def test_agent_routine(agent_id: str):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    try:
        # trigger="manual": nút Run now/Chạy lại — vòng launch được phép nhường
        # chỗ (dừng live view đang giữ hồ sơ) thay vì skip như lịch tự động.
        run_agent_routine(agent_id, trigger="manual")
        return {"status": "success", "message": f"Triggered behavior routine for agent '{agent.name}'"}
    except Exception as e:
        raise HTTPException(500, f"Failed to run behavior routine: {str(e)}")


@app.post("/api/v1/agents/{agent_id}/regenerate_keywords")
async def regenerate_agent_keywords(agent_id: str):
    """Force regenerate daily keywords for an agent (ignores cached date, applies current language)."""
    from tubecli.core.agent import agent_manager
    import asyncio, threading
    from datetime import datetime, timezone as tz

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    # Clear the cached date so check_and_generate_daily_keywords will re-generate
    routine = agent.routine or {}
    existing_dk = routine.get("daily_keywords") or {}
    existing_dk["date"] = ""  # force stale
    routine["daily_keywords"] = existing_dk
    agent_manager.update(agent_id, routine=routine)

    # Reload fresh agent and regenerate
    def _regen():
        try:
            fresh_agent = agent_manager.get(agent_id)
            now_dt = datetime.now(tz.utc)
            new_kw = check_and_generate_daily_keywords(fresh_agent, now_dt)
            print(f"[RegenKw] Regenerated keywords for agent '{fresh_agent.name}': {new_kw}")
        except Exception as e:
            print(f"[RegenKw] Error regenerating keywords for agent {agent_id}: {e}")

    threading.Thread(target=_regen, daemon=True).start()
    return {"status": "success", "message": f"Keyword regeneration started for agent '{agent.name}'. Language: {getattr(agent, 'language', 'auto')}"}


@app.post("/api/v1/agents/{agent_id}/generate_routine")
async def generate_agent_routine_endpoint(agent_id: str):
    """Sinh lại chip hành vi theo buổi (dailyRoutine) từ persona/vai trò hiện tại.

    Nút "Sinh theo vai trò" ở tab Schedule gọi endpoint này. Khác regenerate_keywords
    (chạy nền, trả 'đã bắt đầu'): người dùng bấm chủ động và cần thấy kết quả ngay
    để refresh chip, nên ta chạy ĐỒNG BỘ và trả về routine đã lưu. Chip vẫn sửa
    tay được như cũ sau đó. _seed_agent_routine đã bọc kín lỗi + có fallback nên
    endpoint không bao giờ vỡ vì LLM.
    """
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    routine_map = _seed_agent_routine(agent_id)
    if routine_map is None:
        # Chỉ xảy ra nếu agent biến mất giữa chừng — trả default trung thực.
        routine_map = _default_daily_routine()
    return {"status": "success", "routine": routine_map, "agent_id": agent_id}


class DailyKeywordsUpdateRequest(BaseModel):
    morning: List[str] = []
    afternoon: List[str] = []
    evening: List[str] = []
    night: List[str] = []


@app.put("/api/v1/agents/{agent_id}/daily_keywords")
async def update_agent_daily_keywords(agent_id: str, req: DailyKeywordsUpdateRequest):
    """Manually set/override today's evolved keywords for an agent."""
    import datetime as _dt
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    # Use the agent's timezone so "today" matches what the scheduler sees.
    now = _dt.datetime.now()
    tz_str = getattr(agent, "timezone", None)
    if tz_str and isinstance(tz_str, str) and tz_str.strip():
        try:
            from zoneinfo import ZoneInfo
            now = _dt.datetime.now(ZoneInfo(tz_str.strip()))
        except Exception:
            pass

    def _clean(items):
        seen = []
        for kw in items or []:
            kw = str(kw).strip()
            if kw and kw not in seen:
                seen.append(kw)
        return seen

    routine = agent.routine or {}
    routine["daily_keywords"] = {
        "date": now.strftime("%Y-%m-%d"),
        "morning": _clean(req.morning),
        "afternoon": _clean(req.afternoon),
        "evening": _clean(req.evening),
        "night": _clean(req.night),
    }
    agent = agent_manager.update(agent_id, routine=routine)
    return {"status": "success", "agent": agent.to_dict()}


@app.get("/api/v1/agents/{agent_id}/history")
async def get_agent_history(agent_id: str):
    from tubecli.core.agent import agent_manager
    import json
    from pathlib import Path
    
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
        
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []

    # Raw history rows, unchanged: the dashboard's history tab reads camelCase
    # straight off this. Only the reading is shared with scraped_store; the
    # normalised view lives under /api/v1/scraped/*.
    from tubecli.core import scraped_store

    all_articles = []
    for profile in scraped_store.resolve_profiles(allowed_profiles):
        for a in scraped_store.raw_history(profile):
            if scraped_store.owns(a, agent_id, allowed_profiles, profile):
                a_copy = dict(a)
                a_copy["_profile"] = profile
                all_articles.append(a_copy)

    # Sort by scrapedAt desc
    all_articles.sort(key=lambda x: x.get("scrapedAt", ""), reverse=True)
    return all_articles


# Deliberately `def`, not `async def`: this reads files, and Starlette runs a
# sync endpoint in the threadpool instead of blocking the event loop.
# It inherits the login gate automatically — /api/v1/agents/* is not in
# _AUTH_EXEMPT_EXACT or _AUTH_EXEMPT_PREFIX.
@app.delete("/api/v1/agents/{agent_id}/runs")
def clear_agent_runs(agent_id: str):
    """Nút «Xoá log» trên tab Hoạt động: dọn sạch sổ lượt chạy của MỘT agent.

    Chỉ đụng entry mang agent_id này — file ngày là sổ chung của mọi agent."""
    from tubecli.core.agent import agent_manager
    from tubecli.core import run_log

    if not agent_manager.get(agent_id):
        raise HTTPException(404, f"Agent {agent_id} not found")
    removed = run_log.clear_for_agent(agent_id)
    return {"success": True, "removed": removed}


@app.get("/api/v1/agents/{agent_id}/runs")
def get_agent_runs(agent_id: str, days: int = 14, limit: int = 100):
    """What this agent's runs actually did — including the ones that never ran."""
    from tubecli.core.agent import agent_manager
    from tubecli.core import run_log

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    entries = run_log.list_for_agent(agent_id, days=days, limit=limit)

    # Đính DIỄN BIẾN phiên (run_trail ghi từ node) vào từng lượt — best effort,
    # thiếu file là chuyện thường (lượt cũ trước tính năng, lượt chết sớm).
    try:
        from tubecli.config import ext_data_path
        _tr_dir = ext_data_path("browser") / "session_actions"
        import json as _json
        for _e in entries:
            _rid = str(_e.get("run_id") or "")
            if not _rid:
                continue
            _f = _tr_dir / f"{_rid}.json"
            if _f.exists():
                try:
                    _acts = _json.loads(_f.read_text(encoding="utf-8", errors="replace"))
                    if isinstance(_acts, list):
                        _e["actions"] = _acts[:120]
                except Exception:
                    pass
    except Exception as _te:
        print(f"[Runs] trail attach skipped: {_te}")
    # "Đang làm gì lúc này" cho lượt CÒN sống: đọc đuôi log của nó ra hành động +
    # trang hiện tại, để mặt node/bảng thay chữ trơ "Đang chạy" bằng "Đang đọc ·
    # Gmail". Chỉ làm cho lượt live ĐẦU TIÊN (mới nhất) — một lần đọc file/poll,
    # không quét cả lịch sử. Best-effort tuyệt đối: hỏng thì entry thiếu 'live',
    # bảng vẫn hiện "Đang chạy" như cũ.
    try:
        from tubecli.extensions.browser.process_manager import browser_process_manager
        for e in entries:
            if e.get("type") != "run" or e.get("outcome") not in ("running", "starting"):
                continue
            log_file = (e.get("launch") or {}).get("log_file")
            live = browser_process_manager.read_live_action(log_file) if log_file else None
            if live:
                e["live"] = live
            break
    except Exception:
        pass   # best-effort: thiếu 'live' thì bảng vẫn hiện "Đang chạy" như cũ

    return {
        "agent_id": agent_id,
        "scheduled": bool(getattr(agent, "schedule_enabled", False)),
        "next_run": getattr(agent, "schedule_next_run", None),
        "runs_today": getattr(agent, "schedule_runs_today", 0),
        "max_runs": getattr(agent, "schedule_max_runs", 0),
        "entries": entries,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Scraped corpus
#
# Everything the browser agents collected, queryable. Until now it could only
# be reached one agent at a time, metadata-only, unsorted and unsearchable —
# the bodies were on disk with no way to ask for them.
#
# All of these are `def`, not `async def`: they read JSON files, and Starlette
# runs a sync endpoint in the threadpool rather than blocking the event loop.
# None of the paths appear in _AUTH_EXEMPT_EXACT/_PREFIX, so they inherit the
# login gate — this is scraped page content, not public data.
# ═══════════════════════════════════════════════════════════════════════════

def _agent_scope(agent_id: Optional[str]):
    """(agent_id, allowed_profiles) for an optional agent filter."""
    if not agent_id:
        return None, ()
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return agent_id, (getattr(agent, "allowed_profiles", []) or [])


@app.get("/api/v1/scraped/profiles")
def scraped_profiles():
    """Which profiles hold scraped data, and how much."""
    from tubecli.core import scraped_store

    out = []
    for name in scraped_store.profiles():
        hist = scraped_store.raw_history(name)
        arts = scraped_store.raw_articles(name)
        out.append({
            "profile": name,
            "history_entries": len(hist),
            "articles_with_body": len(arts),
        })
    return {"root": str(scraped_store.data_root()), "profiles": out}


@app.get("/api/v1/scraped/articles")
def scraped_articles(
    agent_id: Optional[str] = None,
    profile: Optional[str] = None,
    q: str = "",
    domain: str = "",
    day: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    with_content: bool = False,
    only_with_content: bool = True,
    limit: int = 50,
    offset: int = 0,
    order: str = "desc",
):
    """Search the corpus.

    Returns only pages that HAVE text. A history row is written for every page
    the browser opened, and most are search results, skip-listed domains, or
    pages a run died on before extraction — 46 of 49 on a real corpus. Pass
    `only_with_content=false` to see the visits too.

    `day`/`since`/`until` take YYYY-MM-DD or the words today/yesterday, and are
    read as LOCAL calendar days — the stored stamps are UTC, so a substring
    match on the date would lose part of every local day.
    `profile` may be comma-separated; unknown names are dropped rather than
    joined into a path.
    """
    from tubecli.core import scraped_store

    aid, allowed = _agent_scope(agent_id)
    profs = [p.strip() for p in profile.split(",") if p.strip()] if profile else None
    return scraped_store.query(
        agent_id=aid, allowed_profiles=allowed, profile=profs, q=q, domain=domain,
        day=day, since=since, until=until, with_content=with_content,
        only_with_content=only_with_content, limit=limit, offset=offset, order=order,
    )


@app.get("/api/v1/scraped/article")
def scraped_article(url: str, profile: Optional[str] = None, agent_id: Optional[str] = None):
    """One article with its full body.

    404 here can mean two different things and they are worth telling apart:
    the URL was never scraped, or it was and the body has since rotated out of
    articles.json (which keeps 100 while history keeps 500).
    """
    from tubecli.core import scraped_store

    aid, allowed = _agent_scope(agent_id)
    rec = scraped_store.get_article(url, profile=profile, allowed_profiles=allowed)
    if not rec:
        raise HTTPException(404, f"Nothing scraped for {url}")
    if not rec.get("has_content"):
        raise HTTPException(
            410,
            f"Đã cào '{rec.get('title') or url}' lúc {rec.get('scraped_at_local') or '?'} "
            f"nhưng phần nội dung đã bị xoay vòng khỏi articles.json "
            f"(giữ tối đa {scraped_store.ARTICLE_CAP} bài/profile). Cào lại để lấy nội dung.",
        )
    return rec


@app.get("/api/v1/scraped/stats")
def scraped_stats(agent_id: Optional[str] = None, profile: Optional[str] = None, days: int = 14):
    """Totals by profile, domain, agent and local day."""
    from tubecli.core import scraped_store

    aid, allowed = _agent_scope(agent_id)
    profs = [p.strip() for p in profile.split(",") if p.strip()] if profile else None
    return scraped_store.stats(agent_id=aid, allowed_profiles=allowed, profile=profs, days=days)


@app.get("/api/v1/scraped/export")
def scraped_export(
    fmt: str = "json",
    agent_id: Optional[str] = None,
    profile: Optional[str] = None,
    q: str = "",
    domain: str = "",
    day: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 200,
    download: bool = True,
):
    """The same query, serialised as json / jsonl / csv / md / txt."""
    from fastapi.responses import Response
    from tubecli.core import scraped_store

    aid, allowed = _agent_scope(agent_id)
    profs = [p.strip() for p in profile.split(",") if p.strip()] if profile else None
    # Exports carry bodies, so a row without one is an empty record in a
    # spreadsheet. Only harvested pages are written out.
    result = scraped_store.query(
        agent_id=aid, allowed_profiles=allowed, profile=profs, q=q, domain=domain,
        day=day, since=since, until=until, with_content=True,
        only_with_content=True, limit=limit,
    )
    try:
        body, media, filename = scraped_store.export(result["items"], fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))

    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=body, media_type=media, headers=headers)


@app.get("/api/v1/scraped/image")
def scraped_image(profile: str, path: str):
    """Serve an image the scraper downloaded alongside an article.

    `path` is taken from a record's images[].localPath, which is absolute and
    therefore has to be proven to sit inside this profile's folder before it is
    opened. image_path() returns None for anything that escapes.
    """
    from fastapi.responses import FileResponse
    from tubecli.core import scraped_store

    resolved = scraped_store.image_path(path, profile=profile)
    if not resolved:
        raise HTTPException(404, "Image not found in this profile")
    guessed = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return FileResponse(str(resolved), media_type=guessed)


@app.get("/api/v1/agents/{agent_id}/scraped")
def agent_scraped(
    agent_id: str,
    q: str = "",
    day: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    with_content: bool = False,
    only_with_content: bool = True,
    limit: int = 50,
    offset: int = 0,
):
    """This agent's own corpus. Same store, scope fixed to the agent.

    Pages with no harvested text are excluded by default; the History tab is
    where visits belong, and /api/v1/agents/{id}/history still returns them.
    """
    from tubecli.core import scraped_store

    aid, allowed = _agent_scope(agent_id)
    return scraped_store.query(
        agent_id=aid, allowed_profiles=allowed, q=q, day=day, since=since, until=until,
        with_content=with_content, only_with_content=only_with_content,
        limit=limit, offset=offset,
    )


@app.get("/api/v1/agents/{agent_id}/scraped-guide")
def agent_scraped_guide(agent_id: str, request: Request, lang: Optional[str] = None):
    """A brief another AI can be handed to fetch this agent's scraped articles.

    The base URL is taken from the request itself, so the brief names the
    address the user actually reached this dashboard on — an IP typed into a
    phone, a hostname behind a tunnel — rather than a localhost that means
    nothing on the machine the brief gets pasted into.

    It never contains the password. That credential opens the whole dashboard,
    and this document exists to be pasted into someone else's chat window; the
    user hands it over separately, or not at all when the consumer runs on this
    box and the loopback exemption applies.
    """
    from tubecli.core import scraped_query, scraped_store
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    if not lang:
        try:
            from tubecli.config import get_language
            lang = (get_language() or "vi").strip()
        except Exception:
            lang = "vi"
    lang = "vi" if str(lang).startswith("vi") else "en"

    from tubecli.core import auth

    allowed = getattr(agent, "allowed_profiles", []) or []
    text = scraped_query.build_guide(
        base_url=str(request.base_url),
        agent_id=agent_id,
        agent_name=getattr(agent, "name", "") or "",
        profiles_list=scraped_store.resolve_profiles(allowed),
        lang=lang,
        read_key=auth.scraped_read_token(),
    )
    return {"agent_id": agent_id, "base_url": str(request.base_url).rstrip("/"),
            "lang": lang, "text": text}


@app.post("/api/v1/scraped/read-key/rotate")
def rotate_scraped_read_key():
    """Mint a new read key; every brief already handed out stops working.

    Deliberately POST, so the key it returns can never be reached by the read
    key itself — that gate is GET-only, and a key able to replace itself would
    be a privilege the whole design is trying not to grant.
    """
    from tubecli.core import auth

    return {"ok": True, "token": auth.rotate_scraped_read_token()}


@app.get("/api/v1/agents/{agent_id}/scraped-article")
async def get_scraped_article_detail(agent_id: str, profile: str, url: str):
    from tubecli.core.agent import agent_manager
    from pathlib import Path
    import json
    
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
        
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []
    if profile not in allowed_profiles:
        raise HTTPException(403, f"Profile {profile} is not associated with this agent")

    from tubecli.core import scraped_store

    for a in scraped_store.raw_articles(profile):
        if a.get("url") == url:
            return a

    raise HTTPException(404, f"Article not found in profile {profile}")


@app.post("/api/v1/agents/{agent_id}/rewrite-article")
async def rewrite_scraped_article(agent_id: str, profile: str, url: str):
    from tubecli.core.agent import agent_manager
    from tubecli.core.brain import AgentBrain
    from pathlib import Path
    import json
    
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
        
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []
    if profile not in allowed_profiles:
        raise HTTPException(403, f"Profile {profile} is not associated with this agent")
        
    from tubecli.core import scraped_store

    article = next((a for a in scraped_store.raw_articles(profile) if a.get("url") == url), None)

    if not article:
        raise HTTPException(404, f"Article not found in profile {profile}")
        
    title = article.get("title", "Untitled")
    content = article.get("content", "")
    if not content:
        raise HTTPException(400, "Bài viết này không có nội dung văn bản để viết lại.")
        
    agent_language = getattr(agent, "language", "auto") or "auto"
    _LANGUAGE_NAMES = {
        "auto": "Vietnamese",
        "vi": "Vietnamese",
        "en": "English",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "es": "Spanish",
        "tr": "Turkish",
        "ru": "Russian",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ar": "Arabic",
        "th": "Thai",
        "id": "Indonesian",
    }
    lang_name = _LANGUAGE_NAMES.get(agent_language, "Vietnamese")
    
    system_prompt = f"You are a content editor. Your job is to rewrite a scraped article into a new, high-quality, coherent and engaging article written in {lang_name}."
    
    user_prompt = f"""Here is the source article:

Title: {title}
Content:
{content[:5000]}

Requirements:
1. Write a completely new article based on this source.
2. It must have an engaging title, a strong opening, clearly separated sections with subheadings, and a conclusion that draws the information together.
3. Do not copy verbatim — rewrite it in your own voice, creatively and logically.
4. Format the article as Markdown.
5. Write the article in {lang_name}.

Return only the Markdown article — no preamble from you."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        raw_response = AgentBrain._call_llm(agent.to_dict(), messages, temperature=0.7)
        return {"status": "success", "content": raw_response}
    except Exception as e:
        raise HTTPException(500, f"Lỗi khi gọi AI viết lại bài: {str(e)}")


class GenerateContentRequest(BaseModel):
    selected_urls: Optional[List[str]] = []
    max_length: Optional[int] = 2000

@app.post("/api/v1/agents/{agent_id}/generate-content-from-today")
async def generate_content_from_today(agent_id: str, req: Optional[GenerateContentRequest] = None):
    from tubecli.core.agent import agent_manager
    from tubecli.core.brain import AgentBrain
    import json
    from pathlib import Path
    from datetime import datetime
    
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
        
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []

    # "Hôm nay" used to be `datetime.now().strftime("%Y-%m-%d") in scrapedAt` —
    # a substring test against a UTC stamp. In UTC+7 that silently discards
    # everything scraped after 17:00 local (already tomorrow in UTC) and
    # everything before 07:00 (still yesterday), so the button reported "chưa
    # cào được gì" on days with a full evening of articles. The store converts
    # the local day to real UTC bounds instead.
    from tubecli.core import scraped_store

    found = scraped_store.query(
        agent_id=agent_id, allowed_profiles=allowed_profiles, day="today",
        with_content=True, only_with_content=True, limit=100,
    )
    # Already newest-first from the store, and shaped back into the camelCase
    # keys the prompt builder below reads.
    today_articles = [
        {"title": a["title"], "url": a["url"], "content": a.get("content", ""),
         "author": a.get("author", ""), "description": a.get("description", ""),
         "images": a.get("images", []), "scrapedAt": a["scraped_at"], "_profile": a["profile"]}
        for a in found["items"]
    ]

    if not today_articles:
        raise HTTPException(400, "Không tìm thấy nội dung nào được cào (scraped) trong ngày hôm nay. Hãy chạy agent đi cào dữ liệu trước.")

    selected_urls = req.selected_urls if req else []
    max_length = req.max_length if (req and req.max_length) else 2000
    
    if selected_urls:
        selected_articles = [a for a in today_articles if a.get("url") in selected_urls]
        if not selected_articles:
            selected_articles = today_articles[:3]
    else:
        selected_articles = today_articles[:3]
    
    context_text = ""
    for idx, art in enumerate(selected_articles, 1):
        title = art.get("title", "Untitled")
        url = art.get("url", "")
        content = art.get("content", "")
        content_snippet = content[:2000]
        context_text += f"Bài viết {idx}:\nTiêu đề: {title}\nĐường dẫn: {url}\nNội dung:\n{content_snippet}\n---\n\n"
        
    agent_language = getattr(agent, "language", "auto") or "auto"
    _LANGUAGE_NAMES = {
        "auto": "Vietnamese",
        "vi": "Vietnamese",
        "en": "English",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "es": "Spanish",
        "tr": "Turkish",
        "ru": "Russian",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ar": "Arabic",
        "th": "Thai",
        "id": "Indonesian",
    }
    lang_name = _LANGUAGE_NAMES.get(agent_language, "Vietnamese")
    
    system_prompt = f"You are a content editor. Your job is to synthesise the information and articles scraped during the day into a new, high-quality, coherent and engaging round-up article written in {lang_name}."
    
    user_prompt = f"""Here is everything collected today:

{context_text}

Requirements:
1. Write a new round-up article based on the material above.
2. It must have an engaging title, a strong opening, clearly separated sections with subheadings, and a conclusion that draws the information together.
3. Do not copy verbatim — synthesise, analyse, edit and connect the pieces logically.
4. Format the article as Markdown.
5. Write the article in {lang_name}.
6. Length: roughly {max_length} characters.

Return only the Markdown article — no preamble from you."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        raw_response = AgentBrain._call_llm(agent.to_dict(), messages, temperature=0.7)
        return {"status": "success", "content": raw_response}
    except Exception as e:
        raise HTTPException(500, f"Lỗi khi gọi AI tổng hợp bài viết: {str(e)}")




# ── Agent Chat ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


# ── AI Proxy Endpoint for Browser Extension ──
@app.post("/api/v1/localai/chat/completions")
async def localai_chat_completions(req: Request):
    """
    Proxy endpoint used by browser extension (ai_engine.js).

    The request names the model when the caller resolved one (open.js is given
    the agent's resolved browser AI on argv); otherwise resolve_browser_ai()
    supplies it. The provider is then inferred from the model name.
    """
    import requests as _requests

    data = await req.json()
    messages = data.get("messages", [])

    # Whose model? The caller's, when it names one. open.js is handed the model
    # Python already resolved for that agent — and this proxy used to throw it
    # away and use the global default for everybody, which is why an agent's own
    # browser AI could never take effect. A caller that names nothing still gets
    # the chain: default browser AI -> default AI -> last resort.
    import os as _os, json as _json
    from tubecli.config import DATA_DIR, resolve_browser_ai
    model = resolve_browser_ai(str(data.get("model") or "").strip())["model"]
    lower_model = model.lower()

    # Load cloud API keys
    cloud_keys_file = _os.path.join(str(DATA_DIR), "cloud_api_keys.json")
    cloud_keys = {}
    if _os.path.exists(cloud_keys_file):
        try:
            with open(cloud_keys_file, "r", encoding="utf-8") as f:
                cloud_keys = _json.load(f)
        except Exception:
            pass

    # Check if 9router is running and query its models list
    nr_running = False
    nr_models = []
    try:
        nr_key = ""
        if "9router" in cloud_keys:
            val = cloud_keys["9router"]
            if isinstance(val, str) and val:
                nr_key = val
            elif isinstance(val, dict):
                for label, info in val.items():
                    if isinstance(info, dict) and info.get("active", True):
                        nr_key = info.get("key", "") or info.get("api_key", "")
                        if nr_key:
                            break
        headers = {}
        if nr_key:
            headers["Authorization"] = f"Bearer {nr_key}"
        resp = _requests.get("http://localhost:20128/v1/models", headers=headers, timeout=0.5)
        if resp.status_code == 200:
            nr_running = True
            data = resp.json()
            if isinstance(data, dict) and "data" in data:
                nr_models = [m.get("id", m.get("name", "")) for m in data["data"] if isinstance(m, dict)]
    except Exception:
        pass

    # Determine provider from model name and 9router running state
    provider = "ollama"
    if "9router" in lower_model or "antigravity" in lower_model or "cx/" in lower_model:
        provider = "9router"
    elif "/" in lower_model:
        # Models with slashes like 'deepseek/deepseek-r1' are 9Router/OpenRouter models
        provider = "9router"
    elif nr_running and (model in nr_models or lower_model in [m.lower() for m in nr_models]):
        provider = "9router"
    elif "gemini" in lower_model:
        provider = "gemini"
    elif "gpt" in lower_model or "o1" in lower_model or "o3" in lower_model:
        provider = "chatgpt"
    elif "claude" in lower_model:
        provider = "claude"
    elif "deepseek" in lower_model:
        provider = "deepseek"
    elif "grok" in lower_model:
        provider = "grok"
    else:
        # Fallback to 9router if it's running on port 20128, otherwise ollama
        if nr_running:
            provider = "9router"
        else:
            provider = "ollama"

    # Get first active API key for selected provider
    api_key = ""
    if provider in cloud_keys:
        val = cloud_keys[provider]
        if isinstance(val, str) and val:
            # Legacy plain-string key format
            api_key = val
        elif isinstance(val, dict):
            for label, info in val.items():
                if isinstance(info, dict) and info.get("active", True):
                    api_key = info.get("key", "") or info.get("api_key", "")
                    if api_key:
                        break

    print(f"[AI Proxy] provider={provider} model={model} has_key={bool(api_key)}")

    response_content = ""
    try:
        if provider == "deepseek":
            if not api_key:
                raise Exception("No API key for Deepseek")
            resp = _requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "stream": False},
                timeout=180,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                raise Exception(f"Deepseek {resp.status_code}: {resp.text[:300]}")

        elif provider == "gemini":
            if not api_key:
                raise Exception("No API key for Gemini")
            model_name = model if "gemini" in model else "gemini-2.0-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            contents = []
            for msg in messages:
                role = "user" if msg["role"] in ("user", "system") else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
            resp = _requests.post(url, json={"contents": contents}, timeout=120)
            if resp.status_code == 200:
                response_content = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            else:
                raise Exception(f"Gemini {resp.status_code}: {resp.text[:300]}")

        elif provider == "chatgpt":
            if not api_key:
                raise Exception("No API key for OpenAI")
            resp = _requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model or "gpt-4o-mini", "messages": messages, "temperature": 0.5},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"OpenAI {resp.status_code}: {resp.text[:300]}")

        elif provider == "claude":
            if not api_key:
                raise Exception("No API key for Claude")
            system_text = ""
            chat_msgs = []
            for msg in messages:
                if msg["role"] == "system":
                    system_text = msg["content"]
                else:
                    chat_msgs.append(msg)
            payload = {"model": model or "claude-sonnet-4-20250514", "max_tokens": 4096, "messages": chat_msgs}
            if system_text:
                payload["system"] = system_text
            resp = _requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"},
                json=payload, timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("content", [{}])[0].get("text", "")
            else:
                raise Exception(f"Claude {resp.status_code}: {resp.text[:300]}")

        elif provider == "grok":
            if not api_key:
                raise Exception("No API key for Grok")
            resp = _requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model or "grok-3", "messages": messages, "temperature": 0.5},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"Grok {resp.status_code}: {resp.text[:300]}")

        elif provider == "9router":
            # 9Router local proxy (OpenAI compatible on port 20128)
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = _requests.post(
                "http://localhost:20128/v1/chat/completions",
                headers=headers,
                json={"model": model or "qwen2.5:7b", "messages": messages, "temperature": 0.5},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"9Router {resp.status_code}: {resp.text[:300]}")

        else:
            # Ollama (local)
            from tubecli.config import OLLAMA_BASE_URL
            resp = _requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("message", {}).get("content", "")
            else:
                raise Exception(f"Ollama {resp.status_code}: {resp.text[:300]}")

    except Exception as e:
        print(f"[AI Proxy] Error: {e}")
        response_content = f"Error: {e}"

    # Return OpenAI-compatible JSON for ai_engine.js
    return {
        "id": "chatcmpl-proxy",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_content},
                "finish_reason": "stop"
            }
        ]
    }


@app.post("/api/v1/localai/generate")
async def localai_generate(req: Request):
    """
    Proxy endpoint for Ollama-style text generation (/api/generate).
    Used by browser extension (ai_engine.js) as fallback.
    Converts to chat/completions format internally.
    """
    data = await req.json()
    prompt = data.get("prompt", "")
    model = data.get("model", "")

    from tubecli.config import resolve_browser_ai
    model = resolve_browser_ai(model)["model"]

    # Reuse the chat/completions logic by constructing a chat request
    from starlette.requests import Request as _Request
    from starlette.datastructures import Headers as _Headers
    import json as _json

    chat_body = _json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
    }).encode()

    # Create a sub-request to reuse localai_chat_completions
    scope = req.scope.copy()
    scope["body"] = chat_body

    class FakeRequest:
        async def json(self_inner):
            return {"messages": [{"role": "user", "content": prompt}], "model": model}

    result = await localai_chat_completions(FakeRequest())

    # Convert chat format to generate format
    response_text = ""
    if isinstance(result, dict):
        choices = result.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")

    return {
        "model": model,
        "response": response_text,
        "done": True,
    }


@app.post("/api/v1/agents/{agent_id}/chat")
async def agent_chat(agent_id: str, req: ChatRequest):
    """Chat with an agent. The brain dispatches skills automatically."""
    import datetime as _dt
    from tubecli.core.agent import agent_manager
    from tubecli.core.skill import skill_manager
    from tubecli.core.brain import AgentBrain

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    agent_dict = agent.to_dict()

    # Get agent's allowed skills
    all_skills = skill_manager.get_all()
    if agent.allowed_skills:
        skills = [s.to_dict() for s in all_skills if s.id in agent.allowed_skills]
    else:
        skills = [s.to_dict() for s in all_skills]  # allow all if not restricted

    # Call brain
    brain_result = AgentBrain.chat(
        message=req.message,
        agent=agent_dict,
        skills=skills,
        history=agent.history_log or [],
    )

    reply = brain_result["reply"]
    skill_used = None

    # ── Handle Brain Result ──
    action = brain_result.get("action")
    
    if action == "run_skill" and brain_result.get("skill_id"):
        skill_id = brain_result["skill_id"]
        skill = skill_manager.get(skill_id)
        if skill:
            skill_used = skill.name
            skill_input = brain_result.get("skill_input", req.message)
            
            # Feature: Random Browser Profile Selection
            # If input mentions "random profile" or "ngẫu nhiên", and it's a browser skill
            if any(x in skill_input.lower() for x in ["ngẫu nhiên", "random profile", "mở profile"]):
                from tubecli.core.config import config_manager
                profiles = config_manager.get_browser_profiles()
                if profiles:
                    import random
                    chosen = random.choice(profiles)
                    skill_input += f"\n(AI Note: Randomly selected browser profile: {chosen})"
            
            try:
                # Call the Autonomous ReAct Loop
                skill_dict = skill.to_dict()
                final_answer = await AgentBrain.autonomous_run(
                    message=skill_input,
                    agent=agent_dict,
                    skill=skill_dict
                )
                reply = final_answer
                skill_manager.update(skill_id, last_run=_dt.datetime.now().isoformat())
            except Exception as e:
                from tubecli.i18n import t
                reply = t("brain.skill_run_error", name=skill.name, error=str(e))
        else:
            from tubecli.i18n import t
            reply = t("brain.skill_not_found", id=skill_id)

    elif action == "create_skill":
        # Feature: AI Self-Creation via Workflow Builder
        # 1. Generate real executable workflow from the user's request
        # 2. Run it immediately to handle the current request
        # 3. Save as a reusable skill for future similar requests
        from tubecli.core.ai_workflow_builder import generate_workflow
        from tubecli.core.workflow_engine import WorkflowEngine
        from tubecli.nodes.registry import (NodePolicy, NodePolicyError,
                                            create_node_from_dict)

        action_data_raw = brain_result.get("_raw_action", {})
        skill_name = action_data_raw.get("name") or brain_result.get("skill_name", "New Skill")
        skill_desc = action_data_raw.get("description") or brain_result.get("skill_desc", "")
        skill_instructions = action_data_raw.get("instructions") or brain_result.get("skill_instructions", [])

        # Determine provider/model from agent config
        wf_provider = agent_dict.get("provider", "ollama")
        wf_model = agent_dict.get("model", "") or agent_dict.get("chatbot_model", "")
        wf_api_key = agent_dict.get("api_key", "")
        if not wf_provider or wf_provider == "local":
            wf_provider = "ollama"

        wf_data = None
        wf_result = None
        wf_blocked = ""      # loại node bị chính sách từ chối, để nói thật với người dùng
        try:
            # Build enriched prompt: original request + instructions hint
            gen_prompt = req.message
            if skill_instructions:
                gen_prompt += "\n\nHints: " + "; ".join(skill_instructions)

            # Generate the workflow
            wf_data = generate_workflow(
                prompt=gen_prompt,
                provider=wf_provider,
                model=wf_model,
                api_key=wf_api_key or "__CLOUD_API__",
            )

            # Run the workflow immediately for the user's current request
            nodes_data = wf_data.get("nodes", [])
            connections = wf_data.get("connections", [])
            if nodes_data:
                # Inject user message into first text_input node
                for nd in nodes_data:
                    if nd.get("type") in ("text_input", "manual_input"):
                        nd.setdefault("config", {})["text"] = req.message
                        break

                # generate_workflow() output is the model's own JSON, three lines
                # old. Nothing about the owner asking for a skill turns it into
                # the owner's choice of node, so it runs under the model allowlist.
                wf_nodes = [create_node_from_dict(
                    nd, policy=NodePolicy.model("api.chat.create_skill"))
                    for nd in nodes_data]
                engine = WorkflowEngine(nodes=wf_nodes, connections=connections)
                wf_result = await engine.run()

        except NodePolicyError as pol_err:
            # KHÔNG nuốt. ai_workflow_builder dạy model dùng google_auth +
            # google_sheets + python_code + output, mà chính sách "model" từ
            # chối đúng những loại đó — nên phần lớn workflow AI sinh ra đều
            # dừng ở đây. Nuốt lỗi thì `wf_result` = None, luồng rơi xuống
            # nhánh else và người dùng đọc "✅ Đã tạo skill" cho một việc CHƯA
            # từng chạy. Skill vẫn được lưu (mang dấu "model") để chủ mở canvas
            # xem và bấm Run — ở đó chủ là người quyết, nên quyền là của chủ.
            wf_blocked = str(pol_err)
            print(f"[AutoSkill] Workflow refused by node policy: {pol_err}")

        except Exception as wf_err:
            print(f"[AutoSkill] Workflow generate/run failed: {wf_err}")

        # Derive trigger commands from skill name + instructions
        trigger_cmds = [skill_name.lower()]
        for instr in (skill_instructions or []):
            words = [w.lower() for w in instr.split() if len(w) > 3]
            if words:
                trigger_cmds.append(" ".join(words[:3]))
        trigger_cmds = list(set(trigger_cmds))[:5]

        # Save as skill (create or update)
        try:
            existing_skill = skill_manager.find_by_name(skill_name)
            if existing_skill and wf_data:
                skill_manager.update(
                    existing_skill.id,
                    workflow_data=wf_data,
                    description=skill_desc or f"AI-generated: {skill_name}",
                    commands=trigger_cmds,
                    # Model viết workflow này, nên nó không bao giờ được chạy
                    # với quyền chủ khi một agent kích hoạt lại sau này
                    # (brain.run_workflow_linear đọc dấu này). Cả nhánh update:
                    # ghi đè workflow của một skill trùng tên = đưa node của
                    # model vào chỗ node của người, dấu phải đi theo nội dung.
                    authored_by="model",
                )
                new_skill = existing_skill
            else:
                new_skill = skill_manager.create(
                    name=skill_name,
                    description=skill_desc or f"AI-generated workflow skill: {skill_name}",
                    skill_type="AI Workflow",
                    workflow_data=wf_data or {
                        "sop": "\n".join(skill_instructions or []),
                        "nodes": []
                    },
                    commands=trigger_cmds,
                    authored_by="model",
                )
            skill_used = f"Created Skill: {skill_name}"

            # Build reply from workflow result or confirmation message
            if wf_result and wf_result.get("status") == "completed":
                # Extract output from last node
                node_results = wf_result.get("node_results", {})
                output_texts = []
                for nid, nr in node_results.items():
                    if isinstance(nr, dict):
                        for key in ("result", "response", "stdout", "rows", "output"):
                            if nr.get(key):
                                output_texts.append(str(nr[key])[:500])
                                break
                    elif nr:
                        output_texts.append(str(nr)[:500])
                if output_texts:
                    reply = "\n".join(output_texts)
                    reply += f"\n\n✅ *Đã lưu thành skill '{skill_name}'* — lần sau hỏi tương tự sẽ dùng ngay."
                else:
                    reply = f"✅ Đã tạo và chạy workflow cho '{skill_name}'.\nĐã lưu thành skill để dùng lại."
            elif wf_blocked:
                # Nói thẳng: đã lưu, CHƯA chạy, và vì sao.
                reply = (
                    f"✅ Đã tạo skill **{skill_name}** — nhưng mình CHƯA chạy nó lần này.\n"
                    f"📝 {skill_desc}\n"
                    f"🔑 Triggers: `{'`, `'.join(trigger_cmds)}`\n\n"
                    f"⚠️ Workflow do AI dựng có loại node mà AI không được phép tự dựng:\n"
                    f"{wf_blocked}\n\n"
                    f"Mở **{skill_name}** trên canvas Workflow, xem lại từng node rồi bấm Run ở đó — "
                    f"bạn bấm thì bạn là người quyết nên nó chạy đủ quyền. Bấm Lưu từ canvas cũng "
                    f"đánh dấu skill này là do bạn dựng, và từ đó agent chạy lại được."
                )
            else:
                reply = (
                    f"✅ Đã tạo skill **{skill_name}**\n"
                    f"📝 {skill_desc}\n"
                    f"🔑 Triggers: `{'`, `'.join(trigger_cmds)}`\n\n"
                    f"Lần sau hỏi tương tự AI sẽ chạy skill này ngay lập tức."
                )

        except Exception as e:
            from tubecli.i18n import t
            reply = t("brain.skill_create_error", error=str(e))

    # Save to history
    history = agent.history_log or []
    history.append({"role": "user", "content": req.message, "timestamp": _dt.datetime.now().isoformat()})
    history.append({"role": "assistant", "content": reply, "timestamp": _dt.datetime.now().isoformat(),
                     "skill_used": skill_used})

    # Keep history manageable (last 50 messages)
    if len(history) > 50:
        history = history[-50:]

    agent_manager.update(agent_id, history_log=history)

    # ── Background Memory Update (non-blocking) ──
    import asyncio
    async def _bg_memory_update():
        try:
            from tubecli.core.brain import AgentBrain
            AgentBrain.post_chat_memory_update(agent_id, agent_dict, history)
            # If history was marked summarized, save it back
            agent_manager.update(agent_id, history_log=history)
        except Exception as e:
            print(f"[Memory] Background update error: {e}")
    asyncio.create_task(_bg_memory_update())

    return {
        "reply": reply,
        "skill_used": skill_used,
        "history": history[-20:],  # return last 20 for UI
    }


@app.delete("/api/v1/agents/{agent_id}/chat")
async def clear_chat_history(agent_id: str):
    """Clear an agent's chat history."""
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    agent_manager.update(agent_id, history_log=[])
    return {"status": "cleared", "agent_id": agent_id}


# ── Agent Memory API ─────────────────────────────────────────────

@app.get("/api/v1/agents/{agent_id}/memory")
async def get_agent_memory(agent_id: str):
    """Get full memory overview for an agent (sessions + knowledge)."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import AgentMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return AgentMemory.get_full_memory(agent_id)


@app.delete("/api/v1/agents/{agent_id}/memory")
async def clear_agent_memory(agent_id: str):
    """Clear all memory for an agent (sessions + knowledge)."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import AgentMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    AgentMemory.clear_all(agent_id)
    return {"status": "cleared", "agent_id": agent_id}


@app.get("/api/v1/agents/{agent_id}/memory/sessions")
async def get_agent_sessions(agent_id: str):
    """Get session summaries for an agent."""
    from tubecli.core.memory import SessionMemory
    sessions = SessionMemory.get_recent_sessions(agent_id, limit=20)
    return {"agent_id": agent_id, "sessions": sessions, "count": len(sessions)}


@app.get("/api/v1/agents/{agent_id}/memory/knowledge")
async def get_agent_knowledge(agent_id: str):
    """Get knowledge facts for an agent."""
    from tubecli.core.memory import KnowledgeMemory
    facts = KnowledgeMemory.get_knowledge(agent_id)
    return {"agent_id": agent_id, "knowledge": facts, "count": len(facts)}


class AddFactRequest(BaseModel):
    fact: str
    category: str = "technical"
    importance: str = "medium"


@app.post("/api/v1/agents/{agent_id}/memory/knowledge")
async def add_agent_fact(agent_id: str, req: AddFactRequest):
    """Manually add a knowledge fact for an agent."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import KnowledgeMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    KnowledgeMemory.add_fact(agent_id, req.fact, req.category, req.importance)
    return {"status": "added", "agent_id": agent_id, "fact": req.fact}


# ── Team Memory API ──────────────────────────────────────────────

@app.get("/api/v1/teams/{team_id}/memory")
async def get_team_memory(team_id: str):
    """Get team shared memory (briefings + knowledge)."""
    from tubecli.core.memory import TeamMemory
    return {
        "team_id": team_id,
        "briefings": TeamMemory.get_briefings(team_id, limit=10),
        "knowledge": TeamMemory.get_team_knowledge(team_id),
    }


class TeamBriefingRequest(BaseModel):
    briefing: str
    context: Dict = {}


@app.post("/api/v1/teams/{team_id}/memory/briefing")
async def add_team_briefing(team_id: str, req: TeamBriefingRequest):
    """Add a task briefing for a team."""
    from tubecli.core.memory import TeamMemory
    TeamMemory.save_briefing(team_id, req.briefing, req.context)
    return {"status": "added", "team_id": team_id}


@app.delete("/api/v1/teams/{team_id}/memory")
async def clear_team_memory(team_id: str):
    """Clear all team memory."""
    from tubecli.core.memory import TeamMemory
    TeamMemory.clear(team_id)
    return {"status": "cleared", "team_id": team_id}


# ── Skills ───────────────────────────────────────────────────────

@app.get("/api/v1/skills")
async def list_skills():
    from tubecli.core.skill import skill_manager
    skills = skill_manager.get_all()
    return {"skills": [s.to_dict() for s in skills], "count": len(skills)}

@app.get("/api/v1/skills/{skill_id}")
async def get_skill(skill_id: str):
    from tubecli.core.skill import skill_manager
    skill = skill_manager.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return skill.to_dict()

@app.post("/api/v1/skills")
async def create_skill(req: SkillCreateRequest, request: Request):
    from tubecli.core.skill import skill_manager
    data = req.model_dump()
    # Drop unset optional fields so Skill defaults apply
    data = {k: v for k, v in data.items() if v is not None}
    commands = data.get("commands") or []
    trigger = data.pop("trigger", "")
    if trigger and not commands:
        commands = [c.strip() for c in trigger.split(",") if c.strip()]
    data["commands"] = commands
    # Nguồn gốc do MÁY CHỦ quyết, không do body: một agent gọi route này (header
    # X-TubeCLI-Agent, phiên guest…) cất được skill vào kho, nhưng skill đó mang
    # dấu "model" nên brain.run_workflow_linear không bao giờ chạy nó với quyền
    # chủ. Đây là cửa duy nhất còn lại để đưa node vào kho sau khi skills.json
    # bị chặn khỏi sandbox AI.
    data["authored_by"] = _skill_author_for_request(request)
    skill = skill_manager.create(**data)
    return {"status": "created", "skill": skill.to_dict()}

@app.put("/api/v1/skills/{skill_id}")
async def update_skill_endpoint(skill_id: str, req: SkillCreateRequest, request: Request):
    from tubecli.core.skill import skill_manager
    data = req.model_dump()
    # Drop unset optional fields so a partial update never clobbers them
    data = {k: v for k, v in data.items() if v is not None}
    commands = data.get("commands") or []
    trigger = data.pop("trigger", "")
    if trigger and not commands:
        commands = [c.strip() for c in trigger.split(",") if c.strip()]
    data["commands"] = commands
    
    # Remove id/created_at if passed in updates
    data.pop("id", None)
    data.pop("created_at", None)
    # Sửa workflow = đưa node mới vào kho, nên đóng dấu lại y như lúc tạo. Agent
    # sửa skill của chủ thì skill đó tụt xuống "model" (phía an toàn); chủ mở
    # canvas sửa lại rồi lưu thì nó trở về "user".
    data["authored_by"] = _skill_author_for_request(request)
    skill = skill_manager.update(skill_id, **data)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"status": "updated", "skill": skill.to_dict()}

@app.post("/api/v1/skills/generate-ai")
async def generate_skill_ai_endpoint(req: SkillGenerateRequest):
    from tubecli.core.ai_workflow_builder import generate_skill_with_ai
    try:
        result = generate_skill_with_ai(
            prompt=req.prompt,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key
        )
        return {"status": "success", "skill": result}
    except Exception as e:
        raise HTTPException(500, f"Skill AI generation failed: {str(e)}")

@app.delete("/api/v1/skills/{skill_id}")
async def delete_skill(skill_id: str):
    from tubecli.core.skill import skill_manager
    if not skill_manager.delete(skill_id):
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"status": "deleted", "skill_id": skill_id}


class SaveAsSkillRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    trigger: str = ""
    workflow_data: Dict = {}
    skill_type: str = "Workflow Skill"


@app.post("/api/v1/workflows/save-as-skill")
async def save_workflow_as_skill(req: SaveAsSkillRequest, request: Request):
    """Convert a workflow into a reusable Skill that Agents can execute."""
    from tubecli.core.skill import skill_manager

    if not req.name:
        raise HTTPException(400, "Skill name is required")

    commands = [req.trigger.strip()] if req.trigger and req.trigger.strip() else []
    # Cùng cửa vào kho như POST /skills — nút Save của canvas (phiên chủ /
    # Origin dashboard) đóng dấu "user", mọi caller khác đóng dấu "model".
    authored_by = _skill_author_for_request(request)

    if req.id:
        existing = skill_manager.get(req.id)
        if existing:
            skill_manager.update(
                existing.id,
                name=req.name,
                workflow_data=req.workflow_data,
                description=req.description,
                commands=commands,
                authored_by=authored_by,
            )
            return {"status": "updated", "skill": existing.to_dict(), "message": f"Skill '{req.name}' updated"}

    # Check if name already exists as fallback
    existing_by_name = skill_manager.find_by_name(req.name)
    if existing_by_name:
        skill_manager.update(
            existing_by_name.id,
            workflow_data=req.workflow_data,
            description=req.description,
            commands=commands,
            authored_by=authored_by,
        )
        return {"status": "updated", "skill": existing_by_name.to_dict(), "message": f"Skill '{req.name}' updated (by name)"}

    skill = skill_manager.create(
        name=req.name,
        description=req.description or f"Workflow skill: {req.name}",
        skill_type=req.skill_type,
        workflow_data=req.workflow_data,
        commands=commands,
        authored_by=authored_by,
    )
    return {"status": "created", "skill": skill.to_dict(), "message": f"Skill '{req.name}' created successfully"}


# ── Who is behind a request that builds nodes? ───────────────────
#
# /skills/{id}/run and /workflows/run both take a workflow and instantiate
# its nodes, and both are reachable over loopback - which auth.check_request
# lets through with no session on purpose, because that is how this machine
# talks to itself. So "it came from 127.0.0.1" says nothing about WHO asked,
# and an agent calling its own server is indistinguishable from the owner
# unless somebody decides. This is that somebody, and it fails towards the
# model:
#
#   X-TubeCLI-Agent header -> model. exec_run_api stamps it on every internal
#          call it makes (core/telegram_actions.py). The model controls that
#          call's endpoint and body; it never controls its headers.
#   guest session -> model. A sharee is not the owner. (_guest_allowed denies
#          these paths outright today; this survives the day one opens.)
#   owner session cookie -> user.
#   one of our own browser pages (an ORIGIN the origin guard accepts)
#          -> user. This is the dashboard's Run button on an install where no
#          password has been set, so no session cookie can exist at all.
#          Origin ONLY, never Referer: the cross-origin middleware above
#          (_guard_cross_origin) validates `origin` and nothing else, so a
#          Referer is a header any local curl can type - and _allowed_hosts()
#          always contains the loopback hosts. Browsers attach Origin to every
#          non-GET/HEAD fetch including same-origin ones, so both callers that
#          matter (workflow.js Run, app.js) are unaffected.
#   an in-process call that DECLARES itself the owner's (_OwnerInProcessCall,
#          below) -> user. Only the scheduler does this, and only because the
#          owner is the only one who can set a schedule.
#   anything else -> model. curl on the box, any other in-process caller, an
#          extension: full node rights need evidence, not silence. The CLI
#          (tubecli workflow run) is the unrestricted path for a person.
class _OwnerInProcessCall:
    """Đứng thay một Request cho lời gọi KHÔNG có HTTP nào phía sau, mà vẫn là
    của CHỦ.

    Đúng một caller hôm nay: scheduler nền chạy một skill CHỦ đã đặt lịch
    (`_run_skill_bg` ở on_startup). Không route nào đặt được `schedule_enabled`
    — SkillCreateRequest không có trường đó, nên lịch chỉ đến từ dashboard/
    skills.json, tức từ chính chủ. Một lượt chạy theo lịch vì thế là hành động
    của chủ bị hoãn lại về thời gian, giống hệt `tubecli skill run`.

    Vì sao không để nó rơi vào nhánh mặc định (model): làm thế thì mọi skill
    đặt lịch có node browser/api/file lặng lẽ ngừng chạy — một thay đổi hành vi
    không ai yêu cầu, và người dùng chỉ thấy "tự dưng lịch không chạy nữa".

    ĐIỀU KIỆN để câu trên còn đúng: model KHÔNG đặt được lịch — KHÔNG qua
    route, và cũng KHÔNG bằng cách ghi thẳng file. Vế thứ hai từng sai: data/
    nằm trong allowlist của sandbox AI, `skills.json` thì không có trong
    AI_PROTECTED_DATA_SUBDIRS, nên một `file_action create_file` ghi đè cả kho
    skill — kể cả `schedule_enabled` — và lịch đó mint quyền chủ ở lần khởi
    động sau (SkillManager đọc file lúc dựng, không đọc lại). Nay skills.json
    và agents.json đã nằm trong danh sách chặn đó
    (extensions/file_manager/file_service.py). Ngày nào có một route (hay một
    action) cho agent bật `schedule_enabled`, hoặc kho skill lại ghi được từ
    sandbox, chỗ này phải hạ xuống NodePolicy.model ngay — nếu không, "đặt
    lịch" thành cửa rửa quyền.
    """

    def __init__(self, why: str):
        self.why = why
        self.headers = {}
        self.cookies = {}
        from types import SimpleNamespace

        self.state = SimpleNamespace()


def _skill_author_for_request(request: Request) -> str:
    """"user" | "model" — AI hay người đứng sau lời gọi tạo/sửa skill này.

    Dùng CHÍNH bộ nhận diện của node policy, để "ai được dựng node gì" và "ai
    được cất node gì vào kho" không bao giờ trả lời khác nhau. Đóng dấu theo
    người gọi chứ không theo trường trong body: caller tự khai `authored_by`
    thì dấu này vô nghĩa.
    """
    return "model" if _node_policy_for_request(request, "api.skills.author").source == "model" else "user"


def _policy_for_stored_skill(request: Request, skill, where: str):
    """Chính sách node cho một skill ĐÃ NẰM TRONG KHO.

    Lấy phần HẸP hơn giữa (a) người gọi là ai và (b) ai đã dựng skill này.
    Skill mang dấu "model" thì dù chủ có bấm Run trên dashboard cũng chỉ được
    allowlist: nội dung workflow là chữ model viết, và chủ bấm Run trên một
    thẻ skill không có nghĩa là chủ đã đọc từng node bên trong. Đây đúng là
    "skill do model tạo" mà §1 nói tới.
    """
    from tubecli.nodes.registry import NodePolicy

    policy = _node_policy_for_request(request, where)
    if str(getattr(skill, "authored_by", "user") or "user").lower() == "model":
        return NodePolicy.model(where + ":model_authored")
    return policy


def _node_policy_for_request(request: Request, where: str):
    from tubecli.nodes.registry import NodePolicy

    # Lời gọi in-process đã được khai rõ là của chủ (xem _OwnerInProcessCall).
    # Đứng TRƯỚC mọi thứ khác vì nó không có header, cookie hay Origin nào để
    # xét — và cũng không bao giờ đến từ mạng, nên không ai giả được nó.
    if isinstance(request, _OwnerInProcessCall):
        return NodePolicy.user(f"{where}:{request.why}")

    try:
        if request.headers.get("x-tubecli-agent"):
            return NodePolicy.model(where + ":agent")
        if getattr(request.state, "guest_scope", None):
            return NodePolicy.model(where + ":guest")
        from tubecli.core import auth

        if auth.session_valid(request.cookies.get(auth.SESSION_COOKIE)):
            return NodePolicy.user(where + ":session")
        page = request.headers.get("origin") or ""
        if page:
            from tubecli.core.origin_guard import is_origin_allowed

            if is_origin_allowed(page, request.headers.get("host", "")):
                return NodePolicy.user(where + ":dashboard")
    except Exception:
        pass  # a check that breaks must land on the safe side, not the open one
    return NodePolicy.model(where)


@app.post("/api/v1/skills/{skill_id}/run")
async def run_skill(skill_id: str, request: Request, input_text: str = ""):
    """Run a skill by executing its stored workflow. Returns error guidance for AI agents."""
    from tubecli.core.skill import skill_manager
    from tubecli.nodes.registry import create_node_from_dict
    from tubecli.core.workflow_engine import WorkflowEngine

    skill = skill_manager.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")

    import datetime
    skill_manager.update(skill_id, last_run=datetime.datetime.now().isoformat())

    if getattr(skill, "skill_format", "workflow") == "browser_script":
        # Temporary payload for browser_script format (pass to runner)
        # Assuming the browser_scripts extension exposes an endpoint or function.
        # For now, return a placeholder result telling the agent/UI to route to script runner.
        return {
            "status": "success", 
            "message": "Browser script triggered", 
            "action": "run_browser_script", 
            "script_id": skill.workflow_data.get("script_id"),
            "data": input_text
        }
        
    elif getattr(skill, "skill_format", "workflow") == "markdown" or getattr(skill, "skill_type", "") == "Markdown":
        # Markdown SOP simply returns its content for LLM context
        # (legacy UI-created skills carry skill_type="Markdown" with format "workflow")
        return {
            "status": "success",
            "message": "Markdown SOP loaded",
            "action": "load_sop",
            "sop_content": skill.workflow_data.get("markdown_content") or skill.workflow_data.get("markdown") or skill.workflow_data.get("sop") or "",
            "data": input_text
        }

    elif getattr(skill, "skill_format", "workflow") == "extension_action":
        # Dispatch to an extension endpoint (skills without workflow nodes
        # that wrap extension features like Subtitle, TTS, Studios...)
        wf = skill.workflow_data or {}
        endpoint = wf.get("endpoint", "")
        if not endpoint:
            raise HTTPException(400, (
                f"Skill '{skill.name}' is an extension_action but has no endpoint. "
                "Set workflow_data.endpoint (e.g. '/api/v1/subtitle/extract')."
            ))
        import httpx
        method = (wf.get("method") or "POST").upper()
        payload = dict(wf.get("payload") or {})
        input_key = wf.get("input_key") or "input"
        payload.setdefault(input_key, input_text)
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
                if method == "GET":
                    resp = await client.get(endpoint, params=payload, timeout=300)
                else:
                    resp = await client.request(method, endpoint, json=payload, timeout=300)
            if resp.status_code >= 400:
                return {
                    "status": "error",
                    "message": f"Extension endpoint {endpoint} returned HTTP {resp.status_code}",
                    "guidance": resp.text[:500],
                }
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:2000]}
            return {"status": "success", "message": "Extension action completed", "outputs": data}
        except Exception as e:
            raise HTTPException(500, f"Extension action dispatch failed: {e}")

    # Default to Workflow Execution
    wf = skill.workflow_data
    nodes_data = wf.get("nodes", [])
    connections = wf.get("connections", [])

    if not nodes_data:
        # Clear guidance for both humans and AI agents instead of a bare 400
        raise HTTPException(400, (
            f"Skill '{skill.name}' has no workflow nodes, so it cannot be executed. "
            "Open Dashboard → Skills and build its workflow, or set skill_format to "
            "'extension_action' with workflow_data.endpoint if it wraps an extension feature. "
            "AI agents: pick a different skill for this task."
        ))

    if input_text:
        for nd in nodes_data:
            if nd.get("type") in ("text_input", "manual_input"):
                nd.setdefault("config", {})["text"] = input_text

    try:
        # A stored skill is a recipe; input_text above is whoever is calling.
        # If that caller cannot be shown to be the owner, the recipe runs with
        # the model allowlist - otherwise an agent could launder a shell command
        # through a skill the owner drew months ago. And a recipe the MODEL
        # wrote stays on the allowlist whoever presses Run.
        _policy = _policy_for_stored_skill(request, skill, "api.skills.run")
        nodes = [create_node_from_dict(nd, policy=_policy) for nd in nodes_data]
    except Exception as e:
        raise HTTPException(400, f"Node creation error: {e}")

    engine = WorkflowEngine(nodes=nodes, connections=connections)
    result = await engine.run()

    # Collect error guidance from node results for AI agents
    errors = []
    guidance = []
    if result.get("logs"):
        for log in result["logs"]:
            if log.get("status") == "error" or "Error" in str(log.get("message", "")):
                errors.append({"node": log.get("node_name", ""), "error": log.get("message", "")})
    if result.get("node_results"):
        for node_id, node_result in result["node_results"].items():
            if isinstance(node_result, dict):
                if node_result.get("_error_guidance"):
                    guidance.append(node_result["_error_guidance"])
                if "Error" in str(node_result.get("status", "")):
                    errors.append({"node": node_id, "error": node_result.get("status", "")})

    if errors or guidance:
        from tubecli.i18n import t
        result["_skill_errors"] = errors
        result["_skill_guidance"] = guidance or [
            t("brain.workflow_error_guidance")
        ]

    return result


# ── Workflows ────────────────────────────────────────────────────

@app.post("/api/v1/workflows/generate")
async def generate_workflow_with_ai(req: WorkflowGenerateRequest):
    """Generate a workflow from a natural language prompt using AI."""
    from tubecli.core.ai_workflow_builder import generate_workflow
    try:
        result = generate_workflow(
            prompt=req.prompt,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
        )
        return {"status": "success", "workflow_data": result}
    except Exception as e:
        raise HTTPException(500, f"Workflow generation failed: {str(e)}")


@app.post("/api/v1/workflows/run")
async def run_workflow(req: WorkflowRunRequest, request: Request):
    """Run a workflow posted as JSON.

    The whole workflow arrives in the body, so this route is the shortest path
    from "can issue an HTTP request to this box" to "run_command node". Two
    things stand in the way: the login gate in the middleware above (this path
    is NOT in _AUTH_EXEMPT_EXACT/_PREFIX - checked, and it must stay out), and
    the node policy below, which is what covers the loopback hole the login
    gate deliberately leaves open.
    """
    import asyncio
    from tubecli.nodes.registry import create_node_from_dict
    from tubecli.core.workflow_engine import WorkflowEngine

    nodes_data = req.workflow_data.get("nodes", [])
    connections = req.workflow_data.get("connections", [])

    if req.input_text:
        for nd in nodes_data:
            if nd.get("type") in ("text_input", "manual_input"):
                nd.setdefault("config", {})["text"] = req.input_text

    try:
        _policy = _node_policy_for_request(request, "api.workflows.run")
        nodes = [create_node_from_dict(nd, policy=_policy) for nd in nodes_data]
    except Exception as e:
        raise HTTPException(400, f"Node creation error: {e}")

    engine = WorkflowEngine(nodes=nodes, connections=connections)
    result = await engine.run()
    return result


@app.get("/api/v1/workflows")
async def list_workflows():
    """List all saved workflows."""
    import json
    from tubecli.config import DATA_DIR

    wf_dir = os.path.join(DATA_DIR, "workflows")
    os.makedirs(wf_dir, exist_ok=True)

    workflows = []
    for fname in os.listdir(wf_dir):
        if fname.endswith(".json"):
            fpath = os.path.join(wf_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                workflows.append({
                    "name": fname.replace(".json", ""),
                    "node_count": len(data.get("nodes", [])),
                    "modified": os.path.getmtime(fpath),
                })
            except Exception:
                pass
    return {"workflows": workflows, "count": len(workflows)}


@app.post("/api/v1/workflows")
async def save_workflow(req: WorkflowSaveRequest):
    """Save a workflow to disk."""
    import json
    from tubecli.config import DATA_DIR

    wf_dir = os.path.join(DATA_DIR, "workflows")
    os.makedirs(wf_dir, exist_ok=True)

    safe_name = "".join(c for c in req.name if c.isalnum() or c in "_- ").strip()
    if not safe_name:
        raise HTTPException(400, "Invalid workflow name")

    fpath = os.path.join(wf_dir, safe_name + ".json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(req.workflow_data, f, indent=2, ensure_ascii=False)

    return {"status": "saved", "name": safe_name}


@app.get("/api/v1/workflows/{name}")
async def get_workflow(name: str):
    """Get a saved workflow by name."""
    import json
    from tubecli.config import DATA_DIR

    fpath = os.path.join(DATA_DIR, "workflows", name + ".json")
    if not os.path.exists(fpath):
        raise HTTPException(404, f"Workflow '{name}' not found")

    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"name": name, "workflow_data": data}


@app.delete("/api/v1/workflows/{name}")
async def delete_workflow(name: str):
    """Delete a saved workflow."""
    from tubecli.config import DATA_DIR

    fpath = os.path.join(DATA_DIR, "workflows", name + ".json")
    if not os.path.exists(fpath):
        raise HTTPException(404, f"Workflow '{name}' not found")

    os.remove(fpath)
    return {"status": "deleted", "name": name}


# ── Nodes ────────────────────────────────────────────────────────

@app.get("/api/v1/nodes")
async def list_nodes():
    from tubecli.nodes.registry import list_available_nodes
    return {"nodes": list_available_nodes()}


# ── Extensions Management ───────────────────────────────────────────

# Trang UI do webui phục vụ hộ các extension không tự khai page_url trong manifest
# (routes thật nằm ở tubecli/extensions/webui/routes.py). API /extensions backfill
# các field này để client ngoài (cloud dashboard) biết đường nhúng iframe + icon —
# không đổi to_dict() của core để khỏi ảnh hưởng nơi khác.
WEBUI_SERVED_PAGES = {
    # icon = tên Material Symbols (cùng bộ icon dashboard dùng), không dùng emoji
    "webui":              {"page_url": "/workflow",           "icon": "account_tree",      "display_name": "Workflow Builder"},
    "multi_agents":       {"page_url": "/teams",              "icon": "groups",            "display_name": "Teams"},
    "market":             {"page_url": "/market",             "icon": "storefront",        "display_name": "Marketplace"},
    "video_downloader":   {"page_url": "/downloader",         "icon": "download",          "display_name": "Video Downloader"},
    "file_manager":       {"page_url": "/file-manager",       "icon": "folder",            "display_name": "File Manager"},
    "universal_tracker":  {"page_url": "/tracker",            "icon": "monitoring",        "display_name": "Universal Tracker"},
    "auth_manager":       {"page_url": "/auth-manager",       "icon": "lock",              "display_name": "Auth Manager"},
    "video_editor":       {"page_url": "/video-editor",       "icon": "movie",             "display_name": "Video Editor"},
    "web_crawler":        {"page_url": "/web-crawler",        "icon": "travel_explore",    "display_name": "Web Crawler"},
    "video_manager":      {"page_url": "/video-manager",      "icon": "video_library",     "display_name": "Video Manager"},
    "subtitle_extractor": {"page_url": "/subtitle-extractor", "icon": "subtitles",         "display_name": "Subtitle Extractor"},
    "tts_vibevoice":      {"page_url": "/tts-vibevoice",      "icon": "record_voice_over", "display_name": "TTS VibeVoice"},
    "ai_arena":           {"page_url": "/ai-arena",           "icon": "sports_esports",    "display_name": "AI Arena"},
    "sheets_manager":     {"page_url": "/sheets-manager",     "icon": "table_chart",       "display_name": "Sheets Manager"},
    "livestream":         {"page_url": "/livestream",         "icon": "live_tv",           "display_name": "Livestream Manager"},
    "template_designer":  {"page_url": "/template-designer",  "icon": "design_services",   "display_name": "Template Designer"},
    "studio3d":           {"page_url": "/studio",             "icon": "view_in_ar",        "display_name": "Studio 3D"},
    "chat":               {"page_url": "/chat",               "icon": "forum",             "display_name": "Chat"},
    "codex":              {"page_url": "/codex",              "icon": "terminal",          "display_name": "Codex"},
    # Panel trong dashboard SPA — page_url là deep-link #/tab (handleRoute của webui);
    # ?embed=1 ẩn sidebar khi bị nhúng iframe (index.html embed-mode)
    "cloud_api":          {"page_url": "/dashboard?embed=1#/api-manager",           "icon": "api",            "display_name": "Cloud API"},
    "ollama_manager":     {"page_url": "/dashboard?embed=1#/api-manager",           "icon": "smart_toy",      "display_name": "Ollama"},
    "browser":            {"page_url": "/dashboard?embed=1#/ext-browser",           "icon": "public",         "display_name": "Browser Engine"},
    "douyin_downloader":  {"page_url": "/dashboard?embed=1#/ext-douyin-downloader", "icon": "music_video",    "display_name": "Douyin Downloader"},
    "calendar_manager":   {"page_url": "/dashboard?embed=1#/ext-calendar",          "icon": "calendar_month", "display_name": "Calendar"},
}

@app.get("/api/v1/extensions")
async def list_extensions():
    from tubecli.core.extension_manager import extension_manager
    extensions = extension_manager.get_all()
    out = []
    for p in extensions:
        d = p.to_dict()
        served = WEBUI_SERVED_PAGES.get(d.get("name"))
        if served:  # chỉ điền chỗ trống — manifest tự khai luôn thắng
            for k, v in served.items():
                if not d.get(k) or (k == "icon" and d.get(k) == "📦"):
                    d[k] = v
        out.append(d)
    return {"extensions": out, "count": len(out)}

@app.post("/api/v1/extensions/{name}/enable")
async def enable_extension(name: str):
    from tubecli.core.extension_manager import extension_manager
    if extension_manager.enable(name):
        return {"status": "enabled", "extension": name}
    raise HTTPException(404, f"Extension '{name}' not found")

@app.post("/api/v1/extensions/{name}/disable")
async def disable_extension(name: str):
    from tubecli.core.extension_manager import extension_manager
    if extension_manager.disable(name):
        return {"status": "disabled", "extension": name}
    raise HTTPException(404, f"Extension '{name}' not found")

@app.put("/api/v1/extensions/{name}")
async def update_extension(name: str, req: ExtensionUpdateRequest):
    from tubecli.core.extension_manager import extension_manager
    extension = extension_manager.get(name)
    if not extension:
         raise HTTPException(404, f"Extension '{name}' not found")
    
    if req.port is not None:
        extension_manager.set_port(name, req.port)
        
    return {"status": "updated", "extension": extension.to_dict()}


@app.get("/api/v1/extensions/{name}/info")
async def extension_info(name: str):
    """Get detailed info about a extension including manifest and SKILL.md."""
    from tubecli.core.extension_manager import extension_manager
    extension = extension_manager.get(name)
    if not extension:
        raise HTTPException(404, f"Extension '{name}' not found")
    info = extension.to_dict()
    info["manifest"] = extension.get_manifest()
    info["nodes"] = list(extension.get_nodes().keys()) if extension.get_nodes() else []
    skill_md = extension.get_skill_md()
    info["skill_md_content"] = skill_md[:2000] if skill_md else None
    return info


@app.get("/api/v1/extensions/{name}/locale/{lang}")
async def extension_locale(name: str, lang: str):
    """Return locale strings for an extension.
    Looks for locales/{lang}.json, falls back to en.json, returns {} if none found.
    """
    from tubecli.core.extension_manager import extension_manager
    import re
    # Sanitize lang to prevent path traversal
    if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', lang):
        lang = "en"
    extension = extension_manager.get(name)
    if not extension or not extension.extension_dir:
        return {}
    locales_dir = os.path.join(extension.extension_dir, "locales")
    # `json` was never imported in this scope, so json.load() raised NameError,
    # the bare `except Exception` swallowed it, and this endpoint always returned
    # {} — every caller got zero strings and rendered raw keys.
    import json
    # English underneath, requested language on top, so a partially translated
    # locale file degrades to English per key rather than leaking key names.
    merged = {}
    for try_lang in (["en", lang] if lang != "en" else ["en"]):
        locale_path = os.path.join(locales_dir, f"{try_lang}.json")
        if not os.path.isfile(locale_path):
            continue
        try:
            with open(locale_path, "r", encoding="utf-8") as f:
                merged.update(json.load(f))
        except Exception:
            pass
    return merged


class ExtensionInstallRequest(BaseModel):
    git_url: str


@app.post("/api/v1/extensions/install")
async def install_extension(req: ExtensionInstallRequest):
    """Install a extension from a git repository URL."""
    from tubecli.core.extension_manager import extension_manager
    result = extension_manager.install_from_git(req.git_url)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@app.delete("/api/v1/extensions/{name}/uninstall")
async def uninstall_extension(name: str):
    """Uninstall an external extension."""
    from tubecli.core.extension_manager import extension_manager
    result = extension_manager.uninstall(name)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@app.get("/api/v1/extensions/{name}/package")
async def package_extension(name: str):
    """Package all files of an extension into a JSON structure for Market upload.
    Returns manifest + all source files so buyers can fully install the extension.
    Auto-detects pip dependencies from Python imports.
    """
    import re
    import ast
    import json as json_lib
    from tubecli.core.extension_manager import extension_manager

    ext = extension_manager.get(name)
    if not ext:
        raise HTTPException(404, f"Extension '{name}' not found")

    ext_dir = ext.extension_dir
    if not ext_dir or not os.path.isdir(ext_dir):
        raise HTTPException(400, "Extension directory not found")

    # ── Mapping: Python module name → pip package name ──────────────
    # Standard library modules are excluded automatically via sys.stdlib_module_names (Python 3.10+)
    # or a manual list. Any module not in stdlib that is imported is considered a dep.
    IMPORT_TO_PIP = {
        # Media / video
        "yt_dlp": "yt-dlp",
        "imageio_ffmpeg": "imageio-ffmpeg",
        "imageio": "imageio",
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "moviepy": "moviepy",
        "ffmpeg": "ffmpeg-python",
        # HTTP / network
        "requests": "requests",
        "httpx": "httpx",
        "aiohttp": "aiohttp",
        "bs4": "beautifulsoup4",
        "lxml": "lxml",
        "selenium": "selenium",
        "playwright": "playwright",
        "pyppeteer": "pyppeteer",
        # Data / AI
        "numpy": "numpy",
        "pandas": "pandas",
        "sklearn": "scikit-learn",
        "scipy": "scipy",
        "torch": "torch",
        "tensorflow": "tensorflow",
        "openai": "openai",
        "anthropic": "anthropic",
        "google.generativeai": "google-generativeai",
        # Web / API
        "fastapi": "fastapi",
        "pydantic": "pydantic",
        "uvicorn": "uvicorn",
        "flask": "Flask",
        "django": "Django",
        "starlette": "starlette",
        # Utils
        "dotenv": "python-dotenv",
        "yaml": "PyYAML",
        "toml": "tomli",
        "rich": "rich",
        "click": "click",
        "tqdm": "tqdm",
        "loguru": "loguru",
        "cryptography": "cryptography",
        "jwt": "PyJWT",
        "paramiko": "paramiko",
        "pyautogui": "pyautogui",
        "pynput": "pynput",
        "pyperclip": "pyperclip",
        "psutil": "psutil",
        "pytesseract": "pytesseract",
        "docx": "python-docx",
        "openpyxl": "openpyxl",
        "xlrd": "xlrd",
        "reportlab": "reportlab",
        "telegram": "python-telegram-bot",
        "discord": "discord.py",
        "tweepy": "tweepy",
        "boto3": "boto3",
        "google.cloud": "google-cloud",
        "google.auth": "google-auth",
        "pymongo": "pymongo",
        "redis": "redis",
        "sqlalchemy": "SQLAlchemy",
        "alembic": "alembic",
        "celery": "celery",
    }

    # Known stdlib top-level module names (supplemented if sys.stdlib_module_names unavailable)
    import sys
    try:
        _STDLIB = sys.stdlib_module_names  # Python 3.10+
    except AttributeError:
        _STDLIB = {
            "os", "sys", "re", "io", "ast", "abc", "math", "time", "json",
            "uuid", "enum", "copy", "glob", "shutil", "logging", "pathlib",
            "typing", "hashlib", "base64", "struct", "socket", "threading",
            "asyncio", "subprocess", "functools", "itertools", "collections",
            "contextlib", "dataclasses", "importlib", "inspect", "traceback",
            "random", "string", "token", "tokenize", "weakref", "signal",
            "platform", "tempfile", "datetime", "calendar", "urllib",
            "http", "html", "email", "csv", "sqlite3", "xml", "zipfile",
            "tarfile", "gzip", "bz2", "lzma", "codecs", "multiprocessing",
        }

    def _scan_imports(py_source: str) -> set:
        """Extract top-level module names from Python source."""
        found = set()
        try:
            tree = ast.parse(py_source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        found.add(node.module.split(".")[0])
        except SyntaxError:
            # Fallback: regex
            for m in re.finditer(r"^(?:import|from)\s+([\w]+)", py_source, re.MULTILINE):
                found.add(m.group(1))
        return found

    # ── Collect all files ──────────────────────────────────────────
    SKIP_DIRS = {
        "__pycache__", ".git", "node_modules", ".venv", "venv",
        "data", "db", "logs", "tmp", "dist", "build",
        ".env", ".vscode", ".idea", "coverage",
    }
    SKIP_EXTS = {".pyc", ".pyo", ".egg-info", ".sqlite3", ".db", ".log", ".exe", ".dll", ".so", ".zip", ".tar", ".gz"}
    MAX_FILE_SIZE = 500_000  # 500KB per file

    # An extension can OPT SPECIFIC DIRS BACK IN via "package_keep_dirs" in its
    # manifest. SKIP_DIRS drops every folder named dist/build on the theory that
    # they are rebuildable artifacts — but capcut_tts ships server/dist ON
    # PURPOSE (a low-RAM VPS must never run tsc), and skipping it silently sold
    # a package whose buyers would have had to compile TypeScript themselves.
    keep_dirs: set = set()
    manifest_path_early = os.path.join(ext_dir, "tubecli-extension.json")
    if os.path.isfile(manifest_path_early):
        try:
            with open(manifest_path_early, "r", encoding="utf-8-sig") as f:
                _m = json_lib.load(f)
            keep_dirs = {str(p).replace("\\", "/").strip("/") for p in _m.get("package_keep_dirs", [])}
        except Exception:
            pass

    # ── Parse .gitignore for extra exclusions ──
    gitignore_patterns = set()
    gitignore_path = os.path.join(ext_dir, ".gitignore")
    if os.path.isfile(gitignore_path):
        try:
            with open(gitignore_path, "r") as f:
                for line in f:
                    line = line.strip().rstrip("/")
                    if line and not line.startswith("#"):
                        gitignore_patterns.add(line)
        except Exception:
            pass

    files = []
    all_imports: set = set()

    def _kept(root_dir: str, d: str) -> bool:
        """True if this dir (or one of its ancestors) is opted back in."""
        rel = os.path.relpath(os.path.join(root_dir, d), ext_dir).replace("\\", "/")
        return any(rel == k or rel.startswith(k + "/") or k.startswith(rel + "/")
                   for k in keep_dirs)

    for root, dirs, filenames in os.walk(ext_dir):
        dirs[:] = [d for d in dirs
                   if (d not in SKIP_DIRS and d not in gitignore_patterns) or _kept(root, d)]

        for fname in filenames:
            if any(fname.endswith(e) for e in SKIP_EXTS):
                continue

            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, ext_dir).replace("\\", "/")

            if os.path.getsize(fpath) > MAX_FILE_SIZE:
                continue

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                files.append({"path": rel_path, "content": content})

                # Scan Python files for imports
                if fname.endswith(".py"):
                    all_imports |= _scan_imports(content)
            except (UnicodeDecodeError, PermissionError):
                continue

    # ── Auto-detect pip packages ───────────────────────────────────
    detected_deps: list = []

    # 1. From requirements.txt (highest priority, preserves version pins)
    req_deps: set = set()
    req_file = os.path.join(ext_dir, "requirements.txt")
    if os.path.exists(req_file):
        try:
            with open(req_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        detected_deps.append(line)
                        pkg = re.split(r"[=<>!;]", line)[0].strip().lower().replace("-", "_")
                        req_deps.add(pkg)
        except Exception:
            pass

    # 2. From scanned imports → map to pip packages
    # Respect exclude_auto_deps from manifest (for lazy-loaded heavy deps)
    exclude_auto = set()
    if os.path.exists(os.path.join(ext_dir, "tubecli-extension.json")):
        try:
            with open(os.path.join(ext_dir, "tubecli-extension.json"), "r", encoding="utf-8-sig") as f:
                _m = json_lib.load(f)
            for exc in _m.get("exclude_auto_deps", []):
                exclude_auto.add(exc.lower().replace("-", "_"))
        except Exception:
            pass

    req_deps_normalized = {r.replace("-", "_").lower() for r in req_deps}
    for module in sorted(all_imports):
        if module in _STDLIB:
            continue
        # Skip modules in exclude_auto_deps (heavy deps installed on-demand)
        if module.lower().replace("-", "_") in exclude_auto:
            continue
        # Check if already covered by requirements.txt
        mod_normalized = module.replace("-", "_").lower()
        pip_name = IMPORT_TO_PIP.get(module)
        if not pip_name:
            continue  # Unknown mapping, skip
        pip_normalized = pip_name.replace("-", "_").lower()
        if pip_normalized in exclude_auto:
            continue
        if pip_normalized in req_deps_normalized or mod_normalized in req_deps_normalized:
            continue  # Already in requirements.txt
        detected_deps.append(pip_name)

    # 3. Merge with existing manifest.dependencies (don't lose manually declared ones)
    read_manifest_path = os.path.join(ext_dir, "tubecli-extension.json")
    manifest = {}
    if os.path.exists(read_manifest_path):
        with open(read_manifest_path, "r", encoding="utf-8-sig") as f:
            manifest = json_lib.load(f)

    existing_deps = manifest.get("dependencies", [])
    existing_normalized = {d.replace("-", "_").lower() for d in existing_deps}
    for dep in existing_deps:
        dep_norm = dep.replace("-", "_").lower()
        if dep_norm not in {d.replace("-", "_").lower() for d in detected_deps}:
            detected_deps.append(dep)

    # Deduplicate while preserving order
    seen = set()
    final_deps = []
    for dep in detected_deps:
        key = re.split(r"[=<>!;]", dep)[0].strip().lower().replace("-", "_")
        if key not in seen:
            seen.add(key)
            final_deps.append(dep)

    # Update manifest with auto-detected deps
    manifest["dependencies"] = final_deps

    # `packed` is the same {manifest, files} payload gzip+base64'd. The market
    # upload sends item_data in a JSON body, and a large extension blows the
    # market server's request-size limit — capcut_tts (351 files, ~1.1 MB of
    # JSON) came back HTTP 413. Compressed it is ~350 KB. The uploader prefers
    # this form when present; the installer's _unwrap_item_data understands it.
    import gzip as _gzip
    import base64 as _b64
    packed_raw = json_lib.dumps({"manifest": manifest, "files": files}, ensure_ascii=False).encode("utf-8")
    packed = _b64.b64encode(_gzip.compress(packed_raw, 9)).decode()

    return {
        "status": "success",
        "manifest": manifest,
        "files": files,
        "file_count": len(files),
        "detected_deps": final_deps,
        "packed": packed,
        "packed_size": len(packed),
        "unpacked_size": len(packed_raw),
    }


@app.get("/api/v1/extensions/skill-mds")
async def get_extension_skill_mds():
    """Return all SKILL.md contents from enabled extensions for AI agents."""
    from tubecli.core.extension_manager import extension_manager
    return {"skill_mds": extension_manager.get_all_skill_mds()}


# ── System Version & Update ─────────────────────────────────────────

@app.get("/api/v1/system/version")
async def system_version():
    """Get current system version and git info."""
    import subprocess
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    git_hash = ""
    git_branch = ""
    project_root = str(BASE_DIR)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            git_hash = result.stdout.strip()
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            git_branch = result.stdout.strip()
    except Exception:
        pass

    return {
        "version": __version__,
        "git_hash": git_hash,
        "git_branch": git_branch,
    }


@app.post("/api/v1/system/check-update")
async def system_check_update():
    """Check if a system update is available by comparing local vs remote git."""
    import subprocess
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    project_root = str(BASE_DIR)

    try:
        # Fetch latest from remote
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=project_root, capture_output=True, text=True, timeout=30,
        )

        # Get current hash
        r_local = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        current_hash = r_local.stdout.strip() if r_local.returncode == 0 else ""

        # Get remote hash
        r_remote = subprocess.run(
            ["git", "rev-parse", "--short", "origin/main"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        latest_hash = r_remote.stdout.strip() if r_remote.returncode == 0 else ""

        # Count commits behind
        r_count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        commits_behind = int(r_count.stdout.strip()) if r_count.returncode == 0 else 0

        # Get changelog (commit messages)
        changelog = []
        if commits_behind > 0:
            r_log = subprocess.run(
                ["git", "log", "--oneline", f"HEAD..origin/main", "--format=%s"],
                cwd=project_root, capture_output=True, text=True, timeout=10,
            )
            if r_log.returncode == 0:
                changelog = [line.strip() for line in r_log.stdout.strip().split("\n") if line.strip()]

        return {
            "has_update": commits_behind > 0,
            "current_version": __version__,
            "current_hash": current_hash,
            "latest_hash": latest_hash,
            "commits_behind": commits_behind,
            "changelog": changelog[:20],
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to check for updates: {e}")


@app.post("/api/v1/system/update")
async def system_update():
    """Pull latest code from git and reinstall dependencies."""
    import subprocess, sys
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    project_root = str(BASE_DIR)
    old_version = __version__

    try:
        # Git pull — stash-aware (see _git_pull_safe)
        pr = _git_pull_safe(project_root, ("git", "pull", "origin", "main"))
        if not pr["ok"]:
            return {"status": "error",
                    "error": pr["message"] + ("\n" + "\n".join(pr["notes"]) if pr["notes"] else ""),
                    "dirty_files": pr["dirty"]}

        # Reinstall (update dependencies)
        r_install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
            cwd=project_root, capture_output=True, text=True, timeout=120,
        )

        # Read new version from file (since module cache still has old value)
        new_version = old_version
        init_file = os.path.join(project_root, "tubecli", "__init__.py")
        try:
            with open(init_file, "r") as f:
                for line in f:
                    if line.startswith("__version__"):
                        new_version = line.split("=")[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

        return {
            "status": "success",
            "old_version": old_version,
            "new_version": new_version,
            "git_output": (pr["output"] + ("\n" + "\n".join(pr["notes"]) if pr["notes"] else ""))[:500],
            "message": "Updated successfully! Please restart the API server to apply changes.",
        }
    except Exception as e:
        raise HTTPException(500, f"Update failed: {e}")


# ── Extension Update ─────────────────────────────────────────────────

@app.post("/api/v1/extensions/{name}/check-update")
async def check_extension_update(name: str):
    """Check if an external extension has updates available."""
    import subprocess
    import json
    from tubecli.core.extension_manager import (
        extension_manager,
        compare_versions,
        get_git_tracking_branch,
        get_git_commit_version,
    )
    from tubecli.extensions.market.market_service import market_service

    ext = extension_manager.get(name)
    if not ext:
        raise HTTPException(404, f"Extension '{name}' not found")

    # System extensions update with the core system
    if ext.extension_type != "external":
        return {
            "name": name,
            "has_update": False,
            "message": "System extensions update with 'System Update'. Use Settings → Update.",
            "current_version": ext.version,
        }

    ext_dir = ext.extension_dir
    git_dir = os.path.join(ext_dir, ".git") if ext_dir else None

    if ext_dir and git_dir and os.path.isdir(git_dir):
        # Git-based checking
        try:
            subprocess.run(
                ["git", "fetch", "origin"],
                cwd=ext_dir, capture_output=True, text=True, timeout=15,
            )
            branch = get_git_tracking_branch(ext_dir)

            r_count = subprocess.run(
                ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
                cwd=ext_dir, capture_output=True, text=True, timeout=10,
            )
            commits_behind = int(r_count.stdout.strip()) if r_count.returncode == 0 else 0

            changelog = []
            if commits_behind > 0:
                r_log = subprocess.run(
                    ["git", "log", "--oneline", f"HEAD..origin/{branch}", "--format=%s"],
                    cwd=ext_dir, capture_output=True, text=True, timeout=10,
                )
                if r_log.returncode == 0:
                    changelog = [l.strip() for l in r_log.stdout.strip().split("\n") if l.strip()]

            # Fetch remote version from git manifest, fallback to remote commit date
            remote_version = None
            try:
                res_show = subprocess.run(
                    ["git", "show", f"origin/{branch}:tubecli-extension.json"],
                    cwd=ext_dir, capture_output=True, text=True, timeout=10
                )
                if res_show.returncode == 0:
                    r_manifest = json.loads(res_show.stdout)
                    remote_version = r_manifest.get("version")
            except Exception:
                pass
            
            if not remote_version or compare_versions(remote_version, "2000.01.01.000000") < 0:
                remote_version = get_git_commit_version(ext_dir, remote=True, branch=branch) or "2026.05.21.000000"

            return {
                "name": name,
                "has_update": commits_behind > 0,
                "current_version": ext.version,
                "remote_version": remote_version,
                "commits_behind": commits_behind,
                "changelog": changelog[:10],
                "is_git": True,
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to check extension git update: {e}")
    else:
        # Marketplace-based checking
        try:
            check_res = await market_service.check_name_exists(ext.name)
            if check_res.get("exists") and check_res.get("item"):
                item = check_res["item"]
                market_version = item.get("version", "0.0.0")
                if compare_versions(market_version, ext.version) > 0:
                    return {
                        "name": name,
                        "has_update": True,
                        "current_version": ext.version,
                        "remote_version": market_version,
                        "public_id": check_res.get("public_id", ""),
                        "is_git": False,
                    }
            return {
                "name": name,
                "has_update": False,
                "message": "Extension is up to date on marketplace.",
                "current_version": ext.version,
                "is_git": False,
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to check extension marketplace update: {e}")


@app.post("/api/v1/extensions/{name}/update")
async def update_extension(name: str):
    """Pull latest code/updates for an external extension."""
    from tubecli.core.extension_manager import extension_manager

    result = extension_manager.update_extension(name)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Update failed"))
    return result


# ── Aggregated i18n (per-extension locales) ─────────────────────────

@app.get("/api/v1/i18n/{lang}")
async def get_aggregated_i18n(lang: str):
    """Aggregate locale files from ALL extensions into a single flat dict.
    Scans both built-in extensions and external extensions directories.
    """
    import re
    import json
    import os

    # Sanitize lang
    if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', lang):
        lang = "en"

    merged = {}

    def _load_locales_from_dir(base_dir):
        """Scan a directory for subdirectories containing locales/."""
        if not os.path.isdir(base_dir):
            return
        for entry in os.listdir(base_dir):
            ext_dir = os.path.join(base_dir, entry)
            if not os.path.isdir(ext_dir):
                continue
            locales_dir = os.path.join(ext_dir, "locales")
            if not os.path.isdir(locales_dir):
                continue
            # English underneath, then the requested language on top. The previous
            # version `break`ed after the first file it found, so an extension that
            # shipped vi.json missing a few keys leaked those key names into the UI
            # as literal text instead of degrading to English.
            for try_lang in (["en", lang] if lang != "en" else ["en"]):
                locale_path = os.path.join(locales_dir, f"{try_lang}.json")
                if not os.path.isfile(locale_path):
                    continue
                try:
                    with open(locale_path, "r", encoding="utf-8") as f:
                        merged.update(json.load(f))
                except Exception:
                    pass

    # 1. Built-in extensions: tubecli/extensions/*/locales/
    builtin_ext_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "extensions")
    _load_locales_from_dir(builtin_ext_dir)

    # 2. External extensions: data/extensions_external/*/locales/
    from tubecli.config import EXTENSIONS_EXTERNAL_DIR
    _load_locales_from_dir(str(EXTENSIONS_EXTERNAL_DIR))

    # No _DEBUG block here: this endpoint is reachable from the browser and was
    # returning absolute install paths (which include the OS username).
    return merged


# ── Language Settings ────────────────────────────────────────────────

class LanguageUpdateRequest(BaseModel):
    language: str


@app.get("/api/v1/settings/language")
async def get_language_setting():
    """Get current language setting."""
    from tubecli.config import get_language, SUPPORTED_LANGUAGES
    return {
        "language": get_language(),
        "supported": SUPPORTED_LANGUAGES,
    }


@app.put("/api/v1/settings/language")
async def set_language_setting(req: LanguageUpdateRequest):
    """Update language setting."""
    from tubecli.config import set_language, SUPPORTED_LANGUAGES
    from tubecli.i18n import load_language
    if req.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Unsupported language: {req.language}. Supported: {SUPPORTED_LANGUAGES}")
    set_language(req.language)
    load_language(req.language)
    return {"status": "updated", "language": req.language}


# ── Profile Settings ───────────────────────────────────────────────────

class ProfileUpdateRequest(BaseModel):
    profile: str


@app.get("/api/v1/settings/default-profile")
async def get_default_profile_setting():
    """Get current default browser profile."""
    from tubecli.config import get_setting
    return {"profile": get_setting("default_browser_profile", "default")}


@app.put("/api/v1/settings/default-profile")
async def set_default_profile_setting(req: ProfileUpdateRequest):
    """Update default browser profile."""
    from tubecli.config import set_setting
    set_setting("default_browser_profile", req.profile)
    return {"status": "updated", "profile": req.profile}


# ── Auth ────────────────────────────────────────────────────────────
# Registered before the extensions, so /login and /api/v1/auth/* cannot be
# shadowed by an extension that happens to claim the same path.
from tubecli.api.auth_routes import router as _auth_router
app.include_router(_auth_router)

# Group context: what each Flow Builder group shares with the agents inside it
# (PUT by the cloud canvas after every save; read by chat/Telegram/scheduler).
from tubecli.api.group_routes import router as _group_router
app.include_router(_group_router)

# Web terminal: trang /terminal + WS pty shell, nhúng iframe trong Flow Builder.
from tubecli.api.terminal_routes import router as _terminal_router
app.include_router(_terminal_router)

# App installer: cài 9Router/Ollama... thành systemd service (node App trong Flow).
from tubecli.api.app_routes import router as _app_router
app.include_router(_app_router)


# ── Register Extension Routes ───────────────────────────────────────
from tubecli.core.extension_manager import extension_manager
extension_manager.discover_extensions()
extension_manager.register_api_routes(app)
