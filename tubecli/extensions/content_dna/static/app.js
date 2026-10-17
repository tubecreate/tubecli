/* Content DNA — trang quản lý ADN nội dung (học / xem / sửa / xoá / xem trước prompt).
   Giao kèo i18n giống Media Library: từ điển gộp /api/v1/i18n/<lang>, khoá phẳng tiền tố «dna.»; chữ tiếng Anh viết
   sẵn trong HTML, applyI18n() chỉ dịch đè. Mọi chuỗi từ máy chủ đi qua textContent. */
'use strict';

let _lang = 'en', _dict = {}, _en = {};

function T(key, fallback, vars) {
  let s = (_dict && _dict[key]) || (_en && _en[key]) || fallback || key;
  if (vars) for (const k of Object.keys(vars)) s = s.split('{' + k + '}').join(String(vars[k]));
  return s;
}

function applyI18n(root) {
  const scope = root || document;
  const put = (attr, fn) => scope.querySelectorAll('[' + attr + ']').forEach((n) => {
    const k = n.getAttribute(attr);
    const v = (_dict && _dict[k]) || (_en && _en[k]);
    if (v) fn(n, v);
  });
  put('data-i18n', (n, v) => { n.textContent = v; });
  put('data-i18n-placeholder', (n, v) => { n.placeholder = v; });
  put('data-i18n-title', (n, v) => { n.title = v; });
  put('data-i18n-aria-label', (n, v) => { n.setAttribute('aria-label', v); });
  if (!root) document.documentElement.lang = _lang;
}

async function loadI18n() {
  const base = window.location.origin;
  let got = false;
  try {
    const r = await fetch(base + '/api/v1/settings/language');
    if (r.ok) { const d = await r.json(); if (d && d.language) { _lang = d.language; got = true; } }
  } catch (e) { /* dùng đoán ở dưới */ }
  if (!got) {
    let cached = '';
    try { cached = localStorage.getItem('tubecli_lang') || ''; } catch (e) { /* riêng tư */ }
    _lang = cached || (navigator.language || 'en').slice(0, 2) || 'en';
  }
  const bust = '?v=' + Date.now();
  try { const r = await fetch(base + '/api/v1/i18n/' + encodeURIComponent(_lang) + bust); if (r.ok) _dict = await r.json(); } catch (e) { /* tiếng Anh sẵn trong HTML */ }
  if (_lang === 'en') _en = _dict;
  else { try { const r = await fetch(base + '/api/v1/i18n/en' + bust); if (r.ok) _en = await r.json(); } catch (e) { /* bỏ qua */ } }
  applyI18n();
}

const $ = (id) => document.getElementById(id);
const API = '/api/v1/content-dna';

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

async function api(path, opts) {
  const r = await fetch(API + path, opts || {});
  let d = null;
  try { d = await r.json(); } catch (e) { /* không phải JSON */ }
  if (!r.ok) throw new Error((d && (typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail))) || ('HTTP ' + r.status));
  return d;
}

function setStatus(msg, kind) {
  const s = $('status');
  s.textContent = msg || '';
  s.className = 'status' + (kind ? ' ' + kind : '');
}

const state = { items: [], rec: null, dirty: false, job: '', pollTimer: 0 };

/* ── danh sách ───────────────────────────────────────────────────────── */

async function loadList() {
  try { state.items = (await api('')).items || []; } catch (e) { state.items = []; setStatus(e.message, 'err'); }
  renderList();
}

function renderList() {
  const box = $('listBox');
  box.replaceChildren();
  $('listEmpty').hidden = state.items.length > 0;
  for (const it of state.items) {
    const b = el('button', 'item' + (state.rec && state.rec.id === it.id ? ' on' : ''));
    b.type = 'button';
    b.appendChild(el('b', '', it.name || it.id));
    const bits = [it.language, it.format, T('dna.list.beats', '{n} beats', { n: it.beats }),
      it.words ? T('dna.list.words', '~{n} words', { n: it.words }) : ''].filter(Boolean);
    b.appendChild(el('span', '', bits.join(' · ')));
    b.appendChild(el('span', '', T('dna.list.samples', 'learned from {n} pieces', { n: it.docs || it.samples || 0 })));
    b.addEventListener('click', () => openDna(it.id));
    box.appendChild(b);
  }
}

/* ── chi tiết ────────────────────────────────────────────────────────── */

const LIST_FIELDS = { fOpenings: 'openings', fClosings: 'closings', fDevices: 'devices', fPhrases: 'signature_phrases', fAvoid: 'avoid' };
const lines = (v) => String(v || '').split('\n').map((s) => s.trim()).filter(Boolean);

