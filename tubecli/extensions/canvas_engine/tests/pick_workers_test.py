# -*- coding: utf-8 -*-
"""Số worker dựng theo SỨC MÁY — không được nhiều tới mức tràn RAM. 22/9/2026.

VÌ SAO CÓ FILE NÀY
  VPS 4 vCPU / 7.751 MB (server tungho2) dựng video Diễn giải 321 nhịp: _pick_workers cho 3 worker theo ước lượng cũ
  (~1 GB mỗi worker) → RAM 98 % trong 15 phút đầu, máy không trả lời 30 phút liền, 48 % sau 12 giờ rồi bị khởi động lại.
  Đo được: mỗi chuỗi node + ffmpeg ăn ~2 GB. User: «có phải do nó quá tải hay sai gì không? sử dụng 4cpu 8gram».

  1. máy 4 lõi / 8 GB → 2 worker (không phải 3)
  2. máy 4 lõi / 4 GB → 1
  3. máy nhiều lõi nhiều RAM giữ như cũ (12 lõi / 32 GB → 8)
  4. không đo được RAM → theo lõi; người dùng ép cứng → theo người dùng
  5. gói tranh to (LRU) và ffmpeg đều được tính vào từng worker

Run:  python tests/pick_workers_test.py     (exit 0 = pass)
"""
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = Path(__file__).resolve().parent.parent / "renderer"
sys.path.insert(0, str(R))
os.chdir(str(R))
import engines.video_encoder as VE  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


real_cpu, real_free, real_sprite, real_settings = VE.os.cpu_count, VE._free_ram_mb, VE._sprite_pack_mb, None
try:
    import config as C
    real_settings = C.load_settings
    C.load_settings = lambda: {}
except Exception:       # noqa: BLE001
    C = None


def machine(cpu, free_mb, sprite_mb=0):
    VE.os.cpu_count = lambda: cpu
    VE._free_ram_mb = lambda: free_mb
    VE._sprite_pack_mb = lambda: sprite_mb


try:
    machine(4, 7000)                      # VPS 8 GB, TubeCLI đang chạy ~700 MB
    ok(VE._pick_workers("16:9") == 2, "4 lõi / 8 GB (7 GB trống) → 2 worker — trước: 3, RAM 98 %", VE._pick_workers("16:9"))
    machine(4, 7000, 256)
    ok(VE._pick_workers("16:9") == 2, "… gói tranh phủ khung đầy LRU (256 MB) vẫn 2", VE._pick_workers("16:9"))
    machine(4, 3300)                      # VPS 4 GB
    ok(VE._pick_workers("16:9") == 1, "4 lõi / 4 GB → 1 worker", VE._pick_workers("16:9"))
    machine(2, 1500)
    ok(VE._pick_workers("16:9") == 1, "máy bé tí → không bao giờ dưới 1", VE._pick_workers("16:9"))
    machine(12, 28000, 256)
    ok(VE._pick_workers("16:9") == 8, "12 lõi / 32 GB → 8 như cũ (trần theo lõi, RAM dư)", VE._pick_workers("16:9"))
    machine(20, 26000, 256)
    ok(VE._pick_workers("16:9") == 11, "20 lõi / 32 GB → RAM giới hạn còn 11 (trước 12) — 12 worker từng tràn RAM 32 GB", VE._pick_workers("16:9"))
    machine(8, 14000)
    ok(VE._pick_workers("9:16") == 6, "8 lõi / 16 GB, video dọc → 6", VE._pick_workers("9:16"))
    machine(4, 0)
    ok(VE._pick_workers("16:9") == 3, "không đo được RAM → theo lõi (4 → 3)", VE._pick_workers("16:9"))
    if C is not None:
        C.load_settings = lambda: {"render_workers": 3}
        machine(4, 3300)
        ok(VE._pick_workers("16:9") == 3, "người dùng ép cứng render_workers=3 → 3, kể cả máy ít RAM (họ chịu trách nhiệm)")
        C.load_settings = lambda: {}
    need = VE._RAM_PER_WORKER_MB["16:9"] + VE._FFMPEG_MB
    ok(need >= 1800 and VE._OS_RESERVE_MB >= 2048, "ước lượng mỗi chuỗi node+ffmpeg ≥ 1,8 GB, chừa ≥ 2 GB cho app + HĐH", (need, VE._OS_RESERVE_MB))
finally:
    VE.os.cpu_count, VE._free_ram_mb, VE._sprite_pack_mb = real_cpu, real_free, real_sprite
    if C is not None and real_settings is not None:
        C.load_settings = real_settings

print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
