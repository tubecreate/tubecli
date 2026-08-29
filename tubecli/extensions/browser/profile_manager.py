"""
Browser Profile Manager
Folder-based profile system with config.json per profile.
Ported from python-video-studio browser-laucher/web_manager.
"""
import os
import json
import shutil
import requests
from datetime import datetime
from typing import List, Optional, Dict, Any
from tubecli.config import DATA_DIR, EXTENSIONS_DATA_DIR

PROFILES_DIR = os.path.join(EXTENSIONS_DATA_DIR, "browser", "browser_profiles")


def extract_raw_key(json_str, key):
    import re
    pattern = rf'"{re.escape(key)}"\s*:'
    match = re.search(pattern, json_str)
    if not match:
        return None
    start_idx = match.end()
    while start_idx < len(json_str) and json_str[start_idx].isspace():
        start_idx += 1
    
    brace_count = 0
    in_string = False
    escape = False
    
    for i in range(start_idx, len(json_str)):
        char = json_str[i]
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char in ('{', '['):
                brace_count += 1
            elif char in ('}', ']'):
                brace_count -= 1
                if brace_count == 0:
                    return json_str[start_idx:i+1]
            elif brace_count == 0 and char in (',', '}'):
                return json_str[start_idx:i]
    return None


def ensure_profiles_dir():
    os.makedirs(PROFILES_DIR, exist_ok=True)


def list_profiles() -> List[Dict[str, Any]]:
    """List all browser profiles with metadata."""
    ensure_profiles_dir()
    profiles = []
    for name in os.listdir(PROFILES_DIR):
        profile_path = os.path.join(PROFILES_DIR, name)
        if os.path.isdir(profile_path):
            config = _load_config(name)
            profiles.append({
                "name": name,
                "created_at": config.get("created_at", ""),
                "tags": config.get("tags", []),
                "proxy": config.get("proxy", ""),
                "browser_version": config.get("browser_version", "latest"),
                "chrome_version": config.get("chrome_version", ""),
                "window_size": config.get("window_size", {"width": 1920, "height": 1080}),
                "notes": config.get("notes", ""),
                "has_cookies": os.path.exists(os.path.join(profile_path, "cookies.json")),
                "has_fingerprint": os.path.exists(os.path.join(profile_path, "fingerprint.json")),
                "google_account": config.get("google_account", None),
                "facebook_account": config.get("facebook_account", None),
                "tiktok_account": config.get("tiktok_account", None),
                "x_account": config.get("x_account", None),
                "discord_account": config.get("discord_account", None),
                "telegram_account": config.get("telegram_account", None),
            })
    # Sort newest first
    profiles.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return profiles


# Bản dự phòng khi CHÍNH câu import shardx_runtime nổ. Phải khớp
# shardx_runtime.FALLBACK_VERSION; chỉ dùng ở nhánh "không đọc nổi module nào".
_SHARDX_FALLBACK_VERSION = "149.0.7827.103"


