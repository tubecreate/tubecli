'use strict';
/*
 * Kho nguyên liệu — túi ảnh / GIF / video dùng chung cho mọi extension.
 *
 * Bố cục là một thư viện ảnh: cột kho bên trái luôn thấy, sân khấu ở giữa, ô
 * soi bên phải. Sân khấu có HAI màn hình, chọn bằng hash:
 *   #/         → lưới kho (màn hình mở đầu)
 *   #/c/<mã>   → bên trong một kho
 * Vào thẳng một đường dẫn, bấm back/forward của trình duyệt đều ra đúng màn
 * hình — hash là nguồn sự thật, `state.view` chỉ đi theo nó.
 *
 * Nguyên tắc của file này:
 *  - Nguồn sự thật là MÁY CHỦ. Mọi lần thêm/xoá/đổi tên đều đọc lại kho bằng
 *    GET /collections/<mã> chứ không tự sửa mảng trên màn hình: `cursor` của
 *    chế độ xoay vòng và ảnh bìa do backend tính, đoán mò ở trình duyệt là hai
 *    bên lệch nhau mà không ai biết.
 *  - Ảnh và video lấy THẲNG từ API bằng thuộc tính src, không tải qua fetch.
 *    Nhờ vậy trang này không tạo objectURL nào — không có gì phải thu hồi, và
 *    một kho 300 tấm cũng không nuốt hết bộ nhớ như khi giữ 300 blob.
 *  - Hỏng thì phải THẤY: mọi lượt gọi hỏng đều đổ một câu tiếng Việt ra dòng
 *    trạng thái ở chân trang. Riêng tải lên thì lỗi từng tệp một, tệp sau vẫn
 *    chạy tiếp — bỏ dở cả lượt vì một tấm sai định dạng là thói xấu.
 *  - Tệp trong kho DÙNG LẠI mãi mãi: cùng một tấm nền được lấy đi lấy lại, mỗi
 *    thumbnail chỉ khác nhau ở phần chữ. Nên trang này không bao giờ nói kho
 *    «đã dùng hết», «sắp cạn» hay «còn mấy tệp nữa». Xoay vòng chỉ là cách đi
 *    lần lượt cho khỏi lấy trùng một tấm hai lần liền; trạng thái hỏng duy
 *    nhất của một kho là RỖNG.
 *  - API chỉ trả {name, kind, bytes}: không có số lần dùng, không có chỉ mục
 *    «mẫu nào đang gọi tới kho». Chỗ nào không có dữ liệu thì nói thẳng là
 *    chưa có, không bịa một con số cho đẹp ô soi.
 */

const API = '/api/v1/media';

const KIND_VI = { image: 'ảnh', gif: 'GIF', video: 'video' };
const KIND_TAG = { image: 'ẢNH', gif: 'GIF', video: 'VIDEO' };
const KIND_ORDER = ['image', 'gif', 'video'];

/* Ô nhỏ hơn ngưỡng này thì tên tệp hiện thường trực: ở cỡ 100px, chữ là thứ
   duy nhất phân biệt được hai tấm hậu cảnh gần giống nhau. */
const NAME_ALWAYS_BELOW = 142;
const GRID_GAP = 4;

const MODE_HINT = {
  random: 'Ngẫu nhiên: mỗi lần gọi lấy một tệp bất kỳ, có thể trùng tệp lần trước.',
  cycle: 'Xoay vòng: đi lần lượt theo thứ tự trong lưới cho khỏi lấy trùng một tấm hai lần liền — ô viền nét đứt là tấm lần tới.',
  ai: 'AI chọn: bấm vào một ô để chỉ đích danh tệp, rồi bấm «Bốc thử».'
};

const MODE_NAME = { random: 'Ngẫu nhiên', cycle: 'Xoay vòng', ai: 'AI chọn' };

/* Biểu tượng: chuỗi SVG hằng, KHÔNG bao giờ ghép dữ liệu người dùng vào đây —
   mọi thứ đến từ máy chủ đều đi qua textContent. */
const ICO = {
  copy: '<svg class="i" viewBox="0 0 16 16"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M2.5 10.5V4a1.5 1.5 0 0 1 1.5-1.5h6.5"/></svg>',
  pen: '<svg class="i" viewBox="0 0 16 16"><path d="m11 2.5 2.5 2.5L6 12.5H3.5V10z"/></svg>',
  trash: '<svg class="i" viewBox="0 0 16 16"><path d="M3 4.5h10M6.5 2.5h3M5 4.5l.6 8.5h4.8l.6-8.5"/></svg>',
  sun: '<svg class="i" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/></svg>',
  moon: '<svg class="i" viewBox="0 0 16 16"><path d="M13.5 9.5A6 6 0 0 1 6.5 2.5a6 6 0 1 0 7 7z"/></svg>',
  auto: '<svg class="i" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6"/><path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" stroke="none"/></svg>',
  play: '<svg viewBox="0 0 16 16" width="11" height="11" fill="currentColor"><path d="M4 2.5v11l9-5.5z"/></svg>',
  next: '<svg viewBox="0 0 16 16" width="9" height="9" fill="currentColor"><path d="M4 2.5v11l9-5.5z"/></svg>'
};

const state = {
  view: 'list',        // 'list' | 'col' — khớp với hash
  collections: [],     // tóm tắt cho lưới và cột trái, từ GET /collections
  stats: { collections: 0, files: 0, dir: '' },
  filter: '',          // ô tìm trên thanh trên — lọc kho ở màn 1, lọc tệp ở màn 2
  col: null,           // kho đang mở (kèm files + cursor)
  mode: 'random',      // cách bốc đang chọn, gương của <select id="pickMode">
  sel: '',             // tệp người dùng bấm chọn
  picked: '',          // tệp vừa bốc được, để tô sáng trong lưới
  uploading: false,
  dragDepth: 0,        // đếm dragenter/dragleave, xem chú thích ở bindDropZone
  pendingDrop: '',     // đường dẫn canvas thả sang lúc chưa mở kho nào
  size: 170,           // cỡ hàng trong lưới tệp, theo thanh trượt
  ar: {},              // tỉ lệ khung hình thật, đo được sau khi ảnh tải xong
  dim: {}              // «1024 × 1280» của cùng tấm đó — API không trả về
};

/* Ô trong lưới tệp, giữ nguyên phần tử qua các lần xếp lại: dựng lại thẻ <img>
   là trình duyệt tải lại ảnh và lưới nháy trắng mỗi lần kéo thanh trượt. */
let gridTiles = [];
let layoutRaf = 0;

/* ── Tiện ích DOM ────────────────────────────────────────────────────── */

const $ = (sel, root) => (root || document).querySelector(sel);

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function ico(name, cls) {
  const s = el('span', cls || 'ic');
  s.style.display = 'inline-flex';
  s.innerHTML = ICO[name] || '';
  return s;
}

function enc(s) { return encodeURIComponent(String(s == null ? '' : s)); }

function clip(s, n) {
  s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

/* Escape cho selector thuộc tính — tên tệp đã được backend lọc về ASCII nhưng
   vẫn phòng dấu ngoặc kép lọt vào từ một bản dữ liệu cũ. */
function cssq(s) { return String(s).replace(/["\\]/g, '\\$&'); }

/* Một câu trạng thái, đổ ra CẢ HAI màn hình: lỗi xoá kho xảy ra ở lưới kho,
   lỗi tải tệp xảy ra ở trong kho, mà chỉ có một hàm để gọi. */
function msg(text, kind) {
  const cls = 'msg' + (kind ? ' ' + kind : '');
  ['#listStatusMsg', '#colStatusMsg'].forEach(function (id) {
    const n = $(id);
    if (!n) return;
    n.textContent = text || '';
    n.className = cls;
  });
}

/* Cỡ tệp cho người đọc. Dấu phẩy thập phân theo cách viết tiếng Việt. */
function fmtBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' B';
  const dec = function (x) { return (Math.round(x * 10) / 10).toFixed(1).replace('.', ','); };
  if (n < 1048576) return dec(n / 1024) + ' KB';
  if (n < 1073741824) return dec(n / 1048576) + ' MB';
  return dec(n / 1073741824) + ' GB';
}

/* {image:12, video:3} → «12 ảnh · 3 video». Đếm theo LOẠI chứ không chỉ tổng:
   một kho 40 tệp toàn video dùng khác hẳn một kho 40 tấm ảnh. */
function kindsLine(kinds) {
  const k = kinds || {};
  const parts = KIND_ORDER.filter(function (x) { return k[x]; })
                          .map(function (x) { return k[x] + ' ' + KIND_VI[x]; });
  return parts.join(' · ');
}

/* «2 giờ trước» / «hôm qua» / «12/09». Giờ tuyệt đối trên thẻ không nói lên
   gì: cái người ta cần biết là kho nào vừa đụng tới. */
function relTime(ts) {
  const t = Number(ts) * 1000;
  if (!t || isNaN(t)) return '';
  const now = new Date();
  const then = new Date(t);
  const day = function (d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); };
  const days = Math.round((day(now) - day(then)) / 86400000);
  if (days <= 0) {
    const s = Math.max(0, Math.round((now.getTime() - t) / 1000));
    if (s < 90) return 'vừa xong';
    if (s < 3600) return Math.round(s / 60) + ' phút trước';
    return Math.round(s / 3600) + ' giờ trước';
  }
  if (days === 1) return 'hôm qua';
  if (days < 7) return days + ' ngày trước';
  const dd = ('0' + then.getDate()).slice(-2);
  const mm = ('0' + (then.getMonth() + 1)).slice(-2);
  return dd + '/' + mm + (then.getFullYear() === now.getFullYear() ? '' : '/' + then.getFullYear());
}

function extOf(name) {
  const m = /\.([A-Za-z0-9]+)$/.exec(String(name || ''));
  return m ? m[1].toUpperCase() : '';
}

function copyText(text, label) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { msg('Đã chép ' + (label || text) + ' vào bộ nhớ tạm.', 'ok'); },
        function (e) { msg('Không chép được vào bộ nhớ tạm: ' + (e && e.message ? e.message : e), 'warn'); });
      return;
    }
  } catch (e) { /* rơi xuống dưới */ }
  msg('Trình duyệt không cho chép tự động — chọn tay: ' + text, 'warn');
}