async function openDna(id) {
  if (state.dirty && !confirm(T('dna.confirm.discard', 'Discard your unsaved changes?'))) return;
  try {
    state.rec = await api('/' + encodeURIComponent(id));
  } catch (e) { setStatus(e.message, 'err'); return; }
  state.dirty = false;
  try { history.replaceState(null, '', '#/' + id); } catch (e) { /* bỏ qua */ }
  fillForm(state.rec);
  renderList();
}

function fillForm(rec) {
  const dna = rec.dna || {};
  const fmt = (dna.formats || [{}])[0] || {};
  $('detailEmpty').hidden = true;
  $('detail').hidden = false;
  $('fName').value = rec.name || '';
  const st = rec.stats || {};
  const when = rec.updated_at ? new Date(rec.updated_at * 1000).toLocaleString(_lang) : '';
  $('meta').textContent = [
    T('dna.meta.learned', 'Learned from {docs} pieces ({samples} analysed one by one)', { docs: st.docs || 0, samples: st.samples || 0 }),
    rec.model ? T('dna.meta.model', 'model {m}', { m: rec.model }) : '',
    T('dna.meta.version', 'version {v}', { v: rec.version || 1 }), when].filter(Boolean).join(' · ');
  setStatus('');
  $('fFormat').value = fmt.name || '';
  $('fFormatDesc').value = fmt.description || '';
  $('fWords').value = dna.words || rec.usual_words || '';
  renderBeats(fmt.beats || []);
  $('fTransitions').value = (fmt.transitions || []).join('\n');
  $('fPacing').value = fmt.pacing || '';
  $('fLanguage').value = dna.language || '';
  $('fGenre').value = dna.genre || '';
  $('fAudience').value = dna.audience || '';
  $('fPersona').value = dna.persona || '';
  $('fTone').value = dna.tone || '';
  $('fStyle').value = dna.style_summary || '';
  for (const [fid, key] of Object.entries(LIST_FIELDS)) $(fid).value = (dna[key] || []).join('\n');
  const topics = dna.topics || {};
  renderClusters(topics.clusters || []);
  $('fTitleFormulas').value = (topics.title_formulas || []).join('\n');
  $('fHooks').value = (topics.hook_types || []).join('\n');
  $('preview').hidden = true;
}

function renderBeats(beats) {
  const ol = $('beats');
  ol.replaceChildren();
  beats.forEach((b) => ol.appendChild(beatRow(b)));
  updateTotal();
}

function beatRow(b) {
  const li = el('li', 'beat');
  const name = el('input', 'b-name');
  name.value = b.name || '';
  name.maxLength = 120;
  name.setAttribute('aria-label', T('dna.f.beat_name', 'Beat name'));
  const shareBox = el('div', 'b-share');
  const share = el('input');
  share.type = 'number'; share.min = '0'; share.max = '100'; share.step = '1';
  share.value = b.share != null ? b.share : '';
  share.setAttribute('aria-label', T('dna.f.beat_share', 'Share of the piece (%)'));
  const bar = el('div', 'bar'); const fill = el('i'); bar.appendChild(fill);
  shareBox.append(share, bar);
  const del = el('button', 'b-del', '×');
  del.type = 'button';
  del.title = T('dna.action.remove_beat', 'Remove this beat');
  del.setAttribute('aria-label', del.title);
  const purpose = el('textarea', 'b-wide b-purpose');
  purpose.rows = 2; purpose.value = b.purpose || '';
  purpose.placeholder = T('dna.f.beat_purpose', 'What this part does for the viewer');
  const how = el('textarea', 'b-wide b-how');
  how.rows = 2; how.value = b.how || '';
  how.placeholder = T('dna.f.beat_how', 'How it is written');
  li.dataset.example = b.example || '';
  li.append(name, shareBox, del, purpose, how);
  share.addEventListener('input', () => { updateTotal(); markDirty(); });
  del.addEventListener('click', () => { li.remove(); updateTotal(); markDirty(); });
  return li;
}

function updateTotal() {
  let total = 0;
  document.querySelectorAll('#beats .beat').forEach((li) => {
    const v = parseFloat(li.querySelector('.b-share input').value) || 0;
    total += v;
    li.querySelector('.bar i').style.width = Math.min(100, v) + '%';
  });
  const pill = $('shareTotal');
  pill.textContent = T('dna.f.total', 'Total {n}%', { n: Math.round(total) });
  pill.classList.toggle('warn', Math.round(total) !== 100);
  pill.title = Math.round(total) !== 100 ? T('dna.f.total_hint', 'Saving rescales the shares to add up to 100%.') : '';
}

