# TubeCLI Update Guide

## v2026.06.05.1 — Extension Data Directory Refactoring

### Tóm tắt thay đổi (Summary)

Phiên bản này tổ chức lại thư mục dữ liệu (`data/`) của TubeCLI. Trước đây, dữ liệu của tất cả extension được đặt trực tiếp trong `data/`, lẫn lộn với các file cấu hình toàn cục. Từ phiên bản này, dữ liệu của từng extension sẽ được tập trung vào `data/extensions_data/<tên_extension>/`.

---

### Cấu trúc mới (New Structure)

```
data/
├── agents.json              ← Cấu hình agents (không đổi)
├── skills.json              ← Cấu hình skills (không đổi)
├── settings.json            ← Cài đặt toàn cục (không đổi)
├── api_port.json            ← Port API (không đổi)
├── logs/                    ← Logs hệ thống (không đổi)
├── workflows/               ← Workflows (không đổi)
├── memory/                  ← Memory của agents (không đổi)
├── extensions_external/     ← Code extension ngoài (không đổi)
│
└── extensions_data/         ← ✅ MỚI: Tất cả dữ liệu extension
    ├── auth_manager/
    │   └── auth_manager.json
    ├── calendar_manager/
    │   └── calendar_manager.json
    ├── studio3d/
    │   └── studio3d_scenes.json
    ├── universal_tracker/
    │   └── universal_tracker_jobs.json
    ├── browser/
    │   └── browser_profiles/
    ├── web_crawler/
    │   ├── web_crawler_exports/
    │   ├── watches.json
    │   ├── watch_logs.json
    │   └── ...
    ├── video_downloader/
    │   ├── ytdl_downloads/
    │   └── downloader_settings.json
    └── content_studio/
        └── content_studio.db
```

---

### Người dùng cũ — Không cần làm gì! (Existing Users)

**Quá trình migration diễn ra hoàn toàn tự động** khi bạn khởi động TubeCLI lần đầu sau khi cập nhật:

1. Hệ thống phát hiện các file/thư mục dữ liệu cũ trong `data/`
2. Di chuyển chúng sang vị trí mới trong `data/extensions_data/`
3. Tạo **Windows Junction** (thư mục) hoặc **Hardlink** (file) tại vị trí cũ để đảm bảo tương thích ngược
4. Đặt ẩn các junction/hardlink đó để `data/` trông gọn gàng hơn

> **Dữ liệu của bạn an toàn tuyệt đối và không bị mất.** Quá trình này chỉ di chuyển vị trí lưu trữ, không xóa hay thay đổi nội dung.

---

### Cách cập nhật (How to Update)

#### Sử dụng script cài đặt (Recommended)

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install.ps1 | iex
```

**Linux / macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install.sh | bash
```

#### Cập nhật thủ công (Manual Update)

```bash
cd /path/to/tubecli
git pull origin main
pip install -e .
```

Sau khi cập nhật, khởi động lại TubeCLI. Migration sẽ tự động chạy.

---

### Rollback (Khôi phục cấu trúc cũ)

Nếu cần khôi phục lại cấu trúc dữ liệu cũ (chỉ dùng khi gặp sự cố nghiêm trọng):

```bash
python tubecli/core/rollback_data.py
```

Script này sẽ:
- Di chuyển tất cả file/thư mục từ `extensions_data/` về lại `data/`
- Xóa các junction/hardlink đã tạo
- Dọn sạch thư mục `extensions_data/` nếu trống

> ⚠️ **Lưu ý:** Sau khi rollback, hãy dùng phiên bản TubeCLI cũ để tránh xung đột.

---

### Các extension bị ảnh hưởng (Affected Extensions)

| Extension | File/Thư mục cũ | Vị trí mới |
|-----------|-----------------|------------|
| `auth_manager` | `data/auth_manager.json` | `data/extensions_data/auth_manager/auth_manager.json` |
| `calendar_manager` | `data/calendar_manager.json` | `data/extensions_data/calendar_manager/calendar_manager.json` |
| `studio3d` | `data/studio3d_scenes.json` | `data/extensions_data/studio3d/studio3d_scenes.json` |
| `universal_tracker` | `data/universal_tracker_jobs.json` | `data/extensions_data/universal_tracker/universal_tracker_jobs.json` |
| `browser` | `data/browser_profiles/` | `data/extensions_data/browser/browser_profiles/` |
| `web_crawler` | `data/web_crawler_exports/`, `data/watches.json`, ... | `data/extensions_data/web_crawler/...` |
| `video_downloader` | `data/ytdl_downloads/`, `data/downloader_settings.json` | `data/extensions_data/video_downloader/...` |
| `content_studio` | `data/content_studio.db` | `data/extensions_data/content_studio/content_studio.db` |

---

### Lợi ích của cấu trúc mới (Benefits)

- **Gọn gàng hơn**: `data/` không còn bị lộn xộn bởi hàng chục file của các extension khác nhau.
- **Dễ backup**: Muốn backup dữ liệu extension? Chỉ cần copy thư mục `data/extensions_data/`.
- **Dễ phát triển extension**: Extension mới tự động có không gian lưu trữ riêng trong `extensions_data/<tên_extension>/`.
- **Tương thích ngược**: Các extension chưa cập nhật vẫn hoạt động bình thường nhờ hệ thống junction/hardlink.

---

### Báo cáo lỗi (Report Issues)

Nếu gặp vấn đề sau khi cập nhật:
- Mở issue tại: https://github.com/tubecreate/tubecli/issues
- Hoặc chạy rollback script để khôi phục trạng thái cũ

---

*Cập nhật lần cuối: 2026-06-05 | Phiên bản: 2026.06.05.1*
