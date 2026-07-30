/**
 * Website Manager Deploy Runner for TubeCLI (Node.js Engine)
 * Runs deploy pipeline natively via Node.js spawn to ensure maximum performance and zero CPU freezing.
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const https = require('https');

// Parse CLI arguments: node deploy_runner.js <config_json_path>
const configPath = process.argv[2];
if (!configPath || !fs.existsSync(configPath)) {
  console.error("Config JSON file required.");
  process.exit(1);
}

const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
// Config file KHÔNG còn chứa secret. Token / password / account-id đến từ BIẾN
// MÔI TRƯỜNG (do Python truyền qua _get_cf_env + SITE_ADMIN_PASSWORD).
const { siteName, githubUrl, siteTitle, buildDir } = config;
const cfApiToken = process.env.CLOUDFLARE_API_TOKEN || process.env.CLOUDFLARE_API_KEY || '';
const cfAccountId = process.env.CLOUDFLARE_ACCOUNT_ID || '';
const cfEmail = process.env.CLOUDFLARE_EMAIL || '';
const adminPassword = process.env.SITE_ADMIN_PASSWORD || '';

// Python là NGUỒN GHI FILE LOG DUY NHẤT (đọc stdout của tiến trình này rồi ghi).
// Node chỉ ghi stdout — tránh 2 tiến trình cùng append vào một file gây nhân đôi
// + hỏng nội dung. Không mở/truncate file log ở đây nữa.
function writeLog(text) {
  const cleanText = text.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{4,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
  process.stdout.write(cleanText);
}

// http/https helper cho bước 8 (seed admin). Trả cả headers để bắt Set-Cookie.
function httpRequest(urlStr, { method = 'GET', body = null, timeout = 15000, headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    let u;
    try { u = new URL(urlStr); } catch (e) { return reject(e); }
    const lib = u.protocol === 'http:' ? http : https;
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const hdrs = { ...headers };
    if (data) {
      hdrs['Content-Type'] = 'application/json';
      hdrs['Content-Length'] = data.length;
    }
    const req = lib.request(u, { method, headers: hdrs, timeout }, (res) => {
      let chunks = '';
      res.on('data', d => { chunks += d; });
      res.on('end', () => resolve({ status: res.statusCode, body: chunks, headers: res.headers }));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(new Error('request timeout')); });
    if (data) req.write(data);
    req.end();
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// Lấy cookie 'admin_token' từ header Set-Cookie của response login.
function extractCookie(resHeaders, name) {
  const sc = resHeaders && resHeaders['set-cookie'];
  if (!sc) return '';
  const arr = Array.isArray(sc) ? sc : [sc];
  for (const c of arr) {
    const m = c.match(new RegExp('(?:^|; )' + name + '=([^;]+)'));
    if (m) return m[1];
  }
  return '';
}

// Kết quả init hợp lệ? (2xx + body {success:true})
function initOk(res) {
  if (!res || res.status < 200 || res.status >= 300) return false;
  try { return JSON.parse(res.body).success === true; } catch { return false; }
}

// Seed admin cho MỘT lần thử. Trả {ok, note}.
// Xử lý bug template: schema.sql đã seed sẵn admin (mật khẩu mặc định 'admin123')
// → /api/admin/init đòi auth. Nên: thử init không-auth trước (DB chưa có admin);
// nếu bị chặn thì login admin/admin123 lấy cookie rồi init lại kèm cookie + force
// (seedData reseed đúng nội dung template + đổi mật khẩu sang mật khẩu người dùng).
async function trySeedAdmin(deployUrl, adminPassword) {
  const base = `${deployUrl}/api/admin/init?adminPassword=${encodeURIComponent(adminPassword)}`;
  let res = await httpRequest(base, { method: 'GET', timeout: 30000 });
  if (initOk(res)) return { ok: true, note: 'seed trực tiếp' };
  const unauth = res.status === 401 || res.status === 403 || /unauthor/i.test(res.body || '');
  if (!unauth) return { ok: false, note: `HTTP ${res.status}` };
  // Đăng nhập bằng admin mặc định rồi init lại có token + force
  const login = await httpRequest(`${deployUrl}/api/auth/login`, {
    method: 'POST', body: { username: 'admin', password: 'admin123' }, timeout: 15000,
  });
  const token = extractCookie(login.headers, 'admin_token');
  if (!token) return { ok: false, note: `login mặc định thất bại (HTTP ${login.status})` };
  res = await httpRequest(`${base}&force=true`, {
    method: 'GET', timeout: 30000, headers: { Cookie: `admin_token=${token}` },
  });
  if (initOk(res)) return { ok: true, note: 'seed qua login admin mặc định + force' };
  return { ok: false, note: `init sau login vẫn HTTP ${res.status}` };
}

function runCommand(command, args, options) {
  return new Promise((resolve, reject) => {
    writeLog(`$ ${command} ${args.join(' ')}\n`);
    
    let execCommand = command;
    let useShell = false;
    if (process.platform === 'win32') {
      if (command === 'npm') { execCommand = 'npm.cmd'; useShell = true; }
      else if (command === 'npx') { execCommand = 'npx.cmd'; useShell = true; }
      else if (command === 'git') { execCommand = 'git'; useShell = false; }
    }

    const mergedEnv = {
      ...process.env,
      ComSpec: process.env.ComSpec || process.env.COMSPEC || 'C:\\WINDOWS\\system32\\cmd.exe',
      COMSPEC: process.env.COMSPEC || process.env.ComSpec || 'C:\\WINDOWS\\system32\\cmd.exe',
      SystemRoot: process.env.SystemRoot || 'C:\\WINDOWS',
      ...(options.env || {}),
      GIT_TERMINAL_PROMPT: '0',
      GCM_INTERACTIVE: 'never'
    };
    const pathKey = Object.keys(mergedEnv).find(k => k.toLowerCase() === 'path') || 'PATH';
    let currentPath = mergedEnv[pathKey] || '';
    const sysPaths = ['C:\\Program Files\\Git\\cmd', 'C:\\Program Files\\nodejs', 'C:\\Windows\\system32'];
    for (const p of sysPaths) {
      if (fs.existsSync(p) && !currentPath.includes(p)) {
        currentPath = `${p};${currentPath}`;
      }
    }
    mergedEnv[pathKey] = currentPath;

    const child = spawn(execCommand, args, {
      ...options,
      shell: useShell,
      env: mergedEnv
    });

    let combinedOutput = '';

    child.stdout.on('data', (data) => {
      const text = data.toString();
      combinedOutput += text;
      writeLog(text);
    });

    child.stderr.on('data', (data) => {
      const text = data.toString();
      combinedOutput += text;
      writeLog(text);
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve(combinedOutput);
      } else {
        const err = new Error(`Command "${command} ${args.join(' ')}" failed with code ${code}`);
        err.output = combinedOutput;
        reject(err);
      }
    });

    child.on('error', (err) => {
      reject(err);
    });
  });
}

async function startDeploy() {
  writeLog(`=== DEPLOY BẮT ĐẦU (NODE ENGINE): ${siteName} ===\n\n`);

  const sitePath = path.join(buildDir, siteName);
  const dbName = `${siteName}-db`;
  const bucketName = `${siteName}-bucket`;
  let hasR2 = false;   // set true nếu tạo được R2 bucket (dùng cho wrangler.toml)

  // CF creds đã được Python set sẵn trong process.env (không còn account-id/email
  // hardcode). Bắt buộc phải có account-id + token.
  if (!cfAccountId) throw new Error('Thiếu CLOUDFLARE_ACCOUNT_ID.');
  if (!cfApiToken) throw new Error('Thiếu Cloudflare API Token.');

  const env = { CLOUDFLARE_ACCOUNT_ID: cfAccountId };
  if (process.env.CLOUDFLARE_API_TOKEN) {
    env.CLOUDFLARE_API_TOKEN = process.env.CLOUDFLARE_API_TOKEN;
  } else if (cfEmail) {
    // Global API Key chỉ khi có email rõ ràng
    env.CLOUDFLARE_API_KEY = cfApiToken;
    env.CLOUDFLARE_EMAIL = cfEmail;
  } else {
    // mặc định coi là API Token
    env.CLOUDFLARE_API_TOKEN = cfApiToken;
  }

  if (process.platform === 'win32') {
    const patchPath = path.join(__dirname, 'patch-symlink.cjs');
    if (fs.existsSync(patchPath)) {
      env.NODE_OPTIONS = `--require ${patchPath.replace(/\\/g, '/')}`;
    }
  }

  const opts = { cwd: sitePath, env };

  try {
    // STEP 1: Clone template
    writeLog(`[1/9] Clone template từ GitHub: ${githubUrl}\n`);
    if (fs.existsSync(sitePath)) {
      try {
        fs.rmSync(sitePath, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
      } catch (rmErr) {
        writeLog(`[WARN] rmSync: ${rmErr.message}\n`);
      }
    }
    fs.mkdirSync(sitePath, { recursive: true });

    // '--' ngăn git phân giải githubUrl bắt đầu bằng '-' thành option (argument
    // injection). URL cũng đã được Python validate bằng regex github/gitlab https.
    await runCommand('git', ['-c', 'credential.helper=', 'clone', '--depth=1', '--', githubUrl, '.'], { cwd: sitePath });
    writeLog(`[1/9] Clone thành công!\n`);

    // Extract template key from githubUrl (e.g. template-korean-news.git -> korean-news)
    let tmplKey = '';
    const matchTmpl = githubUrl.match(/template-([a-zA-Z0-9-]+?)(?:\.git)?$/);
    if (matchTmpl) {
      tmplKey = matchTmpl[1];
    }

    // Check if pre-installed node_modules exist in C:\website-manager\templates
    if (tmplKey) {
      const localTmplDir = path.join('C:', 'website-manager', 'templates', tmplKey);
      const localNodeModules = path.join(localTmplDir, 'node_modules');
      const targetNodeModules = path.join(sitePath, 'node_modules');
      if (fs.existsSync(localNodeModules) && !fs.existsSync(targetNodeModules)) {
        writeLog(`[CACHE] Nạp nhanh node_modules từ template mẫu local (${tmplKey})...\n`);
        try {
          fs.cpSync(localNodeModules, targetNodeModules, { recursive: true, dereference: true });
          writeLog(`[CACHE] Đã nạp xong node_modules!\n`);
        } catch (cacheErr) {
          writeLog(`[CACHE] Bỏ qua cache: ${cacheErr.message}. Tải sạch qua npm...\n`);
        }
      }
    }

    // STEP 2: npm install
    writeLog(`[2/9] Cài đặt dependencies (npm install)... (Có thể mất 1-3 phút)\n`);
    await runCommand('npm', ['install', '--prefer-offline'], opts);
    writeLog(`[2/9] Dependencies đã cài đặt xong.\n`);

    // STEP 3: D1 Database
    writeLog(`[3/9] Tạo Cloudflare D1 database '${dbName}'...\n`);
    let dbId = null;
    try {
      const out = await runCommand('npx', ['wrangler', 'd1', 'create', dbName], opts);
      const m = out.match(/database_id\s*=\s*"([^"]+)"/);
      if (m) dbId = m[1];
    } catch (e) {
      writeLog(`[3/9] Tìm kiếm database sẵn có...\n`);
    }

    if (!dbId) {
      try {
        const listOut = await runCommand('npx', ['wrangler', 'd1', 'list', '--json'], opts);
        const jsonStart = listOut.indexOf('[');
        if (jsonStart !== -1) {
          const dbs = JSON.parse(listOut.substring(jsonStart));
          const match = dbs.find(d => d.name === dbName);
          if (match) dbId = match.uuid || match.id;
        }
      } catch (e) {}
    }

    if (!dbId) throw new Error(`Không thể tạo/tìm D1 database '${dbName}'`);
    writeLog(`[3/9] D1 database sẵn sàng: ID = ${dbId}\n`);

    // STEP 3b: Tạo R2 bucket (KHỚP server.js gốc dòng 1497-1511). Bản port cũ bỏ
    // hẳn R2 → template có upload ảnh/lưu trữ bị hỏng. Nếu tài khoản chưa bật R2
    // thì bỏ qua binding một cách mềm (không fail deploy).
    writeLog(`[R2] Kiểm tra/Tạo R2 bucket "${bucketName}"...\n`);
    try {
      await runCommand('npx', ['wrangler', 'r2', 'bucket', 'create', bucketName], opts);
      hasR2 = true;
      writeLog(`[R2] Bucket sẵn sàng.\n`);
    } catch (e) {
      const msg = e.message || '';
      if (/Please enable R2|10042/i.test(msg)) {
        hasR2 = false;
        writeLog(`[R2] ⚠️ R2 chưa được bật trên tài khoản này — bỏ qua R2 binding. (Bật ở Cloudflare Dashboard → R2 nếu template cần lưu trữ ảnh.)\n`);
      } else if (/already exists|already owned|bucket with this name/i.test(msg)) {
        hasR2 = true;
        writeLog(`[R2] Bucket đã tồn tại — dùng lại.\n`);
      } else {
        hasR2 = false;
        writeLog(`[R2] ⚠️ Không tạo được bucket (${msg}). Tiếp tục không R2.\n`);
      }
    }

    // STEP 4: Schema
    writeLog(`[4/9] Áp dụng schema.sql...\n`);
    const schemaPath = path.join(sitePath, 'schema.sql');
    if (!fs.existsSync(schemaPath)) {
      // Cả 12 template đều có schema.sql — thiếu nghĩa là clone hỏng, KHÔNG bỏ qua.
      throw new Error('Không tìm thấy schema.sql (clone template có thể đã hỏng).');
    }
    // TỰ VÁ escape sai kiểu: nhiều template được export với apostrophe escape kiểu
    // JS/JSON `\'` (backslash+nháy) thay vì SQL `''`. SQLite/D1 không hiểu `\` là
    // escape → `'` đóng chuỗi sớm → "near ...: syntax error". `\'` vốn KHÔNG hợp
    // lệ trong SQLite (chỉ sinh từ lỗi export) nên đổi `\'`→`''` là an toàn.
    // (8/12 template gốc dính lỗi này ở seed "Puritan's Pride".)
    try {
      const rawSchema = fs.readFileSync(schemaPath, 'utf8');
      if (rawSchema.includes("\\'")) {
        const fixedSchema = rawSchema.split("\\'").join("''");
        fs.writeFileSync(schemaPath, fixedSchema, 'utf8');
        const n = rawSchema.split("\\'").length - 1;
        writeLog(`[4/9] ⚠️ Đã tự sửa ${n} chỗ escape sai kiểu (\\' → '') trong schema.sql. Nên sửa tận gốc ở template.\n`);
      }
    } catch (fixErr) {
      writeLog(`[4/9] (Bỏ qua bước tự sửa escape: ${fixErr.message})\n`);
    }
    try {
      await runCommand('npx', ['wrangler', 'd1', 'execute', dbName, '--remote', '--file=schema.sql'], opts);
      writeLog(`[4/9] Schema áp dụng thành công.\n`);
    } catch (e) {
      // schema.sql tạo toàn bộ bảng + seed data. Nếu fail mà bỏ qua thì site
      // deploy 'thành công' với D1 rỗng (trang lỗi, không đăng nhập được).
      // Chỉ tha khi lỗi là 'already exists' (chạy lại trên DB đã có schema).
      if (/already exists/i.test(e.message || '')) {
        writeLog(`[4/9] Schema đã tồn tại — bỏ qua.\n`);
      } else {
        throw new Error(`Áp dụng schema.sql thất bại: ${e.message}`);
      }
    }

    // STEP 5: wrangler.toml (KHỚP server.js gốc dòng 1515-1544, gồm R2 binding).
    writeLog(`[5/9] Tạo wrangler.toml...\n`);
    let wranglerToml = `name = "${siteName}"
main = ".open-next/worker.js"
compatibility_date = "2025-06-01"
compatibility_flags = ["nodejs_compat"]

[assets]
directory = ".open-next/assets"
binding = "ASSETS"

[[d1_databases]]
binding = "DB"
database_name = "${dbName}"
database_id = "${dbId}"
`;
    if (hasR2) {
      wranglerToml += `
[[r2_buckets]]
binding = "R2_BUCKET"
bucket_name = "${bucketName}"
`;
    }
    fs.writeFileSync(path.join(sitePath, 'wrangler.toml'), wranglerToml, 'utf8');
    writeLog(`[5/9] wrangler.toml đã tạo${hasR2 ? ' (kèm R2 binding)' : ''}.\n`);

    // STEP 6: OpenNext build
    writeLog(`[6/9] Build project với OpenNext...\n`);
    try {
      await runCommand('npx', ['-y', '@opennextjs/cloudflare', 'build'], opts);
    } catch (e1) {
      try {
        await runCommand('npx', ['opennextjs-cloudflare', 'build'], opts);
      } catch (e2) {
        await runCommand('npm', ['run', 'build:cf'], opts);
      }
    }
    writeLog(`[6/9] Build hoàn tất!\n`);

    // STEP 7: Wrangler deploy
    writeLog(`[7/9] Deploy lên Cloudflare Workers...\n`);
    const deployOut = await runCommand('npx', ['wrangler', 'deploy'], opts);
    const urlMatch = deployOut.match(/https:\/\/[a-zA-Z0-9.-]+\.workers\.dev/);
    const deployUrl = urlMatch ? urlMatch[0] : `https://${siteName}.workers.dev`;
    writeLog(`[7/9] Deploy thành công! URL: ${deployUrl}\n`);

    // STEP 8: Seed admin — GET /api/admin/init?adminPassword=... (KHỚP server.js
    // gốc dòng 1590-1614). Trước đây bước này không tồn tại → mật khẩu người dùng
    // bị bỏ, mọi site dùng chung credential hardcode trong schema.sql (repo công
    // khai). Worker mới deploy cần thời gian propagate → chờ trước + retry, và
    // parse JSON body kiểm `success` (không chỉ HTTP status).
    let adminSeeded = null;   // null = không seed (không có mật khẩu); true/false = kết quả
    if (adminPassword) {
      writeLog(`[8/9] Chờ 15s cho worker ổn định rồi khởi tạo admin...\n`);
      await sleep(15000);
      let seeded = false;
      for (let attempt = 1; attempt <= 5; attempt++) {
        try {
          // trySeedAdmin: thử init không-auth; nếu bị chặn (schema đã seed admin
          // mặc định) thì login admin/admin123 → init lại kèm cookie + force
          // (reseed đúng nội dung template + đổi mật khẩu). Xem chú thích ở hàm.
          const r = await trySeedAdmin(deployUrl, adminPassword);
          if (r.ok) {
            writeLog(`[8/9] Đã seed admin thành công (${r.note}).\n`);
            seeded = true;
            break;
          }
          writeLog(`[8/9] Lần ${attempt}: ${r.note}. Thử lại sau 20s...\n`);
        } catch (e) {
          writeLog(`[8/9] Lần ${attempt} thất bại: ${e.message}. Thử lại sau 20s...\n`);
        }
        if (attempt < 5) await sleep(20000);
      }
      adminSeeded = seeded;
      if (!seeded) {
        writeLog(`[8/9] ⚠️ CẢNH BÁO: chưa seed được mật khẩu admin. Site có thể đang dùng mật khẩu MẶC ĐỊNH (admin/admin123). Hãy đăng nhập rồi đổi mật khẩu trong trang admin.\n`);
      }
    } else {
      writeLog(`[8/9] Bỏ qua seed admin (không có mật khẩu).\n`);
    }

    // GHI CHÚ: pipeline gốc (server.js) KHÔNG lấy "wp token" khi deploy. App
    // password dạng wp_xxxx_xxxx_xxxx_xxxx được sinh bằng một thao tác RIÊNG
    // (INSERT vào bảng api_keys qua wrangler d1 execute) khi người dùng chủ động
    // tạo — không thuộc luồng deploy. Nên KHÔNG login lấy token ở đây (bản cũ đoán
    // sai endpoint và luôn thất bại). wp_token để trống sau deploy, đúng như gốc.
    writeLog(`[9/9] Hoàn tất khởi tạo.\n`);

    // Marker máy-đọc-được ở CUỐI để Python parse chính xác (không regex quét log).
    // adminSeeded=false → Python gắn cờ cảnh báo site đang dùng mật khẩu mặc định.
    writeLog(`DEPLOY_RESULT ${JSON.stringify({ url: deployUrl, adminSeeded })}\n`);
    writeLog(`[9/9] __DEPLOY_DONE__ === DEPLOY HOÀN TẤT THÀNH CÔNG ===\n`);
    process.exit(0);

  } catch (err) {
    writeLog(`❌ LỖI DEPLOY: ${err.message}\n`);
    process.exit(1);
  }
}

startDeploy();
