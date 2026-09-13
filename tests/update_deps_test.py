# Nút cập nhật trên cloud không được chết ở `pip install -e .` trên Windows.
#
# Chạy:  python tests/update_deps_test.py     (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   13/9/2026: máy Windows chạy TubeCLI bằng miniconda bấm cập nhật từ cloud →
#   "Command '[...python.exe', '-m', 'pip', 'install', '-e', '.', '--quiet']' timed out
#   after 120 seconds". git pull đã xong nhưng máy không khởi động lại, và lần bấm sau
#   chạy lại đúng mã cũ trong RAM — không bao giờ tự thoát ra được. VPS Linux lọt
#   dưới 120s nên không ai thấy.
#   Bản cài editable đọc mã thẳng từ repo; pip chỉ cần khi file khai thư viện đổi.
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.core import update_deps as U   # noqa: E402

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


print("== A. đọc thư viện khai trong pyproject của CHÍNH repo này")
specs = U.declared_dependencies(str(ROOT))
check("A1 có fastapi kèm ràng buộc phiên bản", "fastapi>=0.100" in specs, specs[:6])
check("A2 có click", any(s.startswith("click") for s in specs), specs[:6])
check("A3 không lẫn dòng chú thích", not any(s.startswith("#") or "uvicorn speaks" in s for s in specs))
text = io.open(ROOT / "pyproject.toml", encoding="utf-8").read()
fb = U.deps_from_pyproject_text(text)
check("A4 đường lui không cần tomllib (Python 3.10) ra cùng danh sách", fb == [s for s in specs if s in fb] and len(fb) >= len(specs) - 1,
      (len(fb), len(specs)))

print("== B. chỉ cài khi FILE KHAI THƯ VIỆN đổi trong KHOẢNG commit vừa kéo về")
TMP = tempfile.mkdtemp(prefix="update_deps_")


def git(*args):
    return subprocess.run(["git", *args], cwd=TMP, capture_output=True, text=True, check=True).stdout.strip()


git("init", "-q")
git("config", "user.email", "t@t")
git("config", "user.name", "t")
Path(TMP, "pyproject.toml").write_text('[project]\ndependencies = [\n    "click>=8.0",\n]\n', encoding="utf-8")
git("add", "-A"); git("commit", "-qm", "a")
A = git("rev-parse", "HEAD")
Path(TMP, "README.md").write_text("x", encoding="utf-8")
git("add", "-A"); git("commit", "-qm", "b")
B = git("rev-parse", "HEAD")
Path(TMP, "pyproject.toml").write_text('[project]\ndependencies = [\n    "click>=8.0",\n    "rich>=13",\n]\n', encoding="utf-8")
git("add", "-A"); git("commit", "-qm", "c")
C = git("rev-parse", "HEAD")
Path(TMP, "main.py").write_text("print(1)", encoding="utf-8")
git("add", "-A"); git("commit", "-qm", "d")
D = git("rev-parse", "HEAD")

check("B1 chỉ đổi README → không cài", U.dep_files_changed(TMP, A, B) is False)
check("B2 đổi pyproject → cài", U.dep_files_changed(TMP, B, C) is True)
check("B3 kéo về NHIỀU commit, thư viện đổi ở commit GIỮA → vẫn cài",
      U.dep_files_changed(TMP, B, D) is True, "HEAD~1..HEAD chỉ thấy main.py")
check("B4 không kéo được gì mới → không cài", U.dep_files_changed(TMP, D, D) is False)
check("B5 không biết commit cũ → cài cho chắc", U.dep_files_changed(TMP, "", D) is True)
check("B6 commit không tồn tại → cài cho chắc", U.dep_files_changed(TMP, "deadbeef" * 5, D) is True)
check("B7 git_head đọc đúng", U.git_head(TMP) == D)
check("B8 requirements.txt đọc thêm, bỏ chú thích và tuỳ chọn",
      (Path(TMP, "requirements.txt").write_text("numpy>=1.2  # math\n-e .\n\n# x\n", encoding="utf-8") or True)
      and U.declared_dependencies(TMP) == ["click>=8.0", "rich>=13", "numpy>=1.2"], U.declared_dependencies(TMP))

print("== C. pip: KHÔNG -e, quá giờ/hỏng thì nói rõ")
seen = {}


def fake_run_ok(cmd, **kw):
    seen["cmd"] = cmd
    class R:
        returncode, stdout, stderr = 0, "", ""
    return R()


orig = U.subprocess.run
U.subprocess.run = fake_run_ok
res = U.install_dependencies(TMP, ["click>=8.0"])
check("C1 cài đúng chuỗi yêu cầu", res["ok"] and seen["cmd"][-1] == "click>=8.0", seen.get("cmd"))
check("C2 KHÔNG `-e .` (không đụng bản cài editable, không ghi đè tubecli.exe)",
      "-e" not in seen["cmd"] and "." not in seen["cmd"], seen["cmd"])


def fake_timeout(cmd, **kw):
    raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 1))


U.subprocess.run = fake_timeout
res = U.install_dependencies(TMP, ["rich>=13"], timeout=120)
check("C3 quá giờ → ok=False kèm lệnh để chạy tay", res["ok"] is False and "rich>=13" in res.get("command", ""), res)


def fake_fail(cmd, **kw):
    class R:
        returncode, stdout, stderr = 1, "", "ERROR: No matching distribution found for nope"
    return R()


U.subprocess.run = fake_fail
res = U.install_dependencies(TMP, ["nope"])
check("C4 pip hỏng → nói nguyên văn lỗi", res["ok"] is False and "No matching distribution" in res["error"], res)
U.subprocess.run = orig
check("C5 không có gì để cài → ok ngay", U.install_dependencies(TMP, []) == {"ok": True, "installed": [], "output": ""})

print("== D. hai endpoint cập nhật dùng đúng cách")
srv = io.open(ROOT / "tubecli" / "api" / "server.py", encoding="utf-8").read()
i = srv.index('@app.post("/api/v1/system/update")')
body = srv[i:srv.index("\n@app.", i + 10)]
check("D1 system_update không còn `pip install -e .`", '"install", "-e", "."' not in body)
check("D2 system_update chỉ cài khi file khai thư viện đổi", "update_deps.dep_files_changed(project_root, head_before, head_after)" in body)
check("D3 cài hỏng thì KHÔNG khởi động lại",
      'if res.get("ok"):\n                        _schedule_restart(delay=1.0)' in body)
check("D4 cài chạy nền (tránh giới hạn ~100s của tunnel)", "threading.Thread(target=_deps_then_restart" in body)
check("D5 báo trang chờ lâu hơn khi đang cài thư viện", "180 if deps_installing else 8" in body)
k = srv.index('@app.post("/api/v1/version/update")')
vbody = srv[k:srv.index("\n@app.", k + 10)]
check("D6 version/update so KHOẢNG commit, không chỉ HEAD~1", 'f"{head_before}..HEAD" if head_before else "HEAD~1..HEAD"' in vbody)

shutil.rmtree(TMP, ignore_errors=True)
print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
