# -*- coding: utf-8 -*-
"""Deploy tubecli-scripts to Cloudflare Workers, without wrangler.

Uploads a module worker: worker.js as ESM plus dashboard.html as a Text module
that worker.js imports as a string.

Credentials come from the environment and are never stored here:

    CF_ACCOUNT_ID   32-hex account id
    CF_EMAIL        account email
    CF_API_KEY      Global API Key, or set CF_API_TOKEN for a scoped token
                    (a scoped token is strongly preferred — see README)

ADMIN_TOKEN and CLIENT_KEY are generated on first run into tools/secrets.json,
which is gitignored, and reused on every later deploy.
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
SECRET_FILE = os.path.join(HERE, "secrets.json")

NAME = "tubecli-scripts"
DB_ID = "6cce8231-6a45-43ed-b115-f060758134a6"   # tubecli-scripts-db

ACC = os.environ.get("CF_ACCOUNT_ID", "")
if not ACC:
    sys.exit("CF_ACCOUNT_ID is not set")

if os.environ.get("CF_API_TOKEN"):
    AUTH = {"Authorization": "Bearer " + os.environ["CF_API_TOKEN"]}
elif os.environ.get("CF_API_KEY") and os.environ.get("CF_EMAIL"):
    AUTH = {"X-Auth-Email": os.environ["CF_EMAIL"], "X-Auth-Key": os.environ["CF_API_KEY"]}
else:
    sys.exit("set CF_API_TOKEN, or both CF_EMAIL and CF_API_KEY")

BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACC}"


def call(url, data=None, headers=None, method="GET"):
    req = urllib.request.Request(
        url, data=data,
        headers={**AUTH, "User-Agent": "tubecli-deploy/1.0", **(headers or {})},
        method=method)
    try:
        return json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"success": False, "errors": [{"message": f"HTTP {e.code}"}]}


def show(label, res):
    ok = res.get("success")
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print("       " + json.dumps(res.get("errors"), ensure_ascii=False)[:400])
    return ok


if os.path.exists(SECRET_FILE):
    creds = json.load(open(SECRET_FILE, encoding="utf-8"))
    print("reusing the tokens in tools/secrets.json")
else:
    creds = {"ADMIN_TOKEN": secrets.token_urlsafe(24),
             "CLIENT_KEY": "tcli_" + secrets.token_urlsafe(18)}
    json.dump(creds, open(SECRET_FILE, "w", encoding="utf-8"), indent=2)
    print("generated new tokens into tools/secrets.json")

metadata = {
    "main_module": "worker.js",
    "compatibility_date": "2026-07-01",
    "bindings": [{"type": "d1", "name": "DB", "id": DB_ID}],
    # Without this, re-uploading the script drops every secret it does not
    # re-declare — the classic way a working deploy turns into 503.
    "keep_bindings": ["secret_text"],
}

parts = [
    ("metadata", "metadata.json", "application/json", json.dumps(metadata).encode("utf-8")),
    ("worker.js", "worker.js", "application/javascript+module",
     open(os.path.join(SRC, "worker.js"), "rb").read()),
    ("dashboard.html", "dashboard.html", "text/plain",
     open(os.path.join(SRC, "dashboard.html"), "rb").read()),
]

boundary = "----tubecli" + uuid.uuid4().hex
body = b""
for name, filename, ctype, payload in parts:
    body += (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
             f"Content-Type: {ctype}\r\n\r\n").encode("utf-8")
    body += payload + b"\r\n"
body += f"--{boundary}--\r\n".encode("utf-8")

print(f"\nuploading {NAME} ({len(body) / 1024:.1f} KB)")
if not show("upload worker", call(
        f"{BASE}/workers/scripts/{NAME}", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="PUT")):
    sys.exit(1)

for key, value in creds.items():
    show(f"secret {key}", call(
        f"{BASE}/workers/scripts/{NAME}/secrets",
        data=json.dumps({"name": key, "text": value, "type": "secret_text"}).encode(),
        headers={"Content-Type": "application/json"}, method="PUT"))

show("enable workers.dev route", call(
    f"{BASE}/workers/scripts/{NAME}/subdomain",
    data=json.dumps({"enabled": True, "previews_enabled": False}).encode(),
    headers={"Content-Type": "application/json"}, method="POST"))

sub = call(f"https://api.cloudflare.com/client/v4/accounts/{ACC}/workers/subdomain")
host = (sub.get("result") or {}).get("subdomain", "")
print(f"\nURL: https://{NAME}.{host}.workers.dev")
print("tokens are in tools/secrets.json (gitignored)")
