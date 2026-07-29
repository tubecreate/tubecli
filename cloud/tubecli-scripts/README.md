# tubecli-scripts — kho script trung tâm

Cloudflare Worker + D1 giữ toàn bộ script tự động hoá trình duyệt cho tubecli,
cùng thống kê script nào thật sự chạy được.

- **URL:** https://tubecli-scripts.tubecli.workers.dev
- **Bảng điều khiển:** mở URL trên bằng trình duyệt, nhập admin token
- **D1:** `tubecli-scripts-db` (`6cce8231-6a45-43ed-b115-f060758134a6`)

Hợp đồng API sao đúng theo t2login (`core/script_sync.py`, `core/license_client.py`)
nên client cũ chỉ cần đổi base URL là chạy được.

## API

### Công khai — client gọi

| Method | Đường dẫn | Mô tả |
|---|---|---|
| `GET` | `/api/scripts` | Toàn bộ script đang bật. Lọc: `?since=`, `?category=`, `?engine=` |
| `GET` | `/api/scripts/{slug}` | Một script |
| `GET` | `/api/script-stats` | `{slug: {attempts, successes, last_success_at, last_failure_at, last_error}}` |
| `GET` | `/health` | Kiểm tra sống |

`?since=<YYYY-MM-DD HH:MM:SS>` là **đồng bộ delta**: chỉ trả script đổi từ mốc đó,
kèm mảng `deleted` liệt kê script đã bị tắt để client tự dọn. So sánh dùng `>=`
chứ không phải `>` — mốc thời gian chỉ tới giây, dùng `>` sẽ bỏ sót vĩnh viễn
script được sửa đúng vào giây client đồng bộ.

### Cần `X-Client-Key`

| Method | Đường dẫn | Mô tả |
|---|---|---|
| `POST` | `/api/script-outcome` | Báo kết quả một lần chạy |
| `POST` | `/api/register` | Điểm danh máy khách |

```json
{ "slug": "youtube_search_watch", "success": false,
  "machine_id": "…", "client_version": "2026.07.26", "engine": "shardx",
  "failed_step_index": 7, "failed_step_label": "Bấm video đầu tiên",
  "error": "timeout waiting for selector", "duration_ms": 43120 }
```

Client key nằm sẵn trong ứng dụng nên **không phải bí mật thật** — nó chỉ chặn
người lạ đổ dữ liệu rác làm sai tỉ lệ thành công.

### Cần `X-Admin-Token`

| Method | Đường dẫn | Mô tả |
|---|---|---|
| `GET` | `/api/admin/overview` | Toàn bộ script kèm thống kê + số tổng |
| `GET` | `/api/admin/scripts/{slug}` | Script + thống kê + 50 lượt chạy gần nhất |
| `POST` | `/api/admin/scripts` | Tạo mới (bắt buộc có `slug`). Slug đã tồn tại → **409**, thêm `?overwrite=1` mới ghi đè |
| `POST\|PUT` | `/api/admin/scripts/{slug}` | Cập nhật. Slug trên đường dẫn **luôn thắng** slug trong body |
| `POST` | `/api/admin/scripts/{slug}/toggle` | Bật/tắt |
| `DELETE` | `/api/admin/scripts/{slug}` | Xoá script, **giữ** lịch sử chạy |
| `DELETE` | `/api/admin/scripts/{slug}?purge=1` | Xoá sạch cả lịch sử (chạy được cả khi script đã bị xoá trước đó) |
| `GET` | `/api/admin/outcomes?slug=&failed=1&limit=` | Nhật ký chạy thô |
| `GET` | `/api/admin/clients` | Danh sách máy khách |
| `POST` | `/api/admin/stats/recompute` | Dựng lại bảng thống kê từ nhật ký thô |

`recompute` **cộng dồn** nhật ký thô lên nền kế thừa (`seed_attempts` /
`seed_successes`), không phải ghi đè. Dòng nào không có nhật ký thô thì giữ nguyên.

## Dữ liệu