/* ── Gọi API ─────────────────────────────────────────────────────────── */

async function hit(path, opts) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    // Kèm luôn phần thân lỗi: backend trả câu giải thích tiếng Việt ở đó, giấu
    // đi là người dùng chỉ thấy một con số 400 chẳng nói lên điều gì.
    let detail = '';
    try { detail = clip(await res.text(), 180); } catch (e) { /* thân rỗng */ }
    throw new Error(res.status + (detail ? ' — ' + detail : ' ' + res.statusText));
  }
  return res;
}

async function jget(path) { return (await hit(path)).json(); }

async function jsend(method, path, body) {
  return (await hit(path, {
    method: method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })).json();
}

function fileUrl(cid, name, ver) {
  // ?v= theo lần sửa cuối của kho: thiếu nó thì xoá rồi tải lên một tên trùng
  // vẫn thấy tấm cũ, vì URL không đổi nên trình duyệt giữ nguyên bản trong
  // bộ nhớ đệm.
  return API + '/collections/' + enc(cid) + '/files/' + enc(name) +
         (ver ? '?v=' + Math.round(ver) : '');
}

/* ── Cột trái: mọi kho, luôn nhìn thấy ───────────────────────────────── */

function coverPlaceholder(text) {
  const d = el('div', 'pcard-empty');
  d.appendChild(el('div', 'glyph', '▦'));
  d.appendChild(el('div', null, text || 'kho rỗng'));
  return d;
}

function coverImg(c, alt) {
  const img = el('img');
  img.loading = 'lazy';
  img.alt = alt;
  img.src = fileUrl(c.id, c.cover, c.updated_at);
  return img;
}

function renderRail() {
  const list = $('#railList');
  list.textContent = '';

  state.collections.forEach(function (c) {
    const item = el('button', 'pcard rail-item');
    item.type = 'button';
    item.dataset.id = c.id;
    if (state.col && state.col.id === c.id) item.classList.add('on');
    item.title = 'Mở «' + (c.name || c.id) + '» · mã ' + c.id;

    const shot = el('div', 'rail-shot');
    if (c.cover) {
      const img = coverImg(c, '');
      // Bìa là tệp ĐẦU TIÊN theo tên, có thể là video: thẻ <img> không dựng nổi
      // video nên rơi về ô trống thay vì để một khung vỡ.
      img.addEventListener('error', function () { img.remove(); });
      shot.appendChild(img);
    }
    item.appendChild(shot);

    const t = el('div', 'rail-t');
    t.appendChild(el('div', 'rail-n', c.name || '(không tên)'));

    const m = el('div', 'rail-m');
    const n = Number(c.count) || 0;
    // Chấm đỏ CHỈ khi kho rỗng. Kho có tệp là kho bình thường, dù có một tấm:
    // tệp được dùng đi dùng lại nên một tấm cũng chạy được mãi.
    if (!n) {
      const dot = el('span', 'hdot');
      dot.title = 'Kho rỗng';
      m.appendChild(dot);
    }
    m.appendChild(el('span', null, n ? (kindsLine(c.kinds) || n + ' tệp') : 'rỗng'));
    t.appendChild(m);
    item.appendChild(t);

    item.addEventListener('click', function () { goCollection(c.id); });
    list.appendChild(item);
  });

  if (!state.collections.length) {
    const none = el('div', 'rail-f', 'Chưa có kho nào.');
    none.style.borderTop = '0';
    list.appendChild(none);
  }

  // Câu tóm tắt: chỉ nói khi có kho RỖNG, vì đó là trạng thái duy nhất làm
  // hỏng việc — mẫu trỏ vào kho rỗng thì lớp ảnh ra trống trơn.
  const empty = state.collections.filter(function (c) { return !Number(c.count); });
  const warn = $('#railWarn');
  warn.hidden = !empty.length;
  warn.textContent = empty.length
    ? empty.length + ' kho rỗng — mẫu trỏ vào sẽ ra lớp trống'
    : '';
  warn.title = empty.map(function (c) { return c.name || c.id; }).join(', ');

  renderRailFoot();
}

/* Chân cột: không có hạn mức đĩa nào để vẽ đồng hồ, nên nói đúng thứ đang có —
   tổng số tệp toàn thư viện và dung lượng của kho đang mở. */
function renderRailFoot() {
  const f = $('#railFoot');
  f.textContent = '';
  const s = state.stats || {};

  const l1 = el('div');
  l1.appendChild(el('b', null, String(s.collections || 0)));
  l1.appendChild(document.createTextNode(' kho · '));
  l1.appendChild(el('b', null, String(s.files || 0)));
  l1.appendChild(document.createTextNode(' tệp'));
  f.appendChild(l1);

  if (state.col) {
    const files = state.col.files || [];
    const total = files.reduce(function (a, x) { return a + (x.bytes || 0); }, 0);
    f.appendChild(el('div', null,
      'Kho đang mở: ' + files.length + ' tệp · ' + fmtBytes(total)));
  } else if (s.dir) {
    const d = el('div', null, s.dir);
    d.style.cssText = 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
    d.title = 'Thư mục trên đĩa: ' + s.dir;
    f.appendChild(d);
  }
}

/* ── Màn hình 1: lưới kho ────────────────────────────────────────────── */

async function loadCollections() {
  try {
    const d = await jget('/collections');
    state.collections = d.collections || [];
    state.stats = d.stats || { collections: 0, files: 0, dir: '' };
    renderRail();
    renderList();
    // Vẽ lại inspector ở CẢ hai màn: mở thẳng vào một kho thì stats về sau
    // khi kho đã vẽ, không vẽ lại là «Toàn thư viện: 0 tệp» đứng đó mãi.
    renderInspector();
  } catch (err) {
    state.collections = [];
    renderRail();
    renderList();
    if (state.view === 'list') renderInspector();
    msg('Không lấy được danh sách kho: ' + err.message, 'err');
  }
}

function renderList() {
  const grid = $('#colGrid');
  grid.textContent = '';

  const q = (state.view === 'list' ? state.filter : '').trim().toLowerCase();
  const arr = state.collections.filter(function (c) {
    if (!q) return true;
    return (String(c.name || '') + ' ' + String(c.description || ''))
             .toLowerCase().indexOf(q) >= 0;
  });

  const s = state.stats || {};
  const base = (s.collections || 0) + ' kho · ' + (s.files || 0) + ' tệp';
  const foot = $('#colStats');
  foot.textContent = q ? (arr.length + '/' + (s.collections || 0) + ' kho khớp · ' + base) : base;
  foot.title = s.dir ? 'Thư mục trên đĩa: ' + s.dir : '';

  const sub = $('#listSub');
  sub.textContent = state.collections.length
    ? base + ' — bấm một kho để mở'
    : 'Chưa có kho nào';

  if (!state.collections.length) { grid.appendChild(emptyState()); return; }
  if (!arr.length) {
    grid.appendChild(el('div', 'gal-empty', 'Không có kho nào tên hay mô tả chứa «' + q + '».'));
    return;
  }
  arr.forEach(function (c) { grid.appendChild(colCard(c)); });
}

function emptyState() {
  const box = el('div', 'gal-empty');
  box.appendChild(el('h2', null, 'Chưa có kho nào'));
  box.appendChild(el('p', null,
    'Một kho là một túi nguyên liệu có tên: ảnh, GIF, video để chung một chỗ. ' +
    'Extension khác chỉ cần trỏ vào mã kho rồi để máy bốc — ngẫu nhiên, xoay ' +
    'vòng hay để AI chọn — nên cùng một tấm không phải tải lên năm lần nữa.'));
  const row = el('div', 'row');
  const b = el('button', 'btn primary', '+ Tạo kho');
  b.type = 'button';
  b.addEventListener('click', function () { openCreate(); });
  row.appendChild(b);
  box.appendChild(row);
  return box;
}

function closeMenus() {
  const ms = document.querySelectorAll('.pmenu');
  for (let i = 0; i < ms.length; i++) ms[i].hidden = true;
}

