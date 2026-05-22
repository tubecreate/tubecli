import json
import os

path = r"c:\tubecreate-vue\tubecli\data\edu_video_studio\projects\4e93bff6\lessons\lesson_b7f544\lesson_script.json"

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Step 1: Fix provider icons and center brain
step1_code = data["steps"][0]["elements"][1]["code"]
step1_old_icon = """  ctx.font = '24px ' + T.font;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(prov.icon, targetX, targetY - 2);"""
step1_new_icon = """  ctx.font = '24px ' + T.font;
  ctx.fillStyle = rc(prov.color);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(prov.icon, targetX, targetY - 2);"""
step1_code = step1_code.replace(step1_old_icon, step1_new_icon)

step1_old_brain = """const brainPulse = 1 + 0.08 * Math.sin(time * 2);
ctx.font = `${Math.round(36 * brainPulse)}px ${T.font}`;
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText('🧠', cx, cy - 2);"""
step1_new_brain = """const brainPulse = 1 + 0.08 * Math.sin(time * 2);
ctx.font = `${Math.round(36 * brainPulse)}px ${T.font}`;
ctx.fillStyle = rc('cyan');
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText('🧠', cx, cy - 2);"""
step1_code = step1_code.replace(step1_old_brain, step1_new_brain)
data["steps"][0]["elements"][1]["code"] = step1_code

# Step 2: Fix pipeline block icons
step2_code = data["steps"][1]["elements"][1]["code"]
step2_old = """  const iconScale = active && !completed ? 1 + 0.1 * Math.sin(time * 3) : 1;
  ctx.font = `${Math.round(28 * iconScale)}px ${T.font}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(block.icon, bx + blockW / 2, blockY + 30);"""
step2_new = """  const iconScale = active && !completed ? 1 + 0.1 * Math.sin(time * 3) : 1;
  ctx.font = `${Math.round(28 * iconScale)}px ${T.font}`;
  ctx.fillStyle = active ? rc(block.color) : rc('muted');
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(block.icon, bx + blockW / 2, blockY + 30);"""
step2_code = step2_code.replace(step2_old, step2_new)
data["steps"][1]["elements"][1]["code"] = step2_code

# Step 3: Fix cloud/lock server icon and key icon
step3_code = data["steps"][2]["elements"][1]["code"]
step3_old_srv = """ctx.font = '36px ' + T.font;
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText(connected ? "☁️" : "🔒", srvX + srvW / 2, srvY + srvH / 2 - 10);"""
step3_new_srv = """ctx.font = '36px ' + T.font;
ctx.fillStyle = connected ? rc('green') : rc('muted');
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText(connected ? "☁️" : "🔒", srvX + srvW / 2, srvY + srvH / 2 - 10);"""
step3_code = step3_code.replace(step3_old_srv, step3_new_srv)

step3_old_key = """ctx.font = '34px ' + T.font;
ctx.fillText("🔑", 0, 0);"""
step3_new_key = """ctx.font = '34px ' + T.font;
ctx.fillStyle = connected ? rc('green') : rc('yellow');
ctx.fillText("🔑", 0, 0);"""
step3_code = step3_code.replace(step3_old_key, step3_new_key)
data["steps"][2]["elements"][1]["code"] = step3_code

# Step 5: Fix local runner floppy disk icon
step5_code = data["steps"][4]["elements"][1]["code"]
step5_old = """ctx.font = '40px ' + T.font;
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText("💾", pcX + pcW / 2, pcY + pcH / 2 - 10);"""
step5_new = """ctx.font = '40px ' + T.font;
ctx.fillStyle = rc('green');
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText("💾", pcX + pcW / 2, pcY + pcH / 2 - 10);"""
step5_code = step5_code.replace(step5_old, step5_new)
data["steps"][4]["elements"][1]["code"] = step5_code

# Step 7: Fix advanced configuration system stack icons
step7_code = data["steps"][6]["elements"][1]["code"]
step7_old = """  const iconPulse = active ? 1 + 0.1 * Math.sin(time * 3 + idx) : 1;
  ctx.font = `${Math.round(28 * iconPulse)}px ${T.font}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(mod.icon, mx + moduleW / 2, moduleY + 36);"""
step7_new = """  const iconPulse = active ? 1 + 0.1 * Math.sin(time * 3 + idx) : 1;
  ctx.font = `${Math.round(28 * iconPulse)}px ${T.font}`;
  ctx.fillStyle = active ? rc(mod.color) : rc('muted');
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(mod.icon, mx + moduleW / 2, moduleY + 36);"""
step7_code = step7_code.replace(step7_old, step7_new)
data["steps"][6]["elements"][1]["code"] = step7_code

# Step 9: Fix final telegram/zalo/discord icons and robot brain
step9_code = data["steps"][8]["elements"][1]["code"]
step9_old_ch = """  ctx.font = '24px ' + T.font;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(ch.icon, targetX, targetY - 2);"""
step9_new_ch = """  ctx.font = '24px ' + T.font;
  ctx.fillStyle = rc(ch.color);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(ch.icon, targetX, targetY - 2);"""
step9_code = step9_code.replace(step9_old_ch, step9_new_ch)

step9_old_bot = """const pulse = 1 + 0.07 * Math.sin(time * 2.2);
ctx.font = `${Math.round(32 * pulse)}px ${T.font}`;
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText("🤖", cx, cy - 2);"""
step9_new_bot = """const pulse = 1 + 0.07 * Math.sin(time * 2.2);
ctx.font = `${Math.round(32 * pulse)}px ${T.font}`;
ctx.fillStyle = rc('green');
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillText("🤖", cx, cy - 2);"""
step9_code = step9_code.replace(step9_old_bot, step9_new_bot)
data["steps"][8]["elements"][1]["code"] = step9_code

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Successfully injected explicit fillStyles to all emojis in lesson_script.json!")
