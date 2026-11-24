# Changelog

Notable changes to TubeCLI. Versions match `tubecli/__init__.py`.

## 2026.08.09.250 — 2026-11-24

### Keychain: groups, a proxy per account, and pasting many accounts
- In TubeCLI Cloud › your server › Keychain, **Paste accounts** opens a dialog: pick a group (each group in the list has a
  delete button, and **+** adds a new one), then paste rows straight from Google Sheets or Excel —
  email · password · recovery email · 2FA key · proxy. The preview lists each account with ticks and names the lines that
  will be skipped and why; it never shows a password, 2FA key or proxy login. An email that is already saved is updated
  (or skipped, if you choose), and an empty cell keeps the saved value.
- Every account can keep the proxy it signs in through, encrypted like the password; lists show only host:port. A browser
  profile created for the account uses that proxy.
- The account list filters by group. Deleting a group keeps its accounts and moves them to "No group".
- MCP clients can file an account under a group and give it a proxy (`keychain_save`), and list one group
  (`keychain_accounts`).

### Tokens stored in a git remote stay on your machine
- An extension cloned as `https://<token>@github.com/…` keeps that token in its git settings. TubeCLI no longer shows it:
  the extension list, the Market update check, the install record and git error messages hide the user name and
  password of the remote. Your git settings are not changed.
- Publishing to the Market removes them from the git URL and refuses a package that contains a GitHub token, naming the
  file. Every answer sent to an MCP client is masked as well.

## 2026.08.09.249 — 2026-11-22

### Claude, Codex and other MCP clients can manage YouTube
- Four new tools: `youtube_channels`, `youtube_videos` (filter by scheduled, private, unlisted or public),
  `youtube_schedule` (publish private videos at a set time, or cancel) and `youtube_update` (title, description, tags,
  category, privacy). They need the **Video Manager** extension 2026.11.22.170536 or newer from the Market.
- YouTube publishes a scheduled video by itself, so the machine does not have to be online at that time. Every time
  must carry a timezone and lie in the future; one wrong item refuses the whole call. A video that is already public or
  unlisted is never scheduled, because that would take it offline.
- Each tool uses exactly the account of the channel you name. Account emails and tokens are never returned. A read-only
  connection only gets the two read tools.

### The Market opens at once, with cleaner pages
- The Market shows the list saved on the machine immediately and checks for new versions in the background, instead of
  asking the server on every view, filter and search. It also opens offline.
- Extensions and templates are separate tabs. Extensions are grouped into **Updates available**, **Available** and
  **Installed**, with one button per card. Sell an item, My Listings, Check for updates and Log out are in the **⋯** menu.
- Small windows and phones keep the compact layout of the previous version. Android Window has its own icon.

### Agents: no repeated topics, fewer skipped runs
- A topic that already has an open task, a finished video or a published video rests for the niche's cooldown (21 days by
  default), however the keyword is worded.
- A browser profile that only looks busy (its live view is gone, or was left open for more than 6 hours) no longer blocks
  scheduled runs, and the log says what is holding a profile that really is in use.
- Daily keywords: if the agent's AI model fails, other configured models are tried before yesterday's keywords are reused.
- Unticking **Channel not verified** resumes a paused auto-publish at once.

## 2026.08.09.248 — 2026-11-22

### The Flow Terminal runs PowerShell on Windows machines
- The **SSH Terminal** node now works on Windows servers: it opens PowerShell 7 (`pwsh`) when it is installed, or the
  Windows PowerShell that comes with Windows. Before, it only said "Terminal only works on Linux/macOS servers".
- Copy and paste, resizing and closing work the same as on Linux. TubeCLI installs the small Windows terminal library
  it needs (pywinpty) with this update; a machine that still lacks it installs it the first time a terminal opens.

### The Market fits small windows and phones
- The top of the Market is two compact rows: search with your account and **Sell Item**, then the item types, price
  (All / Free / Paid) and sort order. The duplicate "All Categories" menu is gone.
