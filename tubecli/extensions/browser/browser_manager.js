
// Loaded dynamically, not as a static import. playwright-with-fingerprints is the
// BAS binding and its npm package declares os=win32, so it is simply not installed
// on Linux or macOS. A static import makes this whole module unloadable there —
// which took preview_server.cjs down with it, since that imports BrowserManager.
// Only the BAS launch path touches it; ShardX does its own fingerprinting.
let plugin = null;
try {
    ({ plugin } = await import('playwright-with-fingerprints'));
} catch (e) {
    console.log('[BrowserManager] BAS fingerprint plugin not available on this platform — ShardX only.');
}

function requirePlugin() {
    if (!plugin) {
        throw new Error(
            'This profile uses a BAS engine, which only runs on Windows. '
            + 'Edit the profile to use a ShardX engine instead.'
        );
    }
    return plugin;
}

import fs from 'fs-extra';
import path from 'path';
import axios from 'axios';
import { fileURLToPath } from 'url';
import crypto from 'crypto';

// ── Dò engine ShardX ───────────────────────────────────────────────────────
// Tách khỏi thân launch() vì BA chỗ cần cùng một câu trả lời: hồ sơ ghim ShardX,
// hồ sơ ghim BAS chạy trên máy không phải Windows, và nhánh khoá BAS hết hạn.
// Trước đây chỉ có một khối inline dò ĐÚNG một thư mục phiên bản, nên ghim trỏ
// vào bản chưa tải là hết đường — dù máy đang có engine mới hơn.

function shardxEngineRoot() {
    const home = process.env.HOME || process.env.USERPROFILE;
    if (process.platform === 'win32') {
        const appdata = process.env.APPDATA || (home && path.join(home, 'AppData', 'Roaming'));
        return appdata ? path.join(appdata, 'shardx-launcher') : null;
    }
    if (process.platform === 'darwin') {
        return home ? path.join(home, 'Library', 'Application Support', 'shardx-launcher') : null;
    }
    return home ? path.join(process.env.XDG_CONFIG_HOME || path.join(home, '.config'), 'shardx-launcher') : null;
}

// So sánh theo SỐ, mới nhất đứng trước — cùng cách với resolver trong
// script_runner.js (~:1667). Không so chuỗi: "9" sẽ bị xếp sau "10".
// Dùng cho CẢ HAI họ engine (ShardX 149.0.7827.103, BAS 30.2.0).
function engineVerCmp(a, b) {
    const pa = String(a).split('.').map(Number);
    const pb = String(b).split('.').map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
        const d = (pb[i] || 0) - (pa[i] || 0);
        if (d) return d;
    }
    return 0;
}

// Bố cục thư mục khác nhau giữa bản do launcher tự cài và bản tải thẳng từ CDN,
// nên phải thử từng kiểu.
function shardxBinCandidates(verDir, ver) {
    if (process.platform === 'win32') {
        return [
            path.join(verDir, `ShardX-Windows-${ver}`, 'chrome.exe'),
            path.join(verDir, 'ShardX-Windows', 'chrome.exe'),
            path.join(verDir, 'chrome.exe'),
        ];
    }
    if (process.platform === 'darwin') {
        return [
            path.join(verDir, `ShardX-Mac-arm64-${ver}`, 'ShardX.app', 'Contents', 'MacOS', 'ShardX'),
            path.join(verDir, 'ShardX-Mac-arm64', 'ShardX.app', 'Contents', 'MacOS', 'ShardX'),
        ];
    }
    return [
        path.join(verDir, `ShardX-Linux-${ver}`, 'chrome'),
        path.join(verDir, 'ShardX-Linux', 'chrome'),
        path.join(verDir, 'chrome'),
    ];
}

/**
 * Trả về { exe, version } của một engine ShardX dùng được, hoặc null nếu máy
 * không có engine nào. Ưu tiên đúng bản được ghim; không có thì lấy bản ĐÃ CÀI
 * mới nhất. versionNum rỗng/không truyền nghĩa là "bản mới nhất đang có".
 * Người gọi tự so resolved.version với bản ghim để báo khi phải thay engine.
 */
async function resolveShardxExe(versionNum) {
    const engineRoot = shardxEngineRoot();
    if (!engineRoot) return null;
    const enginesDir = path.join(engineRoot, 'runtime', 'engines');
    if (!await fs.pathExists(enginesDir)) return null;

    const wanted = String(versionNum || '').replace(/ShardX/i, '').replace(/^\s*-\s*/, '').trim();

    let versions = [];
    try {
        for (const name of await fs.readdir(enginesDir)) {
            try {
                if ((await fs.stat(path.join(enginesDir, name))).isDirectory()) versions.push(name);
            } catch (e) { /* một mục lỗi thì bỏ qua, các mục khác vẫn dùng được */ }
        }
    } catch (e) {
        return null;
    }

    const order = [];
    if (wanted && versions.includes(wanted)) order.push(wanted);
    for (const v of versions.filter(v => v !== wanted).sort(engineVerCmp)) order.push(v);

    for (const ver of order) {
        for (const cand of shardxBinCandidates(path.join(enginesDir, ver), ver)) {
            if (!await fs.pathExists(cand)) continue;
            // Archive nén trên Windows không mang bit execute của Unix: engine giải
            // nén xong vẫn spawn hỏng với EACCES.
            if (process.platform !== 'win32') {
                try {
                    await fs.chmod(cand, 0o755);
                    const dir = path.dirname(cand);
                    for (const helper of ['chrome_crashpad_handler', 'chrome_sandbox', 'chrome-sandbox']) {
                        const hp = path.join(dir, helper);
                        if (await fs.pathExists(hp)) await fs.chmod(hp, 0o755);
                    }
                } catch (e) {
                    console.log(`[ShardX] Could not set exec bits on engine ${ver}: ${e.message}`);
                }
            }
            return { exe: cand, version: ver };
        }
    }
    return null;
}

// ── Ghim engine trên hồ sơ ─────────────────────────────────────────────────
// NHÂN quyết định hồ sơ chạy đường nào, KHÔNG phải hệ điều hành: mọi config.json
// đều đã ghi tên nhân trong `browser_version`. Nền tảng chỉ là MỘT yếu tố của câu
// hỏi "nhân đó có dùng được trên máy này không".
//
// Trước đây quyết định gói gọn trong một phép thử chuỗi con PHÂN BIỆT HOA THƯỜNG
// (`browser_version.includes('ShardX')`), nên ghim "shardx 149" hay "SHARDX-149"
// rơi thẳng sang nhánh BAS rồi chết vì khoá — thông báo chẳng liên quan gì tới
// nguyên nhân thật.
function parseEnginePin(browserVersion) {
    const raw = browserVersion == null ? '' : String(browserVersion).trim();
    const low = raw.toLowerCase();
    if (!raw || low === 'default' || low === 'latest') {
        return { family: null, version: null, raw: raw || null };
    }
    if (/shardx/i.test(raw)) {
        const version = raw.replace(/shardx/i, '').replace(/^\s*[-_]\s*/, '').trim();
        return { family: 'shardx', version: version || null, raw };
    }
    return { family: 'bas', version: raw, raw };
}

// Engine BAS trên đĩa đặt tên theo phiên bản BAS (30.2.0) còn hồ sơ ghim theo
// phiên bản CHROMIUM (149.0.7827.54), nên cần cả hai chiều. Để ở đây thay vì
// trong thân launch() để nhánh quyết định engine và nhánh dò engine dùng CHUNG
// một bảng.
const BAS_ENGINE_MAP = {
    '30.2.0': '149.0.7827.54',
    '30.1.0': '148.0.7778.97',
    '30.0.0': '147.0.7727.56',
    '29.9.2': '146.0.7680.80',
    '29.8.1': '145.0.7632.46',
    '29.7.0': '144.0.7559.60',
    '29.5.0': '142.0.7444.60',
    '28.3.1': '138.0.7333.45',
    '28.2.0': '137.0.7222.35'
};
const BAS_REVERSE_MAP = Object.fromEntries(Object.entries(BAS_ENGINE_MAP).map(([k, v]) => [v, k]));

function basEngineDir() {
    return path.join(path.dirname(fileURLToPath(import.meta.url)), 'data', 'script');
}

// Chỉ tính là "đã cài" khi có FastExecuteScript.exe: một lượt tải hỏng để lại
// thư mục rỗng vẫn trông y như đã cài.
async function installedBasVersions() {
    const dir = basEngineDir();
    if (!await fs.pathExists(dir)) return [];
    let names = [];
    try { names = await fs.readdir(dir); } catch (e) { return []; }
    const out = [];
    for (const name of names) {
        if (!/^\d+\.\d+\.\d+$/.test(name)) continue;
        if (await fs.pathExists(path.join(dir, name, 'FastExecuteScript.exe'))) out.push(name);
    }
    return out.sort(engineVerCmp);
}

// Dò trong HỌ BAS: đúng bản được ghim trước, không có thì bản đã cài mới nhất.
// Cùng luật với resolveShardxExe ở trên, để hai họ hành xử giống nhau.
async function resolveBasEngine(wantedVersion) {
    const versions = await installedBasVersions();
    if (!versions.length) return null;
    const wanted = String(wantedVersion || '').trim();
    const picked = (wanted && versions.includes(wanted)) ? wanted : versions[0];
    return { version: picked, dir: path.join(basEngineDir(), picked) };
}

// "Cài rồi" CHƯA CHẮC "dùng được".
//   - không có binding (gói browser-with-fingerprints khai os=win32) → BAS chết
//     ngay khi gọi, không cần thử;
//   - không có engine nào trong data/script → cũng chết.
// Còn KHOÁ hết hạn thì không thể biết trước khi launch: BAS chỉ nói ra lúc mở.
// Trường hợp đó xử ở nhánh isKeyError trong vòng retry, không phải ở đây.
async function basUnusableReason() {
    if (!plugin) {
        return {
            code: 'bas_binding_missing',
            text: `The BAS engine binding is not installed on ${process.platform} `
                + `(browser-with-fingerprints ships Windows binaries only)`
        };
    }
    if (!(await installedBasVersions()).length) {
        return {
            code: 'bas_engine_missing',
            text: `No BAS engine is installed under ${basEngineDir()}`
        };
    }
    return null;
}

// Kết luận "máy này không có engine để chạy hồ sơ đó". Có lớp riêng vì nó phải
// ĐI XUYÊN qua catch bao quanh khối dò engine — nuốt nó chính là chỗ đẻ ra thông
// báo sai "BAS engine, Windows only" khi sự thật là chưa tải engine ShardX.
class EngineUnavailableError extends Error {
    constructor(message) {
        super(message);
        this.name = 'EngineUnavailableError';
        this.code = 'ENGINE_UNAVAILABLE';
    }
}

function extractRawKey(jsonString, key) {
    const searchStr = `"${key}":`;
    const startIdx = jsonString.indexOf(searchStr);
    if (startIdx === -1) return null;
    
    let valStart = startIdx + searchStr.length;
    while (valStart < jsonString.length && /\s/.test(jsonString[valStart])) {
        valStart++;
    }
    
    let braceCount = 0;
    let inString = false;
    let escape = false;
    
    for (let i = valStart; i < jsonString.length; i++) {
        const char = jsonString[i];
        if (escape) {
            escape = false;
            continue;
        }
        if (char === '\\') {
            escape = true;
            continue;
        }
        if (char === '"') {
            inString = !inString;
            continue;
        }
        if (!inString) {
            if (char === '{' || char === '[') {
                braceCount++;
            } else if (char === '}' || char === ']') {
                braceCount--;
                if (braceCount === 0) {
                    return jsonString.slice(valStart, i + 1);
                }
            } else if (braceCount === 0 && (char === ',' || char === '}')) {
                return jsonString.slice(valStart, i);
            }
        }
    }
    return null;
}

const isShardXFpFormat = (fpStr) => {
    try {
        const parsed = typeof fpStr === 'string' ? JSON.parse(fpStr) : fpStr;
        return parsed && (parsed.navigator || parsed.screen || parsed.webgpu) && !parsed.canvas;
    } catch { return false; }
};

function parseChromeVersion(ua) {
    const match = ua.match(/Chrome\/(\d+)\.(\d+)\.(\d+)\.(\d+)/);
    if (match) {
        return {
            major: match[1],
            minor: match[2],
            build: parseInt(match[3], 10),
            patch: parseInt(match[4], 10),
            full: match[0].split('/')[1]
        };
    }
    return {
        major: "124",
        minor: "0",
        build: 6367,
        patch: 207,
        full: "124.0.6367.207"
    };
}