function colCard(c) {
  const card = el('article', 'pcard');
  card.dataset.id = c.id;

  const shot = el('button', 'pcard-shot');
  shot.type = 'button';
  shot.title = 'Mở «' + (c.name || c.id) + '»';
  if (c.cover) {
    const img = coverImg(c, 'Ảnh bìa của kho ' + (c.name || c.id));
    img.addEventListener('error', function () {
      img.remove();
      shot.appendChild(coverPlaceholder('không xem trước được'));
    });
    shot.appendChild(img);
  } else {
    shot.appendChild(coverPlaceholder());
  }
  shot.addEventListener('click', function () { goCollection(c.id); });
  card.appendChild(shot);

  const body = el('div', 'pcard-body');
  const row = el('div', 'pcard-namerow');
  const name = el('button', 'pcard-name', c.name || '(không tên)');
  name.type = 'button';
  name.title = c.name || '';
  name.addEventListener('click', function () { goCollection(c.id); });
  row.appendChild(name);

  const more = el('button', 'icobtn pcard-more', '⋯');
  more.type = 'button';
  more.title = 'Việc khác với kho này';
  more.setAttribute('aria-haspopup', 'true');
  row.appendChild(more);
  body.appendChild(row);

  const desc = el('div', 'pcard-desc' + (c.description ? '' : ' empty'),
                  c.description || 'Chưa có mô tả');
  desc.title = c.description || '';
  body.appendChild(desc);

  const meta = el('div', 'pcard-meta muted');
  if (!Number(c.count)) {
    const dot = el('span', 'hdot');
    dot.title = 'Kho rỗng';
    meta.appendChild(dot);
  }
  meta.appendChild(el('span', null,
    [Number(c.count) ? (kindsLine(c.kinds) || c.count + ' tệp') : 'rỗng', relTime(c.updated_at)]
      .filter(function (x) { return x; }).join(' · ')));
  body.appendChild(meta);
  card.appendChild(body);

  const conf = el('div', 'pconfirm');
  conf.hidden = true;
  card.appendChild(conf);

  const menu = el('div', 'pmenu');
  menu.hidden = true;
  [['Đổi tên', function () { beginCardRename(card, c); }],
   ['Xoá', function () { askDeleteCollection(conf, c); }, 'danger']
  ].forEach(function (item) {
    const b = el('button', 'pmenu-i' + (item[2] ? ' ' + item[2] : ''), item[0]);
    b.type = 'button';
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();
      menu.hidden = true;
      item[1]();
    });
    menu.appendChild(b);
  });
  card.appendChild(menu);

  more.addEventListener('click', function (ev) {
    ev.stopPropagation();
    const show = menu.hidden;
    closeMenus();
    menu.hidden = !show;
  });

  return card;
}

/* Xoá hỏi ngay tại chỗ. KHÔNG dùng window.confirm: trang này chạy trong iframe
   của bảng điều khiển, hộp của trình duyệt hiện lạc hẳn ngữ cảnh. */
function askDeleteCollection(conf, c) {
  conf.textContent = '';
  conf.hidden = false;
  conf.appendChild(el('span', null,
    'Xoá kho «' + clip(c.name, 34) + '»' +
    (c.count ? ' cùng ' + c.count + ' tệp bên trong' : '') + '? Không lấy lại được.'));

  const keepBox = el('label', 'keep');
  const keep = el('input');
  keep.type = 'checkbox';
  keepBox.appendChild(keep);
  keepBox.appendChild(el('span', null, 'Giữ lại tệp trên đĩa, chỉ bỏ kho khỏi danh sách'));
  conf.appendChild(keepBox);

  const yes = el('button', 'btn sm danger', 'Xoá');
  yes.type = 'button';
  yes.addEventListener('click', function () {
    conf.hidden = true;
    deleteCollection(c, keep.checked);
  });
  const no = el('button', 'btn sm', 'Huỷ');
  no.type = 'button';
  no.addEventListener('click', function () { conf.hidden = true; conf.textContent = ''; });
  conf.appendChild(yes);
  conf.appendChild(no);
}

async function deleteCollection(c, keepFiles) {
  const wasOpen = !!(state.col && state.col.id === c.id);
  try {
    await hit('/collections/' + enc(c.id) + '?keep_files=' + (keepFiles ? 'true' : 'false'),
              { method: 'DELETE' });
    msg('Đã xoá kho «' + clip(c.name, 34) + '»' +
        (keepFiles ? ' — tệp vẫn còn trên đĩa.' : '.'), 'ok');
  } catch (err) {
    msg('Xoá kho hỏng: ' + err.message, 'err');
    await loadCollections();
    return;
  }
  // Vừa xoá đúng kho đang mở thì phải ra khỏi nó, không thì màn hình còn đứng
  // trong một kho không còn tồn tại và mọi nút đều 404.
  if (wasOpen) { state.col = null; goList(); return; }
  await loadCollections();
}

function beginCardRename(card, c) {
  const row = $('.pcard-namerow', card);
  const btn = $('.pcard-name', card);
  if (!row || !btn) return;

  const i = el('input', 'in pcard-rename');
  i.type = 'text';
  i.value = c.name || '';
  i.setAttribute('aria-label', 'Tên kho');

  let done = false;
  async function finish(keep) {
    if (done) return;      // Enter rồi blur nổ liền nhau: chỉ nhận lần đầu
    done = true;
    i.remove();
    btn.hidden = false;
    const v = i.value.trim();
    if (!keep || !v || v === c.name) return;
    try {
      const r = await jsend('PUT', '/collections/' + enc(c.id), { name: v });
      c.name = (r.collection && r.collection.name) || v;
      btn.textContent = c.name;
      btn.title = c.name;
      msg('Đã đổi tên kho thành «' + c.name + '».', 'ok');
      await loadCollections();
    } catch (err) {
      msg('Đổi tên kho hỏng: ' + err.message, 'err');
    }
  }

  i.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); finish(true); }
    else if (ev.key === 'Escape') { ev.preventDefault(); finish(false); }
  });
  i.addEventListener('blur', function () { finish(true); });

  btn.hidden = true;
  row.insertBefore(i, btn);
  i.focus();
  i.select();
}

/* ── Màn hình 2: bên trong một kho ───────────────────────────────────── */

async function openCollection(cid) {
  // Tệp kéo từ canvas lúc còn đứng ở lưới kho: giờ đã biết kho, chép vào ngay.
  const pending = state.pendingDrop;
  if (pending) { state.pendingDrop = ''; setTimeout(function () { importPath(pending); }, 300); }
  let c;
  try {
    c = await jget('/collections/' + enc(cid));
  } catch (err) {
    msg('Mở kho «' + cid + '» hỏng: ' + err.message, 'err');
    state.col = null;
    setView('list');
    await loadCollections();
    return;
  }
  state.col = c;
  state.sel = '';
  state.picked = '';
  setView('col');
  renderCollection();
  if (!state.collections.length) loadCollections();
  else renderRail();
  // Dọn câu LỖI cũ nhưng giữ câu vừa báo (ví dụ «đã tạo kho …»): vừa tạo xong
  // đã bị xoá mất dòng báo mã kho thì người dùng không biết trỏ extension khác
  // vào đâu.
  const cur = $('#colStatusMsg');
  if (!cur.textContent || cur.classList.contains('err')) {
    msg(c.count ? '' : 'Kho đang rỗng — kéo tệp thả vào bất cứ đâu trên trang, hoặc bấm «Tải lên».');
  }
}

/* Đọc lại kho sau mỗi lần sửa. Giữ nguyên ô đang chọn và ô vừa bốc NẾU tệp đó
   còn — mất highlight sau mỗi lần xoá một tấm khác là khó chịu vô cớ. */
async function reloadCollection() {
  if (!state.col) return;
  try {
    const c = await jget('/collections/' + enc(state.col.id));
    state.col = c;
    const has = function (n) {
      return n && (c.files || []).some(function (f) { return f.name === n; });
    };
    if (!has(state.sel)) state.sel = '';
    if (!has(state.picked)) state.picked = '';
    renderCollection();
    loadCollections();          // cột trái và số liệu chung cũng phải theo kịp
  } catch (err) {
    msg('Đọc lại kho hỏng: ' + err.message + ' — bấm «← Kho» rồi mở lại.', 'err');
  }
}

function renderCollection() {
  const c = state.col;
  if (!c) return;

  $('#colName').textContent = c.name || '(không tên)';
  $('#colName').title = 'Bấm để đổi tên · mã kho: ' + c.id;
  $('#colName').hidden = false;
  $('#colNameIn').hidden = true;

  const d = $('#colDesc');
  d.textContent = c.description || 'Chưa có mô tả — bấm để viết';
  d.classList.toggle('empty', !c.description);
  d.title = c.description || 'Bấm để sửa mô tả';
  d.hidden = false;
  $('#colDescIn').hidden = true;

  const chip = $('#colKinds');
  chip.textContent = kindsLine(c.kinds);
  chip.hidden = !c.count;

  renderFiles();
  renderNextInfo();
  renderInspector();
  renderRailFoot();
}

/* Vị trí kế tiếp của vòng xoay, theo con trỏ do máy chủ giữ. Chỉ có nghĩa ở
   chế độ xoay vòng: con trỏ chẳng nói lên gì với bốc ngẫu nhiên, hiện nó ra
   chỉ làm người dùng tưởng máy đang thiên vị. */
function nextIndex() {
  const c = state.col;
  if (!c || state.mode !== 'cycle') return -1;
  const files = c.files || [];
  const cur = Number(c.cursor);
  return (cur >= 0 && cur < files.length) ? cur : -1;
}

function nextName() {
  const i = nextIndex();
  return i < 0 ? '' : (state.col.files[i].name);
}

/* Câu một dòng cạnh thanh công cụ. Nói về LƯỢT TỚI, không nói về hàng tồn:
   tệp trong kho dùng lại mãi, không có chuyện đi hết rồi cạn. */
