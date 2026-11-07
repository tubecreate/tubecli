# Changelog

Notable changes to TubeCLI. Versions match `tubecli/__init__.py`.

## 2026.08.09.230 — 2026-11-07

### Video tasks: bring your own voice file
- **Your voice file (optional)** in the Content-video form of the Task board. Upload a recording of the text you
  pasted: the script is read word for word, and the file is cut scene by scene in place of text-to-speech.
- While the scenes are built, a temporary voice reads the text (CapCut when this machine has a CapCut account,
  otherwise Edge; never Muse). It is then swapped for your file. If the file does not match the text, the
  template's voice stays.
- Swapping in the file is faster (Whisper `base`, beam 1) and shows progress: transcribing, matching, cutting
  scene N of M.
- **Re-dub the narration with Muse** (off by default): Muse reads the whole script again in one take, in the voice
  you describe, and replaces the template's voice scene by scene. If Muse fails, the template's voice stays.

### Templates bring their characters
- **Characters** field in the Content-video form: picking a template fills in its cast. Remove a character with ✕,
  or add more from the character library or by uploading a sheet.
- Extension task forms (for example Pod Studio «Video from reference images») fill the image field with the
  template's own images. Remove each one with ✕; files you add are added to them.

## 2026.08.09.229 — 2026-11-05

### Browser: fewer processes and RAM per run
- **At most 2 tabs** in agent runs and in hidden (headless) browsers such as hidden Muse sessions; the limit was
  4 tabs and applied only to agent runs. When a third tab opens, the oldest tab closes; the tab in use is never
  closed. Browsers you open yourself with a window are not touched. On real news sites each ad frame from another
  domain runs in its own renderer process: 4 tabs measured 25–41 renderer processes and 1.4–2.5 GB. A hidden Muse
  session needs exactly 2 tabs (the Muse home tab and the working tab) while `muse_lanes` is 1.
- **Closing has a deadline.** At the end of an agent run, closing the browser now waits at most 30 seconds. If it
  hangs, the run exits and Playwright kills the browser tree, instead of leaving the browser running until the
  session timeout. A run that was about to retry no longer opens a second browser on the same profile while the old
  one is still alive.

## 2026.08.09.228 — 2026-11-05

### Public share links made by Claude (claude.ai connector)
- **No per-link approval.** Ticking "Allow public share links" for a connection in TubeCLI Cloud › Connectors now means
  consent in advance: `share_file` returns the public URLs in the tool result instead of an approval link.
- **Three URLs per file.** The result gives a page (`/s/<token>`), a raw URL (`/raw`) and a direct download URL
  (`/download`). They work with a plain HTTP GET, without sign-in, cookies or headers. Responses carry the right
  `Content-Type` and `Content-Length`, Range is supported, and `/download` is sent as an attachment with `nosniff`.
- **Short expiry.** Links last 30 minutes by default; `expires_minutes` accepts 1–1440. Expired links answer
  `410 Gone`, and `sweep_links()` clears expired records.
- **Media library files.** `share_find` and `share_file` accept files from the media library (`collection` +
  `filename`) or any path inside the data folder.
- **Batch sharing.** New `share_files` shares up to 100 files in one call and returns `{file, url, expires_at}` for each,
  plus the files that were refused and why.
- **Images and videos only.** Allowed: `.png .jpg .jpeg .webp .gif .mp4 .webm .mov`. Both the extension and the file's
  content (magic bytes) must be an image or a video, and the check runs again each time a link is opened. SVG, audio,
  documents, archives, HTML and executables are refused with "Only image and video files can be shared". The list
  lives in `SHAREABLE_TYPES` (`tubecli/core/public_share.py`).
- **Guards.**
  - Only files inside the data folder can be shared. `..`, symlinks leading outside, and sensitive folders and names
    (browser profiles, sessions, cookies, keychain, credentials, tokens, `.env`) are refused.
  - Tokens are 192-bit.
  - A connection can make at most 200 links an hour.
  - Every creation and download is logged to `data/file_manager/share_log.jsonl`.
- **Revoking.**
  - Unticking the box, disconnecting Claude or turning Claude off on a server revokes that connection's live links at
    once (`shares/revoke`).
  - A call that arrives without the `share` permission also revokes that connection's links.
  - `share_revoke` and the revoke button in File Manager return `410 Gone` from then on.
- **Unchanged.** Approval links for other actions (delete, cancel, stop a browser, install an extension, Agent Town)
  work as before. Links the owner makes in File Manager keep working as before. The one change for them: expired or
  revoked owner links now answer 410 instead of 404.
