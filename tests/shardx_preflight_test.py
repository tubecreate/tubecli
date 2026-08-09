"""The ShardX install must refuse BEFORE downloading, not fail at launch.

Run:  python tests/shardx_preflight_test.py     (exit 0 = pass)

Why this file exists. A user installed the engine on a fresh Ubuntu VPS, watched
a 200 MB download complete, saw the install report success — and then got
"The engine is missing libatk-1.0.so.0 ... Failed to launch the browser process"
on the first launch, with nothing connecting that to the install he had just
run.

Two things combined. preflight() checked only for `unzip`, so the Chromium
runtime libraries were never looked at until Chromium itself looked for them;
and install_packages() is deliberately silent when it cannot act — it returns
False rather than blocking a server process on a sudo password nobody can see —
so on a machine without passwordless sudo the libraries were quietly skipped.

The property locked in here: on Linux, a missing runtime library is detected up
front, an attempt is made to install it, and if that cannot be done the caller
gets the library name and the exact command, before any bytes are transferred.
"""
import os
import sys
import types
import unittest.mock as mock

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
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


LINUX = sx.HostSpec("Linux", "ShardX-Linux.zip", ("ShardX-Linux", "chrome"))


def fake_subprocess(cache: bytes):
    """A stand-in for the module's subprocess.

    Patching the real subprocess module instead would also reach
    platform.machine(), which shells out on Windows — that turned host_spec()
    into "no build for linux/" and made this test assert the wrong thing.
    """
    return types.SimpleNamespace(
        run=lambda cmd, **kw: types.SimpleNamespace(
            returncode=0, stdout=(cache if cmd and cmd[0] == "ldconfig" else b""), stderr=b""),
        SubprocessError=Exception, TimeoutExpired=Exception,
        DEVNULL=-3, PIPE=-1, STDOUT=-2,
    )


def ldconfig_cache(present):
    return b"\n".join(b"\t" + so.encode() + b" => /usr/lib/" + so.encode() for so in present)


def main():
    print("=== 1. Windows/macOS khong can thu vien nay ===")
    if sys.platform != "linux":
        check("khong bao thieu gi", sx.missing_chromium_libs() == [],
              str(sx.missing_chromium_libs()))
    else:
        print("  (dang chay tren Linux — bo qua)")

    print("\n=== 2. Linux thieu mot thu vien ===")
    cache = ldconfig_cache([s for s in sx._CHROMIUM_SONAMES if s != "libatk-1.0.so.0"])
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(sx, "subprocess", fake_subprocess(cache)):
        check("phat hien dung ten thu vien",
              sx.missing_chromium_libs() == ["libatk-1.0.so.0"],
              str(sx.missing_chromium_libs()))

    print("\n=== 3. khong cai tu dong duoc -> chan TRUOC khi tai ===")
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(sx, "subprocess", fake_subprocess(cache)), \
         mock.patch.object(sx, "host_spec", lambda: LINUX), \
         mock.patch.object(sx, "_can_install_packages", lambda: None), \
         mock.patch.object(sx.shutil, "which", lambda n: "/usr/bin/unzip"):
        msg = sx.preflight()
    check("preflight tra ve loi", msg is not None)
    check("  neu ten thu vien thieu", "libatk-1.0.so.0" in (msg or ""), (msg or "")[:80])
    check("  noi ro vi sao khong tu cai duoc",
          "sudo would prompt" in (msg or ""), (msg or "")[:80])
    check("  kem lenh chay duoc", "install" in (msg or "").lower())

    print("\n=== 4. du thu vien -> cho qua ===")
    full = ldconfig_cache(sx._CHROMIUM_SONAMES)
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(sx, "subprocess", fake_subprocess(full)), \
         mock.patch.object(sx, "host_spec", lambda: LINUX), \
         mock.patch.object(sx.shutil, "which", lambda n: "/usr/bin/unzip"):
        check("khong bao thieu", sx.missing_chromium_libs() == [])
        check("preflight cho qua", sx.preflight() is None, str(sx.preflight()))

    print("\n=== 5. khong chay duoc ldconfig -> KHONG ket luan hong ===")
    # "Cannot tell" must not become "definitely broken", or a working machine
    # with an unusual libc layout is refused an install it could complete.
    broken = types.SimpleNamespace(
        run=mock.Mock(side_effect=OSError("no ldconfig")),
        SubprocessError=Exception, TimeoutExpired=Exception,
        DEVNULL=-3, PIPE=-1, STDOUT=-2,
    )
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(sx, "subprocess", broken):
        check("tra ve rong", sx.missing_chromium_libs() == [])

    print("\n=== 6. danh sach .so khop voi danh sach goi apt ===")
    pkgs = sx.LINUX_APT_PACKAGES
    for soname, pkg in (("libatk-1.0.so.0", "libatk1.0-0"), ("libgbm.so.1", "libgbm1"),
                        ("libnss3.so", "libnss3"), ("libasound.so.2", "libasound2")):
        check(f"{soname} co goi tuong ung ({pkg})", pkg in pkgs)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