function renderNextInfo() {
  const box = $('#nextInfo');
  box.textContent = '';
  const c = state.col;
  if (!c) return;
  const files = c.files || [];

  if (!files.length) {
    box.appendChild(el('span', null, 'Kho rỗng — mẫu trỏ vào kho này sẽ ra một lớp trống.'));
    return;
  }
  if (state.mode === 'cycle') {
    const i = nextIndex();
    const pill = el('span', 'pill');
    pill.appendChild(ico('next'));
    pill.appendChild(document.createTextNode('lần tới'));
    box.appendChild(pill);
    box.appendChild(el('b', null, i < 0 ? '(chưa xác định)' : files[i].name));
    if (i >= 0) box.appendChild(el('span', null, '(' + (i + 1) + '/' + files.length + ')'));
    return;
  }
  if (state.mode === 'random') {
    box.appendChild(el('span', null,
      'Mỗi lần gọi lấy một tệp bất kỳ trong ' + files.length + ' tệp.'));
    return;
  }
  box.appendChild(el('span', null, state.sel
    ? 'AI chọn: đang chỉ đích danh «' + clip(state.sel, 42) + '».'
    : 'AI chọn: bấm một ô trong lưới để chỉ đích danh tệp.'));
}

/* ── Lưới tệp đều mép ────────────────────────────────────────────────────
   Đọc từ trái sang phải, hết hàng xuống hàng dưới là ĐÚNG thứ tự vòng xoay của
   máy chủ (list_files sắp theo tên). Chiều cao mỗi hàng tính từ tỉ lệ khung
   hình thật, đo được sau khi ảnh tải xong; trước đó tạm coi là vuông. */

function arKey(name) { return (state.col ? state.col.id : '') + '|' + name; }
function arOf(f) { return state.ar[arKey(f.name)] || 1; }

function layoutRows(files, width, target) {
  const rows = [];
  let row = [], sum = 0;
  for (let i = 0; i < files.length; i++) {
    row.push(files[i]);
    sum += arOf(files[i]);
    // Đủ chật để lấp kín một hàng: co lại cho vừa đúng bề ngang.
    if (sum * target + GRID_GAP * (row.length - 1) >= width) {
      rows.push({ h: (width - GRID_GAP * (row.length - 1)) / sum, items: row, full: true });
      row = []; sum = 0;
    }
  }
  // Hàng cuối KHÔNG kéo giãn: hai tấm cuối phình to hết bề ngang trông như lỗi.
  if (row.length) rows.push({ h: target, items: row, full: false });
  return rows;
}

function layoutGrid() {
  const grid = $('#fileGrid');
  if (!grid || !gridTiles.length) return;
  const width = Math.max(160, grid.clientWidth);
  const rows = layoutRows(gridTiles.map(function (t) { return t.f; }), width, state.size);

  let k = 0;
  rows.forEach(function (r) {
    const h = Math.max(48, Math.round(r.h));
    let acc = 0;
    r.items.forEach(function (f, i) {
      let w = Math.round(arOf(f) * r.h);
      // Ô cuối của hàng đầy nhận phần dư, để mép phải thẳng tắp chứ không lởm
      // chởm một hai pixel do làm tròn.
      if (r.full && i === r.items.length - 1) w = width - GRID_GAP * (r.items.length - 1) - acc;
      acc += w;
      const node = gridTiles[k++].node;
      node.style.width = Math.max(40, w) + 'px';
      node.style.height = h + 'px';
    });
  });
}

function scheduleLayout() {
  if (layoutRaf) cancelAnimationFrame(layoutRaf);
  layoutRaf = requestAnimationFrame(function () { layoutRaf = 0; layoutGrid(); });
}

function noteRatio(name, w, h) {
  if (!w || !h) return;
  const r = w / h;
  if (!isFinite(r) || r <= 0) return;
  const key = arKey(name);
  const hadDim = !!state.dim[key];
  const moved = Math.abs((state.ar[key] || 0) - r) >= 0.001;
  state.ar[key] = r;
  state.dim[key] = w + ' × ' + h;
  if (moved) scheduleLayout();
  // Lần đầu đo được kích thước của đúng tệp đang soi: vẽ lại ô soi để thay câu
  // «đang đo…». Lần sau hadDim đã bật nên không vẽ lại nữa — không có vòng lặp.
  if (!hadDim && state.sel === name) renderInspector();
}

function renderFiles() {
  const grid = $('#fileGrid');
  grid.textContent = '';
  gridTiles = [];
  const c = state.col;
  if (!c) return;

  const all = c.files || [];
  const q = (state.view === 'col' ? state.filter : '').trim().toLowerCase();
  const files = q
    ? all.filter(function (f) { return f.name.toLowerCase().indexOf(q) >= 0; })
    : all;

  const total = all.reduce(function (a, f) { return a + (f.bytes || 0); }, 0);
  $('#colCount').textContent = !all.length
    ? 'Kho đang rỗng'
    : (q ? files.length + '/' + all.length + ' tệp khớp «' + q + '» · ' + fmtBytes(total)
         : all.length + ' tệp · ' + fmtBytes(total));

  grid.classList.toggle('names', state.size < NAME_ALWAYS_BELOW);

  if (!all.length) { grid.appendChild(emptyCollection()); return; }
  if (!files.length) {
    grid.appendChild(el('div', 'gal-empty', 'Không có tệp nào tên chứa «' + q + '» trong kho này.'));
    return;
  }

  files.forEach(function (f) {
    const node = fileTile(f);
    gridTiles.push({ f: f, node: node });
    grid.appendChild(node);
  });
  markTiles();
  layoutGrid();
}

function emptyCollection() {
  const wrap = el('div', 'empty-state');
  const box = el('div', 'empty-card');
  box.id = 'emptyCard';

  const ill = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  ill.setAttribute('class', 'empty-ill');
  ill.setAttribute('viewBox', '0 0 150 110');
  ill.innerHTML =
    '<g stroke="var(--text-subtle)" stroke-width="2" fill="var(--bg-secondary)">' +
    '<rect x="18" y="26" width="70" height="52" rx="6" transform="rotate(-8 53 52)"/>' +
    '<rect x="40" y="30" width="70" height="52" rx="6" transform="rotate(4 75 56)"/>' +
    '<rect x="62" y="22" width="70" height="52" rx="6" transform="rotate(-3 97 48)" fill="var(--bg2)"/></g>' +
    '<path d="M78 60 l10-11 8 8 6-6 10 11z" fill="var(--text-subtle)"/>' +
    '<circle cx="82" cy="40" r="4" fill="var(--primary)"/>' +
    '<circle cx="120" cy="88" r="14" fill="var(--primary)"/>' +
    '<path d="M120 81v14M113 88h14" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>';
  box.appendChild(ill);

  box.appendChild(el('h2', null, 'Kho «' + (state.col.name || state.col.id) + '» chưa có tệp nào'));
  box.appendChild(el('p', null,
    'Kéo ảnh, GIF hay video thả vào bất cứ đâu trên trang này. Tên tệp được giữ ' +
    'nguyên — đặt tên có nghĩa thì chế độ «AI chọn» chọn đúng hơn.'));

  const row = el('div', 'row');
  const b = el('button', 'btn primary', 'Chọn tệp');
  b.type = 'button';
  b.addEventListener('click', function () { $('#fileIn').click(); });
  row.appendChild(b);
  box.appendChild(row);

  const foot = el('div', 'foot');
  foot.appendChild(document.createTextNode('Extension đã trỏ được vào kho này bằng mã '));
  foot.appendChild(el('code', 'mono', state.col.id));
  foot.appendChild(document.createTextNode(
    ' ngay bây giờ — tệp đến sau cũng được, máy sẽ bốc khi có.'));
  box.appendChild(foot);

  wrap.appendChild(box);
  return wrap;
}

function fileTile(f) {
  const t = el('div', 'ftile');
  t.dataset.name = f.name;
  t.tabIndex = 0;
  t.title = f.name + ' — ' + (KIND_VI[f.kind] || f.kind) + ' · ' + fmtBytes(f.bytes);

  const src = fileUrl(state.col.id, f.name, state.col.updated_at);
  if (f.kind === 'video') {
    // preload="metadata" là đủ để trình duyệt vẽ khung hình đầu; tải cả video
    // chỉ để làm một ô trong lưới là đốt băng thông của một kho vài GB.
    const v = el('video');
    v.muted = true;
    v.preload = 'metadata';
    v.playsInline = true;
    v.src = src + '#t=0.1';
    v.addEventListener('loadedmetadata', function () {
      noteRatio(f.name, v.videoWidth, v.videoHeight);
    });
    t.appendChild(v);
    const play = el('div', 'ftile-play');
    play.innerHTML = ICO.play;
    t.appendChild(play);
  } else {
    const img = el('img');
    img.loading = 'lazy';
    img.alt = f.name;
    img.src = src;
    img.addEventListener('load', function () {
      noteRatio(f.name, img.naturalWidth, img.naturalHeight);
    });
    img.addEventListener('error', function () {
      img.remove();
      t.appendChild(coverPlaceholder('không đọc được'));
    });
    t.appendChild(img);
  }

  if (f.kind !== 'image') t.appendChild(el('span', 'ftile-kind', KIND_TAG[f.kind] || f.kind));

  t.appendChild(el('div', 'ftile-name', f.name));

  const badge = el('div', 'ftile-badge');
  badge.hidden = true;
  t.appendChild(badge);

  const del = el('button', 'ftile-del', '×');
  del.type = 'button';
  del.title = 'Xoá ' + f.name;
  del.addEventListener('click', function (ev) {
    ev.stopPropagation();
    askDeleteFile(t, f);
  });
  t.appendChild(del);

  t.addEventListener('click', function () { selectFile(f.name); });
  t.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); selectFile(f.name); }
  });
  return t;
}

