"""Đồng bộ thư viện khi cập nhật TubeCLI — KHÔNG `pip install -e .`.

13/9/2026, máy Windows chạy TubeCLI bằng miniconda: nút cập nhật trên cloud báo
"Command '[...python.exe', '-m', 'pip', 'install', '-e', '.', '--quiet']' timed out
after 120 seconds". `git pull` ĐÃ xong, nhưng vì bước pip nổ nên máy không khởi
động lại — và lần bấm sau chạy lại đúng mã cũ đang nằm trong RAM, nên máy không
bao giờ tự thoát ra được. VPS Linux thì lọt dưới 120 giây nên không ai thấy.

`pip install -e .` là bước sai cho việc này:
  - bản cài editable đọc mã thẳng từ thư mục repo: git pull là đủ để có mã mới;
  - nó dựng lại gói trong một môi trường build riêng (tải setuptools/wheel) mỗi lần;
  - trên Windows nó phải ghi đè Scripts\\tubecli.exe — file mà CHÍNH tiến trình máy
    chủ đang giữ.
Việc duy nhất pip thật sự cần làm là cài thư viện MỚI khi file khai thư viện đổi.
"""
import os
import re
import subprocess
import sys
from typing import Dict, List

DEP_FILES = ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")


def git_head(repo: str) -> str:
    """Commit hiện tại của repo, "" nếu không đọc được."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:           # noqa: BLE001
        return ""


def dep_files_changed(repo: str, old_head: str, new_head: str) -> bool:
    """File khai thư viện có đổi giữa hai commit không.

    So cả KHOẢNG old..new, không phải HEAD~1..HEAD: kéo về nhiều commit một lúc thì
    thay đổi thư viện có thể nằm ở commit giữa. Không so được (thiếu commit, git lỗi)
    thì trả True — cài thử một lượt tốn vài giây, còn bỏ sót một thư viện mới là máy
    khởi động lại vào mã không import được.
    """
    if not old_head or not new_head:
        return True
    if old_head == new_head:
        return False
    try:
        r = subprocess.run(["git", "diff", "--name-only", f"{old_head}..{new_head}"],
                           cwd=repo, capture_output=True, text=True, timeout=20)
    except Exception:           # noqa: BLE001
        return True
    if r.returncode != 0:
        return True
    changed = {line.strip() for line in r.stdout.splitlines() if line.strip()}
    return any(f in changed for f in DEP_FILES)


def deps_from_pyproject_text(text: str) -> List[str]:
    """Chuỗi yêu cầu trong `dependencies = [...]` — đường lui khi không có tomllib
    (Python 3.10). Dòng chú thích bên trong mảng bị bỏ qua."""
    m = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)^\]", text or "")
    if not m:
        return []
    return [s.strip() for s in re.findall(r'^\s*"([^"]+)"', m.group(1), re.M) if s.strip()]


def declared_dependencies(repo: str) -> List[str]:
    """Chuỗi yêu cầu (vd "fastapi>=0.100") khai trong pyproject.toml + requirements.txt."""
    specs: List[str] = []
    py = os.path.join(repo, "pyproject.toml")
    if os.path.isfile(py):
        parsed = None
        try:
            import tomllib      # Python 3.11+
            with open(py, "rb") as f:
                parsed = tomllib.load(f)
        except Exception:       # noqa: BLE001
            parsed = None
        if parsed is not None:
            deps = (parsed.get("project") or {}).get("dependencies") or []
            specs.extend(str(s).strip() for s in deps if str(s).strip())
        else:
            try:
                with open(py, encoding="utf-8") as f:
                    specs.extend(deps_from_pyproject_text(f.read()))
            except Exception:   # noqa: BLE001
                pass
    req = os.path.join(repo, "requirements.txt")
    if os.path.isfile(req):
        try:
            with open(req, encoding="utf-8") as f:
                for line in f:
                    line = line.split("#", 1)[0].strip()
                    if line and not line.startswith("-"):
                        specs.append(line)
        except Exception:       # noqa: BLE001
            pass
    seen, out = set(), []
    for s in specs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def install_dependencies(repo: str, specs: List[str], timeout: int = 900) -> Dict:
    """Cài các yêu cầu còn thiếu. Yêu cầu đã thoả thì pip bỏ qua gần như tức thì,
    và KHÔNG đụng tới bản cài editable hay tubecli.exe."""
    if not specs:
        return {"ok": True, "installed": [], "output": ""}
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *specs]
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"pip did not finish within {timeout // 60} minutes",
                "command": " ".join(cmd)}
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "command": " ".join(cmd)}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout or "").strip()[-800:],
                "command": " ".join(cmd)}
    return {"ok": True, "installed": specs, "output": (r.stdout or "")[-400:]}
