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

check('Ctrl+V khong con bi chuyen thanh phim bam',
  /e\.key === 'v' \|\| e\.key === 'V'[\s\S]{0,120}return;/.test(viewSrc));
check('co listener paste lay text that', viewSrc.includes("addEventListener('paste'"));
check('  gui bang insert, khong go tung phim', viewSrc.includes("action: 'insert'"));
check('may chu hieu action insert', srvSrc.includes('keyboard.insertText'));
check('copy: xin vung chon khi tha chuot', viewSrc.includes("type: 'get_selection'"));
check('  may chu tra ve vung chon', srvSrc.includes("type: 'selection'"));
check('  bien giu vung chon khai bao truoc khi dung',
  viewSrc.indexOf('let lastRemoteSelection') < viewSrc.indexOf("addEventListener('copy'"));
const shots = (srvSrc.match(/page\.screenshot\(/g) || []).length;
const withCaret = (srvSrc.match(/caret: 'initial'/g) || []).length;
check('moi khung hinh phat song deu giu con tro', withCaret >= 2, `${withCaret}/${shots} cho chup`);

console.log(`\n${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
