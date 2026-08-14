# CapCut TTS — AI Skill Guide

## Extension: capcut_tts

Text-to-speech through the user's own CapCut account. Wraps the bundled
CapCut-TTS Node server (loopback), which does the real CapCut Web login and
voice synthesis. The user adds their CapCut account(s) in the dashboard; the
extension stores them encrypted (AES-GCM) under the extension's data dir and
never sends them anywhere but CapCut itself.

The Node server is built lazily on first use. A pre-built `dist/` is shipped, so
a low-RAM VPS only installs the 7 runtime deps — it does not compile TypeScript.

## Available Commands

```bash
# List saved CapCut accounts (no passwords shown)
tubecli capcut-tts accounts

# Add / update an account (prompts for the password)
tubecli capcut-tts add-account you@example.com --label "chính"

# Remove an account
tubecli capcut-tts remove-account you@example.com

# Background server state
tubecli capcut-tts status
```

## API Endpoints

Base prefix: `/api/v1/capcut-tts` (behind the origin guard).

| Method | Path | Purpose |
|---|---|---|
| GET | `/accounts` | List saved accounts (masked) + server running state |
| POST | `/accounts` | Add an account `{email, password, label}` |
| DELETE | `/accounts/{email}` | Remove an account |
| POST | `/accounts/{email}/toggle?enabled=` | Enable/disable |
| POST | `/accounts/{email}/test` | Verify by synthesizing a one-word sample |
| GET | `/languages` | Available languages + voice counts |
| GET | `/speakers?email=&language=&category=` | Voices for an account |
| GET | `/preview/{speaker_id}` | Short audio sample of a voice |
| POST | `/synthesize` | `{email, text, speaker, speed, volume}` → audio/mpeg, saved to history |
| GET | `/history` | Recent synthesized files |
| GET | `/history/{filename}` | One saved mp3 |
| GET | `/status` | built / running / port / enabled-account count |

## Notes for agents

- `speaker` is a voice `id` from `/speakers`. Omitting it uses CapCut's default
  voice for the account.
- `speed` 1–20 (10 = 1.0x), `volume` 0–20 (10 = normal).
- Synthesize needs at least one enabled account, and the first enabled account
  seeds the Node server on boot — so add an account before calling `/synthesize`.
- Passwords are stored encrypted and are never returned by any endpoint.
