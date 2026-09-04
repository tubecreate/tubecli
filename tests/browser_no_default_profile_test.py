# No phantom "default" profile: the picker, the launcher and the server all refuse.
import io
import os
import re
import sys

# repo cloud nam canh repo nay
CLOUD = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tubecli-cloud")
NODES = io.open(os.path.join(CLOUD, "components", "flow", "nodes.js"), encoding="utf-8").read()

# 1. the node no longer invents a profile name
assert "profiles[0]?.name || 'default'" not in NODES, "vẫn còn tên bịa 'default'"
assert "useState(data.profile || profiles[0]?.name || '')" in NODES
print("1 state      : không còn useState(... || 'default')")

# 2. the picker renders real profiles only
assert "(profiles.length ? profiles : [{ name: profile }])" not in NODES, "vẫn vẽ card giả"
assert "{profiles.map((p) => {" in NODES
print("2 picker     : chỉ vẽ hồ sơ THẬT, không còn card giả khi danh sách rỗng")

# 3. an empty list shows the create prompt, and "+ Profile" is still there
assert "profiles.length === 0 && (" in NODES and "flow.node.noProfilesYet" in NODES
assert "flow.node.addProfile" in NODES
print("3 rong       : hiện lời nhắc tạo hồ sơ + vẫn còn nút ＋ Profile")

# 4. launching with no profile opens the create form instead of calling the server
m = re.search(r"const launch = async \(profName\) => \{(.{0,400})", NODES, re.S)
assert m and "if (!prof) { setMode('create')" in m.group(1), m.group(1)[:200] if m else "launch() không tìm thấy"
print("4 launch     : không có hồ sơ → mở ô tạo, không gửi tên rỗng xuống server")

# 5. createProfile still downloads the engine BEFORE creating (the point of the change)
cp = NODES[NODES.index("const createProfile = async"):][:2200]
assert "engine/versions" in cp and "engine/download/" in cp and "engine/status/" in cp
assert cp.index("engine/download/") < cp.index("'/api/v1/browser/profiles'"), "phải tải nhân TRƯỚC khi tạo hồ sơ"
print("5 nhan       : tạo hồ sơ = tải nhân ShardX (có tiến độ) rồi mới tạo")

# 6. all nine locales carry both new strings
langs = ["en", "vi", "zh", "zh-TW", "ja", "ko", "ru", "tr", "es"]
for lang in langs:
    src = io.open(os.path.join(CLOUD, "lib", "locales", f"{lang}.js"), encoding="utf-8").read()
    assert "'flow.node.noProfilesYet':" in src and "'flow.node.noProfilesHint':" in src, lang
    assert "{free}" in src[src.index("'flow.node.reason.oom':"):src.index("\n", src.index("'flow.node.reason.oom':"))], f"{lang}: oom thiếu {{free}}"
print(f"6 i18n       : {len(langs)} ngôn ngữ có noProfilesYet/Hint và câu OOM kèm {{free}}")

# 7. the server refuses an empty or unknown profile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import inspect
from tubecli.extensions.browser import routes as R
src = inspect.getsource(R.launch_preview)
assert '"reason": "no_profile"' in src and "os.path.isdir" in src, src[:400]
assert src.index('"no_profile"') < src.index("_launching_lock"), "phải chặn TRƯỚC khi vào khoá launch"
print("7 server     : /preview/launch từ chối hồ sơ rỗng/không có thật, kèm câu giải thích")

# 8. REASON_KEYS requires the RAM number so the server's precise sentence can win
assert "oom:            { key: 'flow.node.reason.oom',           need: ['free'] }" in NODES
print("8 oom        : reasonText đòi {free} → câu có số liệu RAM mới được hiện")
print()
print("ALL 8 GROUPS PASSED")