def resolve_default_browser_version() -> str:
    """Nhân mặc định cho profile mới — NHÂN quyết định, không phải nền tảng.

    Cái quyết định một profile chạy đường nào là NHÂN ghim trên chính nó
    (config.json "browser_version"), vì browser_manager.js định tuyến bằng đúng một
    phép thử `targetChromiumVer.includes('ShardX')`. Nên câu hỏi ở đây chỉ có một:
    trên máy này, nhân nào MỚI NHẤT mà THỰC SỰ DÙNG ĐƯỢC — và ghim đích danh nhân
    đó. Không có "Linux thì ShardX, Windows thì BAS": nền tảng chỉ là một đầu vào
    của "dùng được", nằm gọn trong shardx_runtime.installed_engines().

    "Dùng được" khắt khe hơn "đã cài". Máy này cài đủ cả hai họ nhân, nhưng khoá
    bản quyền BAS đã hết hạn nên mọi lượt mở BAS đều chết ở "Key expired" — kiểm kê
    tính cả khoá, nên BAS ở đây là "đã cài, không dùng được".

    Bản cũ không hỏi câu nào trong số đó: nó quét thư mục engine BAS rồi trả về một
    số Chromium TRẦN, và hằng số cuối cùng `return "149.0.7827.54"` cũng là số
    trần. Số trần chính là một cái ghim BAS. Nên máy không dùng nổi BAS vẫn đóng
    dấu BAS lên MỌI profile mới — lỗi được đẻ ra ở đây, lúc TẠO profile, chứ không
    phải lúc mở trình duyệt. Hàm này không bao giờ được phép trả về số trần nữa trừ
    khi chính BAS đang dùng được.
    """
    try:
        # Import muộn: shardx_runtime hỏng thì cũng không được phép làm chết việc
        # tạo profile, nên nó nằm trong hàm chứ không ở đầu file.
        from tubecli.extensions.browser import shardx_runtime as sx
        pin = sx.default_engine_pin()
        if pin:
            return str(pin)
    except Exception as e:
        print(f"[resolve_default_browser_version] engine inventory unusable: {e}")

    # Không đọc được kiểm kê thì vẫn phải ghim một thứ CỨU ĐƯỢC: ShardX không cần
    # khoá, có bản cho cả ba OS, và tải được bằng POST /engine/download/{version}.
    return f"ShardX {_SHARDX_FALLBACK_VERSION}"


def create_profile(name: str, proxy: str = "", browser_version: str = "latest", tags: List[str] = None,
                   window_size: Dict[str, int] = None, chrome_version: str = "") -> Dict[str, Any]:
    """Create a new browser profile folder with config."""
    ensure_profiles_dir()
    safe_name = "".join(c for c in name if c.isalnum() or c in "_-")
    profile_path = os.path.join(PROFILES_DIR, safe_name)

    if os.path.exists(profile_path):
        raise ValueError(f"Profile '{safe_name}' already exists")

    os.makedirs(profile_path)

    if browser_version in ("default", "latest"):
        browser_version = resolve_default_browser_version()

    config = {
        "created_at": datetime.now().isoformat(),
        "tags": tags or ["Windows", "Chrome"],
        "proxy": proxy,
        "browser_version": browser_version,
        "chrome_version": chrome_version or "",
        "window_size": window_size or {"width": 1920, "height": 1080},
        "notes": "",
        "blacklist": [],
    }
    _save_config(safe_name, config)
    
    # Try fetching initial fingerprint
    get_fingerprint(safe_name)

    return {"name": safe_name, **config}


