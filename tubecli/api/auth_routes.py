"""Login, logout, and the forced first-time password change.

Every path here is exempt from the login gate in server.py (it has to be, or
there would be no way to log in), so each one re-checks what it needs for
itself rather than assuming the middleware did it.
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from tubecli.core import auth

router = APIRouter(tags=["Auth"])


class LoginRequest(BaseModel):
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("/api/v1/auth/status")
async def auth_status(request: Request):
    """What the login screen needs to decide what to render.

    Deliberately says nothing about WHY a remote caller is refused beyond the
    reason code — no hostname, no version, no path — since this is the one
    endpoint reachable before authenticating.
    """
    host = _client(request)
    loopback = auth.is_loopback(host)
    return {
        "configured": auth.is_configured(),
        "must_change_password": auth.is_default_password(),
        "authenticated": loopback or auth.session_valid(
            request.cookies.get(auth.SESSION_COOKIE)),
        "local": loopback,
    }


@router.post("/api/v1/auth/login")
async def login(body: LoginRequest, request: Request, response: Response):
    key = _client(request) or "unknown"

    locked, remaining = auth.throttle_status(key)
    if locked:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Sai quá nhiều lần. Thử lại sau {remaining} giây."},
        )

    auth.ensure_initialised()
    if not auth.verify_password(body.password):
        auth.record_failure(key)
        # The same message whether the password was wrong or the account was
        # never set up, so this cannot be used to probe the install's state.
        return JSONResponse(status_code=401, content={"detail": "Mật khẩu không đúng."})

    auth.clear_failures(key)

    # Trust this address from here on. A cloud VM cannot discover the public
    # address its users browse to — that is NAT'd outside the guest — but the
    # browser just told us in the Host header, and it proved it holds the
    # password. Without this the login succeeds and then every subsequent write
    # is refused by the cross-origin guard, which is what "Add key failed" was.
    try:
        from tubecli.core.origin_guard import remember_host

        remember_host(request.headers.get("origin", ""), request.headers.get("host", ""))
    except Exception:
        pass

    # The default password logs in like any other. It is reported back so the
    # UI can offer the change and keep warning, but it does not bar the door.
    must_change = auth.is_default_password()
    token = auth.create_session()
    response = JSONResponse(content={"ok": True, "must_change_password": must_change})
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,      # JavaScript cannot read it, so an XSS cannot steal it
        samesite="lax",     # not sent on cross-site POSTs, which is the CSRF case
        path="/",
    )
    return response


@router.post("/api/v1/auth/logout")
async def logout(request: Request):
    auth.destroy_session(request.cookies.get(auth.SESSION_COOKIE))
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


@router.post("/api/v1/auth/password")
async def change_password(body: PasswordChangeRequest, request: Request):
    """Change the password. Requires the current one, even from loopback.

    Loopback skips the LOGIN gate, but not this: without the check, any page in
    the user's browser could silently set a password of its choosing on a local
    install and lock the owner out of their own dashboard.
    """
    auth.ensure_initialised()
    key = _client(request) or "unknown"

    locked, remaining = auth.throttle_status(key)
    if locked:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Sai quá nhiều lần. Thử lại sau {remaining} giây."},
        )

    if not auth.verify_password(body.current_password):
        auth.record_failure(key)
        return JSONResponse(status_code=401, content={"detail": "Mật khẩu hiện tại không đúng."})

    if body.new_password == auth.DEFAULT_PASSWORD:
        return JSONResponse(
            status_code=400,
            content={"detail": "Không thể đặt lại đúng mật khẩu mặc định."},
        )

    try:
        auth.set_password(body.new_password)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})

    auth.clear_failures(key)

    # set_password cleared every session, including this caller's. Issue a fresh
    # one so changing the password does not bounce the user to the login screen.
    token = auth.create_session()
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True, samesite="lax", path="/",
    )
    return response


_LOGIN_PAGE = """<!doctype html>
<html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TubeCLI</title>
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:grid;place-items:center;background:#111214;
       color:#ededed;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  .card{width:min(380px,92vw);background:#1a1b1e;border:1px solid #2a2b2f;
        border-radius:14px;padding:30px}
  h1{margin:0 0 4px;font-size:19px;letter-spacing:-.01em}
  p.sub{margin:0 0 22px;color:#9ca3af;font-size:13.5px}
  label{display:block;margin:14px 0 6px;font-size:13px;color:#c9cbd1}
  input{width:100%;padding:11px 13px;border-radius:9px;border:1px solid #33353b;
        background:#111214;color:#ededed;font-size:14.5px}
  input:focus{outline:none;border-color:#5276EB}
  button{width:100%;margin-top:20px;padding:11px;border:0;border-radius:9px;
         background:#5276EB;color:#fff;font-size:14.5px;font-weight:600;cursor:pointer}
  button:disabled{opacity:.55;cursor:default}
  button.ghost{margin-top:9px;background:transparent;border:1px solid #33353b;
               color:#9ca3af;font-weight:500}
  button.ghost:hover{border-color:#4a4d55;color:#c9cbd1}
  .msg{margin-top:14px;font-size:13.5px;min-height:1.2em}
  .err{color:#ef4444}
  .note{margin-top:16px;padding:11px 13px;border-radius:9px;background:#2a2113;
        border:1px solid #4a3a18;color:#f0c674;font-size:13px}
  .note code{display:block;margin-top:9px;padding:8px 10px;border-radius:7px;
             background:#15140f;color:#ffd88a;font:13px/1.5 ui-monospace,Menlo,Consolas,monospace;
             user-select:all;cursor:text}
</style></head><body>
<div class="card">
  <h1 id="title">Đăng nhập TubeCLI</h1>
  <p class="sub" id="sub">Nhập mật khẩu để mở bảng điều khiển.</p>
  <div id="warn" class="note" hidden></div>
  <form id="f">
    <div id="cur-wrap">
      <label for="cur">Mật khẩu</label>
      <input id="cur" type="password" autocomplete="current-password" autofocus>
    </div>
    <div id="new-wrap" hidden>
      <label for="np">Mật khẩu mới</label>
      <input id="np" type="password" autocomplete="new-password">
      <label for="np2">Nhập lại mật khẩu mới</label>
      <input id="np2" type="password" autocomplete="new-password">
    </div>
    <button id="go" type="submit">Đăng nhập</button>
    <button id="skip" type="button" class="ghost" hidden>Để sau, vào thẳng</button>
  </form>
  <div class="msg" id="msg"></div>
</div>
<script>
(function(){
  var $=function(i){return document.getElementById(i)};
  var next=new URLSearchParams(location.search).get('next')||'/dashboard';
  var mode='login';
  // Kept from the login step so the change form does not ask for a password
  // the user just typed. The server still requires it — this only spares the
  // second entry.
  var knownCurrent='';
  function say(t,bad){ $('msg').textContent=t||''; $('msg').className='msg'+(bad?' err':''); }

  function toChange(local){
    mode='change';
    $('title').textContent='Đổi mật khẩu';
    $('sub').textContent='Bạn đang dùng mật khẩu mặc định. Nên đặt một mật khẩu riêng.';
    $('cur-wrap').hidden=true;          // already proved it during login
    $('new-wrap').hidden=false;
    $('go').textContent='Lưu mật khẩu';
    // Skippable, by the product owner's decision. The warning stays visible in
    // the dashboard afterwards so it is a choice rather than an oversight.
    $('skip').hidden=false;
    $('warn').hidden=false;
    $('warn').innerHTML='Nếu giữ mật khẩu mặc định, bất kỳ ai truy cập được máy này '+
      'cũng vào được bảng điều khiển — đọc được API key và cài được extension.'+
      (local?'':'<code>tubecli password</code>');
    $('np').focus();
  }

  $('skip').addEventListener('click', function(){ location.replace(next); });

  fetch('/api/v1/auth/status').then(function(r){return r.json()}).then(function(s){
    if(s.authenticated && !s.must_change_password){
      location.replace(next);
    } else if(s.must_change_password){
      $('warn').hidden=false;
      $('warn').textContent='Máy chủ đang dùng mật khẩu mặc định (123456). '+
        'Đăng nhập rồi đổi ngay để không ai khác vào được.';
    }
  }).catch(function(){});

  $('f').addEventListener('submit', function(e){
    e.preventDefault();
    say('');
    if(mode==='change'){
      if($('np').value!==$('np2').value){ return say('Hai mật khẩu không khớp.',true); }
      $('go').disabled=true;
      fetch('/api/v1/auth/password',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({current_password:knownCurrent||$('cur').value,
                             new_password:$('np').value})})
        .then(function(r){return r.json().then(function(d){return {ok:r.ok,d:d}})})
        .then(function(x){
          $('go').disabled=false;
          if(!x.ok){ return say(x.d.detail||'Không đổi được mật khẩu.',true); }
          location.replace(next);
        }).catch(function(){ $('go').disabled=false; say('Không kết nối được máy chủ.',true); });
      return;
    }
    $('go').disabled=true;
    knownCurrent=$('cur').value;
    fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:$('cur').value})})
      .then(function(r){return r.json().then(function(d){return {ok:r.ok,d:d}})})
      .then(function(x){
        $('go').disabled=false;
        if(!x.ok){ return say(x.d.detail||'Đăng nhập thất bại.',true); }
        if(x.d.must_change_password){ say(''); return toChange(x.d.local); }
        location.replace(next);
      }).catch(function(){ $('go').disabled=false; say('Không kết nối được máy chủ.',true); });
  });
})();
</script></body></html>"""


@router.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(_LOGIN_PAGE)


# Served to the dashboard, which includes it unconditionally. Keeping the banner
# here rather than in app.js means it cannot be lost when the dashboard is
# rebuilt, and it costs nothing when the password has been changed.
_BANNER_JS = """(function(){
  fetch('/api/v1/auth/status').then(function(r){return r.json()}).then(function(s){
    if(!s.must_change_password) return;
    var b=document.createElement('div');
    b.style.cssText='position:fixed;left:0;right:0;bottom:0;z-index:99999;'+
      'display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap;'+
      'padding:9px 16px;background:#4a3a18;color:#f0c674;'+
      'font:13px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;'+
      'border-top:1px solid #6b5320';
    var t=document.createElement('span');
    t.textContent='Đang dùng mật khẩu mặc định — ai truy cập được máy này cũng vào được bảng điều khiển.';
    var a=document.createElement('a');
    a.href='/login?next='+encodeURIComponent(location.pathname+location.hash);
    a.textContent='Đổi mật khẩu';
    a.style.cssText='color:#ffd88a;font-weight:600;text-decoration:underline;cursor:pointer';
    var x=document.createElement('button');
    x.textContent='Ẩn';
    x.style.cssText='background:transparent;border:1px solid #6b5320;color:#f0c674;'+
      'border-radius:6px;padding:3px 10px;font-size:12px;cursor:pointer';
    // Hidden for this tab only, deliberately: sessionStorage forgets on close,
    // so dismissing it does not make the warning go away for good.
    x.onclick=function(){ sessionStorage.setItem('tubecli_pw_banner','off'); b.remove(); };
    b.appendChild(t); b.appendChild(a); b.appendChild(x);
    if(sessionStorage.getItem('tubecli_pw_banner')!=='off') document.body.appendChild(b);
  }).catch(function(){});
})();"""


@router.get("/api/v1/auth/banner.js")
async def banner_js():
    from fastapi.responses import Response as _R

    return _R(content=_BANNER_JS, media_type="application/javascript",
              headers={"Cache-Control": "no-store"})
