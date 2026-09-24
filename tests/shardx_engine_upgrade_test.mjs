// Lên nhân ShardX mới mà vân tay KHÔNG tự mâu thuẫn.
//
// Run:  node tests/shardx_engine_upgrade_test.mjs      (exit 0 = pass)
//
// Ca thật (24/9/2026): hồ sơ tạo thời nhân 149 khai UA "Chrome/149.0.0.0",
// grease "Not)A;Brand", TLS 8 thuật toán ký. Nhân 152 thì Chrome/152,
// "Not?A_Brand", 11 thuật toán (thêm ML-DSA). Code cũ chỉ sửa client_hints →
// UA nói 149 mà Sec-CH-UA nói 152.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const bm = await import(pathToFileURL(path.join(here, '..', 'tubecli', 'extensions', 'browser', 'browser_manager.js')).href);

let pass = 0, fail = 0;
async function t(name, fn) {
    try { await fn(); pass++; console.log(`[PASS] ${name}`); }
    catch (e) { fail++; console.log(`[FAIL] ${name} -> ${e.message}`); }
}

const TLS_152 = {
    signature_algorithms: [2308, 2309, 2310, 1027, 2052, 1025, 1283, 2053, 1281, 2054, 1537],
    cipher_suites: [4865, 4866, 4867, 49195, 49199, 49196, 49200, 52393, 52392, 49171, 49172, 156, 157, 47, 53],
};
const STAMP_152 = { chromium_version: '152.0.7977.65', grease_brand: 'Not?A_Brand', grease_version: '24', tls: TLS_152 };

function profile149() {
    return {
        navigator: {
            platform: 'Win32',
            user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',
        },
        client_hints: { brand: 'Google Chrome', brand_version: '149', brand_full_version: '149.0.7827.103',
                        chrome_build: 7827, chrome_patch: 103, grease_brand: 'Not)A;Brand', grease_version: '24' },
        tls: { signature_algorithms: [1027, 2052, 1025, 1283, 2053, 1281, 2054, 1537], shuffle_extensions: true },
        webgpu: { limits: { maxTextureDimension2D: 16384 } },
    };
}