/* Đổi nhãn và viền mà KHÔNG dựng lại ô: dựng lại là ảnh tải lại, lưới nháy. */
function markTiles() {
  const nn = nextName();
  gridTiles.forEach(function (t) {
    const isNext = !!nn && t.f.name === nn;
    t.node.classList.toggle('sel', t.f.name === state.sel);
    t.node.classList.toggle('picked', t.f.name === state.picked);
    t.node.classList.toggle('next', isNext);
    const badge = $('.ftile-badge', t.node);
    if (!badge) return;
    if (isNext) { badge.hidden = false; badge.textContent = 'kế tiếp'; }
    else if (t.f.name === state.picked) { badge.hidden = false; badge.textContent = 'vừa bốc'; }
    else { badge.hidden = true; badge.textContent = ''; }
  });
}

/* Bấm một ô = chọn nó. Chế độ «AI chọn» cần tới, nhưng vẫn cho chọn ở mọi chế
   độ để người dùng có chỗ neo mắt khi lướt một kho vài trăm tấm. */
function selectFile(name) {
  state.sel = (state.sel === name) ? '' : name;
  markTiles();
  renderNextInfo();
  renderInspector();
  if (state.mode === 'ai') {
    msg(state.sel
      ? 'Bấm «Bốc thử» để nhờ máy chủ lấy đúng «' + clip(state.sel, 40) + '».'
      : 'Chưa chọn tệp nào — chế độ «AI chọn» cần biết tên tệp.');
  }
}

function askDeleteFile(tile, f) {
  if ($('.fconfirm', tile)) return;      // đã hỏi rồi, đừng chồng hộp thứ hai
  const box = el('div', 'fconfirm');
  box.addEventListener('click', function (ev) { ev.stopPropagation(); });
  box.appendChild(el('div', null, 'Xoá «' + clip(f.name, 26) + '»? Không lấy lại được.'));

  const row = el('div', 'row');
  const yes = el('button', 'btn sm danger', 'Xoá');
  yes.type = 'button';
  yes.addEventListener('click', function () { box.remove(); deleteFile(f.name); });
  const no = el('button', 'btn sm', 'Huỷ');
  no.type = 'button';
  no.addEventListener('click', function () { box.remove(); });
  row.appendChild(yes);
  row.appendChild(no);
  box.appendChild(row);

  tile.appendChild(box);
}

async function deleteFile(name) {
  if (!state.col) return;
  try {
    await hit('/collections/' + enc(state.col.id) + '/files/' + enc(name),
              { method: 'DELETE' });
    msg('Đã xoá «' + clip(name, 40) + '».', 'ok');
  } catch (err) {
    msg('Xoá tệp hỏng: ' + err.message, 'err');
  }
  await reloadCollection();
}

/* ── Ô soi bên phải ──────────────────────────────────────────────────────
   Ba dáng: toàn thư viện (ở màn 1), một kho, một tệp. */

function inspSection(title, note) {
  const s = el('section');
  if (title) {
    const h = el('h3');
    h.appendChild(el('span', null, title));
    if (note) h.appendChild(el('em', null, note));
    s.appendChild(h);
  }
  return s;
}

function kvBox(pairs) {
  const box = el('div', 'kv');
  pairs.forEach(function (p) {
    if (!p) return;
    const d = el('div');
    d.appendChild(el('div', 'k', p[0]));
    const v = el('div', 'v', p[1]);
    v.title = p[1];
    d.appendChild(v);
    box.appendChild(d);
  });
  return box;
}

function pathBox(text, label) {
  const box = el('div', 'path');
  box.appendChild(el('code', null, text));
  const b = el('button', 'icobtn');
  b.type = 'button';
  b.title = 'Chép ' + (label || 'đường dẫn');
  b.innerHTML = ICO.copy;
  b.addEventListener('click', function () { copyText(text, label || 'đường dẫn'); });
  box.appendChild(b);
  return box;
}

/* Chỗ dành cho «Đang dùng ở». Backend không có chỉ mục nào cho biết mẫu nào
   đang trỏ tới kho, nên giữ đúng khoảng trống và nói thật. */
function usageSection(cid) {
  const s = inspSection('Đang dùng ở', 'chưa theo dõi');
  const p = el('div', 'nouse');
  p.appendChild(document.createTextNode('Chưa có dữ liệu sử dụng. Trang này không ' +
    'theo dõi được mẫu nào đang gọi tới kho — muốn trỏ vào thì dùng mã '));
  p.appendChild(el('code', 'mono', cid));
  p.appendChild(document.createTextNode(' trong Thumbnail Studio hay Content Studio.'));
  s.appendChild(p);
  return s;
}

function renderInspector() {
  const insp = $('#insp');
  insp.textContent = '';

  if (state.view !== 'col' || !state.col) { insp.appendChild(libraryPanel()); return; }
  const f = (state.col.files || []).filter(function (x) { return x.name === state.sel; })[0];
  if (f) filePanel(insp, f); else collectionPanel(insp);
}

/* Màn 1: nói về cả thư viện. Không có hạn mức đĩa nào để vẽ, nên chỉ có những
   con số máy chủ thật sự trả về. */
function libraryPanel() {
  const wrap = document.createDocumentFragment();
  const s = state.stats || {};

  const head = inspSection('Thư viện');
  head.appendChild(kvBox([
    ['Số kho', String(s.collections || 0)],
    ['Tổng số tệp', String(s.files || 0)]
  ]));
  if (s.dir) head.appendChild(pathBox(s.dir, 'thư mục'));
  wrap.appendChild(head);

  const empty = state.collections.filter(function (c) { return !Number(c.count); });
  const st = inspSection('Kho rỗng', empty.length ? String(empty.length) : 'không có');
  if (!empty.length) {
    st.appendChild(el('div', 'state', 'Mọi kho đều có tệp để bốc.'));
  } else {
    empty.forEach(function (c) {
      const row = el('div', 'state');
      row.style.marginBottom = '6px';
      row.appendChild(el('span', 'hdot'));
      row.appendChild(el('span', null, (c.name || c.id) + ' — mẫu trỏ vào sẽ ra lớp trống'));
      row.addEventListener('click', function () { goCollection(c.id); });
      row.style.cursor = 'pointer';
      st.appendChild(row);
    });
  }
  wrap.appendChild(st);

  const how = inspSection('Kho dùng thế nào');
  how.appendChild(el('div', 'desc-note',
    'Mỗi kho là một túi nguyên liệu có tên. Extension trỏ vào mã kho rồi để máy ' +
    'bốc — cùng một tấm được dùng đi dùng lại, chỉ phần chữ trên thumbnail là khác.'));
  wrap.appendChild(how);

  const acts = inspSection(null);
  acts.className = 'acts';
  const b = el('button', 'btn sm', '+ Tạo kho');
  b.type = 'button';
  b.addEventListener('click', function () { openCreate(); });
  acts.appendChild(b);
  wrap.appendChild(acts);

  return wrap;
}

/* Không chọn tệp nào: nói về cả kho. */
function collectionPanel(insp) {
  const c = state.col;
  const files = c.files || [];
  const total = files.reduce(function (a, f) { return a + (f.bytes || 0); }, 0);

  // Bìa: bốn tấm đầu ghép lại. Ảnh hỏng thì tự rút khỏi lưới ghép.
  const cover = inspSection(null);
  cover.className = 'prevsec';
  const shots = files.filter(function (f) { return f.kind !== 'video'; }).slice(0, 4);
  if (shots.length) {
    const m = el('div', 'mosaic' + (shots.length < 2 ? ' one' : ''));
    shots.forEach(function (f) {
      const img = el('img');
      img.loading = 'lazy';
      img.alt = f.name;
      img.src = fileUrl(c.id, f.name, c.updated_at);
      img.addEventListener('error', function () { img.remove(); });
      m.appendChild(img);
    });
    cover.appendChild(m);
  } else {
    cover.appendChild(el('div', 'mosaic-none', files.length
      ? 'Kho toàn video — chưa có ảnh nào để làm bìa'
      : 'Chưa có bìa — tệp đầu tiên sẽ thành bìa'));
  }
  insp.appendChild(cover);

  const head = inspSection(null);
  const name = el('div', 'fname');
  name.appendChild(el('span', null, c.name || '(không tên)'));
  head.appendChild(name);
  head.appendChild(kvBox([
    ['Số tệp', String(files.length)],
    ['Dung lượng', fmtBytes(total)],
    ['Sửa lần cuối', relTime(c.updated_at) || '—'],
    ['Toàn thư viện', (state.stats.files || 0) + ' tệp']
  ]));
  head.appendChild(pathBox(c.id, 'mã kho'));
  insp.appendChild(head);

  insp.appendChild(pickRuleSection(null));
  insp.appendChild(usageSection(c.id));

  const acts = inspSection(null);
  acts.className = 'acts';
  const ren = el('button', 'btn sm');
  ren.type = 'button';
  ren.innerHTML = ICO.pen;
  ren.appendChild(document.createTextNode('Đổi tên'));
  ren.addEventListener('click', beginColRename);
  acts.appendChild(ren);

  const conf = el('div', 'pconfirm');
  conf.hidden = true;
  conf.style.marginTop = '8px';
  conf.style.width = '100%';

  const del = el('button', 'btn sm ghost');
  del.type = 'button';
  del.style.color = 'var(--red)';
  del.innerHTML = ICO.trash;
  del.appendChild(document.createTextNode('Xoá kho'));
  del.addEventListener('click', function () { askDeleteCollection(conf, c); });
  acts.appendChild(del);
  acts.appendChild(conf);
  insp.appendChild(acts);
}

/* Khối «quy tắc bốc». Đọc như một vòng quay, KHÔNG như một kho hàng đang vơi:
   file được lấy đi lấy lại, xoay vòng chỉ để khỏi trùng tấm hai lần liền. */
