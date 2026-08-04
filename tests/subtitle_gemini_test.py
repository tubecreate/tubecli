"""subtitle_extractor's Gemini engine must never report success over lost audio.

Run:  python tests/subtitle_gemini_test.py     (exit 0 = pass)

Why this file exists. Four separate paths in this engine turned a failure into
a shorter-but-successful transcript, which is the worst possible outcome: the
user keeps a file that looks finished and is missing minutes of speech.

  * _split_audio_ffmpeg ignored ffmpeg's return code and gated only on "did a
    file appear". A broken ffmpeg — the conda build that exits 0xC0000139
    raises no exception and writes nothing — made every chunk vanish, and the
    caller returned {"status": "success", "count": 0}.
  * Timestamps were rebased twice when the model omitted an "end": `end` was
    computed as chunk_start + (already-absolute start + 0.5). On chunk 5 that
    turned a 0.5s cue into an 875-second one, which then became the reported
    video duration.
  * A reply truncated by maxOutputTokens returned [] for the whole 175-second
    chunk and still counted as completed.
  * The retry branch tested `"JSON" in str(e)`, and json.JSONDecodeError does
    not contain that word, so malformed answers were never retried.

The engine is loaded by path because the extension is not an importable
package; that is also how the extension's own routes load it.
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ENGINE = os.path.join(ROOT, "data", "extensions_external", "subtitle_extractor",
                      "engines", "gemini_engine.py")

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def load():
    spec = importlib.util.spec_from_file_location("se_gemini_under_test", ENGINE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def code_only(path):
    """Source with comments and docstrings stripped.

    A "this pattern must be gone" assertion that greps raw text also matches
    the comment written to explain why the pattern was removed, and then fails
    forever on correct code. ast.unparse() drops comments outright; docstrings
    survive as string literals, so they are removed explicitly.
    """
    import ast as _ast

    tree = _ast.parse(open(path, encoding="utf-8").read())
    for node in _ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, _ast.Expr) and isinstance(first.value, _ast.Constant)
                    and isinstance(first.value.value, str)):
                body.pop(0)
                if not body:
                    body.append(_ast.Pass())
    return _ast.unparse(tree)


def main():
    if not os.path.isfile(ENGINE):
        print(f"khong tim thay engine: {ENGINE}")
        return 0  # extension not installed on this machine
    g = load()

    print("=== 1. ffmpeg that bai -> nem loi, khong bo qua lang le ===")
    real_run = g.subprocess.run
    calls = {"n": 0}

    def fail_run(cmd, **kw):
        calls["n"] += 1
        if "ffprobe" in str(cmd[0]).lower():
            return types.SimpleNamespace(returncode=0, stdout=b"600.0\n", stderr=b"")
        # ffmpeg: exactly the conda failure — non-zero, no exception, no file.
        return types.SimpleNamespace(returncode=3221225785, stdout=b"", stderr=b"")

    g.subprocess.run = fail_run
    try:
        g._split_audio_ffmpeg("C:\\nonexistent\\video.mp4")
        check("nem RuntimeError khi ffmpeg that bai", False, "khong nem gi ca")
    except RuntimeError as e:
        msg = str(e)
        check("nem RuntimeError khi ffmpeg that bai", True)
        check("  thong bao co ma loi", "3221225785" in msg, msg[:90])
        check("  thong bao KHONG bao 'Install FFmpeg'", "Install FFmpeg" not in msg, msg[:90])
    except Exception as e:
        check("nem RuntimeError khi ffmpeg that bai", False, f"{type(e).__name__}: {e}")
    finally:
        g.subprocess.run = real_run

    print("\n=== 2. ffprobe khong doc duoc -> khong coi la 0 giay ===")
    def probe_fail(cmd, **kw):
        return types.SimpleNamespace(returncode=3221225785, stdout=b"", stderr=b"")

    g.subprocess.run = probe_fail
    try:
        g._split_audio_ffmpeg("C:\\nonexistent\\video.mp4")
        check("nem loi khi ffprobe hong", False, "khong nem")
    except RuntimeError as e:
        check("nem loi khi ffprobe hong", True)
        check("  neu ten binary trong thong bao", "ffprobe" in str(e).lower(), str(e)[:80])
    finally:
        g.subprocess.run = real_run

    print("\n=== 3. rebase timestamp khong cong doi chunk_start ===")
    # The exact shape that produced an 875-second cue.
    chunk = {"index": 5, "start": 875.0, "duration": 175.0, "path": "x.mp3"}
    raw = [{"start": 3.0, "text": "khong co end"},
           {"start": 10.0, "end": 12.5, "text": "binh thuong"},
           {"start": 20.0, "end": 18.0, "text": "end truoc start"},
           {"start": 900.0, "end": 950.0, "text": "vuot ra ngoai chunk"}]

    subs = g._rebase_subtitles(raw, chunk) if hasattr(g, "_rebase_subtitles") else None
    if subs is None:
        # The logic lives inline in _process_chunk; reproduce its contract by
        # asserting on the source instead of re-implementing it here.
        src = code_only(ENGINE)
        check("khong con cong chunk_start vao gia tri da tuyet doi",
              'float(s.get("end", start + 0.5))' not in src,
              "van con dong cu")
        check("co tinh theo gia tri tuong doi truoc",
              "rel_start" in src and "rel_end" in src)
        check("co kep vao trong pham vi chunk", "chunk_end" in src)
    else:
        by = {s["text"]: s for s in subs}
        check("cue thieu end: 875+3=878, khong phai 1753",
              abs(by["khong co end"]["start"] - 878.0) < 0.01
              and by["khong co end"]["end"] < 880.0,
              str(by.get("khong co end")))

    print("\n=== 4. tra loi bi cat -> ChunkParseError, khong phai chunk rong ===")
    check("ChunkParseError ton tai", hasattr(g, "ChunkParseError"))
    src = code_only(ENGINE)
    check("khong con tra ve chunk rong khi khong parse duoc",
          'return {"subtitles": [], "chunk_index": chunk["index"]}' not in src)
    check("co kiem finishReason MAX_TOKENS", "MAX_TOKENS" in src)

    print("\n=== 5. nhanh retry bat theo KIEU, khong so chuoi 'JSON' ===")
    check("khong con test '\"JSON\" in str(e)'", '"JSON" in str(e)' not in src)
    check("co 'except ChunkParseError'", "except ChunkParseError" in src)
    import json as _json
    try:
        _json.loads("{bad")
    except _json.JSONDecodeError as e:
        check("  (chung minh) str(JSONDecodeError) khong chua 'JSON'",
              "JSON" not in str(e), str(e)[:70])

    print("\n=== 6. khong chan event loop khi tach audio ===")
    check("dung asyncio.to_thread cho _split_audio_ffmpeg",
          "to_thread(_split_audio_ffmpeg" in src)

    print("\n=== 7. het key / het luot thu -> nem loi, khong tra list rong ===")
    check("khong con 'return []' trong process_with_rotation",
          src.count("return []") == 0, f"{src.count('return []')} cho con lai")

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