function renderClusters(clusters) {
  const box = $('clusters');
  box.replaceChildren();
  for (const c of clusters) {
    const row = el('div', 'cluster');
    const left = el('div');
    left.appendChild(el('b', '', c.name));
    const sub = [].concat(c.angles || []).slice(0, 3).join(' · ');
    if (sub) left.appendChild(el('small', '', sub));
    const right = el('div', 'share');
    const bar = el('div', 'bar'); const fill = el('i'); fill.style.width = (c.share || 0) + '%'; bar.appendChild(fill);
    right.append(bar, el('span', '', (c.share || 0) + '%'));
    row.append(left, right);
    box.appendChild(row);
  }
  if (!clusters.length) box.appendChild(el('p', 'empty', T('dna.topics.none', 'No topic clusters.')));
}

function collectForm() {
  const rec = state.rec || {};
  const old = (rec.dna || {});
  const oldFmt = (old.formats || [{}])[0] || {};
  const beats = [];
  document.querySelectorAll('#beats .beat').forEach((li) => {
    const name = li.querySelector('.b-name').value.trim();
    if (!name) return;
    beats.push({ name, share: parseFloat(li.querySelector('.b-share input').value) || 0,
      purpose: li.querySelector('.b-purpose').value.trim(), how: li.querySelector('.b-how').value.trim(),
      example: li.dataset.example || '' });
  });
  const dna = Object.assign({}, old, {
    language: $('fLanguage').value.trim(), genre: $('fGenre').value.trim(), audience: $('fAudience').value.trim(),
    persona: $('fPersona').value.trim(), tone: $('fTone').value.trim(), style_summary: $('fStyle').value.trim(),
    words: parseInt($('fWords').value, 10) || 0,
    formats: [Object.assign({}, oldFmt, { name: $('fFormat').value.trim(), description: $('fFormatDesc').value.trim(),
      beats, transitions: lines($('fTransitions').value), pacing: $('fPacing').value.trim() })]
      .concat((old.formats || []).slice(1)),
    topics: Object.assign({}, old.topics || {}, { title_formulas: lines($('fTitleFormulas').value), hook_types: lines($('fHooks').value) }),
  });
  for (const [fid, key] of Object.entries(LIST_FIELDS)) dna[key] = lines($(fid).value);
  return { name: $('fName').value.trim(), dna };
}

function markDirty() { state.dirty = true; setStatus(T('dna.status.unsaved', 'Unsaved changes'), ''); }