function pickRuleSection(f) {
  const c = state.col;
  const files = c.files || [];
  const s = inspSection('Quy tắc bốc', MODE_NAME[state.mode] + ' · ' + state.mode);
  s.appendChild(el('div', 'desc-note', MODE_HINT[state.mode]));

  if (!files.length) {
    s.appendChild(el('div', 'state', 'Kho rỗng — chưa bốc được gì.'));
    return s;
  }

  if (state.mode === 'cycle') {
    const i = nextIndex();
    const nm = i < 0 ? '' : files[i].name;
    if (f) {
      const pos = files.indexOf(f) + 1;
      if (nm && f.name === nm) {
        const row = el('div', 'state on');
        const pill = el('span', 'pill');
        pill.appendChild(ico('next'));
        pill.appendChild(document.createTextNode('lần tới'));
        row.appendChild(pill);
        row.appendChild(el('span', null, 'Lượt gọi tới sẽ lấy đúng tệp này.'));
        s.appendChild(row);
      } else {
        s.appendChild(el('div', 'state',
          'Đứng thứ ' + pos + '/' + files.length + ' trong vòng. Vòng chạy tới đâu thì lấy tệp ở đó.'));
      }
    } else {
      const row = el('div', 'state on');
      const pill = el('span', 'pill');
      pill.appendChild(ico('next'));
      pill.appendChild(document.createTextNode('lần tới'));
      row.appendChild(pill);
      row.appendChild(el('span', null, nm || '(chưa xác định)'));
      s.appendChild(row);
    }
    if (i >= 0) {
      const prog = el('div', 'prog');
      prog.appendChild(el('span', null, 'Vị trí trong vòng'));
      const bar = el('div', 'bar');
      const fill = el('i');
      fill.style.width = ((i + 1) / files.length * 100).toFixed(1) + '%';
      bar.appendChild(fill);
      prog.appendChild(bar);
      prog.appendChild(el('span', null, (i + 1) + '/' + files.length));
      s.appendChild(prog);
    }
    return s;
  }

  if (state.mode === 'random') {
    s.appendChild(el('div', 'state', f
      ? 'Mỗi lần gọi, tệp này có 1/' + files.length + ' khả năng được lấy.'
      : 'Mỗi lần gọi lấy một tệp bất kỳ trong ' + files.length + ' tệp.'));
    return s;
  }

  s.appendChild(el('div', 'state', f
    ? '«Bốc thử» sẽ lấy đúng tệp đang chọn.'
    : (state.sel ? 'Đang chỉ đích danh «' + clip(state.sel, 34) + '».'
                 : 'Bấm một ô trong lưới để chỉ đích danh tệp.')));
  return s;
}

/* Đang chọn một tệp: nói về tệp đó. Chỉ có ba thứ máy chủ thật sự biết — tên,
   loại, dung lượng; kích thước điểm ảnh là do trình duyệt đo được sau khi tải. */
function filePanel(insp, f) {
  const c = state.col;

  const prevSec = inspSection(null);
  prevSec.className = 'prevsec';
  const prev = el('div', 'prev');
  const ratio = arOf(f);
  const box = el('div', 'prevbox');
  box.style.width = 'min(100%, ' + Math.round(190 * Math.max(0.35, ratio)) + 'px)';
  box.style.aspectRatio = String(ratio);
  const src = fileUrl(c.id, f.name, c.updated_at);
  if (f.kind === 'video') {
    const v = el('video');
    v.muted = true;
    v.preload = 'metadata';
    v.playsInline = true;
    v.controls = true;
    v.src = src;
    v.addEventListener('loadedmetadata', function () { noteRatio(f.name, v.videoWidth, v.videoHeight); });
    box.appendChild(v);
  } else {
    const img = el('img');
    img.alt = f.name;
    img.src = src;
    img.addEventListener('load', function () { noteRatio(f.name, img.naturalWidth, img.naturalHeight); });
    img.addEventListener('error', function () {
      img.remove();
      box.appendChild(coverPlaceholder('không đọc được'));
    });
    box.appendChild(img);
  }
  prev.appendChild(box);
  prevSec.appendChild(prev);
  insp.appendChild(prevSec);

  const head = inspSection(null);
  const name = el('div', 'fname');
  name.appendChild(el('span', null, f.name));
  name.appendChild(el('span', 'kind', extOf(f.name) || KIND_TAG[f.kind] || ''));
  head.appendChild(name);

  head.appendChild(kvBox([
    ['Loại', KIND_VI[f.kind] || f.kind],
    ['Dung lượng', fmtBytes(f.bytes)],
    ['Kích thước', state.dim[arKey(f.name)] || 'đang đo…'],
    ['Kho', c.name || c.id]
  ]));
  head.appendChild(pathBox('media/' + c.id + '/' + f.name, 'đường dẫn'));
  insp.appendChild(head);

  insp.appendChild(pickRuleSection(f));
  insp.appendChild(usageSection(c.id));

  const acts = inspSection(null);
  acts.className = 'acts';

  const open = el('a', 'btn sm', 'Mở tệp gốc');
  open.href = src;
  open.target = '_blank';
  open.rel = 'noopener';
  acts.appendChild(open);

  const del = el('button', 'btn sm ghost');
  del.type = 'button';
  del.style.color = 'var(--red)';
  del.innerHTML = ICO.trash;
  del.appendChild(document.createTextNode('Xoá tệp'));
  del.addEventListener('click', function () {
    const tile = $('.ftile[data-name="' + cssq(f.name) + '"]');
    if (tile) { askDeleteFile(tile, f); tile.scrollIntoView({ block: 'nearest' }); }
    else deleteFile(f.name);
  });
  acts.appendChild(del);
  insp.appendChild(acts);
}

/* ── Tải tệp lên ─────────────────────────────────────────────────────── */

function setUploadBusy(on) {
  state.uploading = on;
  const lbl = $('#upLbl');
  if (lbl) lbl.classList.toggle('busy', on);
  $('#fileIn').disabled = on;
  $('#pickBtn').disabled = on;
}

/* Tải TỪNG tệp một chứ không bắn cả loạt: mỗi lượt là một POST multipart lên
   tới 200 MB, mở mười lượt song song là bóp nghẹt đúng cái máy chủ đang chạy
   trình duyệt của người dùng. Một tệp hỏng thì ghi lại rồi đi tiếp — bỏ dở cả
   lượt vì một tấm sai định dạng là mất công kéo lại từ đầu. */
async function uploadFiles(list) {
  const arr = Array.prototype.slice.call(list || []);
  if (!arr.length) return;
  if (!state.col) { msg('Chưa mở kho nào để tải tệp vào.', 'warn'); return; }
  if (state.uploading) { msg('Đang có lượt tải khác chạy — chờ nó xong đã.', 'warn'); return; }

  setUploadBusy(true);
  let ok = 0;
  const bad = [];
  for (let i = 0; i < arr.length; i++) {
    msg('đang tải ' + (i + 1) + '/' + arr.length + ' — ' + clip(arr[i].name, 40));
    const fd = new FormData();
    fd.append('file', arr[i], arr[i].name);
    try {
      await hit('/collections/' + enc(state.col.id) + '/files', { method: 'POST', body: fd });
      ok++;
    } catch (err) {
      bad.push(clip(arr[i].name, 28) + ' (' + err.message + ')');
    }
  }
  setUploadBusy(false);
  await reloadCollection();

  if (!bad.length) {
    msg('Đã thêm ' + ok + ' tệp vào kho.', 'ok');
  } else {
    msg('Xong ' + ok + '/' + arr.length + ' tệp. Không lên được: ' + clip(bad.join('; '), 220),
        ok ? 'warn' : 'err');
  }
}

/* Thả một đường dẫn có sẵn trên máy (kéo từ File Manager sang) — máy chủ chép
   thẳng vào kho, khỏi đẩy lại vài trăm MB đã nằm sẵn trên đĩa. */
async function importPath(path) {
  if (!state.col) return;
  msg('Đang chép «' + clip(path, 60) + '» vào kho…');
  try {
    const r = await jsend('POST', '/collections/' + enc(state.col.id) + '/import',
                          { path: path });
    msg('Đã chép «' + r.name + '» vào kho.', 'ok');
    await reloadCollection();
  } catch (err) {
    msg('Chép «' + clip(path, 60) + '» vào kho hỏng: ' + err.message, 'err');
  }
}