- In a narrow window the title hides, the type chips and tags scroll sideways instead of wrapping, and on a phone the
  buttons shrink to icons and the cards fill the width. Press Enter in the search box to search.

## 2026.08.09.247 — 2026-11-20

### Claude and other MCP clients can save accounts to the Keychain — when you allow it
- New permission for a connection on TubeCLI Cloud › Connectors: **Allow saving accounts to the Keychain**. With it,
  the AI can store an account you give it (Google, TikTok, Facebook, X, Discord, Telegram or other — email/username,
  password, 2-Step Verification key or backup codes, recovery email, label, note) with `keychain_save`, and list your
  Keychain accounts with `keychain_accounts`.
- Secrets only go in: they are encrypted in the Keychain and no tool can read them back — the list shows only whether
  a password, 2FA key or recovery email is saved. They never appear in tool results, approval cards or logs. Saving
  the same platform + username again updates that account; an empty password keeps the saved one.
- Without the permission both tools refuse and tell the AI how you can turn it on. The Keychain API itself stays
  closed to the AI, and Codex on the machine does not get these tools.

### Windows machines get FFmpeg automatically
- The Windows installer now installs FFmpeg and ffprobe (winget, or a direct download into your user Programs folder
  when winget is missing — common on Windows Server / VPS). Before, it never installed them, so on a fresh Windows
  VPS voice and video tools failed with "[WinError 2] The system cannot find the file specified".
- Machines that are already installed fix themselves: when TubeCLI starts and ffmpeg or ffprobe is missing, it
  downloads them once in the background (about 200 MB unpacked) into %LOCALAPPDATA%\Programs\ffmpeg\bin and uses
  them right away. If the download fails it tries again 6 hours later.

## 2026.08.09.246 — 2026-11-19

### Agents can comment, watch live streams and follow channels
- The Schedule tab has three new tasks: **Comment**, **Watch live** and **Follow / Subscribe**. They run on YouTube or
  TikTok — whichever the browser profile or Android phone is signed in to (random when both).
- Comment: the agent watches a video on its topics, then its own AI writes one short comment from the video title in
  the agent's language. Comments with links, hashtags, @mentions or AI error text are not posted, and the typed text
  is checked in the box before it is sent. The old browser fallback that posted a canned comment is gone.
- Watch live: the agent watches a live stream and never chats. Follow: it subscribes / follows the channel of a video
  it watched, and skips channels it already follows.
- These are public actions on your accounts, so they only run when you turn them on — the AI routine generator never
  enables them. Each agent does at most 4 comments, 3 follows and 6 live streams a day; after that the run watches a
  normal video instead.

### Android phones show what they are signed in to
- With Android Window, each phone shows login chips (Google, Gmail, YouTube, TikTok @name), refreshed on every run.
  The routine only picks tasks the phone can do — for example no email tasks on a phone without a Google account.

### Fixed
- **Run now** on an agent that runs on an Android phone could freeze the server for up to 15 minutes. The run now
  starts in the background and its result appears in the agent's runs.

## 2026.08.09.245 — 2026-11-18

### Agents can run their daily routine on an Android phone
- In the agent settings, the profile picker has a new **Runs on: Browser | Android** switch. Pick a phone from the
  Android Window extension and the agent's daily routine runs in apps on that phone instead of a browser profile:
  Watch video → YouTube app, news and topics → Chrome app, email → Gmail app.
- Email on the phone uses the Google account signed in on it. Check email reads up to 5 unread emails and saves them
  to the agent's data collection. Reply email answers the newest unread email from a real person (no-reply senders
  are skipped). Send report writes a new email to the report recipients. The agent's own AI writes the text, and
  recipients, subject and body are checked before Send; if anything is off, the draft is discarded.
