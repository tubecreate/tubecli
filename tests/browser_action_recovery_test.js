/**
 * A browsing session must not be called a failure for missing an optional step,
 * and a missing model must not be printed as if it were an AI's opinion.
 *
 * Run:  node tests/browser_action_recovery_test.js     (exit 0 = pass)
 *
 * The run this was written from did almost everything asked of it — opened
 * Google, searched the right phrase, clicked the first result, read the page —
 * and was then reported as ">>> Process finished with FAILURE status."
 *
 * Three separate defects combined to produce that:
 *
 * 1. server.py picks one of three behaviour templates at random. Only template
 *    two contains a second "then", so open.js's sentence splitter produced
 *    search -> click -> click. That second click is meant to open "an internal
 *    link within the SAME site", but the click action only knew how to find
 *    Google results (#search a[href]), and by then the browser had left Google.
 *    So roughly one run in three failed, which is exactly the "sometimes red"
 *    the owner reported.
 * 2. Any action error propagated and failed the whole session, discarding
 *    everything that had already succeeded.
 * 3. The self-healing path asks a vision model through the local-AI proxy. That
 *    proxy answers HTTP 200 with the failure inside the response TEXT, and the
 *    code printed it under "AI Diagnosis:" — so a refused connection to Ollama
 *    on port 11434 was presented to the owner as a diagnosis.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EXT = path.join(__dirname, '..', 'tubecli', 'extensions', 'browser');

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`[PASS] ${name}${detail ? `  (${detail})` : ''}`); }
  else { fail++; console.log(`[FAIL] ${name} -> ${detail}`); }
};

// ── 1. The proxy-error detector ──────────────────────────────────────
const visionSrc = fs.readFileSync(path.join(EXT, 'vision_engine.js'), 'utf8');
const isProxyError = eval(
  '(' + visionSrc.match(/function isProxyError[\s\S]*?\n}/)[0].replace(/^function isProxyError/, 'function') + ')'
);

console.log('=== 1. phan biet loi ha tang voi chan doan that ===');
check('bat loi ket noi Ollama',
  isProxyError("Error: HTTPConnectionPool(host='localhost', port=11434) Connection refused"));
check('bat loi thieu mo hinh', isProxyError('model llava:latest not found, try pull the model'));
check('KHONG bat chan doan JSON that',
  !isProxyError('{"explanation":"cookie banner","suggestedAction":{"action":"click"}}'));
check('KHONG bat mo ta bang tieng Anh binh thuong',
  !isProxyError('The page shows a cookie banner covering the results.'));
check('chuoi rong khong lam no vo', isProxyError('') === false);

console.log('\n=== 2. click: con o Google thi tim ket qua, roi Google thi tim link noi bo ===');
const clickSrc = fs.readFileSync(path.join(EXT, 'actions', 'click.js'), 'utf8');
check('co nhanh rieng cho trang KHONG phai Google',
  clickSrc.includes("!page.url().includes('google.com/search')"));
check('nhanh do tim link cung ten mien', clickSrc.includes('here.hostname'));
check('bo qua vai link dau (logo/menu)', /Math\.min\(2,/.test(clickSrc));
check('khong tim thay thi nem softFail', clickSrc.includes('err.softFail = true'));
check('van giu chien luoc Google cho trang ket qua',
  clickSrc.includes("'#search .g a[href]:not([href*=\"google.com\"])'"));

console.log('\n=== 3. buoc phu hong KHONG duoc danh hong ca phien ===');
const openSrc = fs.readFileSync(path.join(EXT, 'open.js'), 'utf8');
check('co bat softFail', openSrc.includes('actionError.softFail'));
check('  va bo qua buoc do thay vi nem tiep', /softFail[\s\S]{0,400}?continue;/.test(openSrc));
check('  ghi lai la da bo qua', /skipped: true/.test(openSrc));
// The ordinary failure path must survive: a real error still propagates.
check('loi THAT su van lam hong phien', openSrc.includes('throw actionError;'));

console.log('\n=== 4. khong con in loi mang duoi nhan "AI Diagnosis" ===');
const diagIdx = visionSrc.indexOf("console.log('AI Diagnosis:'");
const guardIdx = visionSrc.indexOf('if (isProxyError(content))');
check('kiem tra loi truoc khi in chan doan',
  guardIdx > -1 && guardIdx < diagIdx, `guard=${guardIdx} print=${diagIdx}`);
check('noi ro cach khac phuc', visionSrc.includes('ollama pull llava'));

console.log('\n=== 5. GPUMonitor: hoi mot lan, khong spam ===');
// A headless VPS has no nvidia-smi and never will while the process lives.
// Retrying per poll spawned a shell and printed two lines each time, and since
// the run log keeps only the last 2000 characters, that noise reliably pushed
// the real failure out of view — the one thing the log exists to show.
const gpuSrc = fs.readFileSync(path.join(EXT, 'gpu_monitor.js'), 'utf8');
check('nho ket qua giua cac lan goi', /let available = null/.test(gpuSrc));
check('  thoat som khi da biet la khong co', /available === false\) return 0/.test(gpuSrc));
check('  chi canh bao mot lan', /let warned = false/.test(gpuSrc));
check('phan biet "khong co" voi loi tam thoi',
  /not found\|ENOENT/.test(gpuSrc) && /leave the door open/.test(gpuSrc));

const { execFileSync } = await import('child_process');
const probe = `process.env.PATH='C:\\\\khong-ton-tai';` +
  `import('file://${path.join(EXT, 'gpu_monitor.js').replace(/\\/g, '/')}')` +
  `.then(async m => { const v=[]; for (let i=0;i<6;i++) v.push(await m.getGpuUsage());` +
  `console.log('VALS='+v.join(',')); });`;
let out = '';
try { out = execFileSync(process.execPath, ['-e', probe], { encoding: 'utf8' }); } catch (e) { out = String(e); }
const lines = out.split('\n').filter(l => l.includes('[GPUMonitor]'));
check('goi 6 lan -> in dung 1 dong', lines.length === 1, `${lines.length} dong`);
check('  va van tra ve 0', /VALS=0,0,0,0,0,0/.test(out), out.trim().split('\n').pop());

console.log('\n=== 6. ke hoach cua AI: nhan du cac dang tra loi that ===');
// Observed on a live run: "Requesting SKELETON from AI model: gemini-2.5-flash"
// followed by "Failed to parse AI skeleton", after which the session fell back
// to random browsing while still calling itself AI-driven. Asking for JSON with
// format:"json" makes several providers answer with an OBJECT, and the natural
// one here is {"actions": [...]} — which the parser rejected outright.
const smSrc = fs.readFileSync(path.join(EXT, 'session_manager.js'), 'utf8');
const parseBody = smSrc.match(/_cleanAndParseJSON\(content\) \{[\s\S]*?\n  \}/)[0];
const cleanAndParse = new Function('content',
  parseBody.replace(/^_cleanAndParseJSON\(content\) \{/, '').replace(/\n  \}$/, ''));

const shapes = [
  ['mang tran', '[{"action":"click"},{"action":"browse"}]', 2],
  ['boc trong {actions:[]}', '{"actions":[{"action":"click"}]}', 1],
  ['boc trong {steps:[]}', '{"steps":[{"action":"browse"},{"action":"click"}]}', 2],
  ['mot object hanh dong', '{"action":"browse","params":{}}', 1],
  ['co rao markdown', '```json\n[{"action":"click"}]\n```', 1],
  ['mang rong -> null', '[]', null],
  ['van xuoi -> null', 'I cannot help with that request.', null],
];
for (const [name, input, want] of shapes) {
  let r; try { r = cleanAndParse(input); } catch (e) { r = 'threw: ' + e.message; }
  const got = Array.isArray(r) ? r.length : r;
  check(name, got === want, JSON.stringify(got));
}
check('that bai thi IN ra model da tra ve gi',
  /Model returned: \$\{preview\}/.test(smSrc) || smSrc.includes('Model returned:'));

console.log('\n=== 7. remote view: dan duoc, va thay con tro text ===');
// Two separate causes, both reported as "the remote browser feels broken".
//
// Paste: the keydown handler forwarded Control+v to the remote Chromium, which
// pasted the SERVER's clipboard — empty. The clipboard TEXT has to travel, and
// the paste event is the only place it is readable here: navigator.clipboard
// is a secure-context API and this dashboard is reached by IP over http.
//
// Caret: frames come from page.screenshot(), and Playwright defaults that to
// caret:'hide' so screenshots are deterministic. Nothing was wrong with focus —
// the caret was being deliberately removed from every frame.
const viewSrc = fs.readFileSync(
  path.join(__dirname, '..', 'tubecli', 'extensions', 'webui', 'static', 'browser_view.html'), 'utf8');
const srvSrc = fs.readFileSync(path.join(EXT, 'preview_server.cjs'), 'utf8');

// The guard must come BEFORE preventDefault. Cancelling the default action of a
// Ctrl+V keydown cancels the paste itself, so the browser never fires 'paste'.
// The first attempt put the guard four lines too late: the listener was correct
// and had already been disarmed, which is why paste stayed dead through two
// rounds of fixes. Position is the whole property here.
{
  const kd = (viewSrc.match(/canvas\.addEventListener\('keydown'[\s\S]*?\n        \}\);/) || [''])[0];
  const guard = kd.indexOf('e.ctrlKey || e.metaKey');
  const pd = kd.indexOf('e.preventDefault()');
  check('Ctrl+V duoc mien TRUOC preventDefault',
    guard > -1 && pd > -1 && guard < pd, `guard=${guard} preventDefault=${pd}`);
  check('  chi con mot cho kiem (khong de lai ma chet)',
    (kd.match(/e\.ctrlKey \|\| e\.metaKey/g) || []).length === 1);
  check('  mien ca copy/cut, khong chi paste', /'v', 'V', 'c', 'C', 'x', 'X'/.test(kd));
}
// On document, not canvas. A paste event goes to whatever would receive the
// text — an input, a contenteditable, else the document. A <canvas> is none of
// those, so a listener bound to it never fires: Ctrl+V did nothing at all,
// which is exactly what was reported after the first attempt at this fix.
check('listener paste gan vao DOCUMENT', viewSrc.includes("document.addEventListener('paste'"));
check('  khong gan nham vao canvas', !viewSrc.includes("canvas.addEventListener('paste'"));
check('listener copy cung gan vao document', viewSrc.includes("document.addEventListener('copy'"));
check('  nhuong lai cho o nhap that tren trang',
  /activeElement[\s\S]{0,200}INPUT[\s\S]{0,80}TEXTAREA/.test(viewSrc));
check('  gui bang insert, khong go tung phim', viewSrc.includes("action: 'insert'"));
check('may chu hieu action insert', srvSrc.includes('keyboard.insertText'));
check('copy: xin vung chon khi tha chuot', viewSrc.includes("type: 'get_selection'"));
check('  may chu tra ve vung chon', srvSrc.includes("type: 'selection'"));
// handleWSMessage(msg) receives only the message — there is no socket in scope.
// Replying with ws.send there threw "ws is not defined" on every mouse release,
// which the browser surfaced as a red line for each drag the user made.
{
  const body = (srvSrc.match(/async function handleWSMessage\(msg\)[\s\S]*?\n    \}/) || [''])[0];
  check('  tra loi bang broadcast, khong dung ws.send',
    body.includes('broadcast({ type: \'selection\'') && !/\bws\.send\(/.test(body),
    /\bws\.send\(/.test(body) ? 'con ws.send trong handleWSMessage' : '');
}
check('  bien giu vung chon khai bao truoc khi dung',
  viewSrc.indexOf('let lastRemoteSelection') < viewSrc.indexOf("addEventListener('copy'"));

// The inline script must PARSE. The check above only compared string positions,
// so it passed happily while the page carried two `let lastRemoteSelection`
// declarations — a SyntaxError that stopped the whole script and left the remote
// view stuck on "Initializing browser...". Position checks cannot see that; a
// parser can.
{
  const scripts = [...viewSrc.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
    .map(m => m[1]);
  let parseErr = '';
  try {
    // eslint-disable-next-line no-new-func
    new Function(scripts.join('\n;\n'));
  } catch (e) { parseErr = e.message; }
  check('browser_view.html: script noi tuyen phan tich duoc', !parseErr, parseErr);

  const dupes = (scripts.join('\n').match(/\blet\s+lastRemoteSelection\b/g) || []).length;
  check('  khong khai bao trung bien', dupes === 1, `${dupes} lan khai bao`);
}
const shots = (srvSrc.match(/page\.screenshot\(/g) || []).length;
const withCaret = (srvSrc.match(/caret: 'initial'/g) || []).length;
check('moi khung hinh phat song deu giu con tro', withCaret >= 2, `${withCaret}/${shots} cho chup`);

console.log('\n=== 8. luong khung hinh: nhe hon va khong phinh bo nho ===');
// Measured on a live session before this: 177 frames, 19.2 MB in ~35 seconds —
// base64 inside JSON, a fresh Image and a data: URI per frame, five a second,
// sent whether or not anything on the page had changed.
check('gui nhi phan, khong base64 trong JSON',
  srvSrc.includes('broadcastFrame') && !/type: 'frame',\s*\n\s*data: base64/.test(srvSrc));
check('bo khung trung voi khung truoc', /hash === lastHash/.test(srvSrc));
check('bo khung khi socket dang un', /bufferedAmount > MAX_BUFFERED_BYTES/.test(srvSrc));
check('viewport chi gui khi doi', /vpKey !== lastViewport/.test(srvSrc));
// Anchored on the function BODY, not on the first mention of its name — the
// name appears at its call sites first, and a fixed-width window from there
// measures nothing. A click-triggered frame and a streamed frame must use the
// same wire format, or one of them arrives in a shape the client cannot read.
{
  const imm = (srvSrc.match(/async function triggerImmediateFrame\(\)[\s\S]*?\n    \}/) || [''])[0];
  check('anh chup tuc thi dung CUNG kenh nhi phan',
    imm.includes('broadcastFrame(buffer)') && !imm.includes('toString(\'base64\')'),
    imm ? '' : 'khong tim thay ham');
}

// Comments stripped first. A plain substring test passes on
// "// bitmap.close();" — the call commented OUT satisfies it, which is the
// opposite of what is being asserted. Verified: without this, disabling the
// call left the suite green.
// \r stripped BEFORE splitting. These files are CRLF, so split('\n') leaves a
// trailing \r on every line — and in a JavaScript regex \r is a line terminator,
// which `.` refuses to match and `$` will not look past. The comment stripper
// silently matched nothing, and the guard below passed against a commented-out
// call. Verified by disabling the call and watching this fail.
const viewCode = viewSrc
  .replace(/\r/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').map(l => l.replace(/(^|[^:])\/\/.*$/, '$1')).join('\n');

check('client giai ma bang createImageBitmap', viewCode.includes('createImageBitmap'));
check('  va GIAI PHONG bitmap sau khi ve', /bitmap\.close\(\)/.test(viewCode));
check('  bo khung neu dang ve khung truoc', /if \(drawing\) return;/.test(viewSrc));
check('  co duong lui khi thieu createImageBitmap',
  /createObjectURL[\s\S]{0,200}revokeObjectURL/.test(viewSrc));
check('khung nhat ky co tran tren', /MAX_LOG_LINES/.test(viewSrc));

// The relay in the middle has to carry the frame type its endpoints use.
// Switching both ends to binary while the proxy still forwarded only TEXT meant
// frames matched no branch and vanished silently: the socket stayed up, JSON
// status messages kept arriving, and the canvas stayed black. Nothing errored,
// on either side.
{
  const routes = fs.readFileSync(
    path.join(__dirname, '..', 'tubecli', 'extensions', 'browser', 'routes.py'), 'utf8');
  check('cau noi WS chuyen tiep ca khung NHI PHAN',
    /WSMsgType\.BINARY/.test(routes) && /await websocket\.send_bytes\(/.test(routes));
  check('  va chieu nguoc lai cung nhan nhi phan',
    /local_ws\.send_bytes\(/.test(routes));
}

console.log('\n=== 9. tab Nhat ky rieng + giao dien di dong ===');
// The agent dialog was built for a desktop: a 170px label column beside a
// two-column body. On a phone that left about 90px for content, and the run-log
// heading wrapped one character per line.
{
  const WEB = path.join(__dirname, '..', 'tubecli', 'extensions', 'webui', 'static');
  const idx = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  const css = fs.readFileSync(path.join(WEB, 'style.css'), 'utf8');
  const appjs = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
  const en = JSON.parse(fs.readFileSync(path.join(WEB, '..', 'locales', 'en.json'), 'utf8'));
  const vi = JSON.parse(fs.readFileSync(path.join(WEB, '..', 'locales', 'vi.json'), 'utf8'));

  check('co tab runlog rieng', idx.includes('data-atab="runlog"') && idx.includes('id="atab-runlog"'));
  check('  nhat ky khong con nam trong tab Lich su',
    idx.indexOf('id="agent-runs-list"') < idx.indexOf('id="atab-history"'));
  check('  mo tab nao thi nap dung thu do',
    /atab === 'runlog'[\s\S]{0,80}loadAgentRuns\(\)/.test(appjs));

  check('CSS: co diem gay cho man hinh hep', /@media \(max-width: 720px\)/.test(css));
  check('  tab strip chuyen thanh hang ngang', /\.agent-tabs-nav\s*\{[^}]*flex-direction:\s*row/.test(css));
  check('  chi hien icon (an nhan chu)',
    /\.agent-tab-btn > span:not\(\.material-symbols-outlined\)\s*\{\s*display:\s*none/.test(css));
  check('  hai cot xep chong thay vi bi ep',
    /\.agent-history-split\s*\{[^}]*flex-direction:\s*column/.test(css));
  // The label stays in the DOM — hidden, not deleted — so screen readers and
  // the tooltip still have it.
  check('  nhan van con trong DOM cho tro nang', idx.includes('agent_modal.tab_history'));

  check('doi "Sua" thanh "Chi tiet"',
    en['agents.edit'] === 'Details' && vi['agents.edit'] === 'Chi tiết',
    `${en['agents.edit']} / ${vi['agents.edit']}`);
  check('  ke ca tieu de hop thoai',
    en['agent_modal.edit_title'] === 'Details:' && vi['agent_modal.edit_title'] === 'Chi tiết:');
  check('vi phu day du khoa cua en',
    Object.keys(en).every(k => k in vi),
    Object.keys(en).filter(k => !(k in vi)).slice(0, 3).join(', '));
}

console.log(`\n${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