function bindDropZone() {
  const zone = $('#dropZone');
  const veil = $('#dropVeil');

  function veilOn() {
    if (state.view === 'col' && state.col) {
      $('#dropVeilTitle').textContent = 'Thả để thêm vào «' + clip(state.col.name || state.col.id, 40) + '»';
    } else {
      $('#dropVeilTitle').textContent = 'Mở một kho trước đã';
    }
    veil.hidden = false;
    const card = $('#emptyCard');
    if (card) card.classList.add('hot');
    if (state.view === 'col') zone.classList.add('over');
  }

  function veilOff() {
    state.dragDepth = 0;
    veil.hidden = true;
    zone.classList.remove('over');
    const card = $('#emptyCard');
    if (card) card.classList.remove('hot');
  }

  // Thả ở BẤT KỲ đâu trên trang cũng vào kho đang mở: người ta kéo tới giữa
  // màn hình chứ không ngắm cho trúng cái khung lưới.
  // dragenter/dragleave nổ lại mỗi khi con trỏ đi qua một ô con, nên đếm chiều
  // sâu thay vì bật tắt thẳng: không đếm là màn thả nhấp nháy suốt lúc kéo.
  window.addEventListener('dragenter', function (ev) {
    ev.preventDefault();
    state.dragDepth++;
    veilOn();
  });
  window.addEventListener('dragover', function (ev) {
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
  });
  window.addEventListener('dragleave', function () {
    state.dragDepth = Math.max(0, state.dragDepth - 1);
    if (!state.dragDepth) veilOff();
  });

  // Chặn hành vi mặc định của trình duyệt: không chặn là nó mở thẳng tấm ảnh
  // và cuốn luôn trang đang mở đi mất.
  window.addEventListener('drop', function (ev) {
    ev.preventDefault();
    veilOff();
    const dt = ev.dataTransfer;
    if (!dt) return;
    if (!state.col) {
      msg('Chưa mở kho nào — vào một kho rồi thả lại, tệp sẽ vào đúng kho đó.', 'warn');
      return;
    }
    if (dt.files && dt.files.length) { uploadFiles(dt.files); return; }
    let text = '';
    try { text = (dt.getData('text/plain') || '').trim(); } catch (e) { /* nguồn lạ */ }
    if (text) importPath(text);
    else msg('Không thấy tệp nào trong thứ vừa thả.', 'warn');
  });

  // Kéo tệp từ File Manager TRÊN CANVAS FLOW sang trang này. Đó không phải kéo
  // thả HTML5: File Manager là một iframe khác, nó stream toạ độ con trỏ lên
  // canvas, canvas dò node nằm dưới con trỏ rồi postMessage FileRef VÀO iframe
  // của extension (FlowBuilder.js, giao thức 'tubecli-file-drop'). Ta chỉ cần
  // nghe đúng thông điệp ấy, và chỉ tin khi nó đến từ chính cửa sổ cha.
  window.addEventListener('message', function (ev) {
    // Chỉ nhận khi ĐANG BỊ NHÚNG và thông điệp đến từ đúng cửa sổ cha. Trang mở
    // riêng thì window.parent === window, nên thiếu vế đầu là chính trang tự
    // gửi cho mình cũng lọt.
    if (window.parent === window || ev.source !== window.parent) return;
    const d = ev.data;
    if (!d || d.type !== 'tubecli-file-drop' || !d.file) return;
    const path = String(d.file.path || '').trim();
    if (!path) { msg('Canvas thả sang một tệp không có đường dẫn.', 'warn'); return; }
    if (state.col) { importPath(path); return; }
    // Đang ở lưới kho: chưa biết bỏ vào kho nào. Nói rõ chứ không đoán, và
    // nhớ lại để mở kho nào xong là chép ngay vào kho đó.
    state.pendingDrop = path;
    msg('Nhận «' + clip(path, 50) + '» từ canvas — mở kho muốn chép vào, tệp sẽ vào đó.', 'warn');
  });
}

/* ── Bốc thử ─────────────────────────────────────────────────────────── */

async function doPick() {
  if (!state.col) return;
  const files = state.col.files || [];
  if (!files.length) { msg('Kho đang rỗng — chưa có gì để bốc.', 'warn'); return; }

  const body = { mode: state.mode, commit: false };
  if (state.mode === 'ai') {
    if (!state.sel) {
      msg('Chế độ «AI chọn» cần biết tên tệp — bấm vào một ô trong lưới rồi bốc lại.', 'warn');
      return;
    }
    body.file = state.sel;
  }

  const btn = $('#pickBtn');
  btn.disabled = true;
  try {
    const r = await jsend('POST', '/collections/' + enc(state.col.id) + '/pick', body);
    if (!r.file) {
      state.picked = '';
      markTiles();
      msg('Không bốc được tệp nào — ' + (r.why || 'kho rỗng') + '.', 'warn');
      return;
    }
    state.picked = r.file;
    markTiles();
    renderInspector();
    const node = $('.ftile[data-name="' + cssq(r.file) + '"]');
    if (node && node.scrollIntoView) node.scrollIntoView({ block: 'nearest' });
    // commit:false — bốc thử KHÔNG dời con trỏ vòng xoay, nói rõ ra để người
    // dùng khỏi tưởng mình vừa làm lệch thứ tự của các extension khác.
    msg('Bốc được «' + r.file + '»' + (r.why ? ' — ' + r.why : '') +
        '. Chỉ xem thử, vòng xoay giữ nguyên chỗ.', 'ok');
  } catch (err) {
    msg('Bốc thử hỏng: ' + err.message, 'err');
  } finally {
    btn.disabled = state.uploading;
  }
}

/* ── Quy tắc bốc: ô chọn thật và ba nút mặt tiền ─────────────────────── */

function syncSeg() {
  const btns = document.querySelectorAll('#pickSeg button[data-mode]');
  for (let i = 0; i < btns.length; i++) {
    const on = btns[i].dataset.mode === state.mode;
    btns[i].classList.toggle('on', on);
    btns[i].setAttribute('aria-pressed', on ? 'true' : 'false');
  }
}

function setMode(mode) {
  if (!MODE_HINT[mode]) return;
  state.mode = mode;
  const sel = $('#pickMode');
  if (sel.value !== mode) sel.value = mode;
  syncSeg();
  markTiles();               // nhãn «kế tiếp» chỉ có nghĩa ở chế độ xoay vòng
  renderNextInfo();
  renderInspector();
  msg(MODE_HINT[mode] || '');
}

/* ── Sửa tên và mô tả ngay tại chỗ ───────────────────────────────────── */

function beginColRename() {
  if (!state.col) return;
  const btn = $('#colName'), i = $('#colNameIn');
  i.value = state.col.name || '';
  btn.hidden = true;
  i.hidden = false;
  i.focus();
  i.select();
}

async function endColRename(keep) {
  const btn = $('#colName'), i = $('#colNameIn');
  if (i.hidden) return;
  i.hidden = true;
  btn.hidden = false;
  if (!keep || !state.col) return;
  const v = i.value.trim();
  if (!v || v === state.col.name) return;
  try {
    // Chỉ gửi khoá `name`: thiếu `description` thì backend giữ nguyên mô tả cũ,
    // gửi kèm một bản chép trên màn hình mới là chỗ dễ ghi đè nhầm.
    const r = await jsend('PUT', '/collections/' + enc(state.col.id), { name: v });
    state.col.name = (r.collection && r.collection.name) || v;
    renderCollection();
    loadCollections();
    msg('Đã đổi tên kho thành «' + state.col.name + '».', 'ok');
  } catch (err) {
    msg('Đổi tên kho hỏng: ' + err.message, 'err');
  }
}

function beginColDesc() {
  if (!state.col) return;
  const btn = $('#colDesc'), t = $('#colDescIn');
  t.value = state.col.description || '';
  btn.hidden = true;
  t.hidden = false;
  t.focus();
}

async function endColDesc(keep) {
  const btn = $('#colDesc'), t = $('#colDescIn');
  if (t.hidden) return;
  t.hidden = true;
  btn.hidden = false;
  if (!keep || !state.col) return;
  const v = t.value.trim();
  if (v === (state.col.description || '')) return;
  try {
    const r = await jsend('PUT', '/collections/' + enc(state.col.id), { description: v });
    state.col.description = (r.collection && r.collection.description) || v;
    renderCollection();
    loadCollections();
    msg('Đã lưu mô tả kho.', 'ok');
  } catch (err) {
    msg('Lưu mô tả hỏng: ' + err.message, 'err');
    renderCollection();
  }
}

/* ── Đường dẫn theo hash ─────────────────────────────────────────────── */

function setView(name) {
  state.view = name;
  $('#listView').hidden = (name !== 'list');
  $('#colView').hidden = (name !== 'col');

  const s = $('#colSearch');
  s.placeholder = (name === 'col') ? 'Tìm trong kho đang mở' : 'Tìm kho theo tên';
  if (s.value) { s.value = ''; state.filter = ''; }

  // Tải lên chỉ có nghĩa khi đã biết đổ tệp vào kho nào.
  const lbl = $('#upLbl');
  lbl.classList.toggle('off', name !== 'col');
  lbl.title = (name === 'col')
    ? 'Chọn ảnh, GIF hoặc video để thêm vào kho'
    : 'Mở một kho trước đã';
}

function goCollection(cid) {
  const want = '#/c/' + enc(cid);
  if (location.hash === want) applyRoute();     // cùng hash: hashchange không nổ
  else location.hash = want;
}

function goList() {
  if (location.hash === '#/' || location.hash === '') applyRoute();
  else location.hash = '#/';
}

let routeBusy = false;
let routeAgain = false;

async function applyRoute() {
  // Đang chạy dở thì HẸN chạy lại chứ không bỏ: bấm back hai nhát liền mà bỏ
  // nhát sau là màn hình đứng lệch hẳn với thanh địa chỉ.
  if (routeBusy) { routeAgain = true; return; }
  routeBusy = true;
  try {
    const m = /^#\/c\/([^/?#]+)/.exec(location.hash || '');
    if (m) {
      const cid = decodeURIComponent(m[1]);
      if (state.view === 'col' && state.col && state.col.id === cid) return;
      await openCollection(cid);
      return;
    }
    closeMenus();
    state.col = null;
    state.sel = '';
    state.picked = '';
    gridTiles = [];
    setView('list');
    await loadCollections();
  } finally {
    routeBusy = false;
    if (routeAgain) { routeAgain = false; applyRoute(); }
  }
}

/* ── Hộp thoại tạo kho ───────────────────────────────────────────────── */

function createMsg(text, kind) {
  const n = $('#createMsg');
  n.textContent = text || '';
  n.className = 'msg' + (kind ? ' ' + kind : '');
}

