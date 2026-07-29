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
const { siteName, githubUrl, cfApiToken, cfAccountId, adminPassword, siteTitle, logsDir, buildDir } = config;

const logFilePath = path.join(logsDir, `${siteName}.log`);
fs.mkdirSync(logsDir, { recursive: true });
fs.writeFileSync(logFilePath, '', 'utf8');

function writeLog(text) {
  const cleanText = text.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{4,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
  const timestamp = new Date().toISOString();
  fs.appendFileSync(logFilePath, `[${timestamp}] ${cleanText}`);
  process.stdout.write(cleanText);
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

  const env = {
    CLOUDFLARE_ACCOUNT_ID: cfAccountId || '1e59abca10d4d3c00c33fd172c5cf6a2'
  };

  if (cfApiToken && cfApiToken.trim().startsWith('cfut_')) {
    env.CLOUDFLARE_API_TOKEN = cfApiToken.trim();
  } else if (cfApiToken) {
    env.CLOUDFLARE_API_KEY = cfApiToken.trim();
    env.CLOUDFLARE_EMAIL = config.cfEmail || process.env.CLOUDFLARE_EMAIL || 'zhenfai@gmail.com';
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

    await runCommand('git', ['-c', 'credential.helper=', 'clone', '--depth=1', githubUrl, '.'], { cwd: sitePath });
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

    // STEP 4: Schema
    writeLog(`[4/9] Áp dụng schema.sql...\n`);
    const schemaPath = path.join(sitePath, 'schema.sql');
    if (fs.existsSync(schemaPath)) {
      try {
        await runCommand('npx', ['wrangler', 'd1', 'execute', dbName, '--remote', '--file=schema.sql'], opts);
        writeLog(`[4/9] Schema áp dụng thành công.\n`);
      } catch (e) {
        writeLog(`[4/9] CẢNH BÁO: Schema thất bại: ${e.message}\n`);
      }
    } else {
      writeLog(`[4/9] Bỏ qua (không tìm thấy schema.sql).\n`);
    }

    // STEP 5: wrangler.toml
    writeLog(`[5/9] Tạo wrangler.toml...\n`);
    const wranglerToml = `name = "${siteName}"
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
    fs.writeFileSync(path.join(sitePath, 'wrangler.toml'), wranglerToml, 'utf8');
    writeLog(`[5/9] wrangler.toml đã tạo.\n`);

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

    writeLog(`=== DEPLOY HOÀN TẤT THÀNH CÔNG ===\n`);
    process.exit(0);

  } catch (err) {
    writeLog(`❌ LỖI DEPLOY: ${err.message}\n`);
    process.exit(1);
  }
}

startDeploy();
