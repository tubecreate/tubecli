/**
 * 管理 UI の 1 枚ページ
 *
 * Worker から直接返すので外部依存を持たせない
 * トークンはこの端末の localStorage にだけ置き、送信は毎回ヘッダで行う
 */
export const adminPage = `<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CapCut TTS — Tài khoản</title>
<style>
:root{
  --bg:#0b0e13; --surface:#141922; --surface-2:#1b212c; --line:#252c3a;
  --txt:#e6edf3; --muted:#8b98ab; --dim:#5f6b7e;
  --green:#22c55e; --green-dim:#16a34a;
  --amber:#f59e0b; --red:#ef4444; --blue:#3b82f6;
  --r:12px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);
  font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  padding:26px 22px 70px;-webkit-font-smoothing:antialiased}
.wrap{max-width:1160px;margin:0 auto}

.eyebrow{color:var(--green);font-size:11px;font-weight:700;letter-spacing:.11em;text-transform:uppercase}
h1{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:3px 0 5px}
.lede{color:var(--muted);font-size:13.5px}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap}
.head-actions{display:flex;gap:10px;flex-wrap:wrap}

button{font:inherit;cursor:pointer;border-radius:9px;border:1px solid var(--line);
  background:var(--surface);color:var(--txt);padding:9px 15px;transition:.14s}
button:hover:not(:disabled){background:var(--surface-2);border-color:#333d4f}
button:disabled{opacity:.45;cursor:not-allowed}
button.primary{background:var(--green-dim);border-color:var(--green-dim);color:#fff;font-weight:600}
button.primary:hover:not(:disabled){background:var(--green);border-color:var(--green)}
button.ghost{background:transparent}
button.sm{padding:6px 11px;font-size:12.5px}

.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:22px 0 14px}
.field{position:relative}
.field svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--dim)}
input{font:inherit;background:var(--surface);color:var(--txt);border:1px solid var(--line);
  border-radius:9px;padding:9px 12px;width:100%;transition:.14s}
input:focus{outline:none;border-color:var(--green-dim);box-shadow:0 0 0 3px rgba(34,197,94,.12)}
input::placeholder{color:var(--dim)}
.field input{padding-left:33px;min-width:230px}

.stats{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:20px;font-size:12.5px}
.stats .total{color:var(--muted);margin-right:3px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;
  font-size:12px;font-weight:600;background:var(--surface);border:1px solid var(--line)}
.dot{width:7px;height:7px;border-radius:50%;flex:none}
.c-ok .dot{background:var(--green)} .c-ok{color:var(--green)}
.c-wait .dot{background:var(--amber)} .c-wait{color:var(--amber)}
.c-bad .dot{background:var(--red)} .c-bad{color:var(--red)}
.c-off .dot{background:var(--dim)} .c-off{color:var(--muted)}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:16px 17px;position:relative;overflow:hidden;transition:.14s}
.card:hover{border-color:#333d4f}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--dim)}
.card.ok::before{background:var(--green)}
.card.wait::before{background:var(--amber)}
.card.bad::before{background:var(--red)}
.card-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.mail{font-weight:600;font-size:14.5px;word-break:break-all;line-height:1.35}
.tag{color:var(--muted);font-size:12px;margin-top:2px}
.meta{display:grid;grid-template-columns:1fr 1fr;gap:9px 14px;margin:14px 0 13px;
  padding-top:13px;border-top:1px solid var(--line)}
.meta div{min-width:0}
.k{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.06em}
.v{font-size:13px;margin-top:2px;font-variant-numeric:tabular-nums}
.bar{height:3px;border-radius:2px;background:var(--surface-2);overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;background:var(--green);border-radius:2px}
.err{color:var(--red);font-size:11.5px;margin-top:9px;line-height:1.4;
  background:rgba(239,68,68,.08);padding:6px 9px;border-radius:7px}
.acts{display:flex;gap:6px;flex-wrap:wrap;padding-top:12px;border-top:1px solid var(--line)}

.empty{grid-column:1/-1;text-align:center;padding:56px 20px;color:var(--dim);
  border:1px dashed var(--line);border-radius:var(--r)}
.empty svg{opacity:.5;margin-bottom:10px}

.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:18px;margin-bottom:18px}
.panel h2{font-size:14px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.form{display:grid;grid-template-columns:1.4fr 1.2fr 1fr auto;gap:11px;align-items:end}
.form label{display:block;color:var(--dim);font-size:11px;text-transform:uppercase;
  letter-spacing:.06em;margin-bottom:5px}
@media(max-width:760px){.form{grid-template-columns:1fr}}

.gate{max-width:410px;margin:70px auto}
.gate .panel{padding:26px}
.gate h2{font-size:17px;margin-bottom:6px}
.gate p{color:var(--muted);font-size:13px;margin-bottom:18px}

#toast{position:fixed;right:20px;bottom:20px;display:flex;flex-direction:column;gap:9px;z-index:99}
.toast{background:var(--surface-2);border:1px solid var(--line);border-left:3px solid var(--green);
  border-radius:9px;padding:11px 15px;font-size:13px;max-width:370px;
  box-shadow:0 10px 30px rgba(0,0,0,.5);animation:in .22s ease}
.toast.e{border-left-color:var(--red)}
@keyframes in{from{opacity:0;transform:translateY(8px)}}
.spin{display:inline-block;width:13px;height:13px;border:2px solid var(--line);
  border-top-color:var(--green);border-radius:50%;animation:sp .7s linear infinite;vertical-align:-2px}
@keyframes sp{to{transform:rotate(360deg)}}
.hint{color:var(--dim);font-size:12px;margin-top:12px;line-height:1.5}
#fatal{display:none;position:fixed;top:0;left:0;right:0;z-index:200;
  background:#7f1d1d;color:#fff;padding:11px 18px;font-size:13px;line-height:1.5;
  box-shadow:0 4px 20px rgba(0,0,0,.5)}
.inline-err{display:none;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.35);
  color:#fca5a5;border-radius:8px;padding:9px 12px;font-size:12.5px;margin-top:12px;line-height:1.45}
.inline-err.show{display:block}

select,textarea{font:inherit;background:var(--surface-2);color:var(--txt);
  border:1px solid var(--line);border-radius:9px;padding:9px 12px;width:100%;transition:.14s}
select:focus,textarea:focus{outline:none;border-color:var(--green-dim);
  box-shadow:0 0 0 3px rgba(34,197,94,.12)}
textarea{resize:vertical;line-height:1.5;font-family:inherit}
.tts-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:11px}
.tts-opts{display:flex;gap:20px;align-items:flex-end;flex-wrap:wrap;margin-top:14px}
.tts-opts > div{flex:1;min-width:150px}
.num{color:var(--green);font-weight:700;font-variant-numeric:tabular-nums}
input[type=range]{-webkit-appearance:none;appearance:none;height:4px;padding:0;
  background:var(--surface-2);border:0;border-radius:2px;cursor:pointer}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:15px;height:15px;
  border-radius:50%;background:var(--green);cursor:pointer;border:0}
input[type=range]::-moz-range-thumb{width:15px;height:15px;border-radius:50%;
  background:var(--green);cursor:pointer;border:0}
.chk{display:flex;align-items:center;gap:7px;color:var(--muted);
  font-size:13px;cursor:pointer;white-space:nowrap;padding-bottom:2px}
.chk input{width:auto;padding:0;accent-color:var(--green)}
.panel h2{display:flex;align-items:center;gap:8px}
.files{display:flex;flex-direction:column;gap:9px}
.file{display:flex;align-items:center;gap:12px;background:var(--surface-2);
  border:1px solid var(--line);border-radius:9px;padding:10px 13px;flex-wrap:wrap}
.file audio{height:32px;flex:1;min-width:210px}
.file-meta{min-width:0;flex:1.3}
.file-name{font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file-sub{color:var(--dim);font-size:11px;margin-top:2px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tts-out:empty{display:none}
.tts-out{margin-top:15px;padding-top:15px;border-top:1px solid var(--line)}
.tts-out audio{width:100%;height:38px;margin-bottom:11px}
.marks{display:flex;flex-wrap:wrap;gap:5px}
.mark{background:var(--surface-2);border:1px solid var(--line);border-radius:7px;
  padding:4px 9px;font-size:12px;cursor:default}
.mark b{font-weight:600}
.mark span{color:var(--dim);margin-left:6px;font-size:10.5px;font-variant-numeric:tabular-nums}
@media(max-width:760px){.tts-grid{grid-template-columns:1fr}
  .tts-grid > div[style]{grid-column:span 1 !important}}
</style>
</head>
<body>

<div id="fatal"></div>
<div id="toast"></div>

<!-- Script chính có thể chết vì lỗi cú pháp, khi đó không gì báo được cho
     người dùng. Đoạn nhỏ này chạy trước và độc lập, chỉ để hiện lỗi ra màn hình. -->
<script>
window.addEventListener('error', function (event) {
  var box = document.getElementById('fatal');
  if (!box) return;
  box.style.display = 'block';
  box.textContent = 'Lỗi giao diện: ' + (event.message || 'không rõ') +
    (event.lineno ? ' (dòng ' + event.lineno + ')' : '') +
    ' — thử tải lại trang bằng Ctrl+F5.';
});
window.addEventListener('unhandledrejection', function (event) {
  var box = document.getElementById('fatal');
  if (!box) return;
  box.style.display = 'block';
  box.textContent = 'Lỗi: ' + ((event.reason && event.reason.message) || event.reason);
});
</script>

<div class="gate" id="gate">
  <div class="panel">
    <div class="eyebrow">Quản trị</div>
    <h2>CapCut TTS</h2>
    <p>Nhập admin token để tiếp tục.</p>
    <input id="token" type="password" placeholder="ADMIN_TOKEN" onkeydown="if(event.key==='Enter')saveToken()">
    <button class="primary" style="width:100%;margin-top:12px" id="loginBtn" onclick="saveToken()">Đăng nhập</button>
    <div id="loginErr" class="inline-err"></div>
    <p class="hint">Token chỉ lưu trong trình duyệt này và gửi kèm mỗi request dưới dạng Bearer.</p>
  </div>
</div>

<div class="wrap" id="app" style="display:none">
  <div class="head">
    <div>
      <div class="eyebrow">Quản trị</div>
      <h1>Tài khoản CapCut</h1>
      <p class="lede">Theo dõi phiên đăng nhập dùng chung và trạng thái từng tài khoản.</p>
    </div>
    <div class="head-actions">
      <button class="ghost" onclick="load()" id="refreshBtn">Làm mới</button>
      <button class="ghost" onclick="logout()">Thoát</button>
    </div>
  </div>

  <div class="panel" style="margin-top:22px">
    <h2>Thêm tài khoản</h2>
    <div class="form">
      <div><label>Email CapCut</label><input id="email" placeholder="ten@gmail.com"></div>
      <div><label>Mật khẩu</label><input id="password" type="password" placeholder="••••••••"></div>
      <div><label>Ghi chú</label><input id="label" placeholder="tuỳ chọn"></div>
      <button class="primary" onclick="addAccount()" id="addBtn">Thêm</button>
    </div>
    <p class="hint">Mật khẩu được mã hoá AES-GCM trước khi lưu và không bao giờ trả về qua API.</p>
  </div>

  <div class="panel">
    <h2>Thử giọng</h2>
    <div class="tts-grid">
      <div><label>Tài khoản</label><select id="ttsAccount" onchange="loadVoices()"></select></div>
      <div><label>Ngôn ngữ</label><select id="ttsLang" onchange="loadVoices()">
        <option value="">Tất cả</option><option value="vi" selected>Tiếng Việt</option>
        <option value="en">Anh</option><option value="ja">Nhật</option>
        <option value="zh">Trung</option><option value="es">Tây Ban Nha</option>
        <option value="id">Indonesia</option><option value="th">Thái</option>
        <option value="pt">Bồ Đào Nha</option>
      </select></div>
      <div style="grid-column:span 2"><label>Giọng</label>
        <select id="ttsVoice"><option>— chọn tài khoản trước —</option></select></div>
    </div>
    <div style="margin-top:12px"><label>Nội dung</label>
      <textarea id="ttsText" rows="3" placeholder="Nhập văn bản cần đọc…">Xin chào, đây là bản thử giọng.</textarea></div>
    <div class="tts-opts">
      <div><label>Tốc độ <span id="spdV" class="num">10</span></label>
        <input type="range" id="ttsSpeed" min="1" max="20" value="10" oninput="spdV.textContent=this.value"></div>
      <div><label>Âm lượng <span id="volV" class="num">10</span></label>
        <input type="range" id="ttsVol" min="0" max="20" value="10" oninput="volV.textContent=this.value"></div>
      <label class="chk"><input type="checkbox" id="ttsMarks"> Kèm mốc từ</label>
      <label class="chk"><input type="checkbox" id="ttsSave" checked> Lưu vào R2</label>
      <button class="primary" id="ttsBtn" onclick="preview()">Phát thử</button>
    </div>
    <div id="ttsOut" class="tts-out"></div>
  </div>

  <div class="panel">
    <h2>File đã lưu trên R2 <button class="sm ghost" style="margin-left:auto" onclick="loadFiles()">Làm mới</button></h2>
    <div id="files"><div class="empty" style="padding:26px"><span class="spin"></span> Đang tải…</div></div>
  </div>

  <div class="toolbar">
    <div class="field">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="q" placeholder="Lọc theo email hoặc ghi chú" oninput="render()">
    </div>
  </div>

  <div class="stats" id="stats"></div>
  <div class="grid" id="grid"><div class="empty"><span class="spin"></span> Đang tải…</div></div>
</div>

<script>
const $ = (id) => document.getElementById(id);
let token = localStorage.getItem('capcut_admin_token') || '';
let data = [];

function toast(text, kind){
  const el = document.createElement('div');
  el.className = 'toast' + (kind === 'e' ? ' e' : '');
  el.textContent = text;
  $('toast').appendChild(el);
  setTimeout(() => el.remove(), kind === 'e' ? 7000 : 3400);
}

async function api(path, options){
  const res = await fetch('/admin/api' + path, {
    ...options,
    headers:{ 'Content-Type':'application/json', Authorization:'Bearer ' + token },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.message || ('HTTP ' + res.status));
  return body;
}

function showLoginErr(text){
  const box = $('loginErr');
  box.textContent = text;
  box.className = 'inline-err' + (text ? ' show' : '');
}

async function saveToken(){
  const value = $('token').value.trim();
  if (!value){ showLoginErr('Chưa nhập token.'); return; }

  const btn = $('loginBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Đang kiểm tra…';
  showLoginErr('');

  // xác thực trước khi lưu, để token sai không bị ghi vào localStorage
  try{
    const res = await fetch('/admin/api/accounts', {
      headers:{ Authorization:'Bearer ' + value },
    });

    if (res.status === 401 || res.status === 403){
      showLoginErr('Token không đúng. Kiểm tra lại ADMIN_TOKEN.');
      return;
    }
    if (!res.ok){
      const body = await res.json().catch(() => ({}));
      showLoginErr('Máy chủ trả lỗi ' + res.status + '. ' + (body.message || ''));
      return;
    }

    token = value;
    localStorage.setItem('capcut_admin_token', token);
    await load();
  }catch(err){
    showLoginErr('Không kết nối được máy chủ: ' + err.message);
  }finally{
    btn.disabled = false;
    btn.textContent = 'Đăng nhập';
  }
}

function logout(){
  localStorage.removeItem('capcut_admin_token');
  token = '';
  $('app').style.display = 'none';
  $('gate').style.display = '';
}

const ago = (ms) => {
  if (!ms) return '—';
  const s = Math.floor((Date.now() - ms)/1000);
  if (s < 60) return s + ' giây trước';
  if (s < 3600) return Math.floor(s/60) + ' phút trước';
  if (s < 86400) return Math.floor(s/3600) + ' giờ trước';
  return Math.floor(s/86400) + ' ngày trước';
};
const left = (ms) => {
  if (!ms) return '—';
  const s = Math.floor((ms - Date.now())/1000);
  if (s <= 0) return 'đã hết';
  if (s < 3600) return Math.ceil(s/60) + ' phút';
  return Math.round(s/3600) + ' giờ';
};

// trạng thái quyết định màu viền trái và nhãn
function statusOf(a){
  if (!a.enabled) return { key:'off', cls:'', chip:'c-off', text:'Đã tắt' };
  const s = a.session;
  if (!s) return { key:'wait', cls:'wait', chip:'c-wait', text:'Chưa có phiên' };
  if (s.failUntil > Date.now())
    return { key:'bad', cls:'bad', chip:'c-bad', text:'Tạm nghỉ ' + left(s.failUntil) };
  if (s.lockedUntil > Date.now())
    return { key:'wait', cls:'wait', chip:'c-wait', text:'Đang đăng nhập' };
  if (s.bytes < 3000)
    return { key:'bad', cls:'bad', chip:'c-bad', text:'Phiên thiếu cookie' };
  return { key:'ok', cls:'ok', chip:'c-ok', text:'Hoạt động' };
}

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function render(){
  const q = $('q').value.trim().toLowerCase();
  const rows = data.filter((a) =>
    !q || a.email.toLowerCase().includes(q) || (a.label||'').toLowerCase().includes(q));

  const count = { ok:0, wait:0, bad:0, off:0 };
  data.forEach((a) => count[statusOf(a).key]++);

  $('stats').innerHTML =
    '<span class="total">' + data.length + ' tài khoản</span>' +
    '<span class="chip c-ok"><i class="dot"></i>Hoạt động: ' + count.ok + '</span>' +
    '<span class="chip c-wait"><i class="dot"></i>Chờ phiên: ' + count.wait + '</span>' +
    '<span class="chip c-bad"><i class="dot"></i>Có vấn đề: ' + count.bad + '</span>' +
    '<span class="chip c-off"><i class="dot"></i>Đã tắt: ' + count.off + '</span>';

  if (!rows.length){
    $('grid').innerHTML =
      '<div class="empty">' +
      '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">' +
      '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18"/></svg>' +
      '<div>' + (data.length ? 'Không khớp bộ lọc' : 'Chưa có tài khoản nào') + '</div></div>';
    return;
  }

  $('grid').innerHTML = rows.map((a) => {
    const st = statusOf(a);
    const s = a.session;
    const e = encodeURIComponent(a.email);
    // 8 KB を満杯として健全度を出す 3 KB 未満は Cookie 欠けの目安
    const pct = s ? Math.min(100, Math.round((s.bytes/8400)*100)) : 0;

    return '<div class="card ' + st.cls + '">' +
      '<div class="card-top"><div>' +
        '<div class="mail">' + esc(a.email) + '</div>' +
        (a.label ? '<div class="tag">' + esc(a.label) + '</div>' : '') +
      '</div><span class="chip ' + st.chip + '"><i class="dot"></i>' + st.text + '</span></div>' +

      '<div class="meta">' +
        '<div><div class="k">Phiên</div><div class="v">' +
          (s && s.bytes ? s.bytes.toLocaleString() + ' B' : '—') +
          (s && s.bytes ? '<div class="bar"><i style="width:' + pct + '%"></i></div>' : '') +
        '</div></div>' +
        '<div><div class="k">Phiên bản</div><div class="v">' + (s ? 'v' + s.version : '—') + '</div></div>' +
        '<div><div class="k">Hết hạn sau</div><div class="v">' + (s ? left(s.expiresAt) : '—') + '</div></div>' +
        '<div><div class="k">Dùng lần cuối</div><div class="v">' + ago(a.lastUsedAt) + '</div></div>' +
      '</div>' +

      (a.lastError ? '<div class="err">' + esc(a.lastError.slice(0,160)) + '</div>' : '') +

      '<div class="acts">' +
        '<button class="sm" onclick="act(\\'' + e + '\\',\\'test\\',this)">Kiểm tra</button>' +
        '<button class="sm" onclick="act(\\'' + e + '\\',\\'reset\\',this)">Xoá phiên</button>' +
        '<button class="sm" onclick="act(\\'' + e + '\\',\\'clear-backoff\\',this)">Bỏ tạm nghỉ</button>' +
        '<button class="sm" onclick="act(\\'' + e + '\\',\\'' + (a.enabled?'disable':'enable') + '\\',this)">' +
          (a.enabled?'Tắt':'Bật') + '</button>' +
        '<button class="sm" style="color:var(--red)" onclick="del(\\'' + e + '\\')">Xoá</button>' +
      '</div></div>';
  }).join('');
}

// ---- thử giọng ----
function syncAccounts(){
  const sel = $('ttsAccount');
  const prev = sel.value;
  const usable = data.filter((a) => a.enabled);
  sel.innerHTML = usable.length
    ? usable.map((a) => '<option value="' + esc(a.email) + '">' + esc(a.email) + '</option>').join('')
    : '<option value="">— chưa có tài khoản —</option>';
  if (prev && usable.some((a) => a.email === prev)) sel.value = prev;
  else if (usable.length) loadVoices();
}

async function loadVoices(){
  const account = $('ttsAccount').value;
  const sel = $('ttsVoice');
  if (!account){ sel.innerHTML = '<option>— chưa có tài khoản —</option>'; return; }

  sel.innerHTML = '<option>đang tải…</option>';
  sel.disabled = true;
  try{
    const lang = $('ttsLang').value;
    const list = await api('/tts/voices?account=' + encodeURIComponent(account) +
      (lang ? '&language=' + lang : ''));
    sel.innerHTML = list.length
      ? list.map((v) => '<option value="' + esc(v.id) + '">' + esc(v.name || v.id) +
          ' · ' + esc(v.language) + (v.platform ? ' · ' + esc(v.platform) : '') + '</option>').join('')
      : '<option value="">— không có giọng —</option>';
  }catch(err){
    sel.innerHTML = '<option value="">— lỗi —</option>';
    toast(err.message,'e');
  }finally{ sel.disabled = false; }
}

async function preview(){
  const account = $('ttsAccount').value;
  const speaker = $('ttsVoice').value;
  const text = $('ttsText').value.trim();
  if (!account || !speaker) return toast('Chọn tài khoản và giọng','e');
  if (!text) return toast('Chưa nhập nội dung','e');

  const btn = $('ttsBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Đang tạo…';
  $('ttsOut').innerHTML = '';
  try{
    const r = await api('/tts/preview',{ method:'POST', body: JSON.stringify({
      account, text, speaker,
      speed: Number($('ttsSpeed').value),
      volume: Number($('ttsVol').value),
      timestamps: $('ttsMarks').checked,
      save: $('ttsSave').checked,
    })});

    let html = '<audio controls autoplay src="data:' + r.contentType + ';base64,' + r.audio + '"></audio>';
    if (r.words && r.words.length){
      html += '<div class="k" style="margin-bottom:7px">' + r.words.length + ' mốc từ' +
        (r.duration ? ' · ' + r.duration + 's' : '') + '</div><div class="marks">' +
        r.words.map((w) => '<span class="mark"><b>' + esc(w.word) + '</b><span>' +
          w.start.toFixed(2) + '–' + w.end.toFixed(2) + 's</span></span>').join('') + '</div>';
    }
    if (r.savedKey){
      html += '<div class="k" style="margin-top:10px">Đã lưu R2: ' + esc(r.savedKey) + '</div>';
    }
    $('ttsOut').innerHTML = html;
    toast(r.savedKey ? 'Đã tạo và lưu vào R2' : 'Đã tạo giọng');
    if (r.savedKey) loadFiles();
  }catch(err){ toast(err.message,'e'); }
  finally{ btn.disabled = false; btn.textContent = 'Phát thử'; }
}

const kb = (n) => n < 1024 ? n + ' B' : (n/1024).toFixed(0) + ' KB';

async function loadFiles(){
  try{
    const files = await api('/files');
    if (!files.length){
      $('files').innerHTML = '<div class="empty" style="padding:30px">Chưa có file nào</div>';
      return;
    }
    $('files').innerHTML = '<div class="files">' + files.map((f) => {
      const url = '/admin/api/files/' + f.key.split('/').map(encodeURIComponent).join('/');
      return '<div class="file">' +
        '<div class="file-meta">' +
          '<div class="file-name">' + esc(f.text || f.key.split('/').pop()) + '</div>' +
          '<div class="file-sub">' + esc(f.speaker) + ' · ' + kb(f.size) + ' · ' + ago(f.uploadedAt) + '</div>' +
        '</div>' +
        // トークンが要るので src には直接置けない 取得してから blob にする
        '<audio controls preload="none" data-key="' + esc(f.key) + '" onplay="hydrate(this)"></audio>' +
        '<button class="sm" onclick="dl(\\'' + esc(f.key) + '\\')">Tải</button>' +
        '<button class="sm" style="color:var(--red)" onclick="delFile(\\'' + esc(f.key) + '\\')">Xoá</button>' +
      '</div>';
    }).join('') + '</div>';
  }catch(err){ toast(err.message,'e'); }
}

// audio の src にトークンは載せられないので、取得して blob URL に差し替える
async function fetchBlob(key){
  const res = await fetch('/admin/api/files/' + key.split('/').map(encodeURIComponent).join('/'),
    { headers:{ Authorization:'Bearer ' + token } });
  if (!res.ok) throw new Error('Không tải được file');
  return URL.createObjectURL(await res.blob());
}

async function hydrate(el){
  if (el.src) return;
  try{ el.src = await fetchBlob(el.dataset.key); el.play(); }
  catch(err){ toast(err.message,'e'); }
}

async function dl(key){
  try{
    const a = document.createElement('a');
    a.href = await fetchBlob(key);
    a.download = key.split('/').pop();
    a.click();
  }catch(err){ toast(err.message,'e'); }
}

async function delFile(key){
  if (!confirm('Xoá file này khỏi R2?')) return;
  try{
    await api('/files/' + key.split('/').map(encodeURIComponent).join('/'), { method:'DELETE' });
    toast('Đã xoá');
    loadFiles();
  }catch(err){ toast(err.message,'e'); }
}

async function load(){
  const btn = $('refreshBtn');
  if (btn){ btn.disabled = true; btn.innerHTML = '<span class="spin"></span>'; }
  try{
    data = await api('/accounts');
    $('gate').style.display = 'none';
    $('app').style.display = '';
    render();
    syncAccounts();
    loadFiles();
  }catch(err){
    toast(err.message,'e');
    if (/token/i.test(err.message)) logout();
  }finally{
    if (btn){ btn.disabled = false; btn.textContent = 'Làm mới'; }
  }
}

async function addAccount(){
  const email = $('email').value.trim(), password = $('password').value;
  if (!email || !password) return toast('Cần cả email và mật khẩu','e');
  const btn = $('addBtn'); btn.disabled = true;
  try{
    await api('/accounts',{ method:'POST',
      body: JSON.stringify({ email, password, label: $('label').value.trim() }) });
    $('email').value = $('password').value = $('label').value = '';
    toast('Đã thêm ' + email);
    await load();
  }catch(err){ toast(err.message,'e'); }
  finally{ btn.disabled = false; }
}

async function act(email, action, btn){
  const old = btn.textContent;
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>';
  try{
    const r = await api('/accounts/' + email + '/' + action, { method:'POST' });
    if (action === 'test') toast(r.ok ? r.detail : 'Lỗi: ' + r.detail, r.ok ? 's' : 'e');
    else toast('Đã ' + old.toLowerCase());
    await load();
  }catch(err){ toast(err.message,'e'); btn.disabled = false; btn.textContent = old; }
}

async function del(email){
  if (!confirm('Xoá tài khoản này và phiên của nó?')) return;
  try{
    await api('/accounts/' + email, { method:'DELETE' });
    toast('Đã xoá');
    await load();
  }catch(err){ toast(err.message,'e'); }
}

if (token) load();
setInterval(() => { if (token && $('app').style.display !== 'none') load(); }, 30000);
</script>
</body>
</html>`;