await t('UA theo nhân — phần đuôi giữ nguyên', () => {
    const c = profile149();
    assert.equal(bm.applyEngineVersion(c, '152.0.7977.65', STAMP_152), true);
    assert.equal(c.navigator.user_agent,
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36');
});

await t('Client Hints + grease theo dấu cài đặt', () => {
    const c = profile149();
    bm.applyEngineVersion(c, '152.0.7977.65', STAMP_152);
    assert.equal(c.client_hints.brand_version, '152');
    assert.equal(c.client_hints.brand_full_version, '152.0.7977.65');
    assert.equal(c.client_hints.chrome_build, 7977);
    assert.equal(c.client_hints.chrome_patch, 65);
    assert.equal(c.client_hints.grease_brand, 'Not?A_Brand');
    assert.equal(c.client_hints.grease_full_version, '24.0.0.0');
    assert.equal(c.client_hints.brand, 'Google Chrome');
});

await t('TLS: chép khoá của nhân, GIỮ shuffle_extensions của hồ sơ', () => {
    const c = profile149();
    bm.applyEngineVersion(c, '152.0.7977.65', STAMP_152);
    assert.equal(c.tls.signature_algorithms.length, 11);
    assert.equal(c.tls.shuffle_extensions, true);
});

await t('hồ sơ không có khối tls thì để yên (= mặc định của nhân)', () => {
    const c = profile149(); delete c.tls;
    bm.applyEngineVersion(c, '152.0.7977.65', STAMP_152);
    assert.equal(c.tls, undefined);
});

await t('không có dấu (nhân cũ): chỉ sửa phần suy ra từ số, grease giữ nguyên', () => {
    const c = profile149();
    bm.applyEngineVersion(c, '149.0.7827.103', {});
    assert.match(c.navigator.user_agent, /Chrome\/149\.0\.0\.0 /);
    assert.equal(c.client_hints.grease_brand, 'Not)A;Brand');
    assert.equal(c.tls.signature_algorithms.length, 8);
});

await t('UA mobile giữ "Mobile Safari"', () => {
    const c = { navigator: { user_agent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Mobile Safari/537.36' } };
    bm.applyEngineVersion(c, '152.0.7977.65', {});
    assert.match(c.navigator.user_agent, /Chrome\/152\.0\.0\.0 Mobile Safari\/537\.36$/);
});

await t('số phiên bản hỏng thì không đụng gì', () => {
    const c = profile149();
    assert.equal(bm.applyEngineVersion(c, '152', STAMP_152), false);
    assert.match(c.navigator.user_agent, /Chrome\/149/);
});

await t('WebGPU: tắt khi hồ sơ không khai; Linux desktop thì KHÔNG tắt', () => {
    assert.equal(bm.shardxNeedsWebgpuOff(profile149()), false);
    const noGpu = profile149(); delete noGpu.webgpu;
    assert.equal(bm.shardxNeedsWebgpuOff(noGpu), true);
    assert.equal(bm.shardxNeedsWebgpuOff({ navigator: { platform: 'Linux x86_64' } }), false);
    assert.equal(bm.shardxNeedsWebgpuOff({ navigator: { platform: 'Linux armv81', user_agent: 'x Android 14 y' } }), true);
});

await t('--disable-features gộp với danh sách Playwright, không đè', () => {
    const arg = bm.playwrightDisableFeaturesWith('WebGPU');
    const feats = arg.replace('--disable-features=', '').split(',');
    assert.ok(feats.includes('WebGPU'));
    assert.ok(feats.includes('MediaRouter'), 'mất danh sách của Playwright: ' + arg);
    assert.equal(new Set(feats).size, feats.length);
});

await t('bảng BAS có 30.8.0 = Chromium 153; bảng ngược chọn gói MỚI nhất', () => {
    assert.equal(bm.BAS_ENGINE_MAP['30.8.0'], '153.0.8010.37');
    assert.equal(bm.BAS_REVERSE_MAP['153.0.8010.37'], '30.8.0');
    assert.equal(bm.BAS_REVERSE_MAP['150.0.7871.47'], '30.5.0');
    assert.equal(bm.BAS_REVERSE_MAP['149.0.7827.54'], '30.3.0');
});

await t('thư mục tạm của lượt cài lại không bị coi là một nhân', () => {
    assert.ok(bm.SHARDX_VERSION_DIR_RE.test('152.0.7977.65'));
    assert.ok(!bm.SHARDX_VERSION_DIR_RE.test('152.0.7977.65.new'));
    assert.ok(!bm.SHARDX_VERSION_DIR_RE.test('152.0.7977.65.old'));
});

await t('đọc dấu cài đặt; không có dấu thì chỉ mượn manifest khi ĐÚNG số', async () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'sx-stamp-'));
    const saved = { APPDATA: process.env.APPDATA, HOME: process.env.HOME, XDG_CONFIG_HOME: process.env.XDG_CONFIG_HOME };
    process.env.APPDATA = tmp; process.env.XDG_CONFIG_HOME = tmp; process.env.HOME = tmp;
    try {
        const root = process.platform === 'darwin'
            ? path.join(tmp, 'Library', 'Application Support', 'shardx-launcher')
            : path.join(tmp, 'shardx-launcher');
        const eng = path.join(root, 'runtime', 'engines');
        fs.mkdirSync(path.join(eng, '152.0.7977.65'), { recursive: true });
        fs.writeFileSync(path.join(eng, '152.0.7977.65', 'tubecli-install.json'), JSON.stringify(STAMP_152));
        fs.writeFileSync(path.join(root, 'runtime', 'manifest-cache.json'),
            JSON.stringify({ chromium_version: '152.0.7977.65', grease_brand: 'Not?A_Brand', tls: TLS_152 }));
        assert.equal((await bm.readShardxEngineStamp('152.0.7977.65')).grease_brand, 'Not?A_Brand');
        // 149 cài tay, không dấu, manifest đã lên 152 → KHÔNG được mượn grease của 152.
        assert.deepEqual(await bm.readShardxEngineStamp('149.0.7827.103'), {});
        fs.rmSync(path.join(eng, '152.0.7977.65', 'tubecli-install.json'));
        assert.equal((await bm.readShardxEngineStamp('152.0.7977.65')).tls.signature_algorithms.length, 11);
    } finally {
        for (const [k, v] of Object.entries(saved)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; }
        fs.rmSync(tmp, { recursive: true, force: true });
    }
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
