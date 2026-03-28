---
name: auth_manager
description: Manage OAuth credentials & tokens for Google, Facebook, TikTok
---

# Auth Manager Extension

This core extension manages OAuth credentials and authorization tokens for
multiple providers (Google, Facebook, TikTok). Other extensions can use it
to get valid access tokens for API calls.

## Usage from Other Extensions

```python
from tubecli.extensions.auth_manager.extension import auth_manager

# List credentials
credentials = auth_manager.list_credentials(provider="google")

# Get active access token (auto-refreshes if expired)
token = auth_manager.get_active_token("cred_abc123")

# Get full token data
token_data = auth_manager.get_token_data("cred_abc123")
```

## API Endpoints

- `GET /api/v1/auth-manager/providers` — List providers
- `GET /api/v1/auth-manager/credentials` — List credentials
- `POST /api/v1/auth-manager/credentials` — Add credential
- `POST /api/v1/auth-manager/credentials/{id}/authorize` — Start OAuth
- `GET /api/v1/auth-manager/tokens` — List tokens
- `GET /api/v1/auth-manager/tokens/{id}/active` — Get active token

## CLI Commands

- `tubecli auth providers` — List providers
- `tubecli auth list` — List credentials
- `tubecli auth add <provider>` — Add credential
- `tubecli auth authorize <id> -s <scope>` — Start OAuth
- `tubecli auth tokens` — List tokens
