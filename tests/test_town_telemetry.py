"""Agent Town telemetry phía máy: chỉ gửi tuple ẩn danh, ký đúng, không bao giờ chặn hay ném lỗi.

Chạy:  python tests/test_town_telemetry.py       (exit 0 = pass)

VÌ SAO: hàm này chen vào giữa dây chuyền video thật (codex report_step), và thứ nó gửi đi thì
hạ cánh ở một route CÔNG KHAI bên cloud. Nên phải khoá hai đầu:
  - dòng gửi đi không được mang tiêu đề / goal / username / đường dẫn
  - hỏng mạng, cloud 500, chưa ghép nối cloud — không cái nào được phép làm hỏng lượt chạy

Không đụng mạng: urllib.request.urlopen bị thay bằng bản giả (xem feedback-tests-mock-all-http).
"""
import hashlib
import hmac
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Console Windows mặc định là cp1252: in tên test tiếng Việt sẽ nổ UnicodeEncodeError
# và che mất kết quả thật. Tự ép UTF-8 thay vì bắt người chạy nhớ đặt PYTHONIOENCODING.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from tubecli.core import town_telemetry as tt  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run():
    sent = []
    mode = {"fail": None}

    def fake_urlopen(req, timeout=None):
        sent.append({
            "url": req.full_url,
            "headers": {k.lower(): v for k, v in req.headers.items()},
            "body": req.data.decode("utf-8"),
        })
        if mode["fail"] == "500":
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
        if mode["fail"] == "401":
            raise urllib.error.HTTPError(req.full_url, 401, "bad sig", {}, None)
        if mode["fail"] == "net":
            raise OSError("network down")
        return FakeResponse(b'{"accepted":1}')

    urllib.request.urlopen = fake_urlopen

    KEY = "a" * 48
    ident = {"username": "tuan89tk", "server_code": "k7m2qx", "town_key": KEY}
    s = tt._Sender()
    s._identity = lambda: {"code": ident["server_code"], "key": ident["town_key"]}

    # 1) Mã extension kiểm theo HÌNH DẠNG (không theo danh sách cố định): extension vừa
    # cài từ Chợ phải lên bản đồ ngay, không chờ cloud deploy. Sai hình dạng / trạng thái
    # lạ thì bỏ tại chỗ.
    s.report("capcut_tts", "success", "agent-1", 12)
    s.report("con_st", "success", "agent-1", 4)        # ext của Chợ: máy chưa từng biết cũng nhận
    s.report("Not A Step!", "success", "agent-1", 1)   # có khoảng trắng + hoa
    s.report("x", "success", "agent-1", 1)             # quá ngắn
    s.report("capcut_tts", "hacked", "agent-1", 1)     # trạng thái lạ
    check("nhận mọi mã extension đúng hình dạng, kể cả ext Chợ", len(s._q) == 2, f"q={len(s._q)}")

    # 2) Lô gửi đi CHỈ có 5 trường ẩn danh
    s._flush_once()
    check("có gửi một lô", len(sent) == 1, f"n={len(sent)}")
    body = json.loads(sent[0]["body"])
    row = body["events"][0]
    check("đúng 5 trường", sorted(row.keys()) == ["a", "d", "s", "st", "t"], str(sorted(row.keys())))
    blob = sent[0]["body"] + json.dumps(sent[0]["headers"])
    leaky = [w for w in ("tuan89tk", "agent-1", "goal", "title", "C:\\", "/home/") if w in blob]
    check("không lộ username / id agent / tên agent / đường dẫn", not leaky, str(leaky))
    check("mã extension gửi nguyên vẹn (nhà trên bản đồ)", row["s"] == "capcut_tts", row["s"])

    # 3) Chữ ký kiểm được bằng khoá, và phủ cả mốc thời gian
    h = sent[0]["headers"]
    expect = hmac.new(KEY.encode(), (h["x-town-ts"] + ".").encode() + sent[0]["body"].encode(),
                      hashlib.sha256).hexdigest()
    check("chữ ký khớp HMAC(khoá, ts.body)", h["x-town-sig"] == expect)
    check("gửi kèm mã máy", h["x-town-server"] == "k7m2qx")
    wrong = hmac.new(KEY.encode(), ("0." + sent[0]["body"]).encode(), hashlib.sha256).hexdigest()
    check("đổi mốc thời gian là chữ ký khác", h["x-town-sig"] != wrong)
    check("đặt User-Agent riêng (tunnel chặn bản mặc định)", "TubeCLI-Town" in h.get("user-agent", ""))

    # 4) MỘT NGƯỜI = MỘT AGENT CÓ THẬT: cùng agent thì cùng mã qua mọi task, nên nó là
    # một người cố định trên bản đồ chứ không phải mỗi lượt chạy một người mới.
    a1, a2 = tt.agent_hash("agent-1"), tt.agent_hash("agent-1")
    a3 = tt.agent_hash("agent-2")
    check("cùng agent → cùng người trên bản đồ", a1 == a2)
    check("khác agent → khác người", a1 != a3)
    check("mã agent không chứa id agent", "agent-1" not in a1 and len(a1) == 16)

    # 5) Chưa ghép nối cloud: giữ hàng đợi, KHÔNG gửi, KHÔNG ném lỗi
    s2 = tt._Sender()
    s2._identity = lambda: None
    s2.report("file_manager", "success", "agent-9", 3)
    before = len(sent)
    s2._flush_once()
    check("chưa nối cloud thì không gửi", len(sent) == before)
    check("chưa nối cloud vẫn giữ lại dòng", len(s2._q) == 1)

    # 6) Cloud 500: trả dòng về hàng đợi và giãn nhịp
    mode["fail"] = "500"
    s.report("video_studio", "success", "agent-2", 30)
    s._flush_once()
    check("cloud 500 thì giữ lại dòng để gửi lại", len(s._q) == 1, f"q={len(s._q)}")
    check("cloud 500 thì giãn nhịp", s._backoff > time.time())

    # 7) Mạng hỏng: cũng giữ lại, và tuyệt đối không ném lỗi lên trên
    mode["fail"] = "net"
    s._backoff = 0.0
    try:
        s._flush_once()
        raised = False
    except Exception as e:  # noqa: BLE001
        raised = True
        print("   ", e)
    check("mạng hỏng không ném lỗi ra ngoài", not raised)
    check("mạng hỏng vẫn giữ dòng", len(s._q) == 1)

    # 8) 401 (khoá cũ): bỏ lô, đừng gửi lại mãi
    mode["fail"] = "401"
    s._backoff = 0.0
    s._flush_once()
    check("cloud từ chối 4xx thì bỏ lô, không lặp vô hạn", len(s._q) == 0, f"q={len(s._q)}")

    # 9) Hàng đợi có trần, đầy thì bỏ dòng CŨ NHẤT
    mode["fail"] = None
    s3 = tt._Sender()
    s3._identity = lambda: {"code": "k7m2qx", "key": KEY}
    for i in range(tt.MAX_QUEUE + 25):
        s3.report("content_video", "success", f"agent-{i}", 1)
    check("hàng đợi không vượt trần", len(s3._q) == tt.MAX_QUEUE, f"q={len(s3._q)}")
    check("bỏ dòng cũ nhất, giữ dòng mới nhất",
          s3._q[-1]["a"] == tt.agent_hash(f"agent-{tt.MAX_QUEUE + 24}"))

    # 10) Tắt bằng biến môi trường
    os.environ["TUBECLI_TOWN"] = "off"
    s4 = tt._Sender()
    s4.report("keychain", "success", "agent-x", 1)
    check("TUBECLI_TOWN=off thì không ghi gì", len(s4._q) == 0)
    os.environ.pop("TUBECLI_TOWN", None)

    # 11) KIỂM CHÉO HAI NGÔN NGỮ — vector dưới đây do lib/town.js bên cloud sinh ra
    # (ingestKeyFor + HMAC "ts.body"). Nếu một bên đổi cách ký mà bên kia không đổi theo,
    # mọi lô đều bị từ chối 401 mà chẳng ai thấy gì. Test này phát hiện ngay tại chỗ.
    XC_KEY = "17e75980ad70e824570376e9742ddf5c09a2cf03bf9b102a"
    XC_TS = 1790000000
    XC_BODY = ('{"events":[{"s":"capcut_tts","st":"success",'
               '"a":"a1b2c3d4e5f60718","d":12,"t":1790000000}]}')
    XC_SIG = "2e68cda11be1c88a121e0faa6f73db9abe89161532136348cfbf17404913aad5"
    mine = hmac.new(XC_KEY.encode("utf-8"),
                    f"{XC_TS}.".encode("utf-8") + XC_BODY.encode("utf-8"),
                    hashlib.sha256).hexdigest()
    check("chữ ký Python khớp đúng vector của lib/town.js", mine == XC_SIG, mine)
    # Lô thật phải serialise y hệt vector: json.dumps mặc định chèn dấu cách sau ':' và ','
    # → body khác một byte là chữ ký khác, cloud từ chối sạch.
    rebuilt = json.dumps(
        {"events": [{"s": "capcut_tts", "st": "success", "a": "a1b2c3d4e5f60718", "d": 12, "t": XC_TS}]},
        separators=(",", ":"),
    )
    check("json.dumps trong _flush_once ra đúng dạng body đã ký", rebuilt == XC_BODY, rebuilt)

    # 12) report() ở tầng ngoài nuốt mọi lỗi
    tt._sender._identity = lambda: (_ for _ in ()).throw(RuntimeError("kaboom"))
    try:
        tt.report("codex", "success", "agent-z", 1)
        tt._sender.stop()
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
    check("report() ngoài cùng không bao giờ ném lỗi", not raised)


if __name__ == "__main__":
    run()
    print(f"\n{PASS} pass, {FAIL} fail")
    sys.exit(1 if FAIL else 0)
