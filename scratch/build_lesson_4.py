import json
import os

lesson_script = {
  "title": "Bài 4: Kết nối kênh giao tiếp cho AI",
  "subject": "other",
  "total_steps": 12,
  "steps": [
    {
      "id": 1,
      "voice_text": "Bài bốn: Kết nối kênh giao tiếp, cánh tay nối dài của người quản gia. Ở các bài trước, chúng ta đã xây dựng xong ngôi nhà là Gateway và lắp đặt bộ não là AI LLM.",
      "clear": False,
      "elements": [
        {
          "type": "icon",
          "emoji": "📡",
          "size": 64
        },
        {
          "type": "text",
          "text": "Bài 4: Kết nối kênh giao tiếp",
          "fontSize": 52,
          "color": "title",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\nconst r = 60;\n\nctx.strokeStyle = 'rgba(34, 211, 238, 0.05)';\nctx.lineWidth = 1.5;\nfor (let i = 0; i < 8; i++) {\n  const angle = (i * Math.PI) / 4;\n  ctx.beginPath();\n  ctx.moveTo(cx + Math.cos(angle) * (r + 15), cy + Math.sin(angle) * (r + 15));\n  ctx.lineTo(cx + Math.cos(angle) * (r + 120), cy + Math.sin(angle) * (r + 120));\n  ctx.stroke();\n}\n\nconst waveCount = 3;\nfor (let i = 0; i < waveCount; i++) {\n  const waveProg = ((time * 0.15 + i / waveCount) % 1.0);\n  const waveR = r + waveProg * 100;\n  ctx.strokeStyle = `rgba(34, 211, 238, ${0.3 * (1 - waveProg)})`;\n  ctx.lineWidth = 2.5;\n  ctx.beginPath();\n  ctx.arc(cx, cy, waveR, 0, Math.PI * 2);\n  ctx.stroke();\n}\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('cyan');\nctx.lineWidth = 3;\nctx.beginPath();\nctx.roundRect(cx - 35, cy - 35, 70, 70, 18);\nctx.fill();\nctx.stroke();\n\nctx.font = '36px ' + T.font;\nctx.fillStyle = rc('cyan');\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText('📡', cx, cy - 2);\n\nconst channels = [\n  { icon: '💬', a: time * 0.4 },\n  { icon: '✈️', a: time * 0.4 + (2*Math.PI)/3 },\n  { icon: '👾', a: time * 0.4 + (4*Math.PI)/3 }\n];\nchannels.forEach(ch => {\n  const tx = cx + Math.cos(ch.a) * 110;\n  const ty = cy + Math.sin(ch.a) * 110;\n  \n  ctx.fillStyle = 'rgba(15, 23, 42, 0.95)';\n  ctx.strokeStyle = rc('highlight');\n  ctx.lineWidth = 2;\n  ctx.beginPath();\n  ctx.roundRect(tx - 22, ty - 22, 44, 44, 10);\n  ctx.fill();\n  ctx.stroke();\n  \n  ctx.font = '22px ' + T.font;\n  ctx.fillStyle = rc('highlight');\n  ctx.fillText(ch.icon, tx, ty - 2);\n});\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 2,
      "voice_text": "Tuy nhiên, nếu không có các kênh giao tiếp, bạn sẽ phải luôn ngồi trước máy tính để trò chuyện với AI. Bài bốn sẽ giúp bạn kết nối bộ não đó vào các ứng dụng quen thuộc như Zalo, Telegram, WhatsApp hay Discord.",
      "clear": True,
      "elements": [
        {
          "type": "text",
          "text": "Kết nối Đa Kênh Tiện lợi",
          "fontSize": 48,
          "color": "title",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\n\nconst phoneX = cx - 180;\nconst phoneY = cy;\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('cyan');\nctx.lineWidth = 2.5;\nctx.beginPath();\nctx.roundRect(phoneX - 45, phoneY - 80, 90, 160, 16);\nctx.fill();\nctx.stroke();\n\nctx.fillStyle = 'rgba(34, 211, 238, 0.05)';\nctx.beginPath();\nctx.roundRect(phoneX - 38, phoneY - 70, 76, 140, 10);\nctx.fill();\n\nctx.font = '32px ' + T.font;\nctx.fillStyle = rc('cyan');\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText('📱', phoneX, phoneY - 10);\n\nctx.font = 'bold 11px monospace';\nctx.fillStyle = rc('text');\nctx.fillText('CHAT APP', phoneX, phoneY + 35);\n\nconst hubX = cx + 180;\nconst hubY = cy;\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('green');\nctx.lineWidth = 2.5;\nctx.beginPath();\nctx.roundRect(hubX - 55, hubY - 65, 110, 130, 18);\nctx.fill();\nctx.stroke();\n\nconst brainPulse = 1 + 0.06 * Math.sin(time * 2.5);\nctx.font = `${Math.round(40 * brainPulse)}px ${T.font}`;\nctx.fillStyle = rc('green');\nctx.fillText('🧠', hubX, hubY - 15);\n\nctx.font = 'bold 12px monospace';\nctx.fillStyle = rc('green');\nctx.fillText('AI HUB', hubX, hubY + 30);\n\nctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';\nctx.lineWidth = 4;\nctx.beginPath();\nctx.moveTo(phoneX + 45, cy);\nctx.lineTo(hubX - 55, cy);\nctx.stroke();\n\nconst packetCount = 2;\nfor (let i = 0; i < packetCount; i++) {\n  const pProg = (time * 0.28 + i / packetCount) % 1.0;\n  const px = (phoneX + 45) + (hubX - 55 - (phoneX + 45)) * pProg;\n  ctx.fillStyle = rc('cyan');\n  ctx.shadowColor = rc('cyan');\n  ctx.shadowBlur = 8;\n  ctx.beginPath();\n  ctx.arc(px, cy, 5, 0, Math.PI * 2);\n  ctx.fill();\n  ctx.shadowBlur = 0;\n}\n\nconst apps = [\n  { icon: '💬', a: time * 0.35 },\n  { icon: '✈️', a: time * 0.35 + Math.PI / 2 },\n  { icon: '📞', a: time * 0.35 + Math.PI },\n  { icon: '👾', a: time * 0.35 + (3 * Math.PI) / 2 }\n];\napps.forEach(app => {\n  const ax = phoneX + Math.cos(app.a) * 75;\n  const ay = phoneY + Math.sin(app.a) * 75;\n  \n  ctx.fillStyle = 'rgba(15, 23, 42, 0.95)';\n  ctx.strokeStyle = rc('highlight');\n  ctx.lineWidth = 1.5;\n  ctx.beginPath();\n  ctx.roundRect(ax - 18, ay - 18, 36, 36, 8);\n  ctx.fill();\n  ctx.stroke();\n  \n  ctx.font = '18px ' + T.font;\n  ctx.fillStyle = rc('highlight');\n  ctx.fillText(app.icon, ax, ay - 2);\n});\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 3,
      "voice_text": "Hãy tưởng tượng Gateway là bác quản gia đang ngồi trong nhà. Để bạn có thể ra lệnh cho bác ấy khi đang ở ngoài đường, bạn cần lắp đặt các đường dây điện thoại.",
      "clear": False,
      "elements": [
        {
          "type": "box",
          "style": "subtle"
        },
        {
          "type": "text",
          "text": "Mô hình: Quản gia & Chủ nhân",
          "fontSize": 44,
          "color": "highlight",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\n\nconst deskX = cx - 180;\nconst deskY = cy;\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('highlight');\nctx.lineWidth = 2.5;\nctx.beginPath();\nctx.roundRect(deskX - 60, deskY - 65, 120, 130, 16);\nctx.fill();\nctx.stroke();\n\nctx.font = '40px ' + T.font;\nctx.fillStyle = rc('highlight');\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText('🤖', deskX, deskY - 18);\n\nctx.fillStyle = rc('highlight');\nctx.font = 'bold 13px monospace';\nctx.fillText('BUTLER DESK', deskX, deskY + 30);\n\nconst roadX = cx + 180;\nconst roadY = cy;\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('cyan');\nctx.lineWidth = 2.5;\nctx.beginPath();\nctx.roundRect(roadX - 60, roadY - 65, 120, 130, 16);\nctx.fill();\nctx.stroke();\n\nctx.font = '40px ' + T.font;\nctx.fillStyle = rc('cyan');\nctx.fillText('📱', roadX, roadY - 18);\n\nctx.fillStyle = rc('cyan');\nctx.font = 'bold 13px monospace';\nctx.fillText('USER MOBILE', roadX, roadY + 30);\n\nctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';\nctx.lineWidth = 4;\nctx.beginPath();\nctx.moveTo(deskX + 60, cy);\nctx.lineTo(roadX - 60, cy);\nctx.stroke();\n\nconst sigProg = (time * 0.25) % 1.0;\nconst sx = (roadX - 60) - (roadX - deskX - 120) * sigProg;\nctx.fillStyle = rc('yellow');\nctx.shadowColor = rc('yellow');\nctx.shadowBlur = 10;\nctx.beginPath();\nctx.arc(sx, cy, 6, 0, Math.PI * 2);\nctx.fill();\nctx.shadowBlur = 0;\n\nconst clouds = [\n  { icon: '☁️', a: time * 0.4 },\n  { icon: '📡', a: time * 0.4 + Math.PI }\n];\nclouds.forEach(cl => {\n  const clx = roadX + Math.cos(cl.a) * 85;\n  const cly = roadY + Math.sin(cl.a) * 85;\n  ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\n  ctx.strokeStyle = rc('cyan');\n  ctx.lineWidth = 1.5;\n  ctx.beginPath();\n  ctx.roundRect(clx - 16, cly - 16, 32, 32, 8);\n  ctx.fill();\n  ctx.stroke();\n  \n  ctx.font = '16px ' + T.font;\n  ctx.fillStyle = rc('cyan');\n  ctx.fillText(cl.icon, clx, cly - 2);\n});\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 4,
      "voice_text": "Telegram, Zalo và các ứng dụng khác chính là các nhà mạng khác nhau. Việc cài đặt kênh giao tiếp chính là việc đăng ký một số điện thoại riêng cho AI và nối đường dây đó về thẳng phòng của bác quản gia.",
      "clear": False,
      "elements": [
        {
          "type": "text",
          "text": "Các Cổng Nhà Mạng Ứng Dụng",
          "fontSize": 42,
          "color": "cyan",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\n\nconst hubX = cx;\nconst hubY = cy;\nctx.fillStyle = 'rgba(15, 23, 42, 0.95)';\nctx.strokeStyle = rc('green');\nctx.lineWidth = 3;\nctx.beginPath();\nctx.roundRect(hubX - 50, hubY - 50, 100, 100, 20);\nctx.fill();\nctx.stroke();\n\nctx.font = '40px ' + T.font;\nctx.fillStyle = rc('green');\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText('🤖', hubX, hubY - 2);\n\nconst ops = [\n  { name: 'Telegram', icon: '✈️', a: -Math.PI / 4, color: 'cyan' },\n  { name: 'Zalo', icon: '💬', a: Math.PI / 4, color: 'highlight' },\n  { name: 'WhatsApp', icon: '📞', a: (3 * Math.PI) / 4, color: 'green' },\n  { name: 'Discord', icon: '👾', a: (5 * Math.PI) / 4, color: 'orange' }\n];\n\nops.forEach(op => {\n  const ox = hubX + Math.cos(op.a) * 140;\n  const oy = hubY + Math.sin(op.a) * 140;\n  \n  ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';\n  ctx.lineWidth = 2.5;\n  ctx.beginPath();\n  ctx.moveTo(hubX, hubY);\n  ctx.lineTo(ox, oy);\n  ctx.stroke();\n  \n  const sigProg = (time * 0.3 + op.a) % 1.0;\n  const sx = ox + (hubX - ox) * sigProg;\n  const sy = oy + (hubY - oy) * sigProg;\n  ctx.fillStyle = rc(op.color);\n  ctx.beginPath();\n  ctx.arc(sx, sy, 4.5, 0, Math.PI * 2);\n  ctx.fill();\n  \n  ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\n  ctx.strokeStyle = rc(op.color);\n  ctx.lineWidth = 2;\n  ctx.beginPath();\n  ctx.roundRect(ox - 32, oy - 32, 64, 64, 14);\n  ctx.fill();\n  ctx.stroke();\n  \n  ctx.font = '26px ' + T.font;\n  ctx.fillStyle = rc(op.color);\n  ctx.fillText(op.icon, ox, oy - 2);\n  \n  ctx.fillStyle = rc('text');\n  ctx.font = 'bold 11px monospace';\n  ctx.fillText(op.name, ox, oy + 44);\n});\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 5,
      "voice_text": "Dựa trên lộ trình Track không, hướng dẫn bảo mẫu, và Track C, bộ thích ứng kênh, việc kết nối luôn đi qua ba bước chuẩn. Bước một là lấy giấy thông hành, tức là API Token hoặc tài khoản.",
      "clear": True,
      "elements": [
        {
          "type": "text",
          "text": "Lộ trình 3 Bước Kết Nối",
          "fontSize": 52,
          "color": "title",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\nconst stepW = 160;\nconst stepH = 100;\nconst gap = 30;\n\nconst stages = [\n  { num: '1', title: 'GET TOKEN', icon: '🔑', color: 'cyan', startP: 0.0, endP: 0.33 },\n  { num: '2', title: 'WEB UI', icon: '🖥️', color: 'highlight', startP: 0.33, endP: 0.66 },\n  { num: '3', title: 'ROUTING', icon: '🧭', color: 'green', startP: 0.66, endP: 1.0 }\n];\n\nstages.forEach((st, idx) => {\n  const sx = cx - stepW * 1.5 - gap + idx * (stepW + gap) + stepW/2;\n  const sy = cy;\n  \n  const active = stepProgress >= st.startP;\n  const completed = stepProgress >= st.endP;\n  \n  ctx.fillStyle = active ? 'rgba(15, 23, 42, 0.9)' : 'rgba(15, 23, 42, 0.3)';\n  ctx.strokeStyle = active ? rc(st.color) : 'rgba(255, 255, 255, 0.08)';\n  ctx.lineWidth = active ? 2.5 : 1.5;\n  ctx.beginPath();\n  ctx.roundRect(sx - stepW / 2, sy - stepH / 2, stepW, stepH, 14);\n  ctx.fill();\n  ctx.stroke();\n  \n  ctx.fillStyle = active ? rc(st.color) : rc('muted');\n  ctx.beginPath();\n  ctx.arc(sx - stepW/2 + 20, sy - stepH/2 + 20, 12, 0, Math.PI * 2);\n  ctx.fill();\n  \n  ctx.font = 'bold 11px monospace';\n  ctx.fillStyle = '#0a0a1a';\n  ctx.textAlign = 'center';\n  ctx.textBaseline = 'middle';\n  ctx.fillText(st.num, sx - stepW/2 + 20, sy - stepH/2 + 20);\n  \n  const pulse = active && !completed ? 1 + 0.1 * Math.sin(time * 3) : 1;\n  ctx.font = `${Math.round(30 * pulse)}px ${T.font}`;\n  ctx.fillStyle = active ? rc(st.color) : rc('muted');\n  ctx.fillText(st.icon, sx, sy - 12);\n  \n  ctx.font = 'bold 13px monospace';\n  ctx.fillStyle = active ? rc('text') : rc('muted');\n  ctx.fillText(st.title, sx, sy + 25);\n  \n  if (idx < 2) {\n    const nextX = sx + stepW/2;\n    const endX = nextX + gap;\n    ctx.strokeStyle = active && stepProgress >= stages[idx+1].startP ? rc(st.color) : 'rgba(255, 255, 255, 0.08)';\n    ctx.lineWidth = 3;\n    ctx.beginPath();\n    ctx.moveTo(nextX, sy);\n    ctx.lineTo(endX, sy);\n    ctx.stroke();\n  }\n});\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 6,
      "voice_text": "Mỗi ứng dụng nhắn tin sẽ yêu cầu một loại chìa khóa để cho phép OpenClaw truy cập vào. Telegram: bạn chat với a còng BotFather để tạo một con Bot mới và lấy API Token. Discord: bạn vào cổng Developer của Discord để tạo Application và lấy Bot Token. Zalo và WhatsApp thường yêu cầu quét mã quy rờ hoặc cấu hình qua các bộ thích ứng đặc biệt có sẵn trong OpenClaw.",
      "clear": False,
      "elements": [
        {
          "type": "text",
          "text": "Bước 1: Lấy Chìa Khóa API Token",
          "fontSize": 46,
          "color": "highlight",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\nconst keyY = cy;\n\nctx.save();\nctx.translate(cx, keyY);\nctx.rotate(Math.sin(time * 1.5) * 0.12);\nctx.font = '72px ' + T.font;\nctx.fillStyle = rc('yellow');\nctx.shadowColor = rc('yellow');\nctx.shadowBlur = 20;\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText('🔑', 0, -10);\nctx.restore();\n\nconst apps = [\n  { icon: '✈️', a: time * 0.3, name: 'BotFather', color: 'cyan' },\n  { icon: '👾', a: time * 0.3 + Math.PI/2, name: 'Dev Portal', color: 'orange' },\n  { icon: '💬', a: time * 0.3 + Math.PI, name: 'Zalo QR', color: 'highlight' },\n  { icon: '📞', a: time * 0.3 + (3*Math.PI)/2, name: 'WhatsApp QR', color: 'green' }\n];\n\napps.forEach(app => {\n  const ax = cx + Math.cos(app.a) * 140;\n  const ay = keyY + Math.sin(app.a) * 140;\n  \n  ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\n  ctx.strokeStyle = rc(app.color);\n  ctx.lineWidth = 2;\n  ctx.beginPath();\n  ctx.roundRect(ax - 28, ay - 28, 56, 56, 12);\n  ctx.fill();\n  ctx.stroke();\n  \n  ctx.font = '24px ' + T.font;\n  ctx.fillStyle = rc(app.color);\n  ctx.textAlign = 'center';\n  ctx.textBaseline = 'middle';\n  ctx.fillText(app.icon, ax, ay - 8);\n  \n  ctx.font = 'bold 10px monospace';\n  ctx.fillStyle = rc('text');\n  ctx.fillText(app.name, ax, ay + 15);\n  \n  const dotProg = (time * 0.4 + app.a) % 1.0;\n  const dx = ax + (cx - ax) * dotProg;\n  const dy = ay + (keyY - ay) * dotProg;\n  ctx.fillStyle = rc(app.color);\n  ctx.beginPath();\n  ctx.arc(dx, dy, 3.5, 0, Math.PI * 2);\n  ctx.fill();\n});\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 7,
      "voice_text": "Bước hai là đăng ký với bác quản gia qua Web UI Configuration. Sau khi có chìa khóa, bạn không cần đụng vào mã nguồn phức tạp.",
      "clear": False,
      "elements": [
        {
          "type": "text",
          "text": "Bước 2: Cấu Hình Web UI",
          "fontSize": 46,
          "color": "highlight",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\nconst w = 420;\nconst h = 180;\nconst x = cx - w / 2;\nconst y = cy - h / 2;\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.92)';\nctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';\nctx.lineWidth = 2;\nctx.beginPath();\nctx.roundRect(x, y, w, h, 16);\nctx.fill();\nctx.stroke();\n\nctx.fillStyle = 'rgba(255, 255, 255, 0.05)';\nctx.beginPath();\nctx.roundRect(x, y, w, 32, { tl: 16, tr: 16 });\nctx.fill();\n\nconst colors = ['#ff5f56', '#ffbd2e', '#27c93f'];\ncolors.forEach((c, idx) => {\n  ctx.fillStyle = c;\n  ctx.beginPath();\n  ctx.arc(x + 16 + idx * 16, y + 16, 5, 0, Math.PI * 2);\n  ctx.fill();\n});\n\nctx.font = 'bold 11px monospace';\nctx.fillStyle = rc('muted');\nctx.textAlign = 'center';\nctx.fillText('OPENCLAW CONFIGURATION DASHBOARD', cx, y + 20);\n\nconst fieldY = y + 65;\nconst fieldW = 340;\nconst fieldH = 45;\nconst fieldX = cx - fieldW / 2;\n\nctx.fillStyle = 'rgba(0, 0, 0, 0.3)';\nctx.strokeStyle = stepProgress >= 0.7 ? rc('green') : rc('highlight');\nctx.lineWidth = 1.5;\nctx.beginPath();\nctx.roundRect(fieldX, fieldY, fieldW, fieldH, 8);\nctx.fill();\nctx.stroke();\n\nif (stepProgress < 0.7) {\n  ctx.save();\n  ctx.strokeStyle = `rgba(245, 158, 11, ${0.3 + 0.2 * Math.sin(time * 4)})`;\n  ctx.lineWidth = 3;\n  ctx.beginPath();\n  ctx.roundRect(fieldX, fieldY, fieldW, fieldH, 8);\n  ctx.stroke();\n  ctx.restore();\n}\n\nconst secureString = stepProgress >= 0.7 ? 'TOKEN: ●●●●●●●●●●●●●●●● [SECURED]' : 'TOKEN: paste_api_key_here_...';\nctx.font = 'bold 12px monospace';\nctx.fillStyle = stepProgress >= 0.7 ? rc('green') : rc('muted');\nctx.textAlign = 'left';\nctx.textBaseline = 'middle';\nctx.fillText(secureString, fieldX + 15, fieldY + fieldH / 2);\n\nconst badgeY = y + 130;\nctx.fillStyle = stepProgress >= 0.7 ? rc('green') : rc('red');\nctx.beginPath();\nctx.arc(cx - 85, badgeY + 12, 6, 0, Math.PI * 2);\nctx.fill();\n\nctx.font = 'bold 12px monospace';\nctx.fillStyle = rc('text');\nctx.textAlign = 'left';\nctx.fillText(stepProgress >= 0.7 ? 'STATE: CONNECTED TO PROVIDER' : 'STATE: WAITING FOR INTEGRATION', cx - 70, badgeY + 12);\n\nctx.restore();",
          "height": 220
        }
      ]
    },
    {
      "id": 8,
      "voice_text": "Bạn chỉ cần mở Web UI, tức bảng điều khiển đã cài ở bài hai, tìm mục Channel Access, chọn ứng dụng muốn kết nối, ví dụ nhấn vào biểu tượng Telegram, rồi dán đoạn mã Token đã lấy ở bước một vào ô tương ứng và nhấn Lưu.",
      "clear": False,
      "elements": [
        {
          "type": "text",
          "text": "Dán Token Truy Cập & Lưu Lại",
          "fontSize": 42,
          "color": "cyan",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\nconst w = 460;\nconst h = 180;\nconst x = cx - w / 2;\nconst y = cy - h / 2;\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.95)';\nctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';\nctx.lineWidth = 2.5;\nctx.beginPath();\nctx.roundRect(x, y, w, h, 16);\nctx.fill();\nctx.stroke();\n\nctx.fillStyle = 'rgba(255, 255, 255, 0.05)';\nctx.beginPath();\nctx.roundRect(x, y, w, 32, { tl: 16, tr: 16 });\nctx.fill();\n\nconst controlCols = ['#ff5f56', '#ffbd2e', '#27c93f'];\ncontrolCols.forEach((c, idx) => {\n  ctx.fillStyle = c;\n  ctx.beginPath();\n  ctx.arc(x + 16 + idx * 16, y + 16, 5, 0, Math.PI * 2);\n  ctx.fill();\n});\n\nctx.font = 'bold 11px monospace';\nctx.fillStyle = rc('muted');\nctx.textAlign = 'center';\nctx.fillText('CHANNEL SETTINGS > TELEGRAM CONNECT', cx, y + 20);\n\nconst formY = y + 55;\nconst formW = 380;\nconst formH = 45;\nconst formX = cx - formW / 2;\n\nctx.fillStyle = 'rgba(0, 0, 0, 0.35)';\nctx.strokeStyle = stepProgress >= 0.7 ? rc('green') : rc('cyan');\nctx.lineWidth = 1.5;\nctx.beginPath();\nctx.roundRect(formX, formY, formW, formH, 8);\nctx.fill();\nctx.stroke();\n\nconst textVal = stepProgress >= 0.6 ? '784159852:AAFhQ-p0n89a5L2vX_...' : (stepProgress >= 0.2 ? '784159...' : '');\nctx.font = 'bold 13px monospace';\nctx.fillStyle = stepProgress >= 0.7 ? rc('green') : rc('text');\nctx.textAlign = 'left';\nctx.textBaseline = 'middle';\nctx.fillText(textVal, formX + 15, formY + formH / 2);\n\nif (stepProgress < 0.7 && Math.floor(time * 2.5) % 2 === 0) {\n  const tw = ctx.measureText(textVal).width;\n  ctx.fillStyle = rc('cyan');\n  ctx.fillRect(formX + 15 + tw + 2, formY + 12, 2, 20);\n}\n\nconst btnW = 90;\nconst btnH = 34;\nconst btnX = cx + formW/2 - btnW;\nconst btnY = y + 130;\n\nconst btnPressed = stepProgress >= 0.65;\nctx.fillStyle = btnPressed ? rc('green') : rc('cyan');\nif (btnPressed) {\n  ctx.shadowColor = rc('green');\n  ctx.shadowBlur = 10;\n}\nctx.beginPath();\nctx.roundRect(btnX, btnY, btnW, btnH, 8);\nctx.fill();\nctx.shadowBlur = 0;\n\nctx.font = 'bold 12px monospace';\nctx.fillStyle = '#0a0a1a';\nctx.textAlign = 'center';\nctx.fillText(btnPressed ? 'SAVED ✓' : 'SAVE', btnX + btnW / 2, btnY + btnH / 2 + 1);\n\nctx.font = 'bold 12px monospace';\nctx.fillStyle = btnPressed ? rc('green') : rc('muted');\nctx.textAlign = 'left';\nctx.fillText(btnPressed ? '✓ STATUS: BOT AUTHENTICATED [OK]' : '⌛ STATUS: PENDING API SUBMIT', formX, btnY + btnH / 2 + 1);\n\nctx.restore();",
          "height": 220
        }
      ]
    },
    {
      "id": 9,
      "voice_text": "Bước ba là thiết lập người đưa thư, tức Routing và Outbound. Đây là lúc bạn quyết định tin nhắn sẽ đi về đâu.",
      "clear": True,
      "elements": [
        {
          "type": "text",
          "text": "Bước 3: Định Tuyến Routing & Outbound",
          "fontSize": 48,
          "color": "title",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\n\nconst centralY = cy;\nconst leftX = cx - 180;\nconst rightX = cx + 180;\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.95)';\nctx.strokeStyle = rc('highlight');\nctx.lineWidth = 3;\nctx.beginPath();\nctx.roundRect(cx - 45, centralY - 45, 90, 90, 18);\nctx.fill();\nctx.stroke();\n\nctx.font = '36px ' + T.font;\nctx.fillStyle = rc('highlight');\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText('📡', cx, centralY - 2);\n\nctx.font = 'bold 11px monospace';\nctx.fillStyle = rc('highlight');\nctx.fillText('ROUTER', cx, centralY + 36);\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('cyan');\nctx.lineWidth = 2;\nctx.beginPath();\nctx.roundRect(leftX - 45, centralY - 40, 90, 80, 12);\nctx.fill();\nctx.stroke();\n\nctx.font = '28px ' + T.font;\nctx.fillStyle = rc('cyan');\nctx.fillText('📥', leftX, centralY - 10);\nctx.font = 'bold 11px monospace';\nctx.fillStyle = rc('cyan');\nctx.fillText('INBOUND', leftX, centralY + 22);\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('green');\nctx.lineWidth = 2;\nctx.beginPath();\nctx.roundRect(rightX - 45, centralY - 40, 90, 80, 12);\nctx.fill();\nctx.stroke();\n\nctx.font = '28px ' + T.font;\nctx.fillStyle = rc('green');\nctx.fillText('📤', rightX, centralY - 10);\nctx.font = 'bold 11px monospace';\nctx.fillStyle = rc('green');\nctx.fillText('OUTBOUND', rightX, centralY + 22);\n\nctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';\nctx.lineWidth = 4;\nctx.beginPath();\nctx.moveTo(leftX + 45, centralY);\nctx.lineTo(cx - 45, centralY);\nctx.moveTo(cx + 45, centralY);\nctx.lineTo(rightX - 45, centralY);\nctx.stroke();\n\nconst pProgIn = (time * 0.3) % 1.0;\nconst pxIn = (leftX + 45) + (cx - 45 - (leftX + 45)) * pProgIn;\nctx.fillStyle = rc('cyan');\nctx.beginPath();\nctx.arc(pxIn, centralY, 5, 0, Math.PI * 2);\nctx.fill();\n\nconst pProgOut = (time * 0.3 + 0.5) % 1.0;\nconst pxOut = (cx + 45) + (rightX - 45 - (cx + 45)) * pProgOut;\nctx.fillStyle = rc('green');\nctx.beginPath();\nctx.arc(pxOut, centralY, 5, 0, Math.PI * 2);\nctx.fill();\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 10,
      "voice_text": "Inbound Route là đường vào: khi bạn nhắn tin cho Bot trên điện thoại, tin nhắn chạy về Gateway, rồi Gateway chuyển cho Agent là bộ não. Outbound Sending là đường ra: AI suy nghĩ xong, gửi câu trả lời lại cho Gateway, rồi Gateway đẩy về đúng ứng dụng bạn đang dùng để bạn nhận được tin nhắn.",
      "clear": False,
      "elements": [
        {
          "type": "text",
          "text": "Dòng Chảy Tin Nhắn Hai Chiều",
          "fontSize": 42,
          "color": "cyan",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\n\nconst phoneX = cx - 200;\nconst gateX = cx;\nconst brainX = cx + 200;\n\nconst blockW = 100;\nconst blockH = 110;\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('cyan');\nctx.lineWidth = 2;\nctx.beginPath();\nctx.roundRect(phoneX - blockW/2, cy - blockH/2, blockW, blockH, 16);\nctx.fill();\nctx.stroke();\n\nctx.font = '36px ' + T.font;\nctx.fillStyle = rc('cyan');\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText('📱', phoneX, cy - 14);\nctx.font = 'bold 12px monospace';\nctx.fillStyle = rc('text');\nctx.fillText('PHONE', phoneX, cy + 28);\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.95)';\nctx.strokeStyle = rc('highlight');\nctx.lineWidth = 2.5;\nctx.beginPath();\nctx.roundRect(gateX - blockW/2, cy - blockH/2, blockW, blockH, 16);\nctx.fill();\nctx.stroke();\n\nctx.font = '36px ' + T.font;\nctx.fillStyle = rc('highlight');\nctx.fillText('📡', gateX, cy - 14);\nctx.font = 'bold 12px monospace';\nctx.fillStyle = rc('text');\nctx.fillText('GATEWAY', gateX, cy + 28);\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\nctx.strokeStyle = rc('green');\nctx.lineWidth = 2;\nctx.beginPath();\nctx.roundRect(brainX - blockW/2, cy - blockH/2, blockW, blockH, 16);\nctx.fill();\nctx.stroke();\n\nctx.font = '36px ' + T.font;\nctx.fillStyle = rc('green');\nctx.fillText('🧠', brainX, cy - 14);\nctx.font = 'bold 12px monospace';\nctx.fillStyle = rc('text');\nctx.fillText('AI BRAIN', brainX, cy + 28);\n\nctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';\nctx.lineWidth = 3.5;\nctx.beginPath();\nctx.moveTo(phoneX + blockW/2, cy);\nctx.lineTo(gateX - blockW/2, cy);\nctx.moveTo(gateX + blockW/2, cy);\nctx.lineTo(brainX - blockW/2, cy);\nctx.stroke();\n\nconst inProg = (time * 0.35) % 1.0;\nif (inProg < 0.5) {\n  const p1x = (phoneX + blockW/2) + (gateX - blockW/2 - (phoneX + blockW/2)) * (inProg / 0.5);\n  ctx.fillStyle = rc('cyan');\n  ctx.shadowColor = rc('cyan');\n  ctx.shadowBlur = 6;\n  ctx.beginPath(); ctx.arc(p1x, cy - 8, 4.5, 0, Math.PI * 2); ctx.fill();\n} else {\n  const p2x = (gateX + blockW/2) + (brainX - blockW/2 - (gateX + blockW/2)) * ((inProg - 0.5) / 0.5);\n  ctx.fillStyle = rc('cyan');\n  ctx.shadowColor = rc('cyan');\n  ctx.shadowBlur = 6;\n  ctx.beginPath(); ctx.arc(p2x, cy - 8, 4.5, 0, Math.PI * 2); ctx.fill();\n}\nctx.shadowBlur = 0;\n\nconst outProg = (time * 0.35 + 0.5) % 1.0;\nif (outProg < 0.5) {\n  const p1x = (brainX - blockW/2) - (brainX - blockW/2 - (gateX + blockW/2)) * (outProg / 0.5);\n  ctx.fillStyle = rc('green');\n  ctx.shadowColor = rc('green');\n  ctx.shadowBlur = 6;\n  ctx.beginPath(); ctx.arc(p1x, cy + 8, 4.5, 0, Math.PI * 2); ctx.fill();\n} else {\n  const p2x = (gateX - blockW/2) - (gateX - blockW/2 - (phoneX + blockW/2)) * ((outProg - 0.5) / 0.5);\n  ctx.fillStyle = rc('green');\n  ctx.shadowColor = rc('green');\n  ctx.shadowBlur = 6;\n  ctx.beginPath(); ctx.arc(p2x, cy + 8, 4.5, 0, Math.PI * 2); ctx.fill();\n}\nctx.shadowBlur = 0;\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 11,
      "voice_text": "Khi đã cấu hình xong, việc tương tác diễn ra cực kỳ đơn giản. Gửi yêu cầu: bạn mở Zalo hoặc Telegram lên, tìm đúng tên con Bot mình vừa tạo và nhắn: lên kế hoạch đi du lịch Đà Lạt cho tôi. Xử lý ngầm: OpenClaw sẽ tự động nhận diện tin nhắn này đến từ kênh nào, dùng bộ não nào đã cài ở bài ba để xử lý. Nhận phản hồi: chỉ vài giây sau, AI sẽ nhắn tin trả lời bạn ngay trên chính ứng dụng đó.",
      "clear": True,
      "elements": [
        {
          "type": "text",
          "text": "Mô Phỏng Trò Chuyện Trực Quan",
          "fontSize": 46,
          "color": "highlight",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\nconst w = 450;\nconst h = 185;\nconst x = cx - w / 2;\nconst y = cy - h / 2;\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.95)';\nctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';\nctx.lineWidth = 2.5;\nctx.beginPath();\nctx.roundRect(x, y, w, h, 18);\nctx.fill();\nctx.stroke();\n\nctx.fillStyle = 'rgba(255, 255, 255, 0.04)';\nctx.beginPath();\nctx.roundRect(x, y, w, 32, { tl: 18, tr: 18 });\nctx.fill();\n\nctx.font = 'bold 11px monospace';\nctx.fillStyle = rc('cyan');\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText('💬 TELEGRAM CHATBOT SIMULATION', cx, y + 16);\n\nconst bubble1Y = y + 48;\nconst bubble1W = 280;\nconst bubble1H = 40;\nconst bubble1X = x + 20;\n\nctx.fillStyle = 'rgba(255, 255, 255, 0.05)';\nctx.beginPath();\nctx.roundRect(bubble1X, bubble1Y, bubble1W, bubble1H, { tl: 4, tr: 12, br: 12, bl: 12 });\nctx.fill();\n\nctx.font = '12px ' + T.font;\nctx.fillStyle = rc('text');\nctx.textAlign = 'left';\nctx.textBaseline = 'middle';\nctx.fillText('User: Lên kế hoạch đi Đà Lạt cho tôi', bubble1X + 15, bubble1Y + bubble1H / 2);\n\nconst bubble2Y = y + 96;\nconst bubble2W = 310;\nconst bubble2H = 50;\nconst bubble2X = x + w - 20 - bubble2W;\n\nconst responseActive = stepProgress >= 0.5;\n\nif (responseActive) {\n  ctx.fillStyle = 'rgba(16, 185, 129, 0.12)';\n  ctx.strokeStyle = 'rgba(16, 185, 129, 0.3)';\n  ctx.lineWidth = 1.5;\n  ctx.beginPath();\n  ctx.roundRect(bubble2X, bubble2Y, bubble2W, bubble2H, { tl: 12, tr: 4, br: 12, bl: 12 });\n  ctx.fill();\n  ctx.stroke();\n  \n  ctx.font = '12px ' + T.font;\n  ctx.fillStyle = rc('green');\n  ctx.fillText('Bot 🤖: Chào bạn! Đây là kế hoạch Đà Lạt', bubble2X + 15, bubble2Y + 16);\n  ctx.fillStyle = rc('text');\n  ctx.fillText('3 ngày 2 đêm: Thung lũng tình yêu, Langbiang...', bubble2X + 15, bubble2Y + 34);\n} else {\n  ctx.fillStyle = 'rgba(255, 255, 255, 0.02)';\n  ctx.beginPath();\n  ctx.roundRect(bubble2X, bubble2Y, bubble2W, bubble2H, { tl: 12, tr: 4, br: 12, bl: 12 });\n  ctx.fill();\n  \n  const spin = time * 4.5;\n  ctx.save();\n  ctx.translate(bubble2X + 30, bubble2Y + bubble2H / 2);\n  ctx.rotate(spin);\n  ctx.font = '16px ' + T.font;\n  ctx.fillStyle = rc('highlight');\n  ctx.textAlign = 'center';\n  ctx.textBaseline = 'middle';\n  ctx.fillText('🧠', 0, 0);\n  ctx.restore();\n  \n  ctx.font = 'italic 12px ' + T.font;\n  ctx.fillStyle = rc('muted');\n  ctx.fillText('AI Agent is thinking...', bubble2X + 54, bubble2Y + bubble2H / 2);\n}\n\nctx.fillStyle = 'rgba(255, 255, 255, 0.02)';\nctx.fillRect(x + 10, y + 155, w - 20, 1);\n\nctx.font = 'bold 10px monospace';\nctx.fillStyle = rc('muted');\nctx.textAlign = 'center';\nctx.fillText('REALTIME STREAMING: ACTIVE', cx, y + 170);\n\nctx.restore();",
          "height": 225
        }
      ]
    },
    {
      "id": 12,
      "voice_text": "Một điểm hay của OpenClaw trong Track C là nó tự quản lý trạng thái kết nối. Nếu tài khoản Bot bị đăng xuất hoặc gặp lỗi, hệ thống sẽ báo ngay trên Web UI. Bạn có thể quản lý nhiều kênh cùng lúc, vừa dùng Zalo vừa dùng Telegram, mà chỉ cần một bộ não AI duy nhất. Kết luận bài học: chúc mừng bạn, đến đây AI của bạn đã thực sự sống và có thể trò chuyện với bạn ở bất cứ đâu thông qua chiếc điện thoại cầm tay. Lời khuyên: vì mỗi ứng dụng như Telegram, Discord hay Zalo có một cách lấy Token hơi khác nhau, nếu bạn muốn tôi đi sâu vào từng dòng mã hoặc từng bước chụp màn hình cho một ứng dụng cụ thể, hãy cho tôi biết nhé.",
      "clear": True,
      "elements": [
        {
          "type": "text",
          "text": "Tổng Kết & Hướng Phát Triển",
          "fontSize": 48,
          "color": "title",
          "align": "center",
          "bold": True
        },
        {
          "type": "custom_js",
          "code": "ctx.save();\nconst cx = W / 2;\nconst cy = cursorY + 110;\nconst r = 52;\n\nctx.strokeStyle = 'rgba(16, 185, 129, 0.08)';\nctx.lineWidth = 1;\nctx.beginPath();\nctx.arc(cx, cy, r + 40, 0, Math.PI * 2);\nctx.stroke();\n\nconst waveCount = 3;\nfor (let i = 0; i < waveCount; i++) {\n  const waveProg = ((time * 0.12 + i / waveCount) % 1.0);\n  const waveR = r + waveProg * 90;\n  ctx.strokeStyle = `rgba(16, 185, 129, ${0.28 * (1 - waveProg)})`;\n  ctx.lineWidth = 2;\n  ctx.beginPath();\n  ctx.arc(cx, cy, waveR, 0, Math.PI * 2);\n  ctx.stroke();\n}\n\nconst channels = [\n  { name: \"Telegram Bot\", icon: \"✈️\", a: -Math.PI / 2, color: \"cyan\" },\n  { name: \"Zalo API\", icon: \"💬\", a: Math.PI / 6, color: \"highlight\" },\n  { name: \"Discord API\", icon: \"👾\", a: (5 * Math.PI) / 6, color: \"orange\" }\n];\n\nchannels.forEach((ch, idx) => {\n  const targetX = cx + Math.cos(ch.a) * 110;\n  const targetY = cy + Math.sin(ch.a) * 110;\n\n  ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';\n  ctx.lineWidth = 2.5;\n  ctx.setLineDash([4, 4]);\n  ctx.beginPath();\n  ctx.moveTo(cx, cy);\n  ctx.lineTo(targetX, targetY);\n  ctx.stroke();\n  ctx.setLineDash([]);\n\n  const pProg = (time * 0.22 + idx * 0.3) % 1.0;\n  const px = cx + (targetX - cx) * pProg;\n  const py = cy + (targetY - cy) * pProg;\n  ctx.fillStyle = rc(ch.color);\n  ctx.shadowColor = rc(ch.color);\n  ctx.shadowBlur = 10;\n  ctx.beginPath();\n  ctx.arc(px, py, 4.5, 0, Math.PI * 2);\n  ctx.fill();\n  ctx.shadowBlur = 0;\n\n  ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';\n  ctx.strokeStyle = rc(ch.color);\n  ctx.lineWidth = 1.5;\n  ctx.beginPath();\n  ctx.roundRect(targetX - 25, targetY - 25, 50, 50, 12);\n  ctx.fill();\n  ctx.stroke();\n\n  ctx.font = '24px ' + T.font;\n  ctx.fillStyle = rc(ch.color);\n  ctx.textAlign = 'center';\n  ctx.textBaseline = 'middle';\n  ctx.fillText(ch.icon, targetX, targetY - 2);\n\n  ctx.fillStyle = rc('text');\n  ctx.font = 'bold 11px monospace';\n  ctx.fillText(ch.name, targetX, targetY + 38);\n});\n\nctx.fillStyle = 'rgba(15, 23, 42, 0.95)';\nctx.strokeStyle = rc('green');\nctx.lineWidth = 3;\nctx.shadowColor = rc('green');\nctx.shadowBlur = 15;\nctx.beginPath();\nctx.roundRect(cx - 32, cy - 32, 64, 64, 16);\nctx.fill();\nctx.stroke();\nctx.shadowBlur = 0;\n\nconst pulse = 1 + 0.07 * Math.sin(time * 2.2);\nctx.font = `${Math.round(32 * pulse)}px ${T.font}`;\nctx.fillStyle = rc('green');\nctx.textAlign = 'center';\nctx.textBaseline = 'middle';\nctx.fillText(\"🧠\", cx, cy - 2);\n\nctx.restore();",
          "height": 225
        }
      ]
    }
  ]
}

target_file = r"c:\tubecreate-vue\tubecli\data\edu_video_studio\projects\4e93bff6\lessons\lesson_b7f544\lesson_script.json"

with open(target_file, "w", encoding="utf-8") as f:
    json.dump(lesson_script, f, ensure_ascii=False, indent=2)

print("Lesson 4 script written successfully to lesson_script.json")