export function convertBasToShardX(basFp, profileName = "") {
    if (!basFp) return null;
    
    let fp = typeof basFp === 'string' ? JSON.parse(basFp) : basFp;
    
    if (fp.fingerprint) {
        fp = typeof fp.fingerprint === 'string' ? JSON.parse(fp.fingerprint) : fp.fingerprint;
    }

    const ua = fp.ua || (fp.attr && fp.attr["navigator.userAgent"]) || (fp.navigator && fp.navigator.userAgent) || "";
    const chromeVer = parseChromeVersion(ua);

    // Compute polynomial hash-based seed for profileName, otherwise random
    const seed = profileName ? profileName.split('').reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) & 0x7FFFFFFF, 0) : Math.floor(Math.random() * 1000000);

    let timeZone = "Asia/Ho_Chi_Minh";
    try {
        timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || timeZone;
    } catch (e) {}

    const langStr = fp.lang || (fp.attr && fp.attr["navigator.language"]) || "en-US,en;q=0.9";
    const langParts = langStr.split(",").map(p => p.split(";")[0].trim());
    const primaryLang = langParts[0] || "en-US";

    const screenWidth = fp.width || (fp.attr && fp.attr["screen.width"]) || 1920;
    const screenHeight = fp.height || (fp.attr && fp.attr["screen.height"]) || 1080;
    const availWidth = (fp.attr && fp.attr["screen.availWidth"]) || screenWidth;
    const availHeight = (fp.attr && fp.attr["screen.availHeight"]) || screenHeight;
    const colorDepth = (fp.attr && fp.attr["screen.colorDepth"]) || 24;
    const pixelDepth = (fp.attr && fp.attr["screen.pixelDepth"]) || 24;
    const devicePixelRatio = (fp.attr && fp.attr["window.devicePixelRatio"]) || 1;
    const availLeft = (fp.attr && fp.attr["screen.availLeft"]) || 0;
    const availTop = (fp.attr && fp.attr["screen.availTop"]) || 0;

    const webglVendor = fp.webgl_properties?.unmaskedVendor || "Google Inc.";
    const webglRenderer = fp.webgl_properties?.unmaskedRenderer || fp.webgl_properties?.renderer || "";
    const webglVendorMasked = fp.webgl_properties?.vendor || "WebKit";
    const webglRendererMasked = fp.webgl_properties?.renderer || "WebKit WebGL";
    const maxTextureSize = fp.webgl_properties?.maxTextureSize || 16384;
    const maxVertexAttribs = fp.webgl_properties?.maxVertexAttribs || 16;
    
    let webglExtensions = [];
    if (typeof fp.webgl_properties?.extensions === "string") {
        webglExtensions = fp.webgl_properties.extensions.split(",").map(e => e.trim()).filter(Boolean);
    } else if (Array.isArray(fp.webgl_properties?.extensions)) {
        webglExtensions = fp.webgl_properties.extensions;
    } else {
        webglExtensions = [
            "EXT_clip_control", "EXT_color_buffer_float", "EXT_color_buffer_half_float",
            "EXT_conservative_depth", "EXT_depth_clamp", "EXT_disjoint_timer_query_webgl2",
            "EXT_float_blend", "EXT_polygon_offset_clamp", "EXT_render_snorm",
            "EXT_texture_compression_bptc", "EXT_texture_compression_rgtc",
            "EXT_texture_filter_anisotropic", "EXT_texture_mirror_clamp_to_edge",
            "EXT_texture_norm16", "KHR_parallel_shader_compile",
            "NV_shader_noperspective_interpolation", "OES_draw_buffers_indexed",
            "OES_sample_variables", "OES_shader_multisample_interpolation",
            "OES_texture_float_linear", "OVR_multiview2", "WEBGL_blend_func_extended",
            "WEBGL_clip_cull_distance", "WEBGL_compressed_texture_s3tc",
            "WEBGL_compressed_texture_s3tc_srgb", "WEBGL_debug_renderer_info",
            "WEBGL_debug_shaders", "WEBGL_lose_context", "WEBGL_multi_draw",
            "WEBGL_polygon_mode", "WEBGL_provoking_vertex", "WEBGL_stencil_texturing"
        ];
    }

    let webgpuVendor = "intel";
    let webgpuArch = "";
    const rLower = webglRenderer.toLowerCase();
    if (rLower.includes("nvidia") || rLower.includes("geforce")) {
        webgpuVendor = "nvidia";
        webgpuArch = "ampere";
    } else if (rLower.includes("amd") || rLower.includes("radeon")) {
        webgpuVendor = "amd";
    } else if (rLower.includes("intel") || rLower.includes("uhd") || rLower.includes("iris")) {
        webgpuVendor = "intel";
        webgpuArch = "gen-9";
    }

    let platform = "Windows";
    let platformValue = "Win32";
    let platformVersion = "10.0.0";
    const rawPlatform = (fp.attr && fp.attr["navigator.platform"]) || (fp.navigator && fp.navigator.platform) || "Win32";
    if (rawPlatform.toLowerCase().includes("mac") || ua.toLowerCase().includes("macintosh")) {
        platform = "MacIntel";
        platformValue = "MacIntel";
        platformVersion = "13.0.0";
    }

    const shardxFp = {
        name: fp.name || "converted-bas-fp",
        notes: webglRenderer,
        timezone: timeZone,
        icu_locale: primaryLang,
        navigator: {
            language: primaryLang,
            accept_language: langStr,
            languages: langParts,
            user_agent: ua,
            platform: platform,
            platform_value: platformValue,
            platform_version: platformVersion,
            hardware_concurrency: fp.attr?.hardwareConcurrency || fp.navigator?.hardwareConcurrency || 8,
            device_memory: fp.attr?.deviceMemory || fp.navigator?.deviceMemory || 8,
            vendor: fp.attr?.["navigator.vendor"] || fp.navigator?.vendor || "Google Inc.",
            max_touch_points: fp.attr?.maxTouchPoints || fp.navigator?.maxTouchPoints || 0
        },
        client_hints: {
            brand: "Google Chrome",
            brand_version: chromeVer.major,
            platform_version: platformVersion,
            architecture: platform === "Windows" ? "x86" : "arm",
            bitness: "64",
            mobile: false,
            grease_brand: "Not)A;Brand",
            grease_version: "24",
            chrome_build: chromeVer.build,
            chrome_patch: chromeVer.patch,
            brand_full_version: chromeVer.full,
            grease_full_version: "24.0.0.0"
        },
        screen: {
            width: screenWidth,
            height: screenHeight,
            avail_width: availWidth,
            avail_height: availHeight,
            color_depth: colorDepth,
            pixel_depth: pixelDepth,
            device_pixel_ratio: devicePixelRatio,
            color_gamut: "srgb",
            dynamic_range_high: false,
            avail_left: availLeft,
            avail_top: availTop
        },
        window: {
            outer_width: screenWidth,
            outer_height: availHeight,
            inner_width: screenWidth,
            inner_height: availHeight - 87
        },
        webgl: {
            vendor: webglVendor,
            renderer: webglRenderer,
            vendor_masked: webglVendorMasked,
            renderer_masked: webglRendererMasked,
            max_texture_size: maxTextureSize,
            max_vertex_attribs: maxVertexAttribs,
            extensions: webglExtensions
        },
        webgpu: {
            vendor: webgpuVendor,
            architecture: webgpuArch,
            device: "",
            description: "",
            limits: {
                maxTextureDimension1D: 16384,
                maxTextureDimension2D: 16384,
                maxTextureDimension3D: 2048,
                maxTextureArrayLayers: 2048,
                maxBindGroups: 4,
                maxBindGroupsPlusVertexBuffers: 24,
                maxBindingsPerBindGroup: 1000,
                maxDynamicUniformBuffersPerPipelineLayout: 10,
                maxDynamicStorageBuffersPerPipelineLayout: 8,
                maxSampledTexturesPerShaderStage: 48,
                maxSamplersPerShaderStage: 16,
                maxStorageBuffersPerShaderStage: 16,
                maxStorageTexturesPerShaderStage: 8,
                maxUniformBuffersPerShaderStage: 12,
                maxUniformBufferBindingSize: 65536,
                maxStorageBufferBindingSize: 2147483644,
                minUniformBufferOffsetAlignment: 256,
                minStorageBufferOffsetAlignment: 256,
                maxVertexBuffers: 8,
                maxBufferSize: 2147483648.0,
                maxVertexAttributes: 30,
                maxVertexBufferArrayStride: 2048,
                maxInterStageShaderVariables: 28,
                maxColorAttachments: 8,
                maxColorAttachmentBytesPerSample: 128,
                maxComputeWorkgroupStorageSize: 32768,
                maxComputeInvocationsPerWorkgroup: 1024,
                maxComputeWorkgroupSizeX: 1024,
                maxComputeWorkgroupSizeY: 1024,
                maxComputeWorkgroupSizeZ: 64,
                maxComputeWorkgroupsPerDimension: 65535
            }
        },
        audio: {
            sample_rate: fp.audio_properties?.BaseAudioContextSampleRate || 44100,
            channel_count: fp.audio_properties?.AudioDestinationNodeMaxChannelCount || 2
        },
        connection: {
            effective_type: fp.connection?.effectiveType || "4g",
            downlink_mbps: fp.connection?.downlink || 10,
            rtt_msec: fp.connection?.rtt || 50,
            save_data: fp.connection?.saveData || false
        },
        storage_estimate: {
            quota_gb: 10
        },
        webauthn: {
            uvpa: true
        },
        memory: {
            heap_size_limit: 4294967296
        },
        battery: {
            charging: fp.battery?.charging ?? true,
            level: fp.battery?.level ?? 1,
            charging_time: fp.battery?.chargingTime ?? 0,
            discharging_time: String(fp.battery?.dischargingTime ?? "Infinity")
        },
        media_devices: {
            audio_input_count: 1,
            audio_output_count: 1,
            video_input_count: 0
        },
        speech: {
            voices: [
                { name: "Google US English", lang: "en-US", local_service: false, is_default: true },
                { name: "Google UK English Female", lang: "en-GB", local_service: false, is_default: false },
                { name: "Google UK English Male", lang: "en-GB", local_service: false, is_default: false }
            ]
        },
        noise: {
            canvas: { enabled: true, seed: seed },
            webgl: { enabled: true, seed: seed, intensity: 5 },
            audio: { enabled: true, seed: seed },
            client_rects: { enabled: true, seed: seed, max_offset: 5 },
            sensors: { enabled: true, seed: seed },
            fonts: { enabled: true, seed: seed }
        },
        tls: {
            cipher_suites: [4865, 4866, 4867, 49195, 49199, 49196, 49200, 52393, 52392, 49171, 49172, 156, 157, 47, 53],
            signature_algorithms: [1027, 2052, 1025, 1283, 2053, 1281, 2054, 1537],
            shuffle_extensions: true
        }
    };
    
    return shardxFp;
}

/** Ai đang thật sự giữ hồ sơ này? Trả pid nếu còn tiến trình sống, 0 nếu khoá đã mồ côi.
 *
 * SingletonLock của Chromium là symlink trỏ tới "<hostname>-<pid>". Đọc pid rồi
 * kill(pid, 0) — tín hiệu 0 không giết ai, chỉ hỏi "tiến trình này còn không".
 * EPERM cũng là còn sống (tiến trình của user khác). Không đọc được coi như mồ côi:
 * trên Windows khoá là file thường chứ không phải symlink, và Chromium ở đó dùng
 * mutex có tên nên file sót lại không mang thông tin gì.
 */
function singletonHolderPid(profilePath) {
    try {
        const target = fs.readlinkSync(path.join(profilePath, 'SingletonLock'));
        const pid = parseInt(String(target).split('-').pop(), 10);
        if (!Number.isFinite(pid) || pid <= 0) return 0;
        try { process.kill(pid, 0); return pid; }
        catch (e) { return e.code === 'EPERM' ? pid : 0; }
    } catch (e) { return 0; }
}

/** Dọn khoá MỒ CÔI trước khi mở. Ném lỗi rõ ràng nếu khoá đang có chủ thật.
 *
 * Trước bản này browser_manager không dọn khoá lần nào (preview_server.cjs dọn ở
 * 2 chỗ, nên live view sống trong khi lượt theo lịch chết hàng loạt trên Linux).
 */
function clearStaleSingletonLocks(profilePath) {
    const holder = singletonHolderPid(profilePath);
    if (holder) {
        const err = new Error(
            `Profile is already open in another process (pid ${holder}). Close the live view `
            + `or stop that session before launching this profile again.`);
        err.code = 'PROFILE_IN_USE';
        throw err;
    }
    let cleared = 0;
    for (const lf of ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'LOCK']) {
        const p = path.join(profilePath, lf);
        // lstat, KHÔNG existsSync: existsSync đi theo symlink nên một SingletonLock
        // trỏ tới đích đã biến mất sẽ bị coi là "không tồn tại" và không bao giờ được xoá.
        try { fs.lstatSync(p); } catch (e) { continue; }
        try { fs.unlinkSync(p); cleared++; } catch (e) {
            console.warn(`[Launch] Could not remove stale ${lf}: ${e.message}`);
        }
    }
    if (cleared) {
        console.log(`[Launch] Cleared ${cleared} stale Chromium lock file(s) left by a previous session.`);
    }
}

export class BrowserManager {
    constructor(config = {}) {
        this.baseDir = config.baseDir || './profiles';
        this.serviceKey = null;
    }

    async resolveProxyTimezone(proxy) {
        if (proxy) {
            let host = null;
            try {
                let normalized = proxy;
                if (!normalized.includes('://')) {
                    normalized = 'http://' + normalized;
                }
                const u = new URL(normalized);
                host = u.hostname;
            } catch (e) {
                const match = proxy.match(/(?:[^@\n]+@)?(?:www\.)?([^:\/\n]+)/);
                host = match ? match[1] : null;
            }
            
            if (host && host !== '127.0.0.1' && host !== 'localhost') {
                console.log(`[Timezone] Resolving timezone for proxy host: ${host}`);
                try {
                    const resp = await axios.get(`http://ip-api.com/json/${host}`, { timeout: 5000 });
                    if (resp.data && resp.data.status === 'success' && resp.data.timezone) {
                        console.log(`[Timezone] Proxy timezone resolved successfully: ${resp.data.timezone}`);
                        return resp.data.timezone;
                    }
                } catch (e) {
                    console.warn(`[Timezone] Failed to resolve proxy timezone: ${e.message}`);
                }
            }
        }
        
        // Fallback to local system timezone if proxy lookup fails or no proxy
        try {
            const systemTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            if (systemTz) return systemTz;
        } catch (e) {}
        
        return "Asia/Ho_Chi_Minh";
    }