22 script, gộp từ hai nguồn của t2login (API server 17 + file local 18, dòng nào
`updated_at` mới hơn thì thắng), kèm 16 dòng thống kê thật kế thừa. Thống kê kế
thừa cho bộ chọn script một điểm khởi đầu, thay vì bắt nó tự khám phá lại từ đầu
rằng `news_cnn` hỏng 25/26 lần.

Bảng D1: `scripts`, `script_outcomes` (nhật ký thô), `script_stats` (bảng rollup
để `/api/script-stats` chỉ đọc một lượt), `clients`.

### Vì sao thống kê tách làm hai cột

`script_stats.seed_attempts` / `seed_successes` giữ **nguyên vẹn** con số di cư
từ t2login — những lượt chạy mà kho này chưa từng chứng kiến và không có dòng
nhật ký nào phía sau. `attempts` / `successes` là số được công bố, và luôn bằng
`seed_* + nhật ký của chính kho này`.

Tách như vậy vì bản đầu tiên không tách: `recompute` dựng lại từ nhật ký thô rồi
**gán đè**, nên lần chạy thật đầu tiên của một script di cư sẽ biến `114/196`
thành `0/1` — xoá sạch bản sao duy nhất của lịch sử đó, chỉ bằng một cú bấm nút
"Tính lại thống kê" trên giao diện.

## Triển khai

```bash
export CF_ACCOUNT_ID=…            # 32 ký tự hex
export CF_API_TOKEN=…             # token phạm vi hẹp (khuyến nghị)
# hoặc: export CF_EMAIL=… CF_API_KEY=…   (Global API Key)

python tools/deploy.py            # upload worker + secret + bật workers.dev
python tools/smoke_test.py        # 51 kiểm thử trên bản đã deploy
```

Lần deploy đầu sinh `tools/secrets.json` chứa `ADMIN_TOKEN` và `CLIENT_KEY`.
File này **đã gitignore** — mất là phải sinh lại và cập nhật client.

Không dùng wrangler vì máy build chưa cài; `wrangler.toml` vẫn có sẵn nếu bạn
thích dùng CLI. `dashboard.html` được nạp như **Text module** rồi worker import
thành chuỗi, nên sửa giao diện không phải escape gì cả.

### Về khoá Cloudflare

Nên dùng **API Token phạm vi hẹp** (`Workers Scripts:Edit`, `D1:Edit`,
`Account Settings:Read`) thay cho Global API Key. Global key có toàn quyền trên
mọi tài nguyên của tài khoản, không giới hạn được, và không thu hồi riêng lẻ được
— lộ một lần là phải đổi tất cả.

## Bẫy đã gặp

- **`error code: 1010`** — bot protection của Cloudflare chặn User-Agent mặc định
  của `urllib`. Mọi client phải tự khai tên (t2login cũng vậy: `T2Login/1.0 ScriptSync`).
- **`error code: 1101`** — worker ném exception. Nếu router viết `return handler()`
  mà thiếu `await`, promise bị từ chối sau khi `try` đã thoát, catch không bắt
  được, và người gọi nhận trang lỗi trống thay vì JSON. Đây là lý do `fetch()`
  dùng `return await route(...)`.
- **Deploy làm mất secret** — upload worker sẽ xoá mọi binding không khai lại.
  `keep_bindings: ["secret_text"]` giữ chúng lại.
- **Script hỏng thì từ chối, đừng nuốt** — `steps` không parse được sẽ trả 400.
  Ép về `[]` sẽ lưu ra một script chạy 0 bước mà vẫn báo thành công.
- **Deploy xong đừng test ngay** — Cloudflare lan truyền bản mới dần dần, nên
  vài request đầu vẫn rơi vào isolate cũ. Triệu chứng rất dễ chẩn đoán nhầm:
  một nửa bản vá "có tác dụng", nửa kia thì không, dù chúng nằm cùng một file.
  Đợi vài chục giây rồi mới chạy bộ kiểm thử.
- **Slug là tên file trên mọi máy khách** — ký tự lạ bị gấp thành `_`, nhưng slug
  toàn dấu câu (`!!!`, `@@@`) bị **từ chối** chứ không gấp: nếu gấp thì mọi slug
  như vậy đều thành `_` và đè lên nhau.
