# Changelog

Notable changes to TubeCLI. Versions match `tubecli/__init__.py`.

## 2026.08.09.232 — 2026-11-09

### Fix: TubeCLI did not start on Python 3.10 and 3.11
- Versions .230 and .231 stopped at start on machines with Python 3.10 or 3.11:
  «SyntaxError: f-string: expecting '}'» in `tubecli/core/muse.py`. One line used f-string syntax that only
  Python 3.12 accepts. It is rewritten so it works on every Python version TubeCLI supports (3.10 and later).
- New test `tests/py310_fstring_compat_test.py` checks every file in `tubecli/` for f-string syntax that needs
  Python 3.12. On Python 3.10 or 3.11 it compiles every file.

## 2026.08.09.231 — 2026-11-07

### Video tasks
- **Paste subtitles as the content.** A pasted `.srt` or `.vtt` file is read as plain narration: cue numbers,
  timestamps, `WEBVTT` / `NOTE` lines and tags are removed. In Chinese, Japanese and Korean, the transcriber's
  spaces become «，». A pause of 0.6 s or more starts a new paragraph, so scenes split where the speaker pauses.
- **Content you give is not stopped by the niche check.** When you paste the text, give YouTube links or upload a
  voice file, the niche score is noted as a warning and the video goes on. Before, an agent with no niche set up
  stopped such a video at review on every Retry. Automatic publishing still stops off-niche videos.

### Task board: skills
- Skills no longer fail with «[Codex Error] wrong_thread». Skills that call the model (SOP and workflow skills)
  now call it off the server's main loop. Before, Codex refused the call, and other models froze the server
  while they answered.
- A skill that returns an error now marks its step as failed and the task as **Failed**, with the reason. Before,
  the error text was reported as the result and the task went to review.
- A task that asks for a video only goes to review when the skill gives a real video file: the file exists, is not
  empty and has a duration. «Done» with no file is a failed task.

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
