---
name: website_manager
description: >
  Quản lý và deploy websites Cloudflare Workers. Extension cung cấp danh sách website dạng card,
  thêm website thủ công, tạo website tự động từ templates (git clone → build OpenNext → wrangler deploy → D1 + R2).
  Tích hợp với cloud_api để lấy Cloudflare credentials (CF_API_TOKEN + CF_ACCOUNT_ID).
---

# Website Manager Extension

## Chức năng
- **Danh sách websites**: card grid với tên, URL, token (user_token, wp_token), trạng thái (active/deploying/failed)
- **Thêm website thủ công**: Dialog nhập tên, user_token, wp_token, thumbnail
- **Tạo website tự động**: Chọn theme → nhập site_name + CF credentials → deploy pipeline tự động
- **Live deploy log**: SSE stream real-time terminal output
- **Cloudflare credentials**: Lấy từ Cloud Keys (cloud_api extension, provider cloudflare) hoặc nhập thủ công

## API Endpoints

### Website CRUD
- `GET  /api/v1/website-manager/sites` — list all websites
- `POST /api/v1/website-manager/sites` — add website manually
- `PUT  /api/v1/website-manager/sites/{id}` — update website
- `DELETE /api/v1/website-manager/sites/{id}` — delete website

### Deploy
- `POST /api/v1/website-manager/sites/deploy` — start deploy (cf_api_token, cf_account_id optional if saved in cloud_api)
- `GET  /api/v1/website-manager/sites/{name}/logs` — SSE log stream

### Templates & CF
- `GET /api/v1/website-manager/templates` — fetch from autoweb.tubecreate.com/api/templates
- `GET /api/v1/website-manager/cloudflare-profiles` — list CF profiles from cloud_api

### Cloudflare Keys (cloud_api)
- `GET  /api/v1/cloud-api/cloudflare/profiles` — list CF profiles
- `POST /api/v1/cloud-api/cloudflare/profiles` — add CF profile (api_token + account_id)
- `POST /api/v1/cloud-api/cloudflare/profiles/{label}/test` — verify CF token
- `DELETE /api/v1/cloud-api/cloudflare/profiles/{label}` — remove profile

## Deploy Pipeline Steps
1. git clone template từ githubUrl
2. npm install
3. wrangler d1 create → lấy database_id
4. wrangler d1 execute schema.sql --remote
5. Viết wrangler.toml (name, d1_databases, assets)
6. npx @opennextjs/cloudflare build
7. npx wrangler deploy
8. fetch {deployUrl}/api/admin/init?adminPassword=...
9. Generate wptoken (login admin → lấy JWT)

## Data Storage
- Websites: `EXTENSIONS_DATA_DIR/website_manager/websites.json`
- Deploy logs: `EXTENSIONS_DATA_DIR/website_manager/logs/{site_name}.log`
- Build temp: `EXTENSIONS_DATA_DIR/website_manager/build/{site_name}/` (xóa sau deploy)
- CF credentials: `data/cloud_api_keys.json` (provider: cloudflare, dùng compound key format)
