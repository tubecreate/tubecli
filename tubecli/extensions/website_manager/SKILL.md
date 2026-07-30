---
name: website_manager
description: >
  Manage and deploy Cloudflare Workers websites. Provides a card list of websites,
  manual add, and automatic creation from templates (git clone → build OpenNext → wrangler deploy → D1 + R2).
  Integrates with cloud_api for Cloudflare credentials (CF_API_TOKEN + CF_ACCOUNT_ID, or Global API Key + email).
---

# Website Manager Extension

## Features
- **Website list**: card grid with name, URL, tokens (user_token, wp_token), status (active/deploying/failed)
- **Add manually**: dialog to enter name, user_token, wp_token, thumbnail
- **Create automatically**: pick a theme → enter site_name + CF credentials → automatic deploy pipeline
- **Live deploy log**: real-time SSE terminal stream (with a Cancel button to abort a running deploy)
- **Cloudflare credentials**: taken from Cloud Keys (cloud_api extension, cloudflare provider) or entered manually; supports both API Token and Global API Key (with email)
- **Agent skills**: exposes `🌐 Quản lý Website` (list) and `🚀 Tạo Website` (deploy) as runnable skills attached to the Web Agent

## API Endpoints

### Website CRUD
- `GET  /api/v1/website-manager/sites` — list all websites (secrets masked)
- `POST /api/v1/website-manager/sites` — add a website manually
- `PUT  /api/v1/website-manager/sites/{id}` — update a website
- `DELETE /api/v1/website-manager/sites/{id}` — delete a website

### Deploy
- `POST /api/v1/website-manager/sites/deploy` — start a deploy (cf_api_token / cf_account_id / cf_email optional if saved in cloud_api)
- `POST /api/v1/website-manager/sites/{name}/cancel` — cancel a running deploy (kills the whole process tree)
- `GET  /api/v1/website-manager/sites/{name}/logs` — SSE log stream

### Skill endpoints (for agents)
- `POST /api/v1/website-manager/skill/websites` — human-readable site list
- `POST /api/v1/website-manager/skill/deploy` — deploy from a natural-language request (name + template)

### Templates & CF
- `GET /api/v1/website-manager/templates` — fetch from autoweb.tubecreate.com/api/templates
- `GET /api/v1/website-manager/cloudflare-profiles` — list CF profiles from cloud_api

### Cloudflare Keys (cloud_api)
- `GET  /api/v1/cloud-api/cloudflare/profiles` — list CF profiles
- `POST /api/v1/cloud-api/cloudflare/profiles` — add a CF profile (api_token + account_id [+ email for Global API Key])
- `POST /api/v1/cloud-api/cloudflare/profiles/{label}/test` — verify the CF token
- `DELETE /api/v1/cloud-api/cloudflare/profiles/{label}` — remove a profile

## Deploy Pipeline Steps (deploy_runner.js)
1. git clone the template from githubUrl (`--` guards against argument injection)
2. npm install
3. wrangler d1 create → get database_id; and `wrangler r2 bucket create` (skipped gracefully if R2 is not enabled)
4. wrangler d1 execute schema.sql --remote (auto-fixes JS-style `\'` → SQL `''` escaping)
5. Write wrangler.toml (name, d1_databases, assets, r2_buckets when available)
6. npx @opennextjs/cloudflare build
7. npx wrangler deploy
8. Seed admin: GET {deployUrl}/api/admin/init?adminPassword=... — if the template pre-seeds an admin, log in as the default admin (admin/admin123) first, then call init with the cookie + force=true so the user's password and template content are applied
9. Emit a machine-readable `DEPLOY_RESULT {url, adminSeeded}` marker + `__DEPLOY_DONE__`. Note: the `wp_xxxx` application password is NOT generated during deploy — it is created separately via the api_keys table when explicitly requested.

## Data Storage
- Websites: `EXTENSIONS_DATA_DIR/website_manager/websites.json` (atomic write, chmod 0600)
- Deploy logs: `EXTENSIONS_DATA_DIR/website_manager/logs/{site_name}.log`
- Build temp: `EXTENSIONS_DATA_DIR/website_manager/build/{site_name}/` (removed after deploy)
- CF credentials: `data/cloud_api_keys.json` (provider: cloudflare, compound key format)