    async resolveIPDetails(proxy) {
        let host = null;
        if (proxy) {
            try {
                let normalized = proxy;
                if (!normalized.includes('://')) {
                    normalized = 'http://' + normalized;
                }
                const u = new URL(normalized);
                host = u.hostname;
            } catch (e) {
                const match = proxy.match(/(?:[^@\n]+@)?(?:www\.)?([^:\/\n]+)/);
                host = match ? match[1] : null;
            }
        }
        
        let url = 'http://ip-api.com/json/';
        if (host && host !== '127.0.0.1' && host !== 'localhost') {
            url = `http://ip-api.com/json/${host}`;
        }
        
        console.log(`[IPDetails] Resolving details from: ${url}`);
        try {
            const resp = await axios.get(url, { timeout: 5000 });
            if (resp.data && resp.data.status === 'success') {
                console.log(`[IPDetails] Resolved: timezone=${resp.data.timezone}, countryCode=${resp.data.countryCode}`);
                return {
                    timezone: resp.data.timezone || "Asia/Ho_Chi_Minh",
                    countryCode: resp.data.countryCode || "VN"
                };
            }
        } catch (e) {
            console.warn(`[IPDetails] Failed to resolve details: ${e.message}`);
        }
        
        // Fallback: local system timezone and system country
        let timezone = "Asia/Ho_Chi_Minh";
        try {
            timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || timezone;
        } catch (e) {}
        
        // Default countryCode VN or resolve from language
        let countryCode = "VN";
        try {
            const lang = Intl.DateTimeFormat().resolvedOptions().locale;
            if (lang && lang.includes('-')) {
                countryCode = lang.split('-')[1].toUpperCase();
            }
        } catch (e) {}
        
        return { timezone, countryCode };
    }

    getLanguageForCountry(countryCode) {
        const c = countryCode ? countryCode.toUpperCase() : "VN";
        const map = {
            "VN": {
                locale: "vi-VN",
                languages: ["vi-VN", "vi", "en-US", "en"],
                acceptLanguage: "vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5"
            },
            "US": {
                locale: "en-US",
                languages: ["en-US", "en"],
                acceptLanguage: "en-US,en;q=0.9"
            },
            "GB": {
                locale: "en-GB",
                languages: ["en-GB", "en-US", "en"],
                acceptLanguage: "en-GB,en-US;q=0.9,en;q=0.8"
            },
            "RU": {
                locale: "ru-RU",
                languages: ["ru-RU", "ru", "en-US", "en"],
                acceptLanguage: "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            "FR": {
                locale: "fr-FR",
                languages: ["fr-FR", "fr", "en-US", "en"],
                acceptLanguage: "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            "DE": {
                locale: "de-DE",
                languages: ["de-DE", "de", "en-US", "en"],
                acceptLanguage: "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            "UA": {
                locale: "uk-UA",
                languages: ["uk-UA", "uk", "ru-UA", "ru", "en-US", "en"],
                acceptLanguage: "uk-UA,uk;q=0.9,ru-UA;q=0.8,ru;q=0.7,en-US;q=0.6,en;q=0.5"
            },
            "TH": {
                locale: "th-TH",
                languages: ["th-TH", "th", "en-US", "en"],
                acceptLanguage: "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            "ID": {
                locale: "id-ID",
                languages: ["id-ID", "id", "en-US", "en"],
                acceptLanguage: "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            "PH": {
                locale: "fil-PH",
                languages: ["fil-PH", "fil", "en-US", "en"],
                acceptLanguage: "fil-PH,fil;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            "MY": {
                locale: "ms-MY",
                languages: ["ms-MY", "ms", "en-US", "en"],
                acceptLanguage: "ms-MY,ms;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            "SG": {
                locale: "en-SG",
                languages: ["en-SG", "en-GB", "en-US", "en", "zh-SG", "zh"],
                acceptLanguage: "en-SG,en-GB;q=0.9,en-US;q=0.8,en;q=0.7"
            }
        };
        
        return map[c] || {
            locale: "en-US",
            languages: ["en-US", "en"],
            acceptLanguage: "en-US,en;q=0.9"
        };
    }

    async fetchServiceKey() {
        if (this.serviceKey) return this.serviceKey;

        // 1. Try to read from global_settings.json
        try {
            const extDir = path.dirname(fileURLToPath(import.meta.url));
            const settingsPath = path.resolve(extDir, '..', '..', '..', 'data', 'global_settings.json');
            if (await fs.pathExists(settingsPath)) {
                const settings = await fs.readJson(settingsPath);
                if (settings.bas_fingerprint_key && settings.bas_fingerprint_key.trim()) {
                    this.serviceKey = settings.bas_fingerprint_key.trim();
                    plugin?.setServiceKey(this.serviceKey);
                    console.log('Service key loaded from settings.');
                    return this.serviceKey;
                }
            }
        } catch (e) {
            console.warn('Failed to load global settings in browser_manager:', e.message);
        }

        // 2. Fallback to API if not in settings
        try {
            console.log('Fetching service key from API...');
            const response = await axios.get('https://api.tubecreate.com/api/fingerprints/key.php', { timeout: 10000 });
            if (response.data && response.data.status === 'success' && response.data.key) {
                // Decode Base64 key
                this.serviceKey = Buffer.from(response.data.key, 'base64').toString('utf8');
                plugin?.setServiceKey(this.serviceKey);
                console.log('Service key fetched and decoded from API.');
                return this.serviceKey;
            }
            return null;
        } catch (e) {
            console.error(`Error fetching service key: ${e.message}`);
        }
        return null;
    }

    async ensureProfile(profileName) {
        const profilePath = path.resolve(this.baseDir, profileName);
        await fs.ensureDir(profilePath);
        return profilePath;
    }

    async cleanProfile(profileName) {
        const profilePath = path.resolve(this.baseDir, profileName);
        if (await fs.pathExists(profilePath)) {
            console.log(`Cleaning up profile at ${profilePath}...`);
            try {
                // Preserve config.json if it exists
                const configPath = path.join(profilePath, 'config.json');
                if (await fs.pathExists(configPath)) {
                    await fs.copy(configPath, `${configPath}.bak`);
                }
                
                await fs.emptyDir(profilePath);
                
                if (await fs.pathExists(`${configPath}.bak`)) {
                    await fs.move(`${configPath}.bak`, configPath);
                }
            } catch (e) {
                console.warn(`Could not remove/restore profile directory: ${e.message}`);
            }
        }
    }

