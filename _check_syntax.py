import ast
import sys

files = [
    "c:/tubecreate-vue/tubecli/tubecli/core/intent_router.py",
    "c:/tubecreate-vue/tubecli/tubecli/core/skill_selector.py",
    "c:/tubecreate-vue/tubecli/tubecli/core/telegram_actions.py",
    "c:/tubecreate-vue/tubecli/tubecli/core/telegram_listener.py",
    "c:/tubecreate-vue/tubecli/tubecli/core/brain.py",
    "c:/tubecreate-vue/tubecli/tubecli/core/agent.py",
    "c:/tubecreate-vue/tubecli/tubecli/core/specialists.py",
    "c:/tubecreate-vue/tubecli/tubecli/core/fork_agent.py",
    "c:/tubecreate-vue/tubecli/tubecli/cli/init_cmd.py",
]

errors = []
for f in files:
    try:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())
        print(f"OK: {f.split('/')[-1]}")
    except SyntaxError as e:
        print(f"FAIL: {f.split('/')[-1]} -> {e}")
        errors.append(f)

if errors:
    print(f"\n{len(errors)} file(s) have syntax errors!")
    sys.exit(1)
else:
    print(f"\nAll {len(files)} files parse OK!")