- If the Android Window extension is not installed, the run is logged as skipped. It never falls back to a browser
  the owner did not choose.

## 2026.08.09.244 — 2026-11-16

### Pasting long subtitles no longer freezes the form
- The Video content box no longer runs the browser spell check, autocorrect or auto-capitalisation. Spell check
  underlined almost every subtitle line and made the browser re-check hundreds of thousands of characters after a paste.
- The character count, video length estimate and YouTube link check now count the text once per change instead of
  6–8 times.
- For content longer than 20,000 characters, the count updates 0.3 seconds after you stop typing or pasting.
  Pressing Create right after a paste still counts the full text before the limits are checked.

## 2026.08.09.243 — 2026-11-16

### Paste longer subtitles into Video content
- When the content you paste is a subtitle file (.srt or .vtt), the 60,000-character limit now counts only the
  spoken words. Timestamps, cue numbers and WEBVTT / NOTE lines are no longer counted. Before, a subtitle file with
  about 30,000 characters of speech was refused.
- The counter under the box says «characters of speech (subtitle times removed)» for subtitles.
- The video length estimate also counts only the spoken words of subtitles.
- Pasted content can be up to 600,000 characters in total, including the timestamps.

## 2026.08.09.242 — 2026-11-15

### Automatic videos say why they were not published
- When an agent's automatic video is only rendered and not uploaded, the run note now gives the reason, for example
  «publishing paused itself: the last video was 17:51 long and this agent's channel is marked not verified».
- `GET /api/v1/codex/autopublish/{agent_id}` also returns `will_publish` and `why_not` (whether the next automatic
  video is uploaded, and the reason when it is not), plus `when`, `when_choices` and `slots`.
- `PATCH /api/v1/codex/autopublish/{agent_id}` also takes `channel_unverified` (false = the channel is
  phone-verified; this also clears a self-pause), `when` (`now` or `slots`; other values are refused) and `slots`
  (times such as «12:00, 19:00»). `when: slots` with no times is refused.

### Record a video you published by hand
- `POST /api/v1/codex/tasks/{id}/published` with the video's link (`https://youtu.be/<id>`, a `watch?v=` link or
  `https://studio.youtube.com/video/<id>`) or `video_id` writes the link on the task, moves it from review to done
  and counts it toward the agent's daily limit. Nothing is uploaded. A help link is refused, and one video cannot be
  recorded on two tasks.

## 2026.08.09.241 — 2026-11-15

### Dashboard menu on a phone and when collapsed
- On a phone (window under 720 px) the menu button now opens the full menu over the page. Choosing a page, tapping
  outside or pressing Esc closes it. Before, the button did nothing there.
- The menu button is centered in the collapsed menu. Before, it was pushed outside the 68 px strip.
- Groups in the collapsed menu are shown as one block each, with no indent, and the strip no longer scrolls sideways.
  Tap a group's icon to fold or unfold it.
- The «Update now» box no longer overflows the collapsed menu. It becomes one icon; tapping it opens the menu.
- Menu items in the strip are 44 px tall so they are easier to tap.

## 2026.08.09.240 — 2026-11-15

### Back up Content Studio videos to Google Drive from an AI app
- New connector tools `drive_accounts`, `drive_backup`, `drive_backup_status` and `drive_backup_cancel`. An AI app
  connected through TubeCLI Cloud can copy images and videos from a folder of Content Studio (for example
  `outputs/exports`) to a Google account that is already authorized on the machine.
- The owner turns this on per connection in TubeCLI Cloud › Connectors («Allow Google Drive backup»). It is off by
  default.
- A backup runs in the background, one file at a time, largest first. A file already in the Drive folder with the
  same name and size is skipped, a failed file is retried twice, and the backup stops with a clear message when
  Drive is full. Nothing is deleted on the machine and nothing is shared publicly.
- When a backup ends it writes a report in `Documents/TubeCLI backups`: each file with its size, Drive file ID and
  OK or ERROR, and the totals on the machine and on Drive.
