"""Kiểm chứng audio TTS trả về: đúng ngôn ngữ chưa, đọc đúng nội dung chưa.

Dùng faster-whisper để tự phát hiện ngôn ngữ (KHÔNG ép language) rồi so
bản chép lại với văn bản đầu vào. Ép ngôn ngữ sẽ làm mất chính giá trị
của phép kiểm tra này.
"""
import json
import re
import sys
import unicodedata

sys.path.insert(0, r"C:\ReupDouyin")

from faster_whisper import WhisperModel

MODEL_SIZE = "medium"


def normalize(text: str) -> str:
    """Bỏ dấu câu, gộp khoảng trắng, thường hoá — để so khớp từ."""
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\sàáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềể"
                  r"ễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Tiếng Nhật Trung Thái không tách từ bằng khoảng trắng
# So theo từ sẽ luôn ra 0% nên phải chuyển sang so theo cụm ký tự
NO_SPACE_LANGS = {"ja", "zh", "th", "yue", "lo", "my", "km"}


def char_bigrams(text: str) -> set:
    t = re.sub(r"\s+", "", normalize(text))
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def word_overlap(expected: str, actual: str, lang: str = "") -> float:
    """Độ khớp nội dung.

    Ngôn ngữ có khoảng trắng: tỉ lệ từ gốc xuất hiện lại.
    Ngôn ngữ không khoảng trắng: tỉ lệ cụm 2 ký tự trùng nhau.
    """
    if lang in NO_SPACE_LANGS:
        exp, act = char_bigrams(expected), char_bigrams(actual)
        return len(exp & act) / len(exp) if exp else 0.0

    exp = normalize(expected).split()
    act = set(normalize(actual).split())
    if not exp:
        return 0.0
    return sum(1 for w in exp if w in act) / len(exp)


def main() -> None:
    cases = json.load(open(sys.argv[1], encoding="utf-8"))
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")

    print(f"model=faster-whisper/{MODEL_SIZE} cpu/int8  "
          f"(ngôn ngữ để TỰ PHÁT HIỆN, không ép)\n")

    results = []
    for case in cases:
        segments, info = model.transcribe(case["file"], language=None,
                                          vad_filter=True, beam_size=5)
        text = " ".join((s.text or "").strip() for s in segments).strip()

        overlap = word_overlap(case["text"], text, case["expect_lang"])
        lang_ok = info.language == case["expect_lang"]
        content_ok = overlap >= 0.6
        results.append({
            "name": case["name"],
            "engine": case.get("engine", "?"),
            "lang": info.language,
            "lang_prob": round(info.language_probability, 3),
            "lang_ok": lang_ok,
            "overlap": round(overlap, 3),
            "content_ok": content_ok,
            "transcript": text,
        })

        verdict = "PASS" if (lang_ok and content_ok) else "FAIL"
        print(f"[{verdict}] {case['name']}  ({case.get('engine','?')})")
        print(f"    ngôn ngữ phát hiện : {info.language} "
              f"(p={info.language_probability:.3f}) — mong đợi {case['expect_lang']}")
        print(f"    khớp từ            : {overlap:.1%}")
        print(f"    chép lại           : {text[:150]}")
        print()

    print("=" * 70)
    passed = sum(1 for r in results if r["lang_ok"] and r["content_ok"])
    print(f"KẾT QUẢ: {passed}/{len(results)} giọng đạt "
          f"(đúng ngôn ngữ VÀ khớp nội dung >= 60%)")
    json.dump(results, open(sys.argv[2], "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