def delete_profile(name: str) -> bool:
    """Delete a profile and its data."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.exists(profile_path):
        return False
    shutil.rmtree(profile_path)
    return True


def get_profile(name: str) -> Optional[Dict[str, Any]]:
    """Get a single profile's config."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        return None
    config = _load_config(name)
    # Check fingerprint existence
    fp_path = os.path.join(profile_path, "fingerprint.json")
    has_fp = os.path.isfile(fp_path) and os.path.getsize(fp_path) > 100
    # Check cookies — from cookies.json OR Chrome SQLite DB
    cookie_count = 0
    cookie_path = os.path.join(profile_path, "cookies.json")
    if os.path.isfile(cookie_path):
        try:
            import json as _json
            with open(cookie_path, "r", encoding="utf-8") as f:
                c = _json.load(f)
            cookie_count = len(c) if isinstance(c, list) else 0
        except Exception:
            pass
    # Also check Chrome's native cookie DB (in both main and _bas profiles)
    if cookie_count == 0:
        for sub in ["", "_bas"]:
            chrome_cookie_db = os.path.join(PROFILES_DIR, name + sub, "Default", "Network", "Cookies")
            if os.path.isfile(chrome_cookie_db):
                db_size = os.path.getsize(chrome_cookie_db)
                if db_size > 20480:  # Empty DB is ~20KB, cookies add size
                    # Try to read via sqlite3 (works when browser is closed)
                    try:
                        import sqlite3
                        conn = sqlite3.connect(chrome_cookie_db, timeout=0.05)
                        count = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
                        conn.close()
                        if count > 0:
                            cookie_count = count
                            break
                    except Exception:
                        # Browser is running, estimate from file size
                        cookie_count = max(1, (db_size - 20480) // 200)
                        break
    return {"name": name, "has_fingerprint": has_fp, "cookie_count": cookie_count, **config}


def update_profile(name: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Update profile config fields."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        return None
    config = _load_config(name)
    if "browser_version" in kwargs and kwargs["browser_version"] in ("default", "latest"):
        kwargs["browser_version"] = resolve_default_browser_version()
    # proxy_kho / proxy_rotate_minutes: proxy nay den tu kho nao va co xoay khong.
    # Thieu hai khoa nay trong danh sach trang thi update_profile nhan roi VUT DI
    # lang le, va lan mo sau khong biet lay proxy ke tiep o dau de xoay.
    for key in ("tags", "proxy", "proxy_kho", "proxy_rotate_minutes", "browser_version", "chrome_version", "window_size", "notes", "blacklist", "google_account", "facebook_account", "tiktok_account", "x_account", "discord_account", "telegram_account"):
        if key in kwargs and kwargs[key] is not None:
            config[key] = kwargs[key]
    _save_config(name, config)
    return {"name": name, **config}


def bulk_set_proxy(names: List[str], proxy: str) -> List[Dict]:
    """Set proxy for multiple profiles at once."""
    results = []
    for name in names:
        if update_profile(name, proxy=proxy):
            results.append({"name": name, "status": "updated"})
        else:
            results.append({"name": name, "status": "not_found"})
    return results


def get_seed(profile_name: str) -> int:
    if not profile_name:
        import random
        return random.randint(0, 1000000)
    acc = 0
    for char in profile_name:
        acc = (acc * 31 + ord(char)) & 0x7FFFFFFF
    return acc

def parse_chrome_version(ua: str) -> dict:
    import re
    match = re.search(r'Chrome/(\d+)\.(\d+)\.(\d+)\.(\d+)', ua)
    if match:
        return {
            "major": match.group(1),
            "minor": match.group(2),
            "build": int(match.group(3)),
            "patch": int(match.group(4)),
            "full": match.group(0).split('/')[1]
        }
    return {
        "major": "124",
        "minor": "0",
        "build": 6367,
        "patch": 207,
        "full": "124.0.6367.207"
    }

def resolve_proxy_timezone(proxy: Optional[str]) -> str:
    if proxy:
        import re as _re
        host = None
        # Match host/IP from protocol://[user:pass@]host:port or host:port
        _m = _re.search(r'(?:[^@\n]+@)?(?:www\.)?([^:\/\n]+)', proxy)
        if _m:
            host = _m.group(1)
        if host and host not in ('127.0.0.1', 'localhost'):
            try:
                import requests
                resp = requests.get(f"http://ip-api.com/json/{host}", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success" and data.get("timezone"):
                        print(f"[Timezone] Resolved timezone for proxy {host}: {data.get('timezone')}")
                        return data.get("timezone")
            except Exception as e:
                print(f"[Timezone] Failed to resolve proxy timezone: {e}")
                
    # Fallback to default/local
    return "Asia/Ho_Chi_Minh"

def convert_bas_to_shardx(bas_fp: dict, profile_name: str = "") -> dict:
    if not bas_fp:
        return {}
    
    fp = bas_fp
    if "fingerprint" in bas_fp:
        fp = bas_fp["fingerprint"]
        if isinstance(fp, str):
            try:
                fp = json.loads(fp)
            except:
                pass
                
    ua = fp.get("ua", "")
    if not ua and "attr" in fp and isinstance(fp["attr"], dict):
        ua = fp["attr"].get("navigator.userAgent", "")
    if not ua and "navigator" in fp and isinstance(fp["navigator"], dict):
        ua = fp["navigator"].get("userAgent", "")
        
    chrome_ver = parse_chrome_version(ua)
    seed = get_seed(profile_name)
    
    time_zone = "Asia/Ho_Chi_Minh"
    try:
        if "attr" in fp and isinstance(fp["attr"], dict):
            tz = fp["attr"].get("timezone", fp["attr"].get("timeZone"))
            if tz:
                time_zone = tz
    except:
        pass
        
    lang_str = fp.get("lang")
    if not lang_str and "attr" in fp and isinstance(fp["attr"], dict):
        lang_str = fp["attr"].get("navigator.language")
    if not lang_str:
        lang_str = "en-US,en;q=0.9"
        
    lang_parts = [p.split(";")[0].strip() for p in lang_str.split(",")]
    primary_lang = lang_parts[0] if lang_parts else "en-US"
    
    screen_width = fp.get("width")
    if not screen_width and "attr" in fp and isinstance(fp["attr"], dict):
        screen_width = fp["attr"].get("screen.width")
    if not screen_width:
        screen_width = 1920
        
    screen_height = fp.get("height")
    if not screen_height and "attr" in fp and isinstance(fp["attr"], dict):
        screen_height = fp["attr"].get("screen.height")
    if not screen_height:
        screen_height = 1080
        
    avail_width = screen_width
    avail_height = screen_height
    if "attr" in fp and isinstance(fp["attr"], dict):
        avail_width = fp["attr"].get("screen.availWidth", screen_width)
        avail_height = fp["attr"].get("screen.availHeight", screen_height)
        
    color_depth = 24
    pixel_depth = 24
    device_pixel_ratio = 1
    avail_left = 0
    avail_top = 0
    if "attr" in fp and isinstance(fp["attr"], dict):
        color_depth = fp["attr"].get("screen.colorDepth", 24)
        pixel_depth = fp["attr"].get("screen.pixelDepth", 24)
        device_pixel_ratio = fp["attr"].get("window.devicePixelRatio", 1)
        avail_left = fp["attr"].get("screen.availLeft", 0)
        avail_top = fp["attr"].get("screen.availTop", 0)

    webgl_properties = fp.get("webgl_properties", {})
    if not isinstance(webgl_properties, dict):
        webgl_properties = {}
        
    webgl_vendor = webgl_properties.get("unmaskedVendor", "Google Inc.")
    webgl_renderer = webgl_properties.get("unmaskedRenderer", webgl_properties.get("renderer", ""))
    webgl_vendor_masked = webgl_properties.get("vendor", "WebKit")
    webgl_renderer_masked = webgl_properties.get("renderer", "WebKit WebGL")
    max_texture_size = webgl_properties.get("maxTextureSize", 16384)
    max_vertex_attribs = webgl_properties.get("maxVertexAttribs", 16)
    
    webgl_extensions = []
    ext_val = webgl_properties.get("extensions")
    if isinstance(ext_val, str):
        webgl_extensions = [e.strip() for e in ext_val.split(",") if e.strip()]
    elif isinstance(ext_val, list):
        webgl_extensions = ext_val
    else:
        webgl_extensions = [
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
        ]

    webgpu_vendor = "intel"
    webgpu_arch = ""
    r_lower = webgl_renderer.lower() if webgl_renderer else ""
    if "nvidia" in r_lower or "geforce" in r_lower:
        webgpu_vendor = "nvidia"
        webgpu_arch = "pascal"
    elif "amd" in r_lower or "radeon" in r_lower:
        webgpu_vendor = "amd"
    elif "intel" in r_lower or "uhd" in r_lower or "iris" in r_lower:
        webgpu_vendor = "intel"
        webgpu_arch = "gen-9"
        
    platform = "Windows"
    platform_value = "Win32"
    platform_version = "10.0.0"
    
    raw_platform = ""
    if "attr" in fp and isinstance(fp["attr"], dict):
        raw_platform = fp["attr"].get("navigator.platform", "Win32")
    elif "navigator" in fp and isinstance(fp["navigator"], dict):
        raw_platform = fp["navigator"].get("platform", "Win32")
        
    if "mac" in raw_platform.lower() or "macintosh" in ua.lower():
        platform = "MacIntel"
        platform_value = "MacIntel"
        platform_version = "13.0.0"
        
    audio_properties = fp.get("audio_properties", {})
    if not isinstance(audio_properties, dict):
        audio_properties = {}
        
    connection = fp.get("connection", {})
    if not isinstance(connection, dict):
        connection = {}
        
    battery = fp.get("battery", {})
    if not isinstance(battery, dict):
        battery = {}

    shardx_fp = {
        "name": fp.get("name", "converted-bas-fp"),
        "notes": webgl_renderer,
        "timezone": time_zone,
        "icu_locale": primary_lang,
        "navigator": {
            "language": primary_lang,
            "accept_language": lang_str,
            "languages": lang_parts,
            "user_agent": ua,
            "platform": platform,
            "platform_value": platform_value,
            "platform_version": platform_version,
            "hardware_concurrency": fp.get("attr", {}).get("hardwareConcurrency", fp.get("navigator", {}).get("hardwareConcurrency", 8)) if isinstance(fp.get("attr"), dict) else 8,
            "device_memory": fp.get("attr", {}).get("deviceMemory", fp.get("navigator", {}).get("deviceMemory", 8)) if isinstance(fp.get("attr"), dict) else 8,
            "vendor": fp.get("attr", {}).get("navigator.vendor", fp.get("navigator", {}).get("vendor", "Google Inc.")) if isinstance(fp.get("attr"), dict) else "Google Inc.",
            "max_touch_points": fp.get("attr", {}).get("maxTouchPoints", fp.get("navigator", {}).get("maxTouchPoints", 0)) if isinstance(fp.get("attr"), dict) else 0
        },
        "client_hints": {
            "brand": "Google Chrome",
            "brand_version": chrome_ver["major"],
            "platform_version": platform_version,
            "architecture": "x86" if platform == "Windows" else "arm",
            "bitness": "64",
            "mobile": False,
            "grease_brand": "Not)A;Brand",
            "grease_version": "24",
            "chrome_build": chrome_ver["build"],
            "chrome_patch": chrome_ver["patch"],
            "brand_full_version": chrome_ver["full"],
            "grease_full_version": "24.0.0.0"
        },
        "screen": {
            "width": screen_width,
            "height": screen_height,
            "avail_width": avail_width,
            "avail_height": avail_height,
            "color_depth": color_depth,
            "pixel_depth": pixel_depth,
            "device_pixel_ratio": device_pixel_ratio,
            "color_gamut": "srgb",
            "dynamic_range_high": False,
            "avail_left": avail_left,
            "avail_top": avail_top
        },
        "window": {
            "outer_width": screen_width,
            "outer_height": avail_height,
            "inner_width": screen_width,
            "inner_height": avail_height - 87
        },
        "webgl": {
            "vendor": webgl_vendor,
            "renderer": webgl_renderer,
            "vendor_masked": webgl_vendor_masked,
            "renderer_masked": webgl_renderer_masked,
            "max_texture_size": max_texture_size,
            "max_vertex_attribs": max_vertex_attribs,
            "extensions": webgl_extensions
        },
        "webgpu": {
            "vendor": webgpu_vendor,
            "architecture": webgpu_arch,
            "device": "",
            "description": "",
            "limits": {
                "maxTextureDimension1D": 16384,
                "maxTextureDimension2D": 16384,
                "maxTextureDimension3D": 2048,
                "maxTextureArrayLayers": 2048,
                "maxBindGroups": 4,
                "maxBindGroupsPlusVertexBuffers": 24,
                "maxBindingsPerBindGroup": 1000,
                "maxDynamicUniformBuffersPerPipelineLayout": 10,
                "maxDynamicStorageBuffersPerPipelineLayout": 8,
                "maxSampledTexturesPerShaderStage": 48,
                "maxSamplersPerShaderStage": 16,
                "maxStorageBuffersPerShaderStage": 16,
                "maxStorageTexturesPerShaderStage": 8,
                "maxUniformBuffersPerShaderStage": 12,
                "maxUniformBufferBindingSize": 65536,
                "maxStorageBufferBindingSize": 2147483644,
                "minUniformBufferOffsetAlignment": 256,
                "minStorageBufferOffsetAlignment": 256,
                "maxVertexBuffers": 8,
                "maxBufferSize": 2147483648.0,
                "maxVertexAttributes": 30,
                "maxVertexBufferArrayStride": 2048,
                "maxInterStageShaderVariables": 28,
                "maxColorAttachments": 8,
                "maxColorAttachmentBytesPerSample": 128,
                "maxComputeWorkgroupStorageSize": 32768,
                "maxComputeInvocationsPerWorkgroup": 1024,
                "maxComputeWorkgroupSizeX": 1024,
                "maxComputeWorkgroupSizeY": 1024,
                "maxComputeWorkgroupSizeZ": 64,
                "maxComputeWorkgroupsPerDimension": 65535
            }
        },
        "audio": {
            "sample_rate": audio_properties.get("BaseAudioContextSampleRate", 44100),
            "channel_count": audio_properties.get("AudioDestinationNodeMaxChannelCount", 2)
        },
        "connection": {
            "effective_type": connection.get("effectiveType", "4g"),
            "downlink_mbps": connection.get("downlink", 10),
            "rtt_msec": connection.get("rtt", 50),
            "save_data": connection.get("saveData", False)
        },
        "storage_estimate": {
            "quota_gb": 10
        },
        "webauthn": {
            "uvpa": True
        },
        "memory": {
            "heap_size_limit": 4294967296
        },
        "battery": {
            "charging": battery.get("charging", True),
            "level": battery.get("level", 1),
            "charging_time": battery.get("chargingTime", 0),
            "discharging_time": str(battery.get("dischargingTime", "Infinity"))
        },
        "media_devices": {
            "audio_input_count": 1,
            "audio_output_count": 1,
            "video_input_count": 0
        },
        "speech": {
            "voices": [
                { "name": "Google US English", "lang": "en-US", "local_service": False, "is_default": True },
                { "name": "Google UK English Female", "lang": "en-GB", "local_service": False, "is_default": False },
                { "name": "Google UK English Male", "lang": "en-GB", "local_service": False, "is_default": False }
            ]
        },
        "noise": {
            "canvas": { "enabled": True, "seed": seed },
            "webgl": { "enabled": True, "seed": seed, "intensity": 5 },
            "audio": { "enabled": True, "seed": seed },
            "client_rects": { "enabled": True, "seed": seed, "max_offset": 5 },
            "sensors": { "enabled": True, "seed": seed },
            "fonts": { "enabled": True, "seed": seed }
        },
        "tls": {
            "cipher_suites": [4865, 4866, 4867, 49195, 49199, 49196, 49200, 52393, 52392, 49171, 49172, 156, 157, 47, 53],
            "signature_algorithms": [1027, 2052, 1025, 1283, 2053, 1281, 2054, 1537],
            "shuffle_extensions": True
        }
    }
    return shardx_fp


def get_fingerprint(name: str) -> Optional[dict]:
    """Get the fingerprint for a profile, fetching from API if missing/invalid."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        return None

    fp_path = os.path.join(profile_path, "fingerprint_saved.json")
    legacy_fp_path = os.path.join(profile_path, "fingerprint.json")
    shardx_fp_path = os.path.join(profile_path, "shardx_fingerprint.json")
    
    # Read config to check if is_shardx
    config = get_profile(name)
    is_shardx = False
    if config:
        bv = config.get("browser_version")
        if bv and "ShardX" in bv:
            is_shardx = True

    # Try reading existing
    if is_shardx:
        for p in (shardx_fp_path, fp_path, legacy_fp_path):
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        fp = json.load(f)
                    if fp and isinstance(fp, dict) and len(fp) > 5:
                        is_valid_shardx = fp.get("navigator") or fp.get("screen") or fp.get("webgpu")
                        has_noise = fp.get("noise") and fp["noise"].get("canvas") and fp["noise"]["canvas"].get("enabled")
                        if is_valid_shardx and has_noise:
                            return fp
                        
                        # Convert/fix if not valid or noise disabled
                        converted = convert_bas_to_shardx(fp, name)
                        if config:
                            tz = resolve_proxy_timezone(config.get("proxy"))
                            if tz:
                                converted["timezone"] = tz
                        to_save = json.dumps(converted, indent=2, ensure_ascii=False)
                        with open(fp_path, "w", encoding="utf-8") as f_out: f_out.write(to_save)
                        with open(legacy_fp_path, "w", encoding="utf-8") as f_out: f_out.write(to_save)
                        with open(shardx_fp_path, "w", encoding="utf-8") as f_out: f_out.write(to_save)
                        return converted
                except Exception:
                    pass
    else:
        target_path = fp_path if os.path.exists(fp_path) else legacy_fp_path
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    fp = json.load(f)
                    if fp and isinstance(fp, dict) and len(fp) > 5:
                        return fp
            except Exception:
                pass
            
    # Fetch new from API
    try:
        # Read config to pass params
        config = get_profile(name)
        
        # Load BAS key from global_settings
        bas_key = None
        try:
            settings_path = os.path.join(DATA_DIR, "global_settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    bas_key = settings.get("bas_fingerprint_key") or settings.get("browser_service_keys", {}).get("bas")
        except Exception as e:
            print(f"[Fingerprint] Error reading settings: {e}")
        
        tags_param = "Microsoft Windows,Chrome"
        min_browser_version = None
        window_size = None
        
        if config:
            browser_version = config.get("browser_version")
            if browser_version and browser_version not in ("default", "latest"):
                try:
                    import re as _re
                    # Handle "ShardX 148.0.7778.97" or "148.0.7778.97" → "148"
                    _m = _re.search(r'(\d+)\.', browser_version)
                    if _m:
                        min_browser_version = _m.group(1)
                    else:
                        # Fallback: strip non-digit prefix then split
                        _stripped = _re.sub(r'^[^\d]*', '', browser_version)
                        min_browser_version = _stripped.split('.')[0] if _stripped else None
                except:
                    pass
            
            tags = config.get("tags")
            if tags:
                tag_map = {"Windows": "Microsoft Windows", "macOS": "Mac OS X"}
                mapped_tags = [tag_map.get(t, t) for t in tags]
                tags_param = ",".join(mapped_tags)
                
            window_size = config.get("window_size")

        def _do_fetch(params):
            resp = requests.get("https://api.tubecreate.com/api/fingerprints/getfinger.php", params=params, timeout=180.0)
            resp.raise_for_status()
            raw_text = resp.text
            data = resp.json()
            
            if data and data.get("status") == "success":
                fp_data = None
                fp_raw_string = None
                # New format: fingerprint inline
                if data.get("fingerprint"):
                    fp_data = data["fingerprint"]
                    fp_raw_string = extract_raw_key(raw_text, "fingerprint")
                # Old format: download via file_path
                elif data.get("file_path"):
                    fp_url = f"https://api.tubecreate.com/{data['file_path']}"
                    fp_resp = requests.get(fp_url, timeout=120.0)
                    fp_resp.raise_for_status()
                    fp_data = fp_resp.json()
                    fp_raw_string = fp_resp.text
                
                # Validate: check for {valid: false}
                if fp_data and isinstance(fp_data, dict) and fp_data.get("valid") is False:
                    print(f"[Fingerprint] Security Browser returned valid=false: {fp_data.get('message', '?')}")
                    return None, None
                    
                return fp_data, fp_raw_string
            return None, None

        # Attempt 1: with size ranges
        params = {"tags": tags_param}
        if bas_key:
            params["key"] = bas_key.strip()
        if min_browser_version:
            params["min_browser_version"] = min_browser_version
        if window_size:
            w, h = window_size.get("width", 1920), window_size.get("height", 1080)
            params["min_width"] = max(w - 200, 1024)
            params["max_width"] = w + 200
            params["min_height"] = max(h - 200, 600)
            params["max_height"] = h + 200

        fp_data, fp_raw_string = _do_fetch(params)
        
        # Attempt 2: without size
        if not fp_data and window_size:
            print("[Fingerprint] Retrying without size constraints...")
            params2 = {"tags": tags_param}
            if bas_key:
                params2["key"] = bas_key.strip()
            if min_browser_version:
                params2["min_browser_version"] = min_browser_version
            fp_data, fp_raw_string = _do_fetch(params2)
        
        # Attempt 3: without version
        if not fp_data and min_browser_version:
            print("[Fingerprint] Retrying without version constraint...")
            params3 = {"tags": tags_param}
            if bas_key:
                params3["key"] = bas_key.strip()
            fp_data, fp_raw_string = _do_fetch(params3)

        if fp_data and fp_raw_string:
            if is_shardx:
                converted = convert_bas_to_shardx(fp_data, name)
                if config:
                    tz = resolve_proxy_timezone(config.get("proxy"))
                    if tz:
                        converted["timezone"] = tz
                to_save = json.dumps(converted, indent=2, ensure_ascii=False)
                with open(fp_path, "w", encoding="utf-8") as f: f.write(to_save)
                with open(legacy_fp_path, "w", encoding="utf-8") as f: f.write(to_save)
                with open(shardx_fp_path, "w", encoding="utf-8") as f: f.write(to_save)
                return converted
            else:
                with open(fp_path, "w", encoding="utf-8") as f:
                    f.write(fp_raw_string)
                with open(legacy_fp_path, "w", encoding="utf-8") as f:
                    f.write(fp_raw_string)
                return fp_data
            
    except Exception as e:
        print(f"[Fingerprint API Error] {e}")
        
    return None


def reset_fingerprint(name: str) -> bool:
    """Delete the existing fingerprint so it gets re-fetched next time."""
    profile_path = os.path.join(PROFILES_DIR, name)
    fp_path = os.path.join(profile_path, "fingerprint_saved.json")
    legacy_fp_path = os.path.join(profile_path, "fingerprint.json")
    removed = False
    for p in (fp_path, legacy_fp_path):
        if os.path.exists(p):
            try:
                os.remove(p)
                removed = True
            except OSError:
                pass
    return removed


def refresh_fingerprint(name: str) -> Optional[dict]:
    """Force-fetch a fresh fingerprint from API, overwriting any existing one."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        return None
    fp_path = os.path.join(profile_path, "fingerprint_saved.json")
    legacy_fp_path = os.path.join(profile_path, "fingerprint.json")
    # Remove existing fingerprint to force fresh fetch
    for p in (fp_path, legacy_fp_path):
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
    return get_fingerprint(name)


def _load_config(name: str) -> dict:
    config_path = os.path.join(PROFILES_DIR, name, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"tags": ["Windows", "Chrome"], "notes": "", "blacklist": []}


def _save_config(name: str, config: dict):
    config_path = os.path.join(PROFILES_DIR, name, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
