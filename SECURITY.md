# Security

TubeCLI is a self-hosted agent runtime: it runs code, drives browsers that hold your logins, and stores API keys. This page says what protects it, what does not, and how to report a problem. It is written for people and for AI reviewers reading the source.

## Reporting a vulnerability

Please report privately rather than in a public issue: use **GitHub → Security → Report a vulnerability** on [tubecreate/tubecli](https://github.com/tubecreate/tubecli/security/advisories/new). Include the commit you looked at, the file and line, and how to reproduce. We answer with an assessment, then the fix commit.

## Threat model in one paragraph

The **machine owner is fully trusted** — an authenticated owner can, by design, install extensions (arbitrary code), read stored API keys and drive every browser profile. Everything below exists to make sure **nobody else becomes the owner**: not a stranger on the internet, not a web page open in the owner's browser, not a visitor of a public agent.

## What protects the API

| Layer | Where | What it does |
|---|---|---|
| Login gate | `tubecli/api/server.py` → `_require_login`, `tubecli/core/auth.py` → `check_request`, `default_password_refusal` | Every request that is not from loopback needs a session cookie (password login, scrypt-hashed, throttled); while the password is still the default, a remote session may only change it. **Fail-closed**: if a check itself errors, the request gets `503 auth_unavailable`, never the endpoint. |
| Proxy awareness | `auth.behind_proxy` | A request carrying `X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `X-Forwarded-Host` or `CF-Connecting-IP` is never treated as local, so a tunnel or reverse proxy on the same host cannot turn the loopback exemption into a bypass. |
| Origin guard | `_guard_cross_origin`, `tubecli/core/origin_guard.py` | Refuses cross-origin browser requests (CSRF). **Fail-closed** since 2026-10-13. It is not authentication: clients without an `Origin` header are judged by the login gate alone. |
| Guest scope | `auth.guest_scope_for`, `_guest_allowed` | People a workspace is shared with get a token limited to that workspace's paths; outside it → 403. |
| Public agents | `tubecli/core/public_agents.py` | Agent Town calls reach `/api/v1/public/*` only with an HMAC signature, a ±5-minute timestamp and a one-time nonce, and can run only the skills the owner published. |
| Approval gate | `tubecli/extensions/codex/manager.py` | Tasks the AI creates wait in `pending_approval`; deploying, publishing and deleting need a human. Append-only JSONL audit trail per task. |

Exempt from login (reachable without a session): `/login`, `/api/v1/auth/login`, `/api/v1/auth/status`, `/api/v1/auth/guest-login`, `/api/v1/health`, the OAuth callback (guarded by a one-time `state`), the signed public-agent routes, share links `/s/<token>` (the token is the key), public hire file downloads, and static assets. The full list is `_AUTH_EXEMPT_EXACT` / `_AUTH_EXEMPT_PREFIX` in `server.py`; adding a path there is a security decision and needs a comment saying what guards it instead.

## Installing extensions

`POST /api/v1/extensions/install` (and the Market's `/api/v1/market/items/install-git`) clones a git repository and runs its code — it is remote code execution **for the owner**, on purpose.

**Who can call it.** Only the owner: the routes are not in the exempt list, so the login gate decides. `tests/security_gate_test.py` (section E) drives both routes on the real app and checks that the install function is **never reached** for: no session; loopback carrying any forwarding header (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `X-Forwarded-Host`, `CF-Connecting-IP`, including a forged `X-Forwarded-For: 127.0.0.1`); a forged session cookie; the read-only scraped key; a Muse node key; workspace and public guest tokens (403); odd path spellings; and a gate whose checks raise (503). Two positive controls show it *is* reached from loopback without proxy headers and with a valid session.

**What it accepts.** The URL must be `https://…`, `git@host:owner/repo` or an existing local folder; URLs starting with `-`, other transports (`ext::`, `file://`, `http://`) and control characters are refused, and `git clone` is called with `--` before the URL.

**Pinning a reviewed commit.** Pass the full commit hash, either as `commit` in the request body, as `--commit` on the CLI, or as a `#<hash>` suffix on the URL (which works everywhere a URL is accepted):

```bash
tubecli extension install https://github.com/owner/ext.git --commit 0123456789abcdef0123456789abcdef01234567
```

The clone is moved to that commit and the install is refused unless `HEAD` equals it — before the manifest is read or any dependency is installed. Only full hashes are accepted: branches and tags can be moved, and whoever controls a repository can mint a second commit with the same short prefix. A pinned extension is never moved by "update"; reinstall with a new hash to move it.

**What was installed.** Every install and update is recorded in `data/extension_provenance.json`: source URL, commit, whether it was pinned, the previous commit on update, and a SHA-256 of `requirements.txt`, `package.json` and `package-lock.json`.

**What is not isolated.** An extension runs **in the TubeCLI process**, as the same OS user, with the same file, network and API access — like a VS Code extension or a pip package, not like a sandboxed plugin. Its Python and Node.js dependencies come from PyPI and npm as its `requirements.txt` / `package.json` declare (pip enforces hashes when the requirements file carries `--hash=`; npm follows `package-lock.json` integrity hashes when one is committed). There is no sandbox, no per-extension permission model and no signature check. Review the code and its dependency files at the commit you pin, and install only extensions you trust; marketplace extensions are published by TubeCreate.

## Secrets at rest

| File (under `data/`) | Holds | Protection |
|---|---|---|
| `auth.json` | password hash (scrypt), session secret | 0600, atomic write |
| `cloud_api_keys.json` | provider API keys | 0600, atomic write (`core/private_file.py`) |
| `auth_manager.json` | OAuth client secrets, access/refresh tokens | 0600, atomic write (`core/private_file.py`) |
| Keychain vault | social-account passwords | Fernet-encrypted, key file 0600; agents never read the plaintext |
| `codex_gpt` accounts | ChatGPT `auth.json` per subscription | 0600 |

0600 means "only this OS user"; on Windows the files inherit the ACL of the user profile. This is not encryption at rest — anyone who runs code as the same OS user can read these files, which is why extension installs require the owner. If a token may have leaked, revoke it at the provider and re-authorise.

## Known residual risks (stated, not hidden)

- **Default password `123456`.** The installer offers it so a `curl | bash` user has something to type. Since 2026-10-13 a **remote** session made with it can only change it: every other route answers `403 password_change_required` (`auth.default_password_refusal`) and the login page shows the change form with no "skip". The machine itself is unaffected, and so are the installer, the pairing client and the provisioner, which change it over loopback; TubeCLI Cloud refuses to log in to a machine on the default and forces the change. Someone who reaches the port first can still log in with it and set a password of their own, so **set yours at install, or with `tubecli password`.**
- **Bind address.** Desktops bind `127.0.0.1`. Headless servers bind `0.0.0.0:5295` so the dashboard can be opened by IP; behind TubeCLI Cloud the machine is reached through a Cloudflare tunnel and does not need the port open. Firewall 5295 if you do not use it directly.
- **Loopback is trusted.** Any process on the machine can call the API without a session. The machine is the owner's; do not run TubeCLI on a host you share with untrusted users.
- **A same-host proxy must say it is a proxy.** The loopback exemption is safe behind nginx, Caddy or `cloudflared` because they add `X-Forwarded-For` / `CF-Connecting-IP`, which makes the request count as remote. A proxy or port-forwarder on the same machine that adds **no** forwarding header (a raw TCP forward, `socat`, `ssh -L` shared with others, a custom proxy with headers stripped) makes every request it relays look local. If you put one in front of TubeCLI, configure it to send `X-Forwarded-For`.
- **Extensions are not sandboxed.** See *Installing extensions*: pin the commit you reviewed.
- **Install scripts are piped from the network.** If you prefer, download and read them first (below).

## Verifying before you run

```bash
curl -fsSLO https://raw.githubusercontent.com/tubecreate/tubecli/main/install.sh
less install.sh            # read it
bash install.sh
```

```powershell
irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install.ps1 -OutFile install.ps1
notepad install.ps1        # read it
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

To pin a reviewed version, clone and check out a specific commit, then follow *Manual Installation* in the README.

## Regression tests

`tests/security_gate_test.py` loads the real FastAPI app and asserts: no session → 401; a raising auth check → 503, never 200; a raising origin guard → 403; a remote session on the default password reaches only the password change; the install routes are unreachable without the owner (section E, above); refused git URLs; commit pins bind, short hashes are refused, a pinned extension is not auto-updated, and provenance is recorded (section F); secret files written 0600. `tests/auth_test.py` covers hashing, throttling, sessions and the proxy rule.