- The File Manager and Drive APIs stay closed to connected AI apps. Only files directly inside a Content Studio
  folder that really are images or videos can be backed up.

### File Manager
- The filter and sort buttons (Video, Images, Recently edited…) and the search scope button are no longer white on
  the dark theme.
- On a narrow window or a phone, the path has its own row and scrolls to the folder you are in. Before, it was cut
  to «C: › Users ›…» and hidden under 560 px.
- New buttons next to the path: type or paste a path and press Enter to go there, and copy the current path.
  Copying also works when the page is opened over http.
- An agent on the machine can now upload files from TubeCLI's own data folder to Drive. Before, when TubeCLI was
  started by TubeCLI Connect, every file there was refused as «outside the allowed area».
- Uploading a file that is on the machine's disk to Drive now works up to 8 GB (was 512 MB).

### Auth Manager
- Pressing Authorize on a credential that only has a JSON file no longer opens Google's «Missing required
  parameter: client_id» page. A service account key says it needs no authorization (and that Drive upload needs an
  OAuth client). The JSON file of an OAuth client is read for its Client ID and Client Secret.

## 2026.08.09.239 — 2026-11-15

### Publish a video that is already rendered
- `POST /api/v1/codex/tasks/{id}/publish` uploads the finished video of a task in review to YouTube Studio, without
  rendering again. You can send your own title, description and tags. On success the task moves to done with the
  `youtu.be` link in its result. `GET` on the same path shows the job.
- Publish and edit jobs run one browser at a time. A job waits while free RAM is under 1.5 GB or a video is rendering,
  and the browser profile is closed after every job. Waiting jobs survive a restart.
- `PUT /api/v1/youtube/videos/{video_id}` changes the title, description and tags of a published video through
  YouTube Studio. `category_id` and `default_audio_language` are not applied yet. This path is new: check the result
  on YouTube.
- A manual publish counts toward the agent's videos-per-day limit and is refused when the limit is reached
  (`when: "slots"` or `ignore_daily_limit: true` to go past it).

### YouTube upload no longer leaves a draft without saying why
- After pressing Publish the upload script waits up to 30 seconds, presses the Publish button of a confirmation dialog
  if YouTube shows one, and presses again when the button is still enabled. If YouTube still does not publish, the
  task result quotes the error text found on the page.

### Automatic videos
- An agent no longer makes a second video on a topic it already covered in the last 21 days. The run shows
  `skip: duplicate topic`. A duplicate title found after the script is written stops the task before rendering.
- Daily keywords: a reply with quotation marks inside a query no longer breaks the refresh, and an agent no longer
  searches the same first query every day when its keywords were not refreshed.
- Channels marked «not verified» (15-minute limit): scripts are written at about 1600 words and trimmed to fit, also
  for render-only runs. Before, a 2000-word request produced 18-minute videos, publishing paused itself for good,
  and a video that could not be published was still rendered every day.
- `GET` / `PATCH /api/v1/codex/autopublish/{agent_id}` reads and sets the Publish switch and the daily limit of one
  agent. `POST /api/v1/agents/{id}/pause` and `/resume` stop and restart an agent's schedule and automatic videos.
- Title, description and tags at publish time: replies that are not strict JSON are read, other models are tried
  when the agent's model does not answer, and as a last step they are built from the script instead of left empty.

### Fixes
- The image step no longer stops a render when an older Content Studio does not report how many shots have a prompt.
- Auth Manager: editing a credential no longer erases its Client ID and Client Secret. Empty fields now keep the
  saved values, the form says what is saved, and an eye button shows the saved secret when the dashboard is opened on
  the machine itself (never through the tunnel).

## 2026.08.09.238 — 2026-11-14