function openCreate() {
  $('#newName').value = '';
  $('#newDesc').value = '';
  createMsg('');
  $('#createDlg').hidden = false;
  $('#newName').focus();
}

function closeCreate() { $('#createDlg').hidden = true; }

async function createCollection() {
  const name = $('#newName').value.trim();
  if (!name) {
    createMsg('Cần đặt tên cho kho — tên là thứ extension khác nhìn vào để chọn.', 'warn');
    $('#newName').focus();
    return;
  }
  const btn = $('#createGo');
  btn.disabled = true;
  createMsg('Đang tạo…');
  try {
    const r = await jsend('POST', '/collections',
                          { name: name, description: $('#newDesc').value.trim() });
    const c = r.collection;
    if (!c || !c.id) throw new Error('máy chủ không trả kho nào');
    closeCreate();
    msg('Đã tạo kho «' + c.name + '» (mã: ' + c.id + ').', 'ok');
    goCollection(c.id);
  } catch (err) {
    createMsg('Tạo kho hỏng: ' + err.message, 'err');
    msg('Tạo kho hỏng: ' + err.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

/* ── Giao diện sáng / tối ────────────────────────────────────────────────
   Ba nấc: theo hệ thống → tối → sáng. Bảng điều khiển ghim theme qua ?theme=
   trên URL của iframe; người dùng bấm tay thì ghi nhớ để lần sau mở lại đúng
   thế, còn khối script chạy trước khi vẽ nằm ở đầu index.html. */
const THEMES = [null, 'dark', 'light'];
const THEME_VI = { dark: 'tối', light: 'sáng' };
let themeIx = 0;

/* remember=false lúc khởi động: theme lúc đó có thể do bảng điều khiển ghim qua
   ?theme= hoặc do khối script chạy trước khi vẽ đoán ra, ghi đè vào bộ nhớ là
   biến lựa chọn của bảng điều khiển thành lựa chọn của người dùng. */
function applyTheme(remember) {
  const t = THEMES[themeIx];
  const r = document.documentElement;
  if (t) r.setAttribute('data-theme', t);
  else r.removeAttribute('data-theme');
  if (remember) {
    try {
      if (t) localStorage.setItem('media-library-theme', t);
      else localStorage.removeItem('media-library-theme');
    } catch (e) { /* chế độ riêng tư chặn — không sao, chỉ mất phần ghi nhớ */ }
  }
  const b = $('#themeBtn');
  b.innerHTML = t === 'dark' ? ICO.moon : t === 'light' ? ICO.sun : ICO.auto;
  b.title = 'Giao diện: ' + (t ? THEME_VI[t] : 'theo hệ thống');
}

function cycleTheme() { themeIx = (themeIx + 1) % THEMES.length; applyTheme(true); }

/* ── Cỡ ô trong lưới ─────────────────────────────────────────────────── */

function setSize(v) {
  const n = Math.max(96, Math.min(320, Number(v) || 170));
  state.size = n;
  try { localStorage.setItem('media-library-size', String(n)); } catch (e) { /* bỏ qua */ }
  const grid = $('#fileGrid');
  if (grid) grid.classList.toggle('names', n < NAME_ALWAYS_BELOW);
  scheduleLayout();
}

/* ── Nối dây ─────────────────────────────────────────────────────────── */

function bindUi() {
  // ── Thanh trên
  $('#newColBtn').addEventListener('click', function () { openCreate(); });
  $('#railNew').addEventListener('click', function () { openCreate(); });
  $('#themeBtn').addEventListener('click', cycleTheme);

  // Một ô tìm, hai việc: ở lưới kho thì lọc kho, ở trong kho thì lọc tệp.
  $('#colSearch').addEventListener('input', function (ev) {
    state.filter = ev.target.value;
    if (state.view === 'col') renderFiles();
    else renderList();
  });

  // Bấm ra chỗ khác thì đóng mọi menu ⋯ đang mở.
  document.addEventListener('click', function (ev) {
    if (ev.target.closest && ev.target.closest('.pmenu, .pcard-more')) return;
    closeMenus();
  });

  // Bấm vào khoảng trống của lưới tệp = bỏ chọn.
  $('#dropZone').addEventListener('click', function (ev) {
    if (ev.target.closest('.ftile') || ev.target.closest('.empty-card')) return;
    if (!state.sel) return;
    state.sel = '';
    markTiles();
    renderNextInfo();
    renderInspector();
  });

  // ── Hộp thoại tạo kho
  $('#createGo').addEventListener('click', createCollection);
  $('#newName').addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); createCollection(); }
  });
  $('#createDlg').addEventListener('click', function (ev) {
    // Nền mờ, nút ✕ và nút Huỷ đều mang data-close.
    if (ev.target.dataset && ev.target.dataset.close) closeCreate();
  });

  // ── Trong kho
  $('#backBtn').addEventListener('click', function () { goList(); });

  $('#colName').addEventListener('click', beginColRename);
  $('#colNameIn').addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); endColRename(true); }
    else if (ev.key === 'Escape') { ev.preventDefault(); endColRename(false); }
  });
  $('#colNameIn').addEventListener('blur', function () { endColRename(true); });

  $('#colDesc').addEventListener('click', beginColDesc);
  $('#colDescIn').addEventListener('keydown', function (ev) {
    // Enter xuống dòng như mọi ô nhiều dòng khác; Ctrl+Enter mới là lưu.
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); endColDesc(true); }
    else if (ev.key === 'Escape') { ev.preventDefault(); endColDesc(false); }
  });
  $('#colDescIn').addEventListener('blur', function () { endColDesc(true); });

  $('#fileIn').addEventListener('change', function (ev) {
    const files = ev.target.files;
    uploadFiles(files);
    // Xoá giá trị để chọn LẠI đúng tệp vừa chọn vẫn nổ sự kiện change.
    ev.target.value = '';
  });

  $('#pickMode').addEventListener('change', function (ev) { setMode(ev.target.value); });
  $('#pickSeg').addEventListener('click', function (ev) {
    const b = ev.target.closest('button[data-mode]');
    if (b) setMode(b.dataset.mode);
  });
  $('#pickBtn').addEventListener('click', doPick);

  $('#sizeRange').addEventListener('input', function (ev) { setSize(ev.target.value); });

  // ── Phím tắt
  document.addEventListener('keydown', function (ev) {
    const tag = (ev.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || tag === 'select';
    if (ev.key === 'Escape') {
      if (!$('#createDlg').hidden) { closeCreate(); return; }
      if (typing) return;
      if (state.sel) { state.sel = ''; markTiles(); renderNextInfo(); renderInspector(); }
      return;
    }
    if (typing) return;
    if (ev.key === '/') { ev.preventDefault(); $('#colSearch').focus(); return; }
    if (state.view === 'col' && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) {
      if (!gridTiles.length) return;
      ev.preventDefault();
      let i = gridTiles.map(function (t) { return t.f.name; }).indexOf(state.sel);
      i = (ev.key === 'ArrowRight')
        ? Math.min(gridTiles.length - 1, i + 1)
        : Math.max(0, i < 0 ? 0 : i - 1);
      state.sel = gridTiles[i].f.name;
      markTiles();
      renderNextInfo();
      renderInspector();
      gridTiles[i].node.scrollIntoView({ block: 'nearest' });
    }
  });

  bindDropZone();

  // Đổi bề ngang vùng lưới (kéo cửa sổ, thanh cuộn hiện ra) thì xếp lại hàng.
  if (window.ResizeObserver) new ResizeObserver(scheduleLayout).observe($('#dropZone'));
  else window.addEventListener('resize', scheduleLayout);
}

/* ── Khởi động ───────────────────────────────────────────────────────── */

function fatalBox(title, detail) {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;inset:12px auto auto 12px;z-index:9999;max-width:520px;'
    + 'padding:12px 14px;border-radius:10px;background:#3a1212;color:#ffd7d7;'
    + 'font:13px/1.5 system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.5)';
  box.innerHTML = '<b></b><br>'
    + 'Trình duyệt có thể đang chạy bản JavaScript cũ trong bộ nhớ đệm. '
    + 'Nhấn <b>Ctrl+Shift+R</b> để tải lại.<br>'
    + '<span style="opacity:.7"></span>';
  box.firstChild.textContent = title;
  box.lastChild.textContent = detail || '';
  document.body.appendChild(box);
}

async function boot() {
  // Nếu trình duyệt còn giữ bản JS cũ mà HTML đã mới, bindUi sẽ vấp một phần tử
  // không còn tồn tại và chết ngay ở đây — hậu quả là mọi nút đều không bấm
  // được, mà console thì chỉ có một dòng TypeError khó hiểu. Nói thẳng ra.
  try {
    bindUi();
  } catch (err) {
    fatalBox('Giao diện và mã lệch phiên bản.', err && err.message ? err.message : String(err));
    throw err;
  }

  const a = document.documentElement.getAttribute('data-theme');
  const ix = THEMES.indexOf(a);
  themeIx = ix >= 0 ? ix : 0;
  applyTheme(false);

  let saved = 0;
  try { saved = Number(localStorage.getItem('media-library-size')) || 0; } catch (e) { /* bỏ qua */ }
  if (saved) state.size = Math.max(96, Math.min(320, saved));
  $('#sizeRange').value = String(state.size);

  $('#pickMode').value = state.mode;
  syncSeg();

  window.addEventListener('hashchange', function () { applyRoute(); });
  await applyRoute();       // không có hash thì ra lưới kho
}

boot();