async function save() {
  if (!state.rec) return;
  const body = collectForm();
  if (!body.name) { setStatus(T('dna.err.name', 'The DNA needs a name.'), 'err'); return; }
  if (!body.dna.formats[0].beats.length) { setStatus(T('dna.err.beats', 'The structure needs at least one beat.'), 'err'); return; }
  $('btnSave').disabled = true;
  try {
    const rec = await api('/' + encodeURIComponent(state.rec.id), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    state.dirty = false;
    state.rec = await api('/' + encodeURIComponent(rec.id));
    fillForm(state.rec);
    setStatus(T('dna.status.saved', 'Saved — version {v}.', { v: rec.version }), 'ok');
    await loadList();
  } catch (e) { setStatus(e.message, 'err'); }
  $('btnSave').disabled = false;
}

async function del() {
  if (!state.rec) return;
  if (!confirm(T('dna.confirm.delete', 'Delete the DNA “{name}”? Templates that use it will write without a DNA.', { name: state.rec.name }))) return;
  try {
    await api('/' + encodeURIComponent(state.rec.id), { method: 'DELETE' });
    state.rec = null; state.dirty = false;
    $('detail').hidden = true; $('detailEmpty').hidden = false;
    try { history.replaceState(null, '', '#/'); } catch (e) { /* bỏ qua */ }
    await loadList();
  } catch (e) { setStatus(e.message, 'err'); }
}

async function preview() {
  if (!state.rec) return;
  const w = Math.max(60, parseInt($('pvWords').value, 10) || 800);
  try {
    const d = await api('/' + encodeURIComponent(state.rec.id) + '/prompt?words=' + w);
    const pre = $('preview');
    pre.textContent = d.prompt || '';
    pre.hidden = false;
    if (state.dirty) setStatus(T('dna.status.preview_saved', 'The preview shows the SAVED DNA — save first to see your edits.'), '');
  } catch (e) { setStatus(e.message, 'err'); }
}

/* ── hộp học ─────────────────────────────────────────────────────────── */

let relearnId = '';

async function openLearn(id) {
  relearnId = id || '';
  $('learnTitle').textContent = relearnId ? T('dna.learn.title_again', 'Learn this DNA again') : T('dna.learn.title', 'Learn a new DNA');
  $('lName').value = relearnId && state.rec ? state.rec.name : '';
  $('lLinks').value = ''; $('lTexts').value = ''; $('lFiles').value = '';
  const log = $('learnLog'); log.replaceChildren(); log.hidden = true;
  $('lStart').disabled = false;
  const sel = $('lAgent');
  sel.replaceChildren();
  try {
    const agents = (await api('/agents')).agents || [];
    for (const a of agents) {
      const o = el('option', '', a.model ? `${a.name} — ${a.model}` : a.name);
      o.value = a.id;
      sel.appendChild(o);
    }
    if (relearnId && state.rec && state.rec.agent_id) sel.value = state.rec.agent_id;
  } catch (e) { /* để trống: máy chủ tự chọn agent đầu tiên có model */ }
  $('learnDlg').showModal();
}

function logLine(text, err) {
  const log = $('learnLog');
  log.hidden = false;
  const d = el('div', err ? 'err' : '', text);
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}

async function startLearn() {
  const fd = new FormData();
  const name = $('lName').value.trim();
  if (!name) { logLine(T('dna.err.name', 'The DNA needs a name.'), true); return; }
  fd.append('name', name);
  fd.append('agent_id', $('lAgent').value || '');
  fd.append('links', $('lLinks').value);
  fd.append('texts', $('lTexts').value);
  if (relearnId) fd.append('dna_id', relearnId);
  for (const f of $('lFiles').files) fd.append('files', f, f.name);
  $('lStart').disabled = true;
  try {
    const r = await fetch(API + '/learn', { method: 'POST', body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : ('HTTP ' + r.status));
    state.job = d.job;
    logLine(T('dna.learn.started', 'Learning started — this takes a few minutes; you can close this box.'));
    pollJob();
  } catch (e) { logLine(e.message, true); $('lStart').disabled = false; }
}

async function pollJob() {
  clearTimeout(state.pollTimer);
  if (!state.job) return;
  let j;
  try { j = await api('/jobs/' + state.job); } catch (e) { logLine(e.message, true); state.job = ''; $('lStart').disabled = false; return; }
  const last = $('learnLog').lastChild;
  if (!last || last.textContent !== j.message) logLine(j.message, j.status === 'error');
  if (j.status === 'running') { state.pollTimer = setTimeout(pollJob, 2000); return; }
  state.job = '';
  $('lStart').disabled = false;
  if (j.status === 'done') {
    await loadList();
    if ($('learnDlg').open) $('learnDlg').close();
    state.dirty = false;
    await openDna(j.dna_id);
    setStatus(T('dna.status.learned', 'Learned. Check the beats, edit anything, then save.'), 'ok');
  }
}

/* ── khởi động ───────────────────────────────────────────────────────── */

function bind() {
  $('btnLearn').addEventListener('click', () => openLearn(''));
  $('btnRelearn').addEventListener('click', () => state.rec && openLearn(state.rec.id));
  $('btnSave').addEventListener('click', save);
  $('btnDelete').addEventListener('click', del);
  $('btnPreview').addEventListener('click', preview);
  $('btnAddBeat').addEventListener('click', () => {
    $('beats').appendChild(beatRow({ name: '', share: 10 }));
    updateTotal(); markDirty();
    const rows = document.querySelectorAll('#beats .beat');
    rows[rows.length - 1].querySelector('.b-name').focus();
  });
  $('detail').addEventListener('input', (e) => { if (e.target.closest('.preview-bar')) return; markDirty(); });
  $('lStart').addEventListener('click', startLearn);
  $('lCancel').addEventListener('click', async () => {
    if (state.job && confirm(T('dna.confirm.stop', 'Stop learning?'))) {
      try { await api('/jobs/' + state.job + '/cancel', { method: 'POST' }); } catch (e) { /* bỏ qua */ }
    }
    $('learnDlg').close();
  });
  window.addEventListener('beforeunload', (e) => { if (state.dirty) { e.preventDefault(); e.returnValue = ''; } });
}

(async function init() {
  bind();
  await loadI18n();
  await loadList();
  const m = /^#\/(.+)$/.exec(location.hash || '');
  const want = m ? decodeURIComponent(m[1]) : (state.items[0] && state.items[0].id);
  if (want && state.items.some((i) => i.id === want)) await openDna(want);
})();
