# -*- coding: utf-8 -*-
"""core/reup_dub.py — phần thuần (không ffmpeg, không mạng): tách dòng dài, dựng .ass,
chuỗi atempo, đọc khổ video. Chạy: python tests/reup_dub_test.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tubecli.core import reup_dub as rd  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {detail}")


# ── Tách dòng dài ───────────────────────────────────────────────────────────
long_vi = ("Zhongke Shuguang đã thông báo qua tài khoản công khai chính thức vào ngày 10 tháng 7 "
           "rằng cụm siêu máy tính AI đã chính thức hoàn thành và được kết nối với mạng lưới quốc gia.")
out = rd.split_long_subtitles([{"start": 7.6, "end": 16.7, "text": long_vi}])
check("dòng dài bị cắt thành nhiều cue", len(out) >= 3, len(out))
check("mỗi mảnh ≤ ~56 ký tự (mồ côi gộp được tới 1.3x)", all(len(s["text"]) <= 73 for s in out),
      [len(s["text"]) for s in out])
check("không mất chữ nào", " ".join(s["text"] for s in out) == long_vi)
check("mốc liên tục: đầu = start gốc, cuối = end gốc, không chồng",
      out[0]["start"] == 7.6 and out[-1]["end"] == 16.7
      and all(a["end"] == b["start"] for a, b in zip(out, out[1:])))
short = [{"start": 0, "end": 2, "text": "Xin chào."}]
check("dòng ngắn giữ nguyên", rd.split_long_subtitles(short) == [{"start": 0.0, "end": 2.0, "text": "Xin chào."}])
cjk = rd.split_long_subtitles([{"start": 0, "end": 10,
                                "text": "今天我们来聊一聊人工智能的发展，以及它对我们生活的影响，还有未来的趋势和挑战。"}],
                              max_chars=20)
check("CJK cắt theo dấu câu", [s["text"][-1] for s in cjk] == ["，", "，", "。"], [s["text"] for s in cjk])
check("dòng hỏng (start sai kiểu) bị bỏ, không làm sập", rd.split_long_subtitles([{"start": "x", "text": "a"}]) == [])

# ── .ass theo khổ video ─────────────────────────────────────────────────────
ass = rd.build_ass([{"start": 0, "end": 2, "text": "Xin {\\b1}chào\ndòng hai"},
                    {"start": 2.5, "end": 9, "text": "x" * 200}], 576, 768)
check("PlayRes = đúng khổ video", "PlayResX: 576" in ass and "PlayResY: 768" in ass)
check("cỡ chữ gốc 5.5% cạnh ngắn (576 → 32)", ",Arial,32," in ass)
check("ngoặc nhọn của chữ không thành lệnh ASS", "{\\b1}" not in ass and "Xin (\\b1)chào" in ass, ass.splitlines()[-2])
check("xuống dòng → \\N", "chào\\Ndòng hai" in ass)
check("cue quá dài tự thu cỡ, sàn 14", "{\\fs14}xxxx" in ass)
land = rd.build_ass([{"start": 0, "end": 1, "text": "a"}], 1920, 1080)
check("video ngang: chữ theo cạnh ngắn (1080 → 59), lề 12%", ",Arial,59," in land and ",230,230," in land)
check("mốc giờ ASS", rd._ass_time(3725.456) == "1:02:05.46")

# ── atempo + khổ video ──────────────────────────────────────────────────────
check("atempo ≤2 một khâu", rd._atempo_chain(1.5) == "atempo=1.5000")
check("atempo >2 xâu chuỗi", rd._atempo_chain(2.5) == "atempo=2.0,atempo=1.2500")
m = rd._SIZE_RE.search("Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, "
                       "bt470bg/unknown/unknown, progressive), 576x768 [SAR 1:1 DAR 3:4], 161 kb/s")
check("đọc khổ video từ stderr ffmpeg (không nhầm mã codec 0x3163…)", m and m.groups() == ("576", "768"))

# ── Mốc Gemini trôi: cue dồn cục ở đuôi (public_reup) ────────────────────────
from tubecli.core import public_reup as pr  # noqa: E402

drift = [{"start": i * 10.0, "end": i * 10.0 + 9, "text": "x" * 90} for i in range(14)]  # tới 139 s
drift[-1]["end"] = 148.33
drift += [{"start": 148.33, "end": 148.33, "text": "y" * 45} for _ in range(3)]
check("đếm cue dồn cục", pr.collapsed_count(drift) == 3)
fixed = pr.rescue_collapsed(drift, 148.33)
check("cứu xong: không còn cue dài 0, đủ số câu, đúng thứ tự chữ",
      pr.collapsed_count(fixed) == 0 and len(fixed) == len(drift)
      and [s["text"] for s in fixed] == [s["text"] for s in drift])
check("mọi mốc nằm trong video, tăng dần, không chồng",
      all(0 <= s["start"] < s["end"] <= 148.33 for s in fixed)
      and all(a["end"] <= b["start"] + 1e-6 for a, b in zip(fixed, fixed[1:])))
mid = [{"start": 0, "end": 5, "text": "a"}, {"start": 5, "end": 5, "text": "b"},
       {"start": 6, "end": 9, "text": "c"}]
check("dồn cục ở GIỮA thì để nguyên (không đoán)", pr.rescue_collapsed(mid, 10) == mid)
check("không có cue dồn cục thì trả nguyên", pr.rescue_collapsed(drift[:5], 148.33) == drift[:5])

# ── Mốc Gemini sai ĐƠN VỊ «phút.giây»: cả video dồn vào giây đầu (user 19/10/2026) ──
squash = [[0.0, 0.02, "Chư vị đạo hữu, vẫn khỏe chứ?"],
          [0.02, 0.056, "Chắc hẳn ngươi cũng không phải chuyên đến xem chúng ta làm trò cười đâu nhỉ."],
          [0.064, 0.069, "Đúng vậy."], [0.07, 0.089, "Ta chính là đến xem ngươi làm trò cười đó."],
          [0.17, 0.18, "Chào hai thầy."], [0.23, 0.254, "Đạo diễn bảo tôi mang kịch bản mới đến cho hai vị rồi."],
          [0.28, 0.317, "Hai vị đạo diễn, vai diễn của tôi trong kịch bản không đúng phải không, sao lại ít thế này?"],
          [0.339, 0.357, "Alo, được được, tôi đến ngay đây."],
          [0.38, 0.409, "Bình tĩnh nào, lát nữa tôi sẽ nói chuyện với Vọng Ngữ."],
          [0.409, 0.44, "Hình như tôi cũng không có vai diễn nữa rồi, các bạn có nhớ tôi không?"],
          [0.46, 0.479, "Ơ, ngươi là"], [0.479, 0.519, "Là ta, Lão Vũ, người đã đại chiến 300 hiệp với Thiên Cô đó."],
          [0.519, 0.539, "Ừm, ồ, ngươi chắc chắn không phải 30 hiệp chứ?"], [0.545, 0.549, "Thật sao?"],
          [0.565, 0.587, "Xem ra kịch bản của ba chúng ta đều gần như nhau."],
          [0.587, 1.022, "Ừm, nhưng mà Ngọc Ngọc, sao vai diễn của em lại nhiều hơn bọn chị?"],
          [1.05, 1.09, "Nhưng mà kịch bản sau này của ba chị em chúng ta đều giống nhau, sẽ đại triển thân thủ ở Trụy Ma Cốc."],
          [1.1, 1.109, "Ôi!"], [1.109, 1.119, "Ngươi có biết đánh bài không?"],
          [1.119, 1.147, "Hắn là địa chủ, ngươi đánh ta hả đồ lão già!"],
          [1.147, 1.167, "Ta thích đánh thế nào thì đánh thế đó, ngươi quản được ta sao!"],
          [1.167, 1.179, "Các ngươi đừng đánh nữa!"], [1.189, 1.209, "Các ngươi đừng đánh nữa!"], [1.209, 1.229, "Đừng đánh nữa!"],
          [1.26, 1.325, "Hề hề, lại có thêm một Nguyên Anh tu sĩ 300 tuổi, còn có nhiều tán tu thực lực như vậy nữa."],
          [1.325, 1.369, "Lão Lý à, Lạc Vân Tông chúng ta sắp cất cánh rồi!"],
          [1.39, 1.417, "Được rồi, hôm nay đến đây thôi, ngươi còn gì muốn nói không?"],
          [1.417, 1.456, "Server mới của tôi sẽ ra mắt vào tuần tới, chư vị đạo hữu có thể mong chờ nhé!"],
          [1.456, 1.487, "Chuẩn bị xong rồi, cùng uống một ly chứ?"]]
fx = pr.fix_timescale([{"start": a, "end": b, "text": t} for a, b, t in squash], 112.316)
check("job thật 112 s: 1.456 → 105.6 s, «Đúng vậy.» 6.4–6.9 s, câu cuối kết thúc 108.7 s",
      len(fx) == len(squash) and abs(fx[-1]["start"] - 105.6) < 0.01 and abs(fx[-1]["end"] - 108.7) < 0.01
      and abs(fx[2]["start"] - 6.4) < 0.01 and abs(fx[2]["end"] - 6.9) < 0.01,
      [(x["start"], x["end"]) for x in fx[:4]] + [(fx[-1]["start"], fx[-1]["end"])])
check("mọi mốc trong video, tăng dần, không cue 0 s → không kích hoạt tách lại / rescue",
      all(0 <= x["start"] < x["end"] <= 112.316 for x in fx)
      and all(a["start"] <= b["start"] for a, b in zip(fx, fx[1:])) and pr.collapsed_count(fx) == 0)
sp = rd.split_long_subtitles(fx)
un = rd.group_for_tts(sp)
check("sau sửa: cắt dòng + gộp đoạn chạy bình thường, đoạn cuối kết thúc trong video",
      len(sp) >= len(fx) and all(u["end"] > u["start"] for u in un) and un[-1]["end"] <= 112.4, (len(sp), len(un)))
check("mốc bình thường trả nguyên (video 148 s)", pr.fix_timescale(drift[:14], 148.33) == drift[:14])
short = [{"start": 0.5, "end": 1.5, "text": "Chào"}, {"start": 2.0, "end": 3.0, "text": "Xin chào"},
         {"start": 3.5, "end": 4.5, "text": "Tạm biệt"}]
check("nói ít ở đầu video dài (tốc độ đọc bình thường) → KHÔNG đổi", pr.fix_timescale(short, 120.0) == short)
fx2 = pr.fix_timescale([{"start": 175.0 + a, "end": 175.0 + b, "text": t} for a, b, t in squash], 300.0)
check("khúc thứ 2 (từ 175 s) đổi theo đầu khúc", abs(fx2[-1]["start"] - 280.6) < 0.01
      and all(175 <= x["start"] < x["end"] <= 300 for x in fx2), (fx2[0], fx2[-1]))
x100 = [{"start": 0.05, "end": 0.10, "text": "a" * 60}, {"start": 0.62, "end": 0.70, "text": "b" * 90},
        {"start": 0.95, "end": 1.00, "text": "c" * 60}]
fx3 = pr.fix_timescale(x100, 110.0)
check("phần lẻ ≥ 60 → không phải phút.giây, đổi ×100 (0.62 → 62 s)", [x["start"] for x in fx3] == [5.0, 62.0, 95.0], fx3)
check("_run_job sửa đơn vị NGAY sau tách (cả lượt tách lại), trước collapsed_count",
      open(os.path.join(os.path.dirname(__file__), "..", "tubecli", "core", "public_reup.py"), encoding="utf-8").read()
      .count("fix_timescale(await _extract(") == 2)

# ── Ghi phụ đề khít ô gốc (neo tâm \an5) ─────────────────────────────────────
boxed = rd.build_ass([{"start": 0, "end": 2, "text": "Vậy thì bây giờ tôi sẽ dẫn mọi người đi tham quan cảnh"}],
                     1024, 576, [0.118, 0.8795, 0.874, 0.962])
check("có ô gốc → neo TÂM chữ vào tâm ô (\\an5\\pos), không ước số dòng",
      r"{\an5\pos(508,530)}Vậy thì" in boxed, boxed.splitlines()[-1])
check("cỡ chữ theo chiều cao ô (48px*0.4 kẹp ≥5.2% cạnh ngắn → 30)", ",Arial,30," in boxed)

# ── Che phụ đề gốc + logo (reup_cover) ───────────────────────────────────────
from tubecli.core import reup_cover as rc  # noqa: E402

subs_, logos_ = rc.parse_detection('```json {"subtitles":[{"text":"字幕","box":[120,860,880,950]}],'
                                   '"overlays":[{"kind":"logo","text":"柚","box":[0.02,0.03,0.06,0.1]}]} ```')
check("đọc được cả phụ đề lẫn logo; thang 0..1000 quy về 0..1",
      subs_[0]["box"] == [0.12, 0.86, 0.88, 0.95] and logos_[0]["kind"] == "logo")
check("mảng trần (kiểu cũ) = toàn phụ đề; rác → rỗng",
      len(rc.parse_detection('[{"box":[0.1,0.8,0.9,0.9]}]')[0]) == 1 and rc.parse_detection("xin lỗi") == ([], []))
agg = rc.aggregate([[0.3, 0.85, 0.7, 0.9], [0.25, 0.86, 0.72, 0.91]])
check("gộp ô: dải tối thiểu 72 % bề ngang, căn quanh tâm", round(agg[2] - agg[0], 2) == 0.72, agg)
check("delogo đúng ô, chừa mép ≥1px",
      rc.cover_graph([0.0, 0.84, 1.0, 0.93], 576, 768, "delogo") == "[0:v]delogo=x=1:y=644:w=574:h=70[vc]",
      rc.cover_graph([0.0, 0.84, 1.0, 0.93], 576, 768, "delogo"))
blur = rc.cover_graph([0.14, 0.84, 0.86, 0.93], 576, 768, "blur", inp="vlogo", out="vcov")
check("blur/pixel/fill: nhoè mép qua mặt nạ gblur, đọc đúng luồng vào/ra",
      blur.startswith("[vlogo]split") and "alphamerge" in blur and blur.endswith("[vcov]"))
corner = rc.filter_by_size([{"box": [0.058, 0.03, 0.312, 0.094]}, {"box": [0.688, 0.03, 0.982, 0.094]},
                            {"box": [0.35, 0.02, 0.6, 0.08]}, {"box": [0.8, 0.85, 0.97, 0.95]},
                            {"box": [0.0, 0.4, 0.1, 0.5]}, {"box": [0.0, 0.0, 0.5, 0.3]}])
check("logo CHỈ ở hai góc trên (user 28/9) — giữa trên, đáy, cạnh bên, ô to đều bỏ",
      [c["box"][0] for c in corner] == [0.058, 0.688], corner)
clus = rc.cluster_overlays([[{"box": [0.02, 0.03, 0.3, 0.08], "text": "LAB"}], [], [],
                            [{"box": [0.03, 0.03, 0.31, 0.09], "text": ""}], [], []], 6)
check("cửa bền: thấy 2/6 khung < 60 % → loại; need=1 thì giữ để cửa tĩnh chặt quyết",
      clus == [] and len(rc.cluster_overlays([[{"box": [0.02, 0.03, 0.3, 0.08]}]] + [[]] * 5, 6, need=1)) == 1)
pad = rc.pad_logo([0.07, 0.0445, 0.3, 0.0801])
check("nới ô logo (vision trả khít nét chữ)", pad[0] < 0.07 and pad[1] < 0.0445 and pad[3] > 0.0801, pad)

# ── Giọng / ảnh mặc định của agent ───────────────────────────────────────────
from tubecli.core import agent_media as am  # noqa: E402
from tubecli.core.agent import Agent  # noqa: E402

ag = Agent(name="t", tts_engine="CapCut", tts_voice="vi_female_huong", image_provider="9router",
           image_model="ag/gemini-3.1-flash-image")
check("agent giữ giọng + bộ vẽ mặc định (engine chữ hoa vẫn nhận)",
      am.agent_voice(ag) == ("capcut", "vi_female_huong") and am.agent_image(ag) == ("9router", "ag/gemini-3.1-flash-image"))
bad = Agent(name="x", tts_engine="banana", tts_voice="../etc", image_provider="evil", image_model="a b")
check("giá trị lạ → rỗng (= tự động), không làm agent hỏng",
      (bad.tts_engine, bad.tts_voice, bad.image_provider, bad.image_model) == ("", "", "", ""))
check("to_dict có đủ 4 trường", all(k in ag.to_dict() for k in am.MEDIA_FIELDS))
check("đoán tiếng của giọng", [am.voice_lang("capcut", v) for v in
                               ("vi_female_huong", "BV075_streaming", "en_us_002", "ICL_jp_female_tt_you")]
      == ["vi", "vi", "en", "ja"] and am.voice_lang("edge", "zh-CN-XiaoxiaoNeural") == "zh")
check("đoán tiếng phụ đề", [am.guess_lang([t]) for t in ("今天我们聊人工智能", "Xin chào các bạn", "こんにちは元気です", "hello")]
      == ["zh", "vi", "ja", "en"])

import types  # noqa: E402

am_real = am._agent
am._agent = lambda x: ag if x == "A" else (types.SimpleNamespace(tts_engine="edge", tts_voice="en-US-GuyNeural")
                                           if x == "E" else None)
try:
    check("người xem chọn giọng Edge → đúng giọng đó",
          pr.pick_voice({"voice": "en-US-GuyNeural", "lang": "en", "_agent_id": "A"}, []) ==
          ("edge", "en-US-GuyNeural", "en-US-JennyNeural"))
    check("không chọn → giọng MẶC ĐỊNH CapCut của agent",
          pr.pick_voice({"voice": "", "lang": "vi", "_agent_id": "A"}, []) == ("capcut", "vi_female_huong", "vi-VN-HoaiMyNeural"))
    check("giọng mặc định khác tiếng phụ đề (vi ↔ en) → Edge đúng tiếng",
          pr.pick_voice({"voice": "", "lang": "en", "_agent_id": "A"}, []) == ("edge", "en-US-JennyNeural", "en-US-JennyNeural"))
    check("agent đặt Edge → dùng giọng Edge đó",
          pr.pick_voice({"voice": "", "lang": "en", "_agent_id": "E"}, [])[:2] == ("edge", "en-US-GuyNeural"))
    check("agent chưa đặt + giữ tiếng gốc → Edge theo tiếng đoán từ phụ đề",
          pr.pick_voice({"voice": "", "lang": "", "_agent_id": "Z"}, ["我们今天聊聊人工智能的发展"])[:2]
          == ("edge", "zh-CN-XiaoxiaoNeural"))
    check("phụ đề THẬT còn tiếng Trung (dịch hỏng) → giọng theo tiếng thật, không để giọng Việt câm",
          pr.pick_voice({"voice": "", "lang": "vi", "_agent_id": "A"}, ["如果把三國做成一副會動的連環畫會是什麼樣子"])[:2]
          == ("edge", "zh-CN-XiaoxiaoNeural"))
finally:
    am._agent = am_real

check("đếm câu sai tiếng đích (dịch một bước bị Gemini bỏ qua)",
      pr.untranslated([{"text": "大家好，我是柚子Lab。"}, {"text": "Chào mọi người, tôi là Yuzu Lab."},
                       {"text": "123"}], "vi") == [0])
check("tên ngôn ngữ đầy đủ gửi cho bộ dịch", pr.LANG_NAMES["vi"] == "Vietnamese")


# ── Đọc theo ĐOẠN, không ngắt theo dòng (user 19/10/2026) ─────────────────────
vi_lines = [{"start": 0.0, "end": 2.0, "text": "Hôm nay chúng ta nói về trí tuệ nhân tạo,"},
            {"start": 2.0, "end": 4.0, "text": "và ảnh hưởng của nó tới đời sống."},
            {"start": 4.0, "end": 5.5, "text": "Trước hết là việc làm."},
            {"start": 7.0, "end": 9.0, "text": "Sau khe nghỉ dài là câu mới."}]
g = rd.group_for_tts(vi_lines)
check("dòng kề nhau gộp thành một đoạn đọc liền; khe > 0.7 s mới tách",
      len(g) == 2 and g[0]["members"] == [0, 1, 2] and g[0]["start"] == 0.0 and g[0]["end"] == 5.5
      and g[0]["text"] == "Hôm nay chúng ta nói về trí tuệ nhân tạo, và ảnh hưởng của nó tới đời sống. Trước hết là việc làm."
      and g[1]["members"] == [3], g)
cjk = rd.group_for_tts([{"start": 0, "end": 1, "text": "今天我们聊"}, {"start": 1, "end": 2, "text": "人工智能"}])
check("CJK nối liền không chèn dấu cách", cjk[0]["text"] == "今天我们聊人工智能")
long = [{"start": i * 2.0, "end": i * 2.0 + 2.0, "text": "x" * 60} for i in range(8)]
gl = rd.group_for_tts(long)
check("trần 220 ký tự / 12 s mỗi đoạn", all(len(x["text"]) <= 220 and x["end"] - x["start"] <= 12.0 for x in gl) and len(gl) >= 3, [len(x["text"]) for x in gl])
pieces = rd.split_long_subtitles([{"start": 7.6, "end": 16.7, "text": long_vi}])
back = rd.group_for_tts(pieces)
check("dòng bị cắt ≤56 ký tự cho khung hình → gộp lại nguyên câu để đọc",
      len(back) == 1 and back[0]["text"] == long_vi and back[0]["start"] == 7.6 and back[0]["end"] == 16.7, back)
check("dub_video đọc theo units (group_for_tts), .srt / ghi hình vẫn theo dòng",
      "units = group_for_tts(subs)" in open(os.path.join(os.path.dirname(__file__), "..", "tubecli", "core", "reup_dub.py"), encoding="utf-8").read())

# ── Dò phụ đề theo PIXEL + che theo ĐOẠN (user 19/10/2026) ─────────────────────
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

check("mồi Gemini: chỉ ô ở nửa dưới, gần giữa, không quá cao",
      [b["box"][1] for b in rc.subtitle_prior([
          {"box": [0.3, 0.86, 0.7, 0.92]},      # phụ đề thật
          {"box": [0.2, 0.05, 0.8, 0.12]},      # tiêu đề đầu khung
          {"box": [0.02, 0.9, 0.2, 0.95]},      # nhãn góc trái
          {"box": [0.1, 0.5, 0.9, 0.95]},       # ô cao bất thường
      ])] == [0.86])


def synth(text="Xin chào các bạn", blade=False, left_label=False, bg=120, W=960, H=150):
    """Dải đáy giả: nền xám, chữ trắng viền đen căn giữa (như phụ đề cháy), tuỳ chọn vạch
    sáng mảnh của cảnh cùng hàng (lưỡi kiếm) và nhãn nhỏ góc trái."""
    im = Image.new("RGB", (W, H), (bg, bg, bg))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default(size=28)
    tb = None
    if text:
        x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font, stroke_width=2)
        tx, ty = (W - (x1 - x0)) // 2 - x0, 80 - y0
        d.text((tx, ty), text, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        tb = (tx + x0, ty + y0, tx + x1, ty + y1)
    if blade:
        d.rectangle([100, 86, 440, 94], fill=(20, 20, 20))
        d.line([(100, 90), (440, 90)], fill=(250, 250, 250), width=2)
    if left_label:
        d.text((20, 112), "AI remix", font=font, fill=(230, 230, 230), stroke_width=1, stroke_fill=(0, 0, 0))
    return np.asarray(im), tb


rgb, tb = synth()
box = rc.frame_text_box(rc.text_mask(rgb))
check("ô khít quanh chữ trắng viền đen căn giữa (sai ≤ 8 px mỗi cạnh)",
      box is not None and all(abs(a - b) <= 8 for a, b in zip(box, tb)), (box, tb))
rgb_b, tb_b = synth(blade=True)
box_b = rc.frame_text_box(rc.text_mask(rgb_b))
check("vạch sáng mảnh của cảnh cùng hàng không kéo ô sang trái (cột mạnh ≥3 nét)",
      box_b is not None and box_b[0] >= tb_b[0] - 40 and abs(box_b[2] - tb_b[2]) <= 8, (box_b, tb_b))
check("chỉ có vạch cảnh → không coi là phụ đề", rc.frame_text_box(rc.text_mask(synth(text="", blade=True)[0])) is None)
check("nhãn nhỏ góc trái (lệch tâm) → không coi là phụ đề",
      rc.frame_text_box(rc.text_mask(synth(text="", left_label=True)[0])) is None)
rgb_l, tb_l = synth(left_label=True)
box_l = rc.frame_text_box(rc.text_mask(rgb_l))
check("có cả nhãn góc lẫn phụ đề → chỉ lấy phụ đề, nhãn góc để nguyên",
      box_l is not None and box_l[0] >= tb_l[0] - 8 and box_l[1] >= tb_l[1] - 4, (box_l, tb_l))
check("nền phẳng không chữ → None", rc.frame_text_box(rc.text_mask(synth(text="")[0])) is None)
cands = rc.frame_text_candidates(rc.text_mask(rgb_l))
check("ứng viên bị loại nói rõ lý do", any("lệch tâm" in c["why"] for c in cands) and any(not c["why"] for c in cands), cands)

b1 = [0.45, 0.84, 0.55, 0.90]
b2 = [0.33, 0.84, 0.67, 0.90]
segs = rc.build_segments([None, b1, b1, None, b1, b1, b1, None, None, None, b2, b2], fps=8, dur=1.6)
check("đoạn: lấp khe 1 khung, bỏ vệt lẻ, nới mốc ±(½ khung + 0.1 s)",
      len(segs) == 2 and segs[0]["start"] == 0.0 and segs[0]["end"] == 1.04 and segs[1]["start"] == 1.09
      and segs[1]["end"] == 1.6, segs)
check("ô đoạn nới PAD, trị số là float thường (không numpy)",
      segs[0]["box"][0] == round(0.45 - rc.PAD_X, 4) and all(type(v) is float for v in segs[0]["box"]), segs[0])
check("khe 2 khung giữa hai ô chồng nhau cũng được lấp",
      len(rc.build_segments([b1, b1, None, None, b1, b1], fps=8, dur=1.0)) == 1)
check("khe 2 khung giữa hai ô KHÁC chỗ thì tách đoạn",
      len(rc.build_segments([b1, b1, None, None, [0.1, 0.1, 0.2, 0.2], [0.1, 0.1, 0.2, 0.2]], fps=8, dur=1.0)) == 2)
g = rc.segments_graph(segs, 1920, 1080, "delogo")
check("delogo theo đoạn: hai ô khác nhau → hai filter, mỗi cái enable đúng khoảng",
      g.count("delogo=") == 2 and "enable='between(t,0.00,1.04)'" in g and "enable='between(t,1.09,1.60)'" in g, g)
g2 = rc.segments_graph([{"start": 0, "end": 1, "box": b1}, {"start": 2, "end": 3, "box": [0.451, 0.84, 0.551, 0.90]}], 1920, 1080, "delogo")
check("hai đoạn cùng ô (IoU ≥ 0.8) gộp một filter với tổng các khoảng",
      g2.count("delogo=") == 1 and "between(t,0.00,1.00)+between(t,2.00,3.00)" in g2, g2)
g3 = rc.segments_graph(segs, 1920, 1080, "blur", inp="vlogo", out="vcov")
check("blur/pixel/fill theo đoạn: che ô HỢP, enable gắn vào overlay",
      g3.startswith("[vlogo]split") and "overlay=" in g3 and ":enable='between(t,0.00,1.04)+between(t,1.09,1.60)'[vcov]" in g3, g3)
check("ô neo chữ mới = trung vị các ô đoạn", rc.place_box(segs) == [round((segs[0]["box"][i] + segs[1]["box"][i]) / 2, 4) for i in range(4)])
check("cover_graph vẫn như cũ khi không có enable (tương thích)",
      rc.cover_graph([0.0, 0.84, 1.0, 0.93], 576, 768, "delogo") == "[0:v]delogo=x=1:y=644:w=574:h=70[vc]")
check("render_only / dub_video nhận cover_segments; chế độ 'none' không lồng tiếng",
      "cover_segments" in rd.render_only.__code__.co_varnames and "cover_segments" in rd.dub_video.__code__.co_varnames
      and "render_only(" in open(os.path.join(os.path.dirname(__file__), "..", "tubecli", "core", "public_reup.py"), encoding="utf-8").read())

print(f"\n{passed} pass, {failed} fail")
sys.exit(1 if failed else 0)
