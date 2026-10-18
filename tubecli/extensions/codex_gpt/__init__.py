"""Codex GPT — Codex CLI (OpenAI) chạy trên máy, quản lý NHIỀU gói đăng ký + phiên chat trong Flow.

User 3/10/2026: «thêm node codex gpt (khác với codex task board). Giống như 9router, node codex này
cài vào sử dụng dòng lệnh codex như bình thường nhưng giúp người dùng quản lý multi subscribe và
quản lý các phiên chat UI/UX dễ dàng trong flow».

Không phải extension bật/tắt: route gắn thẳng vào server (như Terminal) — api/server.py. Thư mục nằm
dưới extensions/ chỉ để bộ dịch chung (/api/v1/i18n) gom được locales/.

  cli.py      tìm / cài / cập nhật Codex CLI (npm vào thư mục riêng, không cần sudo)
  rpc.py      nói chuyện JSON-RPC với `codex app-server` (stdio, luồng đọc riêng — chạy được dưới
              mọi event loop, kể cả SelectorEventLoop của uvicorn trên Windows)
  accounts.py két tài khoản: mỗi gói đăng ký một auth.json riêng, không bao giờ trả ra ngoài
  service.py  cầu nối: MỘT CODEX_HOME chung (lịch sử phiên dùng chung) + auth.json của tài khoản đang
              dùng; hết hạn mức thì tự chuyển tài khoản và làm tiếp phiên đang dở
  routes.py   REST /api/v1/codex-gpt/* + WebSocket + trang /codex-gpt
  telegram.py bot Telegram riêng: chat được phép ↔ phiên Codex, trả lời + nút duyệt về điện thoại (18/10/2026)
"""
