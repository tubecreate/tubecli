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

console.log(`\n${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