    async getFingerprint(profileName, options = {}) {
        const profilePath = await this.ensureProfile(profileName);
        const fingerprintPath = path.join(profilePath, 'fingerprint_saved.json');
        const legacyFingerprintPath = path.join(profilePath, 'fingerprint.json');
        const configPath = path.join(profilePath, 'config.json');

        let fingerprint;

        let isShardX = false;
        let tags = options.tags || ['Windows', 'Chrome'];
        if (await fs.pathExists(configPath)) {
             try {
                  const config = await fs.readJson(configPath);
                  // Cùng một cách đọc ghim với launch(): trước đây chỗ này cũng
                  // dùng phép thử chuỗi con phân biệt hoa thường, nên ghim "shardx
                  // 149" nhận nhầm fingerprint kiểu BAS cho một engine ShardX.
                  if (parseEnginePin(config.browser_version).family === 'shardx') {
                      isShardX = true;
                  }
                  if (config.tags && Array.isArray(config.tags)) {
                      tags = config.tags;
                  }
             } catch (e) {}
        }

        // 1. Try to load existing
        if (await fs.pathExists(fingerprintPath) || await fs.pathExists(legacyFingerprintPath)) {
            console.log('Loading saved fingerprint...');
            try {
                const targetFpPath = await fs.pathExists(fingerprintPath) ? fingerprintPath : legacyFingerprintPath;
                const data = await fs.readFile(targetFpPath, 'utf8');
                if (data && data.length > 20) {
                    let parsed = null;
                    try {
                        parsed = JSON.parse(data);
                    } catch (e) {}

                    if (parsed && typeof parsed === 'object') {
                        if (isShardX) {
                            if (!isShardXFpFormat(parsed)) {
                                console.log('[Fingerprint] Loaded BAS fingerprint, but profile is ShardX. Converting to ShardX format...');
                                const converted = convertBasToShardX(parsed, profileName);
                                try {
                                    const config = await fs.readJson(configPath).catch(() => ({}));
                                    const resolvedTz = await this.resolveProxyTimezone(config.proxy);
                                    if (resolvedTz) {
                                        converted.timezone = resolvedTz;
                                    }
                                } catch (err) {}
                                const toSave = JSON.stringify(converted, null, 2);
                                await fs.outputFile(fingerprintPath, toSave, 'utf8');
                                await fs.outputFile(legacyFingerprintPath, toSave, 'utf8');
                                fingerprint = toSave;
                            } else {
                                // Ensure noise settings are enabled for existing ShardX fingerprint
                                let needsUpdate = false;
                                if (!parsed.noise || 
                                    !parsed.noise.canvas || !parsed.noise.canvas.enabled || 
                                    !parsed.noise.webgl || !parsed.noise.webgl.enabled) {
                                    needsUpdate = true;
                                }
                                if (needsUpdate) {
                                    console.log('[Fingerprint] Existing ShardX fingerprint has noise disabled/missing. Enabling it...');
                                    const seed = profileName ? profileName.split('').reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) & 0x7FFFFFFF, 0) : Math.floor(Math.random() * 1000000);
                                    parsed.noise = {
                                        canvas: { enabled: true, seed: seed },
                                        webgl: { enabled: true, seed: seed, intensity: 5 },
                                        audio: { enabled: true, seed: seed },
                                        client_rects: { enabled: true, seed: seed, max_offset: 5 },
                                        sensors: { enabled: true, seed: seed },
                                        fonts: { enabled: true, seed: seed }
                                    };
                                    const toSave = JSON.stringify(parsed, null, 2);
                                    await fs.outputFile(fingerprintPath, toSave, 'utf8');
                                    await fs.outputFile(legacyFingerprintPath, toSave, 'utf8');
                                    // Also save shardx_fingerprint.json
                                    const savedFpPath = path.join(profilePath, 'shardx_fingerprint.json');
                                    await fs.outputFile(savedFpPath, toSave, 'utf8');
                                    fingerprint = toSave;
                                } else {
                                    fingerprint = data;
                                }
                            }
                        } else {
                            fingerprint = data;
                        }
                    } else {
                        fingerprint = data;
                    }
                    console.log(`Fingerprint loaded successfully (${typeof fingerprint}, ${fingerprint.length} chars).`);
                    return fingerprint;
                }
            } catch (e) {
                console.warn('Failed to load saved fingerprint, fetching new one:', e.message);
            }
        }

        // Check local ShardX fingerprints repository directory first if isShardX is true
        if (isShardX) {
            const extDir = path.dirname(fileURLToPath(import.meta.url));
            const localShardxDir = path.resolve(extDir, '..', '..', '..', '..', 'shardx_fps', 'shardx-fingerprints');
            if (await fs.pathExists(localShardxDir)) {
                try {
                    let filterPrefix = 'win';
                    const hasMac = tags.some(t => t.toLowerCase().includes('mac'));
                    const hasLinux = tags.some(t => t.toLowerCase().includes('linux'));
                    if (hasMac) {
                        filterPrefix = 'mac';
                    } else if (hasLinux) {
                        filterPrefix = 'linux';
                    }
                    const files = (await fs.readdir(localShardxDir)).filter(f => f.endsWith('.json') && f.startsWith(filterPrefix));
                    if (files.length > 0) {
                        const idx = profileName.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % files.length;
                        const shardxFpPath = path.join(localShardxDir, files[idx]);
                        console.log(`[Fingerprint] Found local ShardX fingerprint: ${files[idx]} (consistent hash pick)`);
                        const shardxData = await fs.readJson(shardxFpPath);
                        try {
                            const config = await fs.readJson(configPath).catch(() => ({}));
                            const resolvedTz = await this.resolveProxyTimezone(config.proxy);
                            if (resolvedTz) {
                                shardxData.timezone = resolvedTz;
                            }
                        } catch (err) {}
                        const seed = profileName.split('').reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) & 0x7FFFFFFF, 0);
                        shardxData.noise = {
                            canvas: { enabled: true, seed: seed },
                            webgl: { enabled: true, seed: seed, intensity: 5 },
                            audio: { enabled: true, seed: seed },
                            client_rects: { enabled: true, seed: seed, max_offset: 5 },
                            sensors: { enabled: true, seed: seed },
                            fonts: { enabled: true, seed: seed }
                        };
                        
                        const toSave = JSON.stringify(shardxData, null, 2);
                        await fs.outputFile(fingerprintPath, toSave, 'utf8');
                        await fs.outputFile(legacyFingerprintPath, toSave, 'utf8');
                        
                        // Also save shardx_fingerprint.json
                        const savedFpPath = path.join(profilePath, 'shardx_fingerprint.json');
                        await fs.outputFile(savedFpPath, toSave, 'utf8');
                        
                        return toSave;
                    }
                } catch (err) {
                    console.warn('[Fingerprint] Failed to load from local ShardX fingerprints folder:', err.message);
                }
            }
        }

        // Check local BAS fingerprints repository directory first
        const localBasDir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'data', 'bas_fingerprints');
        if (await fs.pathExists(localBasDir)) {
            try {
                const files = (await fs.readdir(localBasDir)).filter(f => f.endsWith('.json'));
                if (files.length > 0) {
                    const idx = profileName.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % files.length;
                    const basFpPath = path.join(localBasDir, files[idx]);
                    console.log(`[Fingerprint] Found local BAS fingerprint: ${files[idx]} (consistent hash pick)`);
                    const basData = await fs.readJson(basFpPath);
                    
                    let finalFp = basData;
                    if (isShardX) {
                        console.log('[Fingerprint] Converting local BAS fingerprint to ShardX format...');
                        finalFp = convertBasToShardX(basData, profileName);
                        try {
                            const config = await fs.readJson(configPath).catch(() => ({}));
                            const resolvedTz = await this.resolveProxyTimezone(config.proxy);
                            if (resolvedTz) {
                                finalFp.timezone = resolvedTz;
                            }
                        } catch (err) {}
                    }
                    
                    const toSave = JSON.stringify(finalFp, null, 2);
                    await fs.outputFile(fingerprintPath, toSave, 'utf8');
                    await fs.outputFile(legacyFingerprintPath, toSave, 'utf8');
                    return toSave;
                }
            } catch (err) {
                console.warn('[Fingerprint] Failed to load from local BAS fingerprints folder:', err.message);
            }
        }

        // Read config for version/window_size
        let minBrowserVersion = null;
        let windowSize = null;
        
        if (await fs.pathExists(configPath)) {
             try {
                 const config = await fs.readJson(configPath);
                 if (config.browser_version && config.browser_version !== 'default' && config.browser_version !== 'latest') {
                     // Handle "ShardX 148.0.7778.97" or "148.0.7778.97" → extract numeric major version "148"
                     const _vMatch = config.browser_version.match(/(\d+)\./);
                     minBrowserVersion = _vMatch ? _vMatch[1] : config.browser_version.replace(/^[^\d]*/, '').split('.')[0];
                 }
                 if (config.window_size) windowSize = config.window_size;
             } catch (e) {}
        }
        
        // Map common OS names to Security Browser expected tags
        const tagMap = { 'Windows': 'Microsoft Windows', 'macOS': 'Mac OS X' };
        const mappedTags = tags.map(t => tagMap[t] || t);

        // This service supplies fingerprints for the BAS plugin. Without the plugin
        // the result cannot be used by anything, and asking anyway cost about seven
        // seconds of retries and printed "404" and "Query limit reached" during an
        // otherwise healthy ShardX launch. ShardX carries its own fingerprint via
        // --fingerprint-profile.
        if (!plugin) {
            console.log('Skipping BAS fingerprint service (ShardX supplies its own fingerprint).');
            return null;
        }

        // 2. Fetch via PHP API (key stays on server)
        console.log(`Fetching fingerprint via api.tubecreate.com [tags: ${mappedTags.join(',')}, size: ${windowSize ? `${windowSize.width}x${windowSize.height}` : 'default'}]...`);
        
        let basKey = '';
        try {
            const extDir = path.dirname(fileURLToPath(import.meta.url));
            const settingsPath = path.resolve(extDir, '..', '..', '..', 'data', 'global_settings.json');
            if (await fs.pathExists(settingsPath)) {
                const settings = await fs.readJson(settingsPath);
                if (settings.bas_fingerprint_key && settings.bas_fingerprint_key.trim()) {
                    basKey = settings.bas_fingerprint_key.trim();
                }
            }
        } catch (e) {
            console.warn('Failed to load global settings in getFingerprint:', e.message);
        }

        let attempts = 0;
        let triedWithoutSize = false;
        while (attempts < 3) {
            try {
                const params = { tags: mappedTags.join(',') };
                if (minBrowserVersion) params.min_browser_version = minBrowserVersion;
                if (windowSize && !triedWithoutSize) {
                    // Use ranges instead of exact match — Security Browser pool may not have exact resolution
                    params.min_width = Math.max(windowSize.width - 200, 1024);
                    params.max_width = windowSize.width + 200;
                    params.min_height = Math.max(windowSize.height - 200, 600);
                    params.max_height = windowSize.height + 200;
                }
                
                let resp;
                if (basKey) {
                    resp = await axios.post('https://api.tubecreate.com/api/fingerprints/getfinger.php', {
                        key: basKey,
                        ...params
                    }, {
                        responseType: 'text',
                        timeout: 180000,
                        maxContentLength: 50 * 1024 * 1024,
                        maxBodyLength: 50 * 1024 * 1024
                    });
                } else {
                    resp = await axios.get('https://api.tubecreate.com/api/fingerprints/getfinger.php', { 
                        params,
                        responseType: 'text',
                        timeout: 180000,
                        maxContentLength: 50 * 1024 * 1024,
                        maxBodyLength: 50 * 1024 * 1024
                    });
                }
                const rawText = resp.data;
                const data = JSON.parse(rawText);
                
                if (data && data.status === 'success') {
                    // New format: fingerprint included directly in response
                    if (data.fingerprint) {
                        console.log(`Got fingerprint directly from API response.`);
                        // Extract RAW JSON string to preserve exact cryptographic signature and key order
                        fingerprint = extractRawKey(rawText, 'fingerprint') || JSON.stringify(data.fingerprint);
                    } 
                    // Old format: download via file_path
                    else if (data.file_path) {
                        const fpUrl = `https://api.tubecreate.com/${data.file_path}`;
                        console.log(`Downloading fingerprint from API...`);
                        const fpResp = await axios.get(fpUrl, { responseType: 'text', timeout: 120000 });
                        fingerprint = fpResp.data;
                    } else {
                        throw new Error('No fingerprint data in API response');
                    }
                    
                    // Validate: Security Browser may return {valid: false, message: "..."}
                    let parsedFp = null;
                    try {
                        parsedFp = typeof fingerprint === 'string' ? JSON.parse(fingerprint) : fingerprint;
                    } catch (e) {}

                    if (parsedFp && parsedFp.valid === false) {
                        console.warn(`[Fingerprint] Security Browser returned invalid: ${parsedFp.message}`);
                        if (!triedWithoutSize && windowSize) {
                            console.log('[Fingerprint] Retrying without size constraints...');
                            triedWithoutSize = true;
                            attempts++;
                            continue;
                        }
                        throw new Error(`Security Browser: ${parsedFp.message}`);
                    }
                    
                    if (!fingerprint || (typeof fingerprint !== 'object' && typeof fingerprint !== 'string')) {
                        throw new Error('Invalid fingerprint data received from API');
                    }

                    if (isShardX && parsedFp) {
                        console.log('[Fingerprint] Fetched BAS fingerprint for ShardX profile. Converting to ShardX format...');
                        const converted = convertBasToShardX(parsedFp, profileName);
                        try {
                            const config = await fs.readJson(configPath).catch(() => ({}));
                            const resolvedTz = await this.resolveProxyTimezone(config.proxy);
                            if (resolvedTz) {
                                converted.timezone = resolvedTz;
                            }
                        } catch (err) {}
                        fingerprint = converted;
                    }

                    // Save it
                    const toSave = typeof fingerprint === 'object' ? JSON.stringify(fingerprint, null, 2) : fingerprint;
                    await fs.outputFile(fingerprintPath, toSave, 'utf8');
                    await fs.outputFile(legacyFingerprintPath, toSave, 'utf8');
                    return toSave;
                } else {
                    throw new Error('Invalid response from getfinger.php');
                }
            } catch (e) {
                console.error(`Fingerprint fetch attempt ${attempts + 1} failed: ${e.message}`);
                attempts++;
                await new Promise(r => setTimeout(r, 2000));
            }
        }
        throw new Error('Failed to fetch fingerprint after all attempts');
    }

    /**
     * Patch the fingerprint's User-Agent to match the actual engine Chromium version.
     * This prevents mismatch where fingerprint says Chrome/124 but engine is Chrome/146.
     * @param {object|string} fingerprint - The fingerprint data
     * @param {string} targetChromiumVer - Target Chromium version (e.g. '146.0.7680.80')
     * @returns {object|string} - Patched fingerprint
     */
    patchFingerprintUserAgent(fingerprint, targetChromiumVer) {
        if (!fingerprint || !targetChromiumVer) return fingerprint;
        
        const majorVersion = targetChromiumVer.split('.')[0]; // e.g. '147'
        
        try {
            let fp = typeof fingerprint === 'string' ? JSON.parse(fingerprint) : fingerprint;
            const wasString = typeof fingerprint === 'string';
            
            // Handle Security Browser v5 wrapper format: { canvas, webgl, fingerprint: { navigator, attr, ... } }
            // Patch the INNER fingerprint object, but return the full wrapper
            let target = fp;
            if (fp.fingerprint) {
                target = typeof fp.fingerprint === 'string' ? JSON.parse(fp.fingerprint) : fp.fingerprint;
                console.log('[Fingerprint] Patching inside Security Browser wrapper...');
            }
            
            // 1. Patch navigator.userAgent — replace Chrome/XXX.0.0.0 with correct major version
            if (target.navigator && target.navigator.userAgent) {
                const oldUA = target.navigator.userAgent;
                const newUA = oldUA
                    .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                    .replace(/ Edg\/[\d.]+/g, '')
                    .replace(/ Edge\/[\d.]+/g, '');
                if (oldUA !== newUA) {
                    target.navigator.userAgent = newUA;
                    console.log(`[Fingerprint] Patched navigator.userAgent: Chrome/${oldUA.match(/Chrome\/(\d+)/)?.[1] || '?'} → Chrome/${majorVersion}`);
                }
            }
            
            // 1b. Patch Security Browser specific attr object
            if (target.attr && target.attr['navigator.userAgent']) {
                const oldUA = target.attr['navigator.userAgent'];
                const newUA = oldUA
                    .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                    .replace(/ Edg\/[\d.]+/g, '')
                    .replace(/ Edge\/[\d.]+/g, '');
                if (oldUA !== newUA) {
                    target.attr['navigator.userAgent'] = newUA;
                    console.log(`[Fingerprint] Patched attr[navigator.userAgent]: Chrome/${oldUA.match(/Chrome\/(\d+)/)?.[1] || '?'} → Chrome/${majorVersion}`);
                }
            }
            
            // 2. Patch navigator.appVersion
            if (target.navigator && target.navigator.appVersion) {
                target.navigator.appVersion = target.navigator.appVersion
                    .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                    .replace(/ Edg\/[\d.]+/g, '')
                    .replace(/ Edge\/[\d.]+/g, '');
            }
            
            // 2b. Patch Security Browser specific attr appVersion
            if (target.attr && target.attr['navigator.appVersion']) {
                target.attr['navigator.appVersion'] = target.attr['navigator.appVersion']
                    .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                    .replace(/ Edg\/[\d.]+/g, '')
                    .replace(/ Edge\/[\d.]+/g, '');
            }
            
            // 3. Patch navigator.userAgentData.brands
            if (target.navigator && target.navigator.userAgentData && Array.isArray(target.navigator.userAgentData.brands)) {
                for (const brand of target.navigator.userAgentData.brands) {
                    if (brand.brand === 'Google Chrome' || brand.brand === 'Chromium') {
                        brand.version = majorVersion;
                    }
                }
            }
            
            // 4. Patch navigator.userAgentData.fullVersionList
            if (target.navigator && target.navigator.userAgentData && Array.isArray(target.navigator.userAgentData.fullVersionList)) {
                for (const entry of target.navigator.userAgentData.fullVersionList) {
                    if (entry.brand === 'Google Chrome' || entry.brand === 'Chromium') {
                        entry.version = targetChromiumVer;
                    }
                }
            }
            
            // 5. Patch HTTP Headers
            if (target.headers) {
                const keys = Object.keys(target.headers);
                
                const uaKey = keys.find(k => k.toLowerCase() === 'user-agent');
                if (uaKey && target.headers[uaKey]) {
                    target.headers[uaKey] = target.headers[uaKey]
                        .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                        .replace(/ Edg\/[\d.]+/g, '')
                        .replace(/ Edge\/[\d.]+/g, '');
                }
                
                const secChUaKey = keys.find(k => k.toLowerCase() === 'sec-ch-ua');
                if (secChUaKey && target.headers[secChUaKey]) {
                    target.headers[secChUaKey] = target.headers[secChUaKey]
                        .replace(/"Chromium";v="\d+"/g, `"Chromium";v="${majorVersion}"`)
                        .replace(/"Google Chrome";v="\d+"/g, `"Google Chrome";v="${majorVersion}"`);
                }
                
                const secChUaFullKey = keys.find(k => k.toLowerCase() === 'sec-ch-ua-full-version-list');
                if (secChUaFullKey && target.headers[secChUaFullKey]) {
                    target.headers[secChUaFullKey] = target.headers[secChUaFullKey]
                        .replace(/"Chromium";v="[\d.]+"/g, `"Chromium";v="${targetChromiumVer}"`)
                        .replace(/"Google Chrome";v="[\d.]+"/g, `"Google Chrome";v="${targetChromiumVer}"`);
                }
            }
            
            // Write patched target back into wrapper if applicable
            if (fp.fingerprint && target !== fp.fingerprint && target !== fp) {
                fp.fingerprint = typeof fp.fingerprint === 'string' ? JSON.stringify(target) : target;
            }
            
            return wasString ? JSON.stringify(fp) : fp;
        } catch (e) {
            console.warn(`[Fingerprint] Failed to patch UA: ${e.message}`);
            return fingerprint;
        }
    }

    normalizeProxy(proxy) {
        if (!proxy) return null;
        
        // Handle socks5://user:pass:host:port format (common in some providers)
        // Convert to socks5://user:pass@host:port
        const simpleFormatRegex = /^(socks5|http|https):\/\/([^:@]+):([^:@]+):([^:@]+):(\d+)$/i;
        const match = proxy.match(simpleFormatRegex);
        
        if (match) {
            const [_, protocol, user, pass, host, port] = match;
            const normalized = `${protocol.toLowerCase()}://${user}:${pass}@${host}:${port}`;
            console.log(`[BrowserManager] Normalized proxy: ${proxy} -> ${normalized}`);
            return normalized;
        }
        
        return proxy;
    }

    applyProxy(proxyString) {
        const normalized = this.normalizeProxy(proxyString);
        if (normalized) {
            console.log(`Applying proxy: ${normalized}`);
            // Optional-chained: these configure the BAS plugin, so without it they
            // are no-ops. Left bare they threw "Cannot set properties of null",
            // which aborted the launch before the ShardX path was even reached.
            plugin?.useProxy(normalized, {
                changeTimezone: true,
                changeGeolocation: true
            });
        } else {
            console.log('No proxy configured. Clearing proxy settings.');
            // Directly unset the proxy property to ensure no proxy is sent to the engine
            if (plugin) plugin.proxy = null;
        }
    }

    async launch(profileName, options = {}) {
        await this.fetchServiceKey();
        const profilePath = await this.ensureProfile(profileName);
        // Khoá sót của phiên trước làm Chromium bỏ chạy ("Failed to create a
        // ProcessSingleton ... Aborting now to avoid profile corruption") và giết
        // MỌI lượt sau, mỗi lượt ~5 giây. Dọn ở đây — phễu chung của mọi đường gọi.
        clearStaleSingletonLocks(profilePath);
        let {
            headless = false,
            proxy = null,
            fingerprint = null,
            args = []
        } = options;

        const configPath = path.join(profilePath, 'config.json');
        
        // Proxy Persistence Logic
        if (proxy) {
            // New proxy provided -> Normalize and Save it
            const normalizedProxy = this.normalizeProxy(proxy);
            if (normalizedProxy) {
                proxy = normalizedProxy; // Use normalized version
                console.log(`Saving new proxy configuration to profile: ${proxy}`);
                try {
                    const currentConfig = await fs.pathExists(configPath) ? await fs.readJson(configPath) : {};
                    currentConfig.proxy = proxy;
                    await fs.writeJson(configPath, currentConfig, { spaces: 2 });
                } catch (e) {
                    console.warn('Failed to save proxy config:', e.message);
                }
            }
        } else {
            // No proxy provided -> Try to load from config
            try {
                if (await fs.pathExists(configPath)) {
                    const savedConfig = await fs.readJson(configPath);
                    if (savedConfig.proxy) {
                        console.log(`Loaded saved proxy: ${savedConfig.proxy}`);
                        proxy = savedConfig.proxy;
                    }
                }
            } catch (e) {
                console.warn('Failed to load proxy config:', e.message);
            }
        }

        // "Free Mode" (skip_fingerprint.txt) ĐÃ BỎ. Cờ đó đổi "không mở được trang
        // nào" lấy "mở được trang nhưng TẮT SẠCH antidetect" — mà mọi báo cáo vẫn
        // ghi thành công, nên chẳng ai biết hồ sơ đang chạy trần. Khoá BAS hết hạn
        // nay được xử bằng cách đổi sang ShardX (không cần khoá, vẫn có antidetect
        // riêng) ở nhánh isKeyError trong vòng retry bên dưới.
        //
        // File cũ còn sót trên đĩa thì CHỈ báo, không đọc và cũng không xoá: trong
        // repo này không còn chỗ nào khác đọc nó (đã dò cả cây nguồn), và lượt mở
        // trình duyệt không phải chỗ để tự ý sửa thư mục hồ sơ của người dùng.
        const skipFingerprintPath = path.join(profilePath, 'skip_fingerprint.txt');
        if (await fs.pathExists(skipFingerprintPath)) {
            console.warn(`[Launch] Hồ sơ còn cờ Free Mode cũ (${skipFingerprintPath}). Cờ này KHÔNG còn tác dụng `
                + `— antidetect vẫn bật bình thường. Xoá file đi cho sạch.`);
        }

        // Apply proxy (already normalized if it came from args, or loaded from config)
        this.applyProxy(proxy);

        // ── Quyết định engine ───────────────────────────────────────────
        // Ghim trên hồ sơ QUYẾT ĐỊNH họ engine; máy chỉ trả lời "có dùng được
        // không". Dò trong họ đó một cách khoan dung (đúng bản ghim → không có thì
        // bản đã cài mới nhất), và chỉ mượn họ kia khi họ được ghim KHÔNG có đường
        // sống trên máy này — mượn thì phải nói to.
        let targetChromiumVer = null;
        let targetBasVer = null;
        let shardxExePath = null;
        let isShardXProfile = false;  // track outside try block
        let enginePin = { family: null, version: null, raw: null };
        try {
                const conf = await fs.pathExists(configPath) ? await fs.readJson(configPath) : {};
                let rawPin = conf.browser_version;
                // Ghim cũ thiếu số build: '149.0.0.0' không khớp thư mục engine nào.
                if (rawPin === '149.0.0.0') rawPin = '149.0.7827.54';
                enginePin = parseEnginePin(rawPin);
                targetChromiumVer = enginePin.version;

                let isShardX = false;

                // (1) Ghim ShardX → dò trong họ ShardX, không bao giờ tự rơi sang BAS.
                if (enginePin.family === 'shardx') {
                    isShardX = true;
                    isShardXProfile = true;
                    const resolved = await resolveShardxExe(enginePin.version);
                    if (!resolved) {
                        // Bản cũ ném lỗi ở đây rồi bị catch bên dưới nuốt mất:
                        // isShardXProfile vẫn true nhưng shardxExePath null, guard
                        // dispatch trượt, hồ sơ rơi xuống nhánh BAS và người dùng đọc
                        // được "BAS engine, Windows only" — trong khi sự thật là
                        // engine ShardX chưa tải về.
                        throw new EngineUnavailableError(
                            `This profile is pinned to ShardX ${enginePin.version || '(any version)'}, `
                            + `but no ShardX engine is installed on this ${process.platform} host `
                            + `(looked under ${shardxEngineRoot() || '(no home directory)'}/runtime/engines). `
                            + `Download it from the Browser page — POST /engine/download/${enginePin.version || '{version}'}.`);
                    }
                    shardxExePath = resolved.exe;
                    targetChromiumVer = resolved.version;
                    targetBasVer = null;
                    if (enginePin.version && resolved.version !== enginePin.version) {
                        console.warn(`[Launch] ENGINE_SUBSTITUTED pinned=shardx/${enginePin.version} `
                            + `used=shardx/${resolved.version} reason=pinned_version_not_installed`);
                        console.warn(`[Launch] Bản ShardX ${enginePin.version} chưa tải; dùng bản đã cài mới nhất `
                            + `${resolved.version}. Tải đúng bản ghim ở trang Browser nếu cần khớp tuyệt đối.`);
                    }
                    console.log(`[Launch] Resolved ShardX engine ${resolved.version} at ${resolved.exe}`);
                }

                // (2) Ghim BAS (hoặc chưa ghim) trên máy KHÔNG chạy được BAS. Đây là
                //     DUY NHẤT chỗ được đổi họ trước khi mở, và nó chỉ mở ra khi họ
                //     được ghim không có đường sống trên máy này.
                if (!isShardX) {
                    const basBlocker = await basUnusableReason();
                    if (basBlocker) {
                        const alt = await resolveShardxExe(null);
                        if (alt) {
                            isShardX = true;
                            isShardXProfile = true;
                            shardxExePath = alt.exe;
                            targetChromiumVer = alt.version;
                            targetBasVer = null;
                            console.warn(`[Launch] ENGINE_SUBSTITUTED pinned=bas/${enginePin.version || '(none)'} `
                                + `used=shardx/${alt.version} reason=${basBlocker.code}`);
                            console.warn(`[Launch] ${basBlocker.text} — chạy hồ sơ này bằng ShardX ${alt.version} `
                                + `(không cần khoá, vẫn có antidetect riêng). Sửa ghim của hồ sơ thành `
                                + `"ShardX ${alt.version}" để khỏi phải đoán lại mỗi lần mở.`);
                        } else {
                            throw new EngineUnavailableError(
                                `${basBlocker.text}, and no ShardX engine is installed either, so no engine on `
                                + `this host can run profile "${profileName}". Download one from the Browser page `
                                + `(POST /engine/download/{version}), then pin the profile to "ShardX <version>".`);
                        }
                    }
                }

                if (!isShardX) {
                    // Dò trong họ BAS, cùng luật khoan dung như họ ShardX: đúng
                    // bản ghim → không có thì bản đã cài mới nhất. Ghim lưu theo số
                    // CHROMIUM còn engine trên đĩa đặt tên theo số BAS, nên phải đổi
                    // qua bảng trước khi so.
                    if (targetChromiumVer && !BAS_REVERSE_MAP[targetChromiumVer] && BAS_ENGINE_MAP[targetChromiumVer]) {
                        // Hồ sơ ghim thẳng số BAS ("30.2.0") chứ không phải số Chromium.
                        targetBasVer = targetChromiumVer;
                        targetChromiumVer = BAS_ENGINE_MAP[targetBasVer];
                    } else {
                        targetBasVer = BAS_REVERSE_MAP[targetChromiumVer] || null;
                    }
                    const pinnedBasVer = targetBasVer;
                    const pinnedChromium = targetChromiumVer;

                    const basResolved = await resolveBasEngine(pinnedBasVer);
                    if (basResolved) {
                        targetBasVer = basResolved.version;
                        const usedChromium = BAS_ENGINE_MAP[targetBasVer] || targetBasVer;
                        if (enginePin.family === 'bas' && usedChromium !== pinnedChromium) {
                            console.warn(`[Launch] ENGINE_SUBSTITUTED pinned=bas/${pinnedBasVer || pinnedChromium} `
                                + `used=bas/${targetBasVer} reason=pinned_version_not_installed`);
                            console.warn(`[Launch] Engine BAS cho Chromium ${pinnedChromium} chưa cài; dùng bản đã cài `
                                + `mới nhất ${targetBasVer} (Chromium ${usedChromium}).`);
                        } else if (enginePin.family !== 'bas') {
                            console.log(`[Launch] Hồ sơ chưa ghim engine — dùng bản BAS đã cài mới nhất: `
                                + `${targetBasVer} (Chromium ${usedChromium}).`);
                        }
                        targetChromiumVer = usedChromium;
                        console.log(`[Launch] Resolved BAS engine ${targetBasVer} (Chromium ${targetChromiumVer}) at ${basResolved.dir}`);
                    }
                    // Không còn nhánh "chẳng có engine BAS nào": khối quyết định ở
                    // trên đã chặn từ trước (mượn ShardX hoặc EngineUnavailableError),
                    // nên tới được đây nghĩa là chắc chắn có engine.

                    if (targetChromiumVer && targetChromiumVer !== 'default' && targetChromiumVer !== 'latest') {
                        console.log(`[Launch] Using browser version: ${targetChromiumVer}`);
                        plugin?.useBrowserVersion(targetChromiumVer);
                        
                        // CRITICAL HOTFIX: The plugin's engine.js ignores useBrowserVersion() when 
                        // deciding which FastExecuteScript.exe to spawn, relying on project.xml instead.
                        // We must dynamically rewrite its project.xml to match our target BAS version!
                        if (targetBasVer) {
                            try {
                                const __dirname = path.dirname(fileURLToPath(import.meta.url));
                                const projectXmlPath = path.join(__dirname, 'node_modules', 'browser-with-fingerprints', 'project.xml');
                                if (await fs.pathExists(projectXmlPath)) {
                                    let xmlContent = await fs.readFile(projectXmlPath, 'utf8');
                                    xmlContent = xmlContent.replace(/<EngineVersion>.*?<\/EngineVersion>/, `<EngineVersion>${targetBasVer}</EngineVersion>`);
                                    await fs.writeFile(projectXmlPath, xmlContent, 'utf8');
                                    console.log(`[Launch] Hotfixed plugin project.xml engine version to ${targetBasVer}`);
                                }
                            } catch (err) {
                                console.warn('[Launch] Failed to apply project.xml hotfix:', err.message);
                            }
                        }
                    }
                }
        } catch (e) {
            // "Máy này không có engine chạy được hồ sơ đó" là KẾT LUẬN, không phải
            // sự cố phụ. Nuốt nó xuống rồi đi tiếp bằng họ engine kia chính là chỗ
            // đẻ ra thông báo sai: hồ sơ ghim ShardX chưa tải engine lại được báo là
            // "BAS engine, Windows only". Chỉ lỗi BẤT NGỜ (config.json hỏng, đọc đĩa
            // lỗi) mới được bỏ qua ở đây.
            if (e instanceof EngineUnavailableError) throw e;
            console.warn('Failed to resolve browser_version path:', e.message);
        }

        // ═══════════════════════════════════════════════════════════════
        // SHARDX LAUNCH PATH — bypass playwright-with-fingerprints plugin
        // ShardX engine does spoofing at Chromium C++ level, not via JS.
        // Fingerprint format is different: {navigator, webgpu, screen, ...}
        // Injected via --fingerprint-profile=<file> CLI flag.
        // No service key, no PHP API needed.
        // ═══════════════════════════════════════════════════════════════
        // Engine THỰC SỰ dùng, để người gọi (open.js, run_log, preview server) đọc
        // được bằng máy thay vì đoán từ log. _launchShardX bổ sung nốt cờ antidetect.
        const usingShardX = !!(isShardXProfile && shardxExePath);
        this.lastLaunchInfo = {
            profile: profileName,
            pin: enginePin.raw || null,
            engine: usingShardX ? 'shardx' : 'bas',
            engineVersion: usingShardX ? targetChromiumVer : (targetBasVer || targetChromiumVer || null),
            substituted: !!(enginePin.family && enginePin.family !== (usingShardX ? 'shardx' : 'bas')),
            antidetect: null,
        };

        if (isShardXProfile && shardxExePath) {
            return await this._launchShardX({
                profileName, profilePath, shardxExePath, proxy, fingerprint, headless, args, targetChromiumVer
            });
        }

        // ═══════════════════════════════════════════════════════════════
        // BAS (Security Browser) LAUNCH PATH — uses playwright-with-fingerprints plugin
        // ═══════════════════════════════════════════════════════════════

        // Stop here with a sentence the user can act on. Without the plugin every
        // call below would be a TypeError on null, which says nothing about the
        // actual problem: this profile is pinned to a Windows-only engine.
        requirePlugin();

        // Apply fingerprint with retry logic (BAS only)
        if (fingerprint) {
             let fpAttempts = 0;
             while (fpAttempts < 2) {
                 try {
                    if (fingerprint) {
                        // Pass stringified JSON or raw token to plugin.useFingerprint (always string)
                        const fpString = typeof fingerprint === 'object' ? JSON.stringify(fingerprint) : fingerprint;
                        plugin.useFingerprint(fpString);
                    }
                    break; // Success
                 } catch (e) {
                     console.error(`Error applying fingerprint (Attempt ${fpAttempts + 1}/2):`, e.message);
                     if (fpAttempts === 0) {
                         console.warn('Fingerprint might be corrupted. Deleting and re-fetching...');
                         try {
                              const fingerprintPath = path.join(profilePath, 'fingerprint_saved.json');
                              const legacyFingerprintPath = path.join(profilePath, 'fingerprint.json');
                              await fs.remove(fingerprintPath);
                              await fs.remove(legacyFingerprintPath);
                              fingerprint = await this.getFingerprint(profileName, { tags: ['Microsoft Windows', 'Chrome'] });
                          } catch (err) {
                              console.error('Failed to refresh fingerprint:', err.message);
                         }
                     } else {
                         throw e; // Fail on second attempt
                     }
                     fpAttempts++;
                 }
             }
        }

        // Default args (BAS)
        const launchArgs = [
            '--start-maximized',
            '--proxy-bypass-list=localhost,127.0.0.1,::1',
            '--disable-blink-features=AutomationControlled',
            '--test-type',
            ...args
        ];

        // Đối xứng với ShardX: mở hồ sơ mà KHÔNG có dấu vân tay thì phải nói ra.
        // Lượt chạy thật trên máy này rơi đúng vào đây — getFingerprint hỏng phía
        // người gọi ("Query limit reached"), người gọi nuốt lỗi rồi vẫn gọi launch
        // với fingerprint null, BAS mở bình thường và mọi báo cáo ghi "thành công".
        const basAntidetectOn = !!fingerprint;
        this.lastLaunchInfo = Object.assign({}, this.lastLaunchInfo, { antidetect: basAntidetectOn });
        if (basAntidetectOn) {
            console.log(`[Launch] ANTIDETECT_ON profile=${profileName} engine=bas`);
        } else {
            console.error(`[Launch] ANTIDETECT_OFF profile=${profileName} engine=bas reason=no_fingerprint_applied`);
            console.error(`[Launch] ⚠️ Hồ sơ "${profileName}" mở bằng BAS mà không có dấu vân tay nào được áp — `
                + `lượt chạy này KHÔNG ẩn danh.`);
        }

        console.log(`Launching browser [Profile: ${profileName}]...`);
        
        plugin.useProfile(profilePath, { loadProxy: false, loadFingerprint: false });

        // LAUNCH RETRY LOGIC (BAS)
        let launchAttempt = 1;
        const maxLaunchAttempts = 3;
        let lastError = null;

        while (launchAttempt <= maxLaunchAttempts) {
            try {
                const context = await plugin.launchPersistentContext(profilePath, {
                    headless,
                    viewport: null, // Disable default Playwright viewport override
                    args: launchArgs,
                    userDataDir: profilePath,
                    ignoreDefaultArgs: ['--enable-automation'],
                });
                // BẰNG CHỨNG DUY NHẤT rằng khoá vân tay BAS còn sống. Không thể
                // hỏi qua mạng: key.php trả khoá về ngon lành rồi engine vẫn chết
                // "Key expired" lúc mở. Chỉ một lượt mở THẬT mới trả lời được, và
                // đây là chỗ nó vừa trả lời xong.
                // process_manager._note_launch_evidence() đọc dòng này trong log
                // rồi gọi shardx_runtime.mark_bas_key_ok(). Thiếu nó thì phán quyết
                // chỉ đi được một chiều: hỏng thì ghi, tốt thì không ai ghi — và
                // máy CHỈ có BAS chạy khoá dùng chung sẽ vĩnh viễn bị coi là không
                // dùng được. ĐỔI CHUỖI NÀY LÀ PHẢI ĐỔI CẢ BÊN ĐỌC.
                console.log(`[Launch] BAS_LAUNCH_OK profile=${profileName} `
                    + `engine=bas version=${targetBasVer || targetChromiumVer || 'unknown'}`);
                return context;
            } catch (e) {
                lastError = e;
                const errMsg = e.message.toLowerCase();
                const isProxyError = errMsg.includes('failed to get proxy ip') || 
                                     errMsg.includes('proxy') ||
                                     errMsg.includes('timeout') ||
                                     errMsg.includes('http request error') ||
                                     errMsg.includes('incorrect format');
                const isEngineFlake = errMsg.includes('browserautomationstudio') || 
                                      errMsg.includes('referenceerror: can\'t find variable');
                // "FingerprintSwitcher key is missing" là một kiểu hỏng khoá có
                // thật nhưng không khớp hai chuỗi cũ, nên trước đây rơi xuống nhánh
                // "lỗi lạ" và ném thẳng ra ngoài, không ai nhận ra là lỗi khoá.
                const isKeyError    = /key expired|invalid key|key is missing|missing key|service key/.test(errMsg);
                const isFingerprintError = errMsg.includes('fingerprint') && (errMsg.includes('not found') || errMsg.includes('error'));

                if (isFingerprintError && launchAttempt === 1) {
                    console.warn(`[Launch] ⚠️ Fingerprint rejected by engine: ${e.message}`);
                    console.warn(`[Launch] Deleting old fingerprint and fetching a fresh one...`);
                    try {
                        const fingerprintPath = path.join(profilePath, 'fingerprint_saved.json');
                        const legacyFingerprintPath = path.join(profilePath, 'fingerprint.json');
                        await fs.remove(fingerprintPath);
                        await fs.remove(legacyFingerprintPath);
                        fingerprint = await this.getFingerprint(profileName, { tags: ['Microsoft Windows', 'Chrome'] });
                        const fpString = typeof fingerprint === 'object' ? JSON.stringify(fingerprint) : fingerprint;
                        plugin.useFingerprint(fpString);
                        console.log('[Launch] Fresh fingerprint applied. Retrying launch...');
                    } catch (refreshErr) {
                        console.error('[Launch] Failed to refresh fingerprint:', refreshErr.message);
                    }
                    launchAttempt++;
                    continue;
                }

                if (isProxyError || isEngineFlake || isKeyError) {
                    if (isKeyError) {
                         // Khoá BAS chỉ lộ ra lúc mở, nên đây là chỗ DUY NHẤT biết nó
                         // hỏng. ShardX không cần khoá và vẫn tự làm antidetect qua
                         // --fingerprint-profile, nên mở lại chính hồ sơ này bằng
                         // ShardX là ĐỔI ENGINE, không phải tắt antidetect — khác hẳn
                         // "Free Mode" cũ (mở được trang nhưng chạy trần).
                         const alt = await resolveShardxExe(null);
                         if (alt) {
                             console.warn(`[Launch] ENGINE_SUBSTITUTED pinned=bas/${targetBasVer || targetChromiumVer || '(none)'} `
                                 + `used=shardx/${alt.version} reason=bas_key_rejected`);
                             console.warn(`[Launch] BAS từ chối khoá (${String(e.message).split('\n')[0]}) — mở lại hồ sơ bằng `
                                 + `ShardX ${alt.version}. Sửa ghim hồ sơ thành "ShardX ${alt.version}" để mỗi lượt khỏi `
                                 + `phải hỏng một lần mở trước khi đổi.`);
                             if (this.lastLaunchInfo) {
                                 this.lastLaunchInfo.substituted = true;
                                 this.lastLaunchInfo.substitutionReason = 'bas_key_rejected';
                             }
                             try {
                                 return await this._launchShardX({
                                     profileName, profilePath, shardxExePath: alt.exe, proxy, fingerprint,
                                     headless, args, targetChromiumVer: alt.version
                                 });
                             } catch (shardxErr) {
                                 // Kể cả HAI lý do: nói mỗi lý do sau thì người đọc log
                                 // tưởng ShardX là engine được chọn từ đầu.
                                 // Chỉ lấy DÒNG ĐẦU của lỗi ShardX: phần sau là nguyên
                                 // dòng lệnh Chromium, trong đó có --fingerprint-profile,
                                 // mà preview_server.cjs (~:962) hễ thấy chuỗi
                                 // "fingerprint" trong thông báo lỗi là xoá luôn dấu vân
                                 // tay đã lưu của hồ sơ.
                                 throw new Error(
                                     `The BAS engine refused its licence (key expired / invalid key): `
                                     + `${String(e.message).split('\n')[0]}. Falling back to the installed ShardX `
                                     + `${alt.version} engine failed too: ${String(shardxErr.message).split('\n')[0]}`);
                             }
                         }
                         // Không có ShardX để mượn: nói thẳng, đừng mở bừa. Chuỗi
                         // "key expired / invalid key" giữ nguyên để classifyFatal
                         // bên preview_server.cjs (~:145) vẫn xếp đúng engine_expired.
                         throw new Error(
                             `The BAS engine refused its licence (key expired / invalid key): `
                             + `${String(e.message).split('\n')[0]}. This host has no ShardX engine to fall back to — `
                             + `download one from the Browser page (POST /engine/download/{version}), then pin this `
                             + `profile to "ShardX <version>".`);
                    }

                    if (errMsg.includes('incorrect format')) {
                         if (!options.proxy) {
                             console.warn(`[Launch] 'Incorrect format' persisted with NO PROXY! This confirms FINGERPRINT is invalid.`);
                             throw new Error('FINGERPRINT_FATAL_ERROR');
                         }
                         console.warn(`[Launch] 'Incorrect format' error detected. This likely means PROXY is invalid.`);
                         this.applyProxy(null);
                         options.proxy = null;
                         launchAttempt++;
                         continue;
                    }

                    console.warn(`[Launch] Attempt ${launchAttempt} failed with recoverable error: ${e.message}. Retrying...`);
                    launchAttempt++;
                    await new Promise(r => setTimeout(r, 3000));
                } else {
                    throw e;
                }
            }
        }
        
        throw new Error(`Failed to launch browser after ${maxLaunchAttempts} attempts. Last error: ${lastError?.message}`);
    }

    /**
     * Launch ShardX browser directly — no playwright-with-fingerprints plugin.
     * ShardX Chromium engine reads fingerprint via --fingerprint-profile=<file>
     * and does all spoofing at the C++ engine level (Blink/V8/network stack).
     * Uses bundled fingerprint profiles from %APPDATA%\shardx-launcher\runtime\fingerprints\
     * or falls back to fingerprint saved in the profile folder.
     */
    async _launchShardX({ profileName, profilePath, shardxExePath, proxy, fingerprint, headless, args, targetChromiumVer }) {
        console.log(`[ShardX] Launching with native engine at: ${shardxExePath}`);

        const configPath = path.join(profilePath, 'config.json');
        const conf = await fs.pathExists(configPath) ? await fs.readJson(configPath) : {};

        // ── 1. Resolve fingerprint for ShardX ──────────────────────────
        // Priority: (a) profile's saved fingerprint.json (ShardX format)
        //           (b) bundled ShardX fingerprint library
        //           (c) launch without --fingerprint-profile (use engine defaults)
        let shardxFpFile = null;

        // (a) Check for saved ShardX fingerprint in profile folder
        const savedFpPath = path.join(profilePath, 'shardx_fingerprint.json');
        const legacyFpPath = path.join(profilePath, 'fingerprint.json');

        if (await fs.pathExists(savedFpPath)) {
            shardxFpFile = savedFpPath;
            console.log(`[ShardX] Using saved ShardX fingerprint: ${savedFpPath}`);
            // Profile cũ có thể đang giữ fingerprint Windows sinh ra từ thời chọn theo
            // 'win*'. Nói thẳng ra đây, vì đây chính là lý do bài test báo "Masking
            // detected" mà không có gì trong log giải thích.
            try {
                const savedFp = await fs.readJson(savedFpPath);
                const fpPlat = String(savedFp?.navigator?.platform || '').toLowerCase();
                const hostPlat = process.platform === 'win32' ? 'windows'
                    : process.platform === 'darwin' ? 'macos' : 'linux';
                if (fpPlat && !fpPlat.includes(hostPlat)) {
                    console.warn(`[ShardX] ⚠ Fingerprint của profile khai '${savedFp.navigator.platform}' nhưng engine chạy trên ${hostPlat}. `
                        + `Dấu vân tay sẽ không nhất quán (WebGPU, font, GPU). Xoá ${path.basename(savedFpPath)} để hệ thống cấp lại bản khớp OS.`);
                }
            } catch (e) { /* fingerprint hỏng thì luồng dưới đã xử lý */ }
        } else if (fingerprint) {
            let finalFp = fingerprint;
            if (!isShardXFpFormat(fingerprint)) {
                console.log(`[ShardX] Converting passed-in BAS fingerprint to ShardX format...`);
                try {
                    finalFp = convertBasToShardX(fingerprint, profileName);
                } catch (e) {
                    console.error(`[ShardX] Failed to convert fingerprint: ${e.message}`);
                }
            }
            if (isShardXFpFormat(finalFp)) {
                // Ensure noise is enabled for the passed-in fingerprint
                const parsedFp = typeof finalFp === 'string' ? JSON.parse(finalFp) : finalFp;
                const seed = profileName ? profileName.split('').reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) & 0x7FFFFFFF, 0) : Math.floor(Math.random() * 1000000);
                parsedFp.noise = {
                    canvas: { enabled: true, seed: seed },
                    webgl: { enabled: true, seed: seed, intensity: 5 },
                    audio: { enabled: true, seed: seed },
                    client_rects: { enabled: true, seed: seed, max_offset: 5 },
                    sensors: { enabled: true, seed: seed },
                    fonts: { enabled: true, seed: seed }
                };
                const fpContent = JSON.stringify(parsedFp, null, 2);
                await fs.outputFile(savedFpPath, fpContent, 'utf8');
                shardxFpFile = savedFpPath;
                console.log(`[ShardX] Wrote ShardX fingerprint from caller to: ${savedFpPath}`);
            }
        }

        if (!shardxFpFile) {
            // (b) Pick from bundled ShardX fingerprint library
            const appdata = process.env.APPDATA;
            const localappdata = process.env.LOCALAPPDATA;
            const home = process.env.HOME || process.env.USERPROFILE;
            const extDir = path.dirname(fileURLToPath(import.meta.url));
            const localWorkspaceFpDir = path.resolve(extDir, '..', '..', '..', '..', 'shardx_fps', 'shardx-fingerprints');
            // Every entry here was a Windows path (APPDATA / LOCALAPPDATA are
            // undefined elsewhere) apart from a developer-machine folder. On Linux
            // and macOS the loop therefore found nothing, shardxFpFile stayed null,
            // --fingerprint-profile was never passed, and the engine ran with no
            // fingerprint at all — silently, since nothing checked.
            const shardxFpDirs = [
                localWorkspaceFpDir,
                appdata      ? path.join(appdata, 'shardx-launcher', 'runtime', 'fingerprints') : null,
                localappdata ? path.join(localappdata, 'shardx-sdk', 'fingerprints') : null,
                home && process.platform === 'darwin'
                    ? path.join(home, 'Library', 'Application Support', 'shardx-launcher', 'runtime', 'fingerprints') : null,
                home && process.platform === 'darwin'
                    ? path.join(home, 'Library', 'Application Support', 'shardx-sdk', 'fingerprints') : null,
                home && process.platform === 'linux'
                    ? path.join(process.env.XDG_CONFIG_HOME || path.join(home, '.config'), 'shardx-launcher', 'runtime', 'fingerprints') : null,
                home && process.platform === 'linux'
                    ? path.join(process.env.XDG_CACHE_HOME || path.join(home, '.cache'), 'shardx-sdk', 'fingerprints') : null,
            ].filter(Boolean);

            // Fingerprint phải khớp HỆ ĐIỀU HÀNH đang chạy engine.
            //
            // Chỗ này từng luôn ưu tiên 'win*' với lý do "Windows là phổ biến nhất".
            // Trên server Linux điều đó tạo ra mâu thuẫn không thể vá bằng JS: thư
            // viện của ShardX cho bản win-* có khối "webgpu", bản linux-* thì KHÔNG
            // (ShardX tắt WebGPU trên Linux để khớp Chrome Linux thật). Trình duyệt
            // khai là Windows Chrome 149 mà không có WebGPU, cộng thêm font Windows
            // không tồn tại trên máy và GPU thật là phần mềm dựng hình — các trang
            // kiểm tra dấu vân tay bắt ngay và báo "Masking detected".
            //
            // Muốn cố tình giả OS khác (chấp nhận bị phát hiện) thì đặt trong
            // data/global_settings.json: "shardx_fingerprint_platform": "win"|"linux"|"mac".
            const hostFpPrefix = process.platform === 'win32' ? 'win'
                : process.platform === 'darwin' ? 'mac' : 'linux';
            let wantPrefix = hostFpPrefix;
            try {
                const extDir2 = path.dirname(fileURLToPath(import.meta.url));
                const gsPath = path.resolve(extDir2, '..', '..', '..', 'data', 'global_settings.json');
                if (await fs.pathExists(gsPath)) {
                    const gs = await fs.readJson(gsPath);
                    const pick = String(gs.shardx_fingerprint_platform || 'auto').toLowerCase();
                    if (['win', 'windows', 'linux', 'mac', 'macos'].includes(pick)) {
                        wantPrefix = pick.startsWith('win') ? 'win' : (pick.startsWith('mac') ? 'mac' : 'linux');
                    }
                }
            } catch (e) { /* thiếu settings thì cứ theo host */ }

            let bundledFp = null;
            for (const fpDir of shardxFpDirs) {
                if (!await fs.pathExists(fpDir)) continue;
                const all = (await fs.readdir(fpDir)).filter(f => f.endsWith('.json'));
                let files = all.filter(f => f.startsWith(wantPrefix));
                if (files.length === 0) {
                    // Thư viện thiếu bản cho OS này: dùng tạm bản khác còn hơn chạy
                    // trần không fingerprint, nhưng phải nói rõ vì kết quả sẽ lệch.
                    console.warn(`[ShardX] Thư viện không có fingerprint '${wantPrefix}*'; dùng tạm bản khác — dấu vân tay sẽ không khớp hệ điều hành.`);
                    files = all;
                }
                if (wantPrefix !== hostFpPrefix && files.length) {
                    console.warn(`[ShardX] Ép fingerprint '${wantPrefix}' trên máy '${hostFpPrefix}' theo cấu hình — trang kiểm tra dấu vân tay sẽ báo không nhất quán.`);
                }
                if (files.length > 0) {
                    // Pick a stable fingerprint per profile name (hash-based, consistent across runs)
                    const idx = profileName.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % files.length;
                    bundledFp = path.join(fpDir, files[idx]);
                    console.log(`[ShardX] Picked bundled fingerprint: ${files[idx]} (khớp OS '${wantPrefix}', từ ${fpDir})`);
                    break;
                }
            }

            if (bundledFp) {
                shardxFpFile = savedFpPath;
                try {
                    const shardxData = await fs.readJson(bundledFp);
                    const seed = profileName.split('').reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) & 0x7FFFFFFF, 0);
                    shardxData.noise = {
                        canvas: { enabled: true, seed: seed },
                        webgl: { enabled: true, seed: seed, intensity: 5 },
                        audio: { enabled: true, seed: seed },
                        client_rects: { enabled: true, seed: seed, max_offset: 5 },
                        sensors: { enabled: true, seed: seed },
                        fonts: { enabled: true, seed: seed }
                    };
                    const toSave = JSON.stringify(shardxData, null, 2);
                    await fs.outputFile(savedFpPath, toSave, 'utf8');
                    await fs.outputFile(legacyFpPath, toSave, 'utf8');
                    console.log(`[ShardX] Saved picked fingerprint with enabled noise to profile folder: ${savedFpPath}`);
                } catch (e) {
                    console.warn(`[ShardX] Failed to save picked fingerprint with noise: ${e.message}`);
                    shardxFpFile = bundledFp;
                }
            } else {
                // (c) No fingerprint available — engine will use its own defaults
                console.warn('[ShardX] No bundled fingerprint found. Engine will use built-in defaults.');
                console.warn('[ShardX] Install ShardBrowser at https://github.com/ProxyShard/ShardBrowser to get 170 profiles.');
            }
        }

        // ── 1b. Antidetect có thật sự bật không? ────────────────────────
        // Lỗ cũ: không tìm được fingerprint thì chỉ console.warn rồi mở bình thường
        // — trang vẫn mở, History vẫn đầy, mọi báo cáo vẫn "thành công", trong khi
        // hồ sơ chạy TRẦN và mọi hồ sơ trên máy trông y hệt nhau. Người gọi không
        // có cách nào biết. Nay trạng thái này có một dòng mốc cố định trong log
        // (ANTIDETECT_ON / ANTIDETECT_OFF) và một cờ máy đọc được trên manager.
        // BÊN ĐỌC: process_manager._note_launch_evidence() quét ANTIDETECT_OFF
        // trong log của tiến trình rồi đính warnings=["ANTIDETECT_OFF"] vào bản ghi
        // run_log — nên một lượt mở TRẦN không còn vào sổ như một lượt thành công
        // sạch. `this.lastLaunchInfo` thì vẫn CHƯA có ai đọc: nó để sẵn cho người
        // gọi trong tiến trình (open.js, preview_server) khi cần, đừng tưởng đã nối.
        const antidetectOn = !!shardxFpFile;
        try {
            this.lastLaunchInfo = Object.assign({}, this.lastLaunchInfo, {
                profile: profileName,
                engine: 'shardx',
                engineVersion: targetChromiumVer || null,
                antidetect: antidetectOn,
                fingerprintFile: shardxFpFile || null,
            });
        } catch (e) { /* ghi chú chẩn đoán hỏng cũng không được chặn lượt mở */ }
        if (antidetectOn) {
            console.log(`[ShardX] ANTIDETECT_ON profile=${profileName} fingerprint=${path.basename(shardxFpFile)}`);
        } else {
            console.error(`[ShardX] ANTIDETECT_OFF profile=${profileName} reason=no_fingerprint_available`);
            console.error(`[ShardX] ⚠️ Hồ sơ "${profileName}" mở KHÔNG có dấu vân tay: engine chạy bằng mặc định của `
                + `chính nó, nên mọi hồ sơ trên máy này trông giống hệt nhau. Cài thư viện fingerprint `
                + `(ShardBrowser) rồi mở lại nếu lượt chạy này cần ẩn danh.`);
        }

        // ── 2. Build launch args ────────────────────────────────────────
        const launchArgs = [
            // NOTE: --user-data-dir is passed as the first positional arg to
            // launchPersistentContext(), NOT as a CLI flag. Playwright enforces this.
            '--no-first-run',
            '--restore-last-session',
            '--hide-crash-restore-bubble',
            '--disable-blink-features=AutomationControlled',
            '--proxy-bypass-list=localhost,127.0.0.1,::1',
            '--remote-debugging-port=0',
            // KHÔNG có '--remote-allow-origins=*'. Cờ đó tắt lượt kiểm Origin trên
            // bắt tay WebSocket của DevTools — đúng thứ Chrome thêm vào để một trang
            // web không lái được cổng debug mà nó với tới. Trước thì cổng chỉ mở vài
            // giây cho một lượt chạy script; giờ khung live view giữ nó mở suốt phiên,
            // và sau cổng ấy là toàn bộ cookie + mọi tab đã đăng nhập. Người dùng duy
            // nhất là connectOverCDP của runner (chạy trong Node, không gửi Origin
            // nào — đã đối chiếu playwright-core), nên bỏ cờ này không mất gì.
            ...args
        ]
            // Người gọi (preview server) có thể chỉ định cổng CDP cố định để công bố
            // cho runner attach. Chromium lấy lần xuất hiện SAU của cùng một switch,
            // nhưng để hai cái cùng tên trong dòng lệnh là mời gọi hiểu nhầm — bỏ
            // mặc định '=0' đi khi người gọi đã tự chọn.
            .filter((a, i, all) => !(a === '--remote-debugging-port=0'
                && all.some((b, j) => j !== i && b.startsWith('--remote-debugging-port=')
                    && b !== '--remote-debugging-port=0')));

        if (shardxFpFile) {
            try {
                const tempDir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'data', 'temp_fps');
                await fs.ensureDir(tempDir);
                const safeName = crypto.createHash('md5').update(profileName).digest('hex') + '.json';
                const tempFpPath = path.join(tempDir, safeName);
                
                // Read and explicitly ensure noise is enabled before writing to the temp ASCII path
                const shardxData = await fs.readJson(shardxFpFile);
                
                // Dynamic timezone, language, and Client Hints override right before launch
                try {
                    const ipDetails = await this.resolveIPDetails(proxy);
                    if (ipDetails) {
                        console.log(`[ShardX] Injecting resolved timezone: ${ipDetails.timezone}`);
                        shardxData.timezone = ipDetails.timezone;
                        
                        const langDetails = this.getLanguageForCountry(ipDetails.countryCode);
                        console.log(`[ShardX] Injecting resolved language details [locale: ${langDetails.locale}, country: ${ipDetails.countryCode}]`);
                        
                        shardxData.icu_locale = langDetails.locale;
                        if (!shardxData.navigator) shardxData.navigator = {};
                        shardxData.navigator.language = langDetails.locale;
                        shardxData.navigator.accept_language = langDetails.acceptLanguage;
                        shardxData.navigator.languages = langDetails.languages;
                    }
                } catch (tzErr) {
                    console.warn(`[ShardX] Error injecting timezone/language: ${tzErr.message}`);
                }

                // Dynamic Client Hints version override right before launch
                if (targetChromiumVer) {
                    try {
                        const parts = targetChromiumVer.split('.');
                        if (parts.length === 4) {
                            const major = parts[0];
                            const build = parseInt(parts[2], 10);
                            const patch = parseInt(parts[3], 10);
                            
                            if (!shardxData.client_hints) shardxData.client_hints = {};
                            
                            shardxData.client_hints.brand = "Google Chrome";
                            shardxData.client_hints.brand_version = major;
                            shardxData.client_hints.brand_full_version = targetChromiumVer;
                            shardxData.client_hints.chrome_build = build;
                            shardxData.client_hints.chrome_patch = patch;
                            
                            console.log(`[ShardX] Injected Client Hints version: brand_full_version=${targetChromiumVer}, build=${build}, patch=${patch}`);
                        }
                    } catch (chErr) {
                        console.warn(`[ShardX] Error injecting Client Hints version: ${chErr.message}`);
                    }
                }

                const seed = profileName ? profileName.split('').reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) & 0x7FFFFFFF, 0) : Math.floor(Math.random() * 1000000);
                shardxData.noise = {
                    canvas: { enabled: true, seed: seed },
                    webgl: { enabled: true, seed: seed, intensity: 5 },
                    audio: { enabled: true, seed: seed },
                    client_rects: { enabled: true, seed: seed, max_offset: 5 },
                    sensors: { enabled: true, seed: seed },
                    fonts: { enabled: true, seed: seed }
                };
                await fs.outputJson(tempFpPath, shardxData, { spaces: 2 });
                console.log(`[ShardX] Wrote fingerprint with enabled noise to safe ASCII path: ${tempFpPath}`);
                shardxFpFile = tempFpPath;
            } catch (err) {
                console.warn('[ShardX] Failed to write fingerprint with noise to temp ASCII path:', err.message);
            }

            launchArgs.push(`--fingerprint-profile=${shardxFpFile}`);
        }

        // Cấu hình kích thước cửa sổ
        if (conf.window_size && conf.window_size.width && conf.window_size.height) {
            launchArgs.push(`--window-size=${conf.window_size.width},${conf.window_size.height}`);
        } else {
            launchArgs.push('--start-maximized');
        }

        // Headless is decided once here and passed to Playwright as an option;
        // pushing --headless as a raw arg as well would fight with it.
        let effectiveHeadless = headless;

        // Linux-only flags. Without these the engine starts and exits immediately,
        // and because nothing surfaced the exit reason the Remote page simply sat
        // on "Initializing browser..." forever.
        if (process.platform === 'linux') {
            // Chromium refuses to run as root unless the sandbox is disabled
            // ("Running as root without --no-sandbox is not supported"), and inside
            // a container root is the normal case.
            const isRoot = typeof process.getuid === 'function' && process.getuid() === 0;
            if (isRoot && !launchArgs.includes('--no-sandbox')) {
                launchArgs.push('--no-sandbox', '--disable-setuid-sandbox');
                console.log('[ShardX] Running as root — added --no-sandbox');
            }
            // Containers get a 64 MB /dev/shm by default, which Chromium exhausts
            // and then crashes; this makes it use /tmp instead.
            if (!launchArgs.includes('--disable-dev-shm-usage')) {
                launchArgs.push('--disable-dev-shm-usage');
            }
            // No display means no on-screen window is possible; run headless rather
            // than dying on "Missing X server or $DISPLAY". Remote streams over CDP,
            // so headless is exactly what it needs anyway.
            if (!effectiveHeadless && !process.env.DISPLAY && !process.env.WAYLAND_DISPLAY) {
                effectiveHeadless = true;
                launchArgs.push('--disable-gpu');
                console.log('[ShardX] No DISPLAY — running headless');
            }
        }

        // Mật khẩu proxy PHẢI đi bằng tuỳ chọn `proxy` của Playwright, KHÔNG phải
        // --proxy-server: Chromium không nhận đăng nhập trên dòng lệnh, nên bản cũ
        // ném phần user:pass đi rồi trình duyệt vẫn mở, chỉ có mọi trang chết
        // ERR_PROXY_CONNECTION_FAILED — lượt chạy vào sổ "thành công" với 0 trang.
        //
        // KHÔNG gọi normalizeProxy() ở đây: regex của nó rã chuỗi theo thứ tự
        // [protocol, user, pass, host, port] trong khi dạng nhà cung cấp thật sự là
        // [host, port, user, pass]. Hai lỗi của nó triệt tiêu nhau nên nó bỏ qua cả
        // 14 proxy đang có; ai chỉ sửa cái \d+ mà không sửa thứ tự sẽ biến
        // tên host thành username và trỏ hồ sơ vào một proxy không tồn tại.
        // Cùng luật với routes.parse_proxy() / routes.proxy_blocker().
        const parseProxyParts = (raw) => {
            const v = String(raw || '').trim();
            if (!v) return null;
            let m = v.match(/^([a-z0-9]+):\/\/([^:\/@]+):([^:\/@]*)@([^:\/@]+):(\d+)\/?$/i);
            if (m) return { scheme: m[1].toLowerCase(), host: m[4], port: m[5],
                            user: m[2], password: m[3], hasCredentials: true };
            m = v.match(/^([a-z0-9]+):\/\/([^:\/@]+):(\d+)\/?$/i);
            if (m) return { scheme: m[1].toLowerCase(), host: m[2], port: m[3],
                            user: '', password: '', hasCredentials: false };
            // scheme://host:port:user:pass — dạng nhà cung cấp, KHÔNG phải user trước.
            m = v.match(/^([a-z0-9]+):\/\/([^:\/@]+):(\d+):([^:\/@]+):([^:\/@]+)\/?$/i);
            if (m) return { scheme: m[1].toLowerCase(), host: m[2], port: m[3],
                            user: m[4], password: m[5], hasCredentials: true,
                            providerForm: true };
            return null;
        };
        const KNOWN_PROXY_SCHEMES = ['http', 'https', 'socks5', 'socks4'];
        let proxyOption = null;
        if (proxy) {
            const px = parseProxyParts(proxy);
            if (!px || !KNOWN_PROXY_SCHEMES.includes(px.scheme) || px.providerForm) {
                throw new Error(
                    `Proxy "${proxy}" is not in a form the engine can read. Use `
                    + `scheme://user:password@host:port with http, https, socks5 or socks4. `
                    + `The provider style scheme://host:port:user:password is not supported `
                    + `— rewrite it with the '@' form. (Chromium answers ERR_NO_SUPPORTED_PROXIES.)`);
            }
            if (px.hasCredentials && px.scheme.startsWith('socks')) {
                throw new Error(
                    `Profile "${profileName}" uses a SOCKS5 proxy with a username and password. `
                    + `The ShardX engine cannot authenticate to one: Chromium has no SOCKS5 login `
                    + `support and Playwright refuses it outright. Use an HTTP/HTTPS proxy from the `
                    + `same provider (the same credentials usually work), or an unauthenticated `
                    + `SOCKS5 endpoint.`);
            }
            proxyOption = { server: `${px.scheme}://${px.host}:${px.port}` };
            if (px.hasCredentials) {
                proxyOption.username = px.user;
                proxyOption.password = px.password;
            }
            console.log(`[ShardX] Proxy: ${proxyOption.server}`
                + (px.hasCredentials ? ' (with credentials)' : ''));
        }

        // ── 3. Launch via patchright (stealth Playwright) ───────────────
        // patchright is already in node_modules (playwright-with-fingerprints depends on it)
        // We use chromium.launchPersistentContext with the ShardX executable
        try {
            const { chromium } = await import('playwright');
            console.log(`[ShardX] Spawning: ${shardxExePath}`);
            const context = await chromium.launchPersistentContext(profilePath, {
                executablePath: shardxExePath,
                headless: effectiveHeadless,
                viewport: null, // Disable default Playwright viewport override to allow window-size / start-maximized
                args: launchArgs,
                ignoreDefaultArgs: ['--enable-automation', '--enable-blink-features=IdleDetection'],
                ignoreHTTPSErrors: true,
                ...(proxyOption ? { proxy: proxyOption } : {}),
            });

            // Bơm script ẩn danh để vượt qua các bộ kiểm tra bot cơ bản
            await context.addInitScript(() => {
                try {
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                } catch (e) {}
            });

            console.log('[ShardX] ✅ Browser launched successfully.');
            return context;
        } catch (e) {
            // Chromium's own stderr comes back inside the Playwright error, but as
            // one long blob nobody reads. Translate the causes that actually happen
            // on Linux into something the caller can act on, and keep the original
            // text attached.
            let hint = '';
            const msg = String(e.message || '');
            if (/root without --no-sandbox/i.test(msg)) {
                hint = 'Chromium will not run as root without --no-sandbox.';
            } else if (/error while loading shared libraries|cannot open shared object/i.test(msg)) {
                const lib = (msg.match(/(lib[\w.+-]+\.so[\w.]*)/) || [])[1] || 'a shared library';
                hint = `The engine is missing ${lib}. Install the Chromium runtime libraries `
                     + `(Debian/Ubuntu: apt install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 `
                     + `libcups2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 `
                     + `libpango-1.0-0 libcairo2 libasound2).`;
            } else if (/Missing X server|DISPLAY/i.test(msg)) {
                hint = 'No display is available; this profile has to run headless (use Remote).';
            } else if (/EACCES|permission denied/i.test(msg)) {
                hint = `The engine binary is not executable: chmod +x "${shardxExePath}".`;
            } else if (/ENOENT/i.test(msg)) {
                hint = `The engine binary was not found at ${shardxExePath}. Reinstall it from the Browser page.`;
            }
            console.error(`[ShardX] Launch failed: ${hint || msg}`);
            const err = new Error(hint ? `${hint} (${msg.split('\n')[0]})` : msg);
            err.cause = e;
            throw err;
        }
    }

    async getStats(profileName) {
        const profilePath = await this.ensureProfile(profileName);
        const statsPath = path.join(profilePath, 'stats.json');
        
        if (await fs.pathExists(statsPath)) {
            try {
                return await fs.readJson(statsPath);
            } catch (e) {
                console.warn(`Failed to read stats for ${profileName}, resetting...`);
            }
        }
        
        // Default Stats
        return {
            level: 1,
            class: 'Novice',
            exp: 0,
            impact: 0,
            assist: 0,
            mistake: 0,
            int: 0, // Intelligence
            apm: 0, // Actions Per Minute (tracked loosely)
            kda: 0.0
        };
    }

    async updateStats(profileName, actionType, context = {}) {
        const stats = await this.getStats(profileName);
        const profilePath = path.resolve(this.baseDir, profileName);
        
        // 1. Update Core Stats based on Action
        switch (actionType) {
            case 'search':
            case 'browse':
            case 'navigate':
                // Check for INT growth (tech keywords)
                const techKeywords = ['code', 'python', 'javascript', 'ai', 'data', 'algorithm', 'server', 'linux'];
                const content = (context.keyword || context.url || '').toLowerCase();
                if (techKeywords.some(k => content.includes(k))) {
                    stats.int += 1;
                }
                break;
                
            case 'comment':
            case 'type':
                // Impact growth
                stats.impact += 5; 
                stats.int += 0.5;
                break;
                
            case 'watch':
            case 'click':
            case 'like':
                // Assist/Support growth
                stats.assist += 1;
                break;

            case 'error':
                stats.mistake += 1;
                break;
        }

        // 2. Calculate KDA
        // KDA = (Impact + Assist) / (Mistake || 1)
        stats.kda = parseFloat(((stats.impact + stats.assist) / (stats.mistake || 1)).toFixed(2));

        // 3. Level Up Logic (Simple EXP based on total actions)
        stats.exp += 1;
        stats.level = Math.floor(Math.sqrt(stats.exp) * 0.5) + 1;

        // 4. Class Evolution
        if (stats.level >= 5) {
            if (stats.int > stats.impact && stats.int > stats.assist) stats.class = 'Scholar'; 
            else if (stats.impact > stats.assist) stats.class = 'Builder'; 
            else if (stats.assist > stats.impact) stats.class = 'Supporter';
            else stats.class = 'Novice';
        }
        
        // Save
        await fs.writeJson(path.join(profilePath, 'stats.json'), stats, { spaces: 2 });
        return stats;
    }
}
