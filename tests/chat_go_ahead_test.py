# Tests: bare go-ahead detection and re-fire of the previous registry intent.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tubecli.extensions.chat import pipeline as CP
from tubecli.core import intent_router as R

# 1. go-ahead detection
yes = ["bạn làm đi", "làm đi", "ok", "OK làm luôn", "cứ làm đi", "đồng ý", "go ahead", "Do it!", "yes", "làm luôn nhé", "thực hiện đi", "được"]
no = ["làm video từ những gì đã đọc hôm nay", "ok nhưng đổi sang tiếng Anh", "làm cái khác", "không", "tải video https://x.y", "ok, rút gọn còn 30 giây"]
for m in yes:
    assert CP._is_go_ahead(m), f"should be go-ahead: {m!r}"
for m in no:
    assert not CP._is_go_ahead(m), f"must NOT be go-ahead: {m!r}"
print(f"1 go-ahead   : {len(yes)} yes / {len(no)} no — all correct")

# 2. re-fire the previous registry intent
agent = {"id": "a1"}
hist = [
    {"role": "user", "content": "làm video từ những gì đã đọc hôm nay"},
    {"role": "assistant", "content": "Đây là kịch bản… Bạn muốn hướng nào? 1. … 2. …"},
]
it = CP._go_ahead_intent("bạn làm đi", hist, agent, [])
assert it is not None and it.intent_type == "content_video", it
assert R.defer_to_model(it) is it, "re-fired intent must survive the desk"
print("2 re-fire    : 'bạn làm đi' after 'làm video từ…' → content_video (survives desk)")

# 3. no re-fire when the previous message is not a registry command / is itself a go-ahead / empty
assert CP._go_ahead_intent("ok", [{"role": "user", "content": "kể chuyện cười đi"}], agent, []) is None
assert CP._go_ahead_intent("ok", [{"role": "user", "content": "ok"}, {"role": "user", "content": "làm đi"}], agent, []) is None
assert CP._go_ahead_intent("làm đi", [], agent, []) is None
assert CP._go_ahead_intent("làm video từ những gì đã đọc hôm nay", hist, agent, []) is None, "a real command is not a go-ahead"
print("3 no re-fire : chit-chat / go-ahead chains / empty history / real command → None")

# 4. history that already contains the current message (defensive) still finds the real previous command
hist2 = hist + [{"role": "user", "content": "bạn làm đi"}]
it = CP._go_ahead_intent("bạn làm đi", hist2, agent, [])
assert it is not None and it.intent_type == "content_video"
print("4 history    : current message present in history is skipped")

# 5. prompt rule present
from tubecli.core import brain as B
import inspect
assert "bare go-ahead" in inspect.getsource(B), "rule 9 missing from system prompt"
print("5 prompt     : rule 9 (go-ahead => act, never re-ask) present")
print()
print("ALL 5 GROUPS PASSED")