### Preview a video before you create it
- The «Video from content» form of the task board has a new **Preview** button. It shows every setting of the
  video before anything starts: template (language, frame, length), the AI that writes the content, the AI that
  draws the pictures, the voice (including your own voice file, cut by your subtitles' times or by Whisper), the
  source, how the script is written, still pictures or video clips, subtitles, characters, thumbnail, the review
  stop, YouTube, Google Drive, watermark, and which steps will run.
- The preview checks once that the AI services answer: it asks the content AI for one word, checks the Muse
  accounts or the image key (nothing is drawn), the voice engine, and Content Studio with ffmpeg. Each check shows
  green, orange or red with the reason.
- **Back** returns to the form with everything you typed; **Create video** or **Add to queue** starts the video
  exactly as shown.

## 2026.08.09.237 — 2026-11-14

### New task: the buttons are at the top
- In the New task window of the task board, Cancel, Add to queue and Create are now at the top right, next to the
  title, instead of at the bottom. The window also sits at the top of the board. When the task board is a tall
  frame in Flow, you no longer scroll down to find the buttons.

## 2026.08.09.236 — 2026-11-14

### Your voice file is cut by your subtitles' times
- When the content you paste is a subtitle file (.srt or .vtt) and you add your voice file, the video uses the
  times in the subtitles to cut your voice file scene by scene. It no longer listens to the file again, so it needs
  no Whisper and takes seconds. The video's subtitles keep those times.
- A subtitle line that runs over a part with no speech (a film clip, music) is placed at the end of its time.
- If the subtitles do not belong to the voice file (their times run past its end) or do not match the script, the
  task says so and listens to the file instead.

### Whisper installs itself
- When the content is plain text with a voice file and the machine has no Whisper (faster-whisper), TubeCLI now
  installs it with pip the first time, in the Python that runs TubeCLI, and says so on the task board. Before, these
  machines guessed the cuts from the temporary voice, failed on long files, and kept the temporary voice.
- If the install fails, the reason is in the task's warning, and TubeCLI waits 6 hours before trying again.

## 2026.08.09.235 — 2026-11-14

### Muse errors say which server and which browser
- A failed Muse request (chat, image, or video, including `GET /api/v1/muse/v1/videos/jobs/{id}`) now returns
  `server_code`, `server_name` and `browser` (the browser profile that ran it) inside `error`. The message ends with
  the same label, for example «[server t3rwap (VPS Contabo) · browser muse-vinh-21]», so you know which machine and
  profile to check.
- When the request ran on a remote Muse node, the error names that node's server and browser, not the machine that
  forwarded it. An older node that does not report them is named by its address.
- The server name comes from TubeCLI Cloud. It is sent the next time the cloud signs in to the machine.

### TubeCLI Connect
- Downloading cloudflared no longer fails when Python is missing root certificates: it falls back to curl.exe, then
  PowerShell, which use the Windows certificate store. Certificate checks stay on.
- A machine with an older TubeCLI updates itself during pairing, then asks for the cloud key.

## 2026.08.09.234 — 2026-11-13

### TubeCLI Connect no longer asks for the dashboard password
- Pairing a machine with TubeCLI Cloud now needs only the pairing code. TubeCLI Connect creates a **cloud key** on
  the machine (`tubecli cloud-key --new`) and gives it to the cloud with the code. The cloud signs in with that key.
- The dashboard password stays on the machine. Changing or forgetting it no longer disconnects the cloud, so the
  errors «Dashboard password is wrong» in the pairing window and «TubeCLI login failed» in Flow no longer come from
  a password the cloud did not know about.
- The key is a long random string. The machine stores only its hash. Wrong keys count toward the same login lockout
  as wrong passwords. While the password is still the default 123456, remote access can still only change it.
- Remove the key in Settings → «Password & TubeCLI Cloud» → «Remove cloud key», or with
  `tubecli cloud-key --revoke`. The cloud loses access at once. `tubecli cloud-key --status` shows whether one is set.
- When a member is removed from a server, the cloud replaces the key (`/api/v1/auth/cloud-key/rotate`).
- A machine with TubeCLI older than this version still pairs the old way: the password field appears with an
  explanation. A machine paired the old way keeps working; enter a new pairing code in Connect to switch to a key.

## 2026.08.09.233 — 2026-11-10

### Niche channels no longer stop for days at «OFF-NICHE SOURCES»
- When fewer than 3 collected sources fit the niche, an automatic video no longer stops in review. It takes a topic
  from the agent's keyword bank (its daily keywords), skips topics used in the last 21 days or already in an open task,
  and writes from the primary text plus the on-niche sources. The task records `source: bank` and
  `keyword_source: bank`; `BANK_LOW` warns when fewer than 10 unused topics are left. Off-niche material is never used.
- Sources older than 30 days, and sources the niche gate rejected on an earlier run, are dropped before the gate
  instead of being judged again every day.
- When the Niche settings of an agent are empty, the «NICHE CONFIG» block of its system prompt is used
  (Must relate to, Deny terms, Minimum niche score).

### Daily keywords refresh again
- If generating the day's keywords fails, TubeCLI tries the machine's default model, then reuses the previous
  keywords instead of falling back to generic searches such as «github trending». The error is shown on the run in the
  agent's Activity. Queries with a blocked niche term are dropped. «Regenerate keywords» uses the agent's time zone.

### Publishing to YouTube Studio
- The publish step only accepts a real video link (youtu.be/<id>). A help link from the upload dialog is no longer
  reported as the published video. With no video id the step ends as «Needs a check» (UNVERIFIED), not success.
- If the channel name matches no API token and no browser profile (including a profile picked for publishing),
  publishing stops with a clear error instead of uploading to the profile's default channel.
- A template image model that fails permanently («model not supported») is reported once per model.

### Codex board
- A task an agent answers with a refusal or «I can't do this» ends as failed with the agent's reason, not in review.
- «Clean up the board»: accept auto-publish tasks that reached YouTube (never publishes again), and close failed
  tasks older than N days (kept, can be retried). Both show the count first and ask before running.

### Browser sessions
- Stuck sessions are closed and logged: past their time limit, hidden Muse sessions idle for 30 minutes, and manual
  sessions open for more than 4 hours (`browser_manual_max_hours`, 0 = off). Live-viewed sessions are never closed.
- Hidden Muse sessions take at most all but one slot of the scheduled-browser limit. A «busy» skip lists who holds
  the slots, and the agent's run shows why no video was created.
- `GET /api/v1/scripts/executions/history` accepts `include_log=false` and `log_tail=N`.

## 2026.08.09.232 — 2026-11-09

### Fix: TubeCLI did not start on Python 3.10 and 3.11
- Versions .230 and .231 stopped at start on machines with Python 3.10 or 3.11:
  «SyntaxError: f-string: expecting '}'» in `tubecli/core/muse.py`. One line used f-string syntax that only
  Python 3.12 accepts. It is rewritten so it works on every Python version TubeCLI supports (3.10 and later).
- New test `tests/py310_fstring_compat_test.py` checks every file in `tubecli/` for f-string syntax that needs
  Python 3.12. On Python 3.10 or 3.11 it compiles every file.

### TubeCLI Connect (Windows) no longer breaks the install after a crash
- Connect used to treat every failed start as missing libraries and ran `pip install -e .`. After the crash above,
  pip could not finish replacing `tubecli.exe` (the file was in use), and the launcher was lost. Connect then
  started `TubeCLI.bat`, which opens the interactive menu instead of the server («Aborted!»).
- Connect now reinstalls libraries only when the server log says a module is missing. For any other error it
  says so in the log and asks you to update TubeCLI.
- Connect only uses a `tubecli.exe` launcher; `.bat` and `.cmd` files are skipped, and it starts
  `python -m tubecli.main` instead.

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
