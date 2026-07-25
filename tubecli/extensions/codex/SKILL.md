---
name: "Codex"
description: "Mission control: tạo task, giao cho agent/team, chờ người duyệt, worker chạy nền, nghiệm thu kết quả."
version: "1.0.0"
author: "TubeCreate"
---

# 🎛 Codex — bảng điều khiển công việc

Codex là nơi chứa MỌI việc thật sự cần làm. Bất kỳ yêu cầu nào **chạy lâu**, **tốn tài nguyên** (LLM, browser, tải/upload), **thay đổi dữ liệu hoặc thế giới bên ngoài**, hoặc **cần người xem lại kết quả** → KHÔNG làm inline, mà tạo task Codex rồi báo số task cho người dùng. Chỉ trả lời trực tiếp khi câu hỏi là tra cứu/giải thích nhanh, không tạo ra thay đổi nào.

## 🛑 Luật duyệt (BẮT BUỘC)
- Task do AI tạo **LUÔN** ở trạng thái `pending_approval` và **chờ người duyệt**. AI **không được** tự duyệt task của mình.
- Sau khi tạo task, **TUYỆT ĐỐI KHÔNG** nói rằng việc đã chạy/đã xong. Chỉ được nói: đã tạo `#<n>`, đang chờ duyệt, và hướng dẫn gõ `approve <n>`.
- Vòng đời: `pending_approval → queued → running → review → done` (+ `failed` có thể retry, `rejected`, `cancelled`).

## ⚠️ Luật PAYLOAD PHẲNG (BẮT BUỘC)
Bộ phân tích action chỉ đọc được JSON **một tầng, toàn giá trị vô hướng** (string/number/bool). **KHÔNG** dùng object lồng nhau, **KHÔNG** dùng mảng trong action.
Muốn chia việc lớn thành nhiều việc nhỏ → phát **NHIỀU action `codex_create_task` liên tiếp**, mỗi action một `goal`. Không bao giờ gói danh sách subtask vào một action.

## 📥 codex_create_task — tạo việc mới
```json
{"action": "codex_create_task", "goal": "Mô tả đầy đủ việc cần làm", "title": "Tên ngắn", "assignee_type": "agent", "assignee": "Tên agent hoặc tên team", "skill": "Tên skill (tùy chọn)", "priority": 0}
```
- `goal` (bắt buộc) — mô tả tự đủ nghĩa, worker sẽ chỉ đọc chuỗi này.
- `assignee_type`: `"agent"` hoặc `"team"`. `assignee` nhận **TÊN** (khớp tên agent/team đã có), không cần ID.
- `priority`: số càng lớn chạy càng trước (mặc định 0).

## 📥 codex_list_tasks — xem danh sách
```json
{"action": "codex_list_tasks", "status": "active"}
```
`status`: `active` (mặc định) | `pending_approval` | `queued` | `running` | `review` | `done` | `failed` | `rejected` | `cancelled`.

## 📥 codex_task_status — chi tiết một task
```json
{"action": "codex_task_status", "task": "3"}
```
`task` nhận số ngắn (`3`), id đầy đủ, hoặc một phần tiêu đề.

## 📥 codex_approve / codex_reject — quyết định thay người dùng
Chỉ dùng khi **người dùng nói rõ** muốn duyệt/từ chối.
```json
{"action": "codex_approve", "task": "3", "note": "Lý do (tùy chọn)"}
```
```json
{"action": "codex_reject", "task": "3", "note": "Lý do (tùy chọn)"}
```

## 📥 codex_cancel — huỷ task đang chờ/đang chạy
```json
{"action": "codex_cancel", "task": "3"}
```

## 📥 codex_retry — chạy lại task `failed` hoặc `review`
```json
{"action": "codex_retry", "task": "3"}
```

## 🌐 HTTP API (qua `run_api`, prefix `/api/v1/codex`)
Ưu tiên dùng các action `codex_*` ở trên. Chỉ dùng `run_api` cho các endpoint GET không có trong action list.

| Method | Endpoint | Mục đích |
|--------|----------|----------|
| GET | `/api/v1/codex/stats` | Đếm task theo trạng thái |
| GET | `/api/v1/codex/tasks?status=&limit=` | Danh sách task |
| POST | `/api/v1/codex/tasks` | Tạo task (dùng `codex_create_task` thay thế) |
| GET | `/api/v1/codex/tasks/{id}` | Task + event log |
| GET | `/api/v1/codex/tasks/{id}/events?after=&limit=` | Nhật ký sự kiện |
| POST | `/api/v1/codex/tasks/{id}/approve` · `/reject` · `/cancel` · `/retry` | Quyết định |
| POST | `/api/v1/codex/tasks/{id}/review` | Nghiệm thu (`accepted: true/false`) |
| POST | `/api/v1/codex/tasks/{id}/plan` | AI chia nhỏ mục tiêu (CHẬM 10–60s) |
| GET | `/api/v1/codex/assignees` | Danh sách agent + team |
| GET | `/api/v1/codex/worker` | Trạng thái worker |

Bảng trực quan: `GET /codex`.

## ⌨️ Lệnh text (0 token — người dùng gõ thẳng, AI không cần xử lý)
`codex` · `codex <n>` · `approve <n>` · `reject <n>` · `retry <n>` · `accept <n>` · `codex cancel <n>` · `codex running|done|failed`
(«cancel»/«huỷ» đứng một mình đã bị luồng xác nhận kế hoạch của bot chiếm, nên huỷ task phải gõ kèm tiền tố `codex`.)
Khi tin nhắn người dùng đúng dạng này, **đừng** sinh action — hệ thống tự xử lý.

## 💡 Ví dụ
**User:** "Nghiên cứu 5 đối thủ kênh YouTube của tôi rồi viết báo cáo"
→ việc dài, tốn tài nguyên, cần review ⇒ tạo task, không tự làm:
```json
{"action": "codex_create_task", "goal": "Nghiên cứu 5 kênh YouTube đối thủ cùng chủ đề, so sánh tần suất đăng, tiêu đề, thumbnail, lượt xem trung bình và viết báo cáo tổng hợp kèm đề xuất", "title": "Báo cáo 5 đối thủ YouTube", "assignee_type": "team", "assignee": "Research Team"}
```

**User:** "Dịch bài này rồi đăng lên WordPress, xong thì tạo ảnh minh hoạ"
→ hai việc ⇒ **hai action riêng biệt**, không nhét mảng:
```json
{"action": "codex_create_task", "goal": "Dịch bài viết sang tiếng Việt và đăng lên WordPress", "title": "Dịch + đăng WordPress", "assignee_type": "agent", "assignee": "Writer"}
```
```json
{"action": "codex_create_task", "goal": "Tạo ảnh minh hoạ cho bài viết vừa đăng lên WordPress", "title": "Ảnh minh hoạ bài viết", "assignee_type": "agent", "assignee": "Designer"}
```

**User:** "Có task nào đang chờ tôi duyệt không?"
```json
{"action": "codex_list_tasks", "status": "pending_approval"}
```

**User:** "Task 3 tới đâu rồi?"
```json
{"action": "codex_task_status", "task": "3"}
```
