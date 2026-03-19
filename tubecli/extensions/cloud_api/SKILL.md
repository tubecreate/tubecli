# Cloud API Management — AI Skill Guide

## Extension: cloud_api
Manages cloud AI provider API keys for Gemini, OpenAI, Claude, DeepSeek, Grok.

## Available Commands

### List Providers
```
tubecli cloud-api providers
```
Shows all supported AI providers and whether keys are configured.

### Add API Key
```
tubecli cloud-api add-key <provider> <api_key> --label <label>
```
Providers: `gemini`, `openai`, `claude`, `deepseek`, `grok`

### Remove API Key
```
tubecli cloud-api remove-key <provider> --label <label>
```

### Test API Key
```
tubecli cloud-api test <provider> --label <label>
```

### List Keys
```
tubecli cloud-api keys --provider <provider>
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/cloud-api/providers` | List providers |
| GET | `/api/v1/cloud-api/keys` | List keys (masked) |
| POST | `/api/v1/cloud-api/keys` | Add key |
| DELETE | `/api/v1/cloud-api/keys` | Remove key |
| POST | `/api/v1/cloud-api/keys/test` | Test key validity |
| GET | `/api/v1/cloud-api/keys/{provider}/active` | Get active key |

## AI Usage
When an agent needs to call a cloud AI model, use the cloud-api extension to retrieve the API key:
1. Call `GET /api/v1/cloud-api/keys/{provider}/active` to check if a key exists
2. If no key, prompt the user to add one via `tubecli cloud-api add-key`
3. The agent's `cloud_api_keys` field can also store per-agent keys
