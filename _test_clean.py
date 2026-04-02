"""Quick test for _clean_json_from_text"""
from tubecli.core.brain import AgentBrain

# Test 1: Bare nested JSON (the exact pattern from user's screenshot)
t1 = '{"tool": "finishWorkflow", "params": {"finalAnswer": "Ket qua tim kiem ok"}}'
r1 = AgentBrain._clean_json_from_text(t1)
print(f"Test1: {r1}")
assert r1 == "Ket qua tim kiem ok", f"FAILED: got {r1}"

# Test 2: Code block JSON
t2 = '```json\n{"tool": "finishWorkflow", "params": {"finalAnswer": "Hello World"}}\n```'
r2 = AgentBrain._clean_json_from_text(t2)
print(f"Test2: {r2}")
assert r2 == "Hello World", f"FAILED: got {r2}"

# Test 3: Normal text (should pass through)
t3 = "Normal text response"
r3 = AgentBrain._clean_json_from_text(t3)
print(f"Test3: {r3}")
assert r3 == t3, f"FAILED: got {r3}"

# Test 4: Telegram listener clean
from tubecli.core.telegram_listener import TelegramListener
tl = TelegramListener()
r4 = tl._clean_reply_text(t1)
print(f"Test4: {r4}")
assert r4 == "Ket qua tim kiem ok", f"FAILED: got {r4}"

print("\n✅ All tests passed!")
