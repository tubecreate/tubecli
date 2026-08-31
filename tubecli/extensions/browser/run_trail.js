// Nhật ký DIỄN BIẾN của một lượt chạy — từng hành động (search gì, bấm gì, xem
// bao lâu, đọc trang nào) ghi ra file theo run_id để bảng Hoạt động mở rộng
// lượt là thấy dòng thời gian, thay vì chỉ một câu query trơ.
//
// File: <data>/extensions_data/browser/session_actions/<run_id>.json (mảng
// entry). Ghi THROTTLE 1s + fire-and-forget: nhật ký phụ trợ không được phép
// làm chậm hay làm hỏng phiên. Cap 300 entry — quá là phiên bất thường, giữ
// phần ĐẦU (mở màn + lúc còn tỉnh táo) thay vì phần đuôi lặp vô hạn.
import fs from 'fs-extra';
import path from 'path';

let _file = '';
let _entries = [];
let _timer = null;
let _dirty = false;

const CAP = 300;

function _flush() {
  _timer = null;
  if (!_file || !_dirty) return;
  _dirty = false;
  fs.outputJson(_file, _entries, { spaces: 1 }).catch(() => {});
}

export function initTrail(dirPath, runId) {
  try {
    if (!dirPath || !runId) return;
    _file = path.join(dirPath, `${String(runId).replace(/[^A-Za-z0-9_-]/g, '')}.json`);
    _entries = [];
    console.log(`[Trail] Recording session actions to ${_file}`);
  } catch (e) { _file = ''; }
}

export function logTrail(entry) {
  try {
    if (!_file || !entry || _entries.length >= CAP) return;
    // KHÔNG BAO GIỜ ghi credential: action login chỉ giữ platform.
    const e = { t: new Date().toISOString(), ...entry };
    if (e.action === 'login' && e.params) e.params = { platform: e.params.platform || '' };
    _entries.push(e);
    _dirty = true;
    if (!_timer) _timer = setTimeout(_flush, 1000);
  } catch (x) {}
}
