"""Token git không được rời máy (user 22/11/2026: «phần mà người khác có thể thấy trong tương lai»).

Remote git hay được viết kèm token (https://ghp_…@github.com/…) và git lưu nguyên vào .git/config. TubeCLI đọc địa chỉ đó
ra cho GET /api/v1/extensions, kiểm cập nhật của Chợ, sổ nguồn gốc, câu lỗi git — MCP và khách dùng chung đều đọc được;
đăng lên Chợ thì thành công khai. KHÔNG sửa .git/config: git trên máy vẫn dùng địa chỉ như cũ.

  strip_credentials(url)   địa chỉ để HIỆN: bỏ user:mật khẩu@ (giữ «git@host:…», đó là tên đăng nhập ssh chứ không phải bí mật)
  scrub(text)              che token + user:mật khẩu@ trong một đoạn chữ (stderr của git, kết quả MCP)
  package_leaks(data)      gói extension sắp đăng lên Chợ có token GitHub ở file nào (không bao giờ trả token)
"""
from __future__ import annotations

import base64
import gzip
import json
import re
from typing import Any, List

# Tiền tố chính thức của GitHub; phần thân thật dài 36+ ký tự — nhận từ 20 để token bị cắt bớt vẫn bị che.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])(gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,255}")
# https://<bất kỳ>@host — tới dấu @ CUỐI trước dấu / (mật khẩu có thể chứa @)
_HTTP_USERINFO = re.compile(r"(?i)\b(https?://)[^\s/'\"<>]*@")
_OTHER_PASSWORD = re.compile(r"(?i)\b((?:ssh|git|ftps?|git\+ssh|git\+https?)://)([^\s/:@'\"<>]*):[^\s/'\"<>]*@")
MASK = "***"


def scrub(text: Any) -> str:
    """Che bí mật git trong một đoạn chữ. Không đụng gì khác."""
    s = "" if text is None else str(text)
    if "@" in s:
        s = _HTTP_USERINFO.sub(r"\1", s)
        s = _OTHER_PASSWORD.sub(r"\1\2@", s)
    if "gh" in s or "github_pat_" in s:
        s = TOKEN_RE.sub(lambda m: m.group(1) + MASK, s)
    return s


def strip_credentials(url: Any) -> str:
    """Địa chỉ git để hiện / gửi đi: không bao giờ kèm token, mật khẩu."""
    return scrub(str(url or "").strip())


def _unwrap(data: Any, depth: int = 0) -> Any:
    """item_data của Chợ: JSON lồng chuỗi, hoặc bọc {format: gzip+b64, data}."""
    if depth > 4:
        return data
    if isinstance(data, (str, bytes)):
        try:
            return _unwrap(json.loads(data), depth + 1)
        except (ValueError, TypeError):
            return data
    if isinstance(data, dict) and str(data.get("format") or "").startswith("gzip") and isinstance(data.get("data"), str):
        try:
            return _unwrap(gzip.decompress(base64.b64decode(data["data"])).decode("utf-8"), depth + 1)
        except Exception:      # noqa: BLE001 — gói hỏng: để Chợ tự báo
            return data
    return data


_REAL = re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_([A-Za-z0-9]{36,255})|github_pat_([A-Za-z0-9_]{50,255}))")


def _has_real_token(text: str) -> bool:
    """Giống token thật (đủ dài, nhiều ký tự khác nhau) — «ghp_xxxx…» trong tài liệu thì không."""
    return any(len(set(m.group(1) or m.group(2))) >= 12 for m in _REAL.finditer(text))


def _walk(node: Any, where: str, out: List[str]) -> None:
    if isinstance(node, str):
        if _has_real_token(node) and where not in out:
            out.append(where)
        return
    if isinstance(node, dict):
        name = node.get("path") or node.get("name") if isinstance(node.get("content"), str) else None
        for k, v in node.items():
            if k == "content_b64" and isinstance(v, str):
                try:
                    v = base64.b64decode(v).decode("utf-8", errors="ignore")
                except Exception:      # noqa: BLE001
                    continue
            _walk(v, str(name) if name else (f"{where}.{k}" if where else str(k)), out)
        return
    if isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            _walk(v, where, out)


def package_leaks(data: Any) -> List[str]:
    """Nơi trong gói có token GitHub: tên file, hoặc tên trường («manifest.git_url»). [] = sạch."""
    out: List[str] = []
    _walk(_unwrap(data), "", out)
    return out[:20]


def publish_refusal(item_data: Any) -> str:
    """Vì sao gói này không được đăng lên Chợ ("" = được)."""
    leaks = package_leaks(item_data)
    if not leaks:
        return ""
    more = "" if len(leaks) < 20 else " …"
    return ("This package contains a GitHub token, and everyone can read a Market package. Remove it and publish again. "
            "If the token was ever shared, also delete it at github.com/settings/tokens. Found in: " + ", ".join(leaks) + more)
