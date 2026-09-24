# -*- coding: utf-8 -*-
"""ShardX dựng lại CÙNG số phiên bản, và thư viện fingerprint đổi theo nhân.

Run:  python tests/shardx_rebuild_test.py     (exit 0 = pass)

Ca thật: 152.0.7977.65 ra 9/9/2026 (engine_build 2) rồi dựng lại 13/9 (engine_build 4)
mà không đổi số. check_update() cũ chỉ so số nên máy cài hôm 9/9 thấy "đã mới nhất"
mãi. Thư viện fingerprint cũng chỉ tải MỘT lần, nên hồ sơ mới trên 152 vẫn bốc bản
thời 149.

Không đụng đĩa thật (launcher_root trỏ vào thư mục tạm), không gọi mạng.
"""
import json
import os
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.browser import shardx_runtime as sx

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


SPEC = sx.host_spec()


def manifest(build="4", etag="eb86-24", fp_etag="e2f2"):
    return {
        "chromium_version": "152.0.7977.65",
        "engine_build": build,
        "grease_brand": "Not?A_Brand",
        "grease_version": "24",
        "tls": {"signature_algorithms": list(range(11))},
        "revision": 7,
        "archives": {SPEC.archive: etag, sx.FINGERPRINTS_ARCHIVE: fp_etag},
    }


def fake_engine(root: Path, version: str):
    exe = sx.engine_dir(version).joinpath(*SPEC.binary_subpath)
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"x")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "shardx-launcher"
    with mock.patch.object(sx, "launcher_root", lambda: root), \
         mock.patch.dict(os.environ, {sx.ENV_VERSION_OVERRIDE: ""}):

        man = manifest()
        with mock.patch.object(sx, "fetch_manifest", lambda *a, **k: man):
            fake_engine(root, "149.0.7827.103")
            info = sx.check_update()
            check("149 đã cài, manifest 152 → có bản mới",
                  info["update_available"] and not info["rebuild_available"], info)

            fake_engine(root, "152.0.7977.65")
            # Nhân cài trước khi có dấu: KHÔNG biết bản dựng → không ép tải lại.
            info = sx.check_update()
            check("152 không dấu → coi là mới nhất", info["up_to_date"] and not info["update_available"], info)

            stamp = sx.write_install_stamp("152.0.7977.65", manifest(build="2", etag="old-etag"))
            check("dấu chép grease + tls của đúng đợt",
                  stamp.get("grease_brand") == "Not?A_Brand" and len(stamp["tls"]["signature_algorithms"]) == 11,
                  stamp)
            info = sx.check_update()
            check("cùng số, build 2 vs 4 → rebuild_available",
                  info["rebuild_available"] and info["update_available"] and not info["up_to_date"], info)
            check("báo bản dựng đang cài", info["installed_engine_build"] == "2", info)

            sx.write_install_stamp("152.0.7977.65", man)
            info = sx.check_update()
            check("cài lại xong → hết báo", info["up_to_date"] and not info["rebuild_available"], info)

            # Bản cũ tải qua worker: manifest nói số khác → dấu chỉ có số, không grease/tls sai đợt.
            st = sx.write_install_stamp("149.0.7827.103", man)
            check("dấu nhân cũ không mượn grease của 152", "grease_brand" not in st, st)

            # Thư mục tạm của lượt cài lại không được tính là một nhân.
            fake_engine(root, "152.0.7977.65.new")
            check("bỏ qua *.new / *.old",
                  sx.installed_versions() == ["152.0.7977.65", "149.0.7827.103"], sx.installed_versions())

            # Thư viện fingerprint
            check("chưa có thư viện → cần tải", sx.fingerprints_outdated(man))
            fpd = sx.fingerprints_dir()
            fpd.mkdir(parents=True, exist_ok=True)
            (fpd / "win-a.json").write_text("{}", encoding="utf-8")
            check("thư viện không dấu etag → coi là cũ", sx.fingerprints_outdated(man))
            (fpd / ".tubecli-etag").write_text("e2f2", encoding="utf-8")
            check("etag khớp → không cần tải", not sx.fingerprints_outdated(man))
            check("manifest thay gói → cần tải", sx.fingerprints_outdated(manifest(fp_etag="new")))
            check("không đọc được manifest → không kết luận", not sx.fingerprints_outdated({}))

        # Tải hỏng giữa chừng: thư viện cũ phải còn nguyên.
        def boom(*a, **k):
            raise OSError("network down")
        with mock.patch.object(sx, "fetch_manifest", lambda *a, **k: manifest(fp_etag="newer")), \
             mock.patch.object(sx, "download", boom):
            ok = sx.install_fingerprints()
            check("tải hỏng → thư viện cũ còn nguyên",
                  ok and (sx.fingerprints_dir() / "win-a.json").exists(), ok)

check("FALLBACK_VERSION ≥ 152", sx._version_key(sx.FALLBACK_VERSION) >= (152, 0, 0, 0), sx.FALLBACK_VERSION)
check("bảng BAS có 30.8.0 → 153", sx.bas_chromium_for("30.8.0") == "153.0.8010.37")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
