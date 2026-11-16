# Storigen (lite) — Auto-ID engine

Gives every Blaze story a unique clip ID, follows the exported file from the **Playout INBOX** to the finished **MXF on Nitro**, and tells the desk when the clip is ready to be attached to the right story.

* One Python program. **No Docker, no WSL2, no VM, no packages to install.** Needs only Python 3.9 or newer.
* Runs the same on **Mac** (tested design target) and Windows (script included, not yet tried on a real PC).
* It only **reads** the Playout and Nitro folders. It never moves, copies, renames or deletes a file.

## The flow

```
Blaze story  ->  ID made  ->  editor exports with the ID in the file name  ->  Playout/INBOX/<NEWS|PROGRAMS|PROMO|ADS>
    your existing job converts it, the original disappears from INBOX, the MXF lands in Nitro ONAIR/<date>/<category>
    watcher: file in INBOX = EXPORTING;  original gone AND MXF with the same ID on Nitro (size stable) = ON_NITRO
    Blaze shows the clip (placeholder turns green, or the desk attaches it)  ->  desk presses Mark done
```

States: `WAITING_FOR_CLIP`, `EXPORTING`, `ON_NITRO`, `ATTACHED` (desk confirmed), `NEEDS_DESK` (something needs a person, with the reason), `QUARANTINED`.

## Two ways to link a clip to its Blaze story: `LINK_MODE` in `autoid.env`

| | `LINK_MODE=placeholder` (default) | `LINK_MODE=story_id` |
|---|---|---|
| Where the ID comes from | The journalist types the **rundown name** and **story name** on the web page | A feed reports the story with **Blaze's own story ID**; the ID is made automatically |
| How the story is tied to the clip | The journalist pastes the ID into the **placeholder's Media Slug** in that story (Media Search > Placeholder). Blaze links it. | The ID is tied to Blaze's story ID. The desk opens the story from a link and attaches (Media Search > Playout > paperclip) |
| Needs from Blaze | A Placeholder button with an editable Media Slug | Story and rundown IDs from Blaze: MOS device entry (needs Karthavya), or your own feed script |
| Typing IDs by hand | Always on | Off (set `ALLOW_MANUAL=1` for a fallback) |

Everything else (ID format, watcher, states, alerts, desk buttons, logins) is the same in both modes.

## Upgrading (for example 9.16.0 to 9.16.1)

1. Stop nothing yet. Copy the new files over the installed folder: **do not overwrite `autoid.env` or the `data` folder** (your settings, users, database and ledger live there). Add any new lines from `autoid.env.example` to your `autoid.env` if you want to change a default (the defaults work without them).
2. Restart the one service that runs everything: Mac `launchctl kickstart -k gui/$(id -u)/com.autoid.lite`; Windows `Stop-ScheduledTask AutoID; Start-ScheduledTask AutoID`. The web server and the Blaze poller both restart, and the server brings the database up to the new schema by itself, keeping all data (`data/backups` is the place to restore from).
3. Check: `python3 autoid.py status`, open the page (the footer shows the version), and read the poller log.

## Install on a Mac

1. Install Python 3.9+ if `python3 --version` says less (python.org installer, or `xcode-select --install`).
2. Copy this folder to the Mac, then in Terminal inside it: `./deploy/mac/install_mac.sh you@company.com`
   It creates `autoid.env` (with fresh secrets and the first admin password, printed once) and a launchd job.
3. Mount the shares (`deploy/mac/mount_shares.sh`, edit the two lines) so they appear as `/Volumes/...`. Use a **read-only** account for Nitro.
4. Edit `autoid.env`: `LINK_MODE`, `EXPORTS_DIR`, `INBOX_SUBDIRS`, `NITRO_DIR`. Then: `python3 autoid.py doctor` (fix every FIX line) and `python3 autoid.py selftest`.
5. Start: `launchctl load -w ~/Library/LaunchAgents/com.autoid.lite.plist`. Open `http://<mac-name>:8080`.
6. Always-on Mac: `./deploy/mac/keep_awake.sh` (no sleep, restart after power failure). Automatic login is needed for the launchd job and is not available while FileVault is on. macOS may ask once to allow access to network volumes: allow it.

Windows: `deploy\windows\install_windows.ps1` (run as Administrator); use UNC paths (`\\nas\Playout\INBOX`) in `autoid.env`.

## Daily use

**Placeholder mode.** Editor or journalist: web page > rundown name + story name (copy them from Blaze) > Create ID > in Blaze open that story > Media Search > Placeholder > paste the ID into Media Slug > Save. The editor exports the file named exactly with the ID into Playout. When the row turns `ON_NITRO`, check that the red clip in the story turned green (if not: Media Search > Playout > paperclip), then press **Mark done**.

**Story-ID mode.** IDs appear on the page by themselves. Editor copies the ID, exports. At `ON_NITRO` the desk presses **Open in Blaze + copy ID**, attaches from Media Search > Playout, presses **Mark attached**.

A same rundown + story name on the same day is flagged as a duplicate before a second ID is made. Each file version gets its own ID (`+ Version` adds `_V2`).

## Feeding stories (story_id mode)

* **MOS gateway** (built in): `MOS_ENABLED=1`, add a MOS device in Blaze pointing at this machine (ports 10540 and 10541). `ONLY_RUNDOWNS=9 PM Bulletin,R123` limits IDs to chosen rundowns (exact roID or text in the rundown name). Raw messages are kept in `data/gateway/mos_capture.log`. `tools/mos_sniffer.py` is a passive listener for testing what Blaze sends.
* **Any script or tap**: `python3 tools/push_story.py --rundown-id RO1 --rundown-name "9 PM" --story-id 2669125 --slug "EXP VNR AGRI"`, or call the API directly with the header `X-API-Key` (the value in `autoid.env`):
  `POST /svc/stories` {blaze_rundown_id, blaze_story_id, slug, rundown_name}  ·  `POST /svc/rundowns/sync` {blaze_rundown_id, rundown_name, stories:[{blaze_story_id, slug}]} (the complete list; missing stories are removed and their clips held for the desk)  ·  `POST /svc/stories/delete`  ·  `POST /svc/stories/rename`.
  The same story ID always returns the same clip ID.

## Commands

`python3 autoid.py init | run | status | doctor | selftest | backup`. Sample dashboard with made-up stories and no server: `python3 tools/make_standalone.py --out demo.html`, then open the file. Logs: `data/logs/` (rotated). Database: `data/autoid.db`; a copy is made daily in `data/backups/` (14 kept). Update: replace the program files, keep `autoid.env` and `data/`, then `launchctl unload` and `load` the job.

## Alerts

The page shows problems in red. Optional: `ALERT_WEBHOOK_URL` (Teams/Slack style) or SMTP settings. Alerts fire for: watcher or gateway silent, NAS/Nitro folder not reachable (a share that is not mounted is detected, not treated as empty), file stuck in INBOX, file gone from INBOX with no MXF on Nitro, a file name with no ID or a mistyped ID, a story removed in Blaze while its clip is already on Nitro.

## Rules worth knowing

* The file name must **start with the ID** (`YYYYMMDD_NNNNC_SLUG`). The MXF on Nitro must keep that start (slug and extension may differ).
* Slugs are ASCII: a Tamil-only story name becomes `STORY` in the ID. The original name is kept in the record and shown on the page.
* "Gone from INBOX" means the name no longer appears in the folder listing (deleted, moved or renamed with a leading dot). A folder that cannot be read stops the poll; it is never treated as "finished".
* Logins: local users, roles editor/admin, a valid-upto date per user. Passwords are salted PBKDF2. The page runs on plain http inside the LAN (the Blaze page itself is http). Put HTTPS in front and set `COOKIE_SECURE=1` if you need it.

## What has and has not been tested

Tested (Linux, automated): the server over real HTTP in both modes, logins and rules, duplicates, the watcher against fake Playout and Nitro folders (file seen, file gone + MXF, no MXF, bad name, restart), MOS message handling, the supervisor start/stop, the self-test. The Mac mount detection was tested on sample `mount` output, and the launchd file by generating and parsing it, **not on a real Mac**.
Not tested: a real Mac or Windows machine, real Blaze, real Nitro, a real MOS device, the placeholder behaviour in your Blaze. Run `selftest`, then follow the spikes in `docs/SPIKES.md`.

## Folder layout

`autoid.py` launcher · `autoid.env` settings · `autoid_lite/` server, watcher, gateway, web page · `deploy/` Mac and Windows scripts · `tools/` sniffer and feed script · `tests/` · `data/` database, logs, backups (created on first run).
Tests need pytest (`pip install pytest`, only for development): `python3 -m pytest tests`.

## Blaze poller (no MOS, no licence): `tools/blaze_poll.py`  (phase 1: read only)

Blaze's own web page uses a REST service (`/DataService/...`). The poller reads the same service with a logged-in session, so story IDs arrive without MOS.
Use with `LINK_MODE=story_id`, then in `autoid.env`: `BLAZE_POLL=1`, `BLAZE_SESSION_ID`, `BLAZE_USERNAME` (the two cookies of a logged-in Blaze tab), `BLAZE_SHOW_IDS=34427` (the number in `/DataService/shows/34427/slugs`).
Commands: `python3 tools/blaze_poll.py show 34427` (what Blaze returns for a rundown) · `once` (one pass) · `media` (Blaze's Playout list) · `probe <storyId> [versionId]` (find itemId and order) · `summary [N]` (last N days, default 5) · `run`.
It never writes to Blaze. With `BLAZE_ATTACH=dry` it finds the finished file in Blaze's media list (matched on the ID at the start of the file name) and only **prints** the attach call it would make. The live attach is phase 2.
The session cookie expires: when it does the page turns red (`blaze_poll` silent) and the log says PROBLEM. The login call comes later.

The registry keeps the full map for every story: show (rundown) ID, slug ID, story ID, position and clip ID. `python3 tools/blaze_poll.py map` prints it. Only the story ID and show ID are used for the attach; the slug ID is stored for later use.

### Trust ladder and the daily tool-vs-desk report
The poller READS every followed story's clips from Blaze each minute (`BLAZE_RECONCILE_SECS`). A clip carrying one of our IDs is remembered in `data/blaze_ledger.db`; when it sits in the right story the clip is marked ATTACHED in Auto-ID (`BLAZE_CONFIRM=1`, read-back only, so the desk no longer has to press Mark done).
The ledger also keeps what the tool WOULD have attached. Once a day (when the broadcast day changes) it writes `data/reports/agreement_YYYYMMDD.csv` and logs a summary; `python3 tools/blaze_poll.py report [YYYYMMDD]` prints it any time.
Per clip: AGREE, DISAGREE (desk used another file), TOOL_MISSED (desk attached a file the tool never found), WRONG_STORY, DUPLICATE, OVERDUE, WAITING, NO_FILE. Agreement = AGREE / (AGREE + DISAGREE + TOOL_MISSED + WRONG_STORY + DUPLICATE). Turn the live attach on only after the numbers have been clean for days on real bulletins.
`BLAZE_IGNORE_TITLES` lists template rows (BREAK, OPEN MONTAGE ...) that never get an ID; the whole title must match.

`BLAZE_ONLY_FORMAT_IDS` (for example `20,21,23,27`) limits IDs to the chosen Blaze story formats; the title list still removes template rows inside those formats.
Mac install also sets a nightly restart at 04:30 (`com.autoid.lite.restart`, started with `launchctl load -w ~/Library/LaunchAgents/com.autoid.lite.restart.plist`). It only clears memory; it does not renew an expired Blaze session cookie.

### The two lines to watch (attach dry run) and the 5-day check before going live
Live attach **exists but is OFF**. The default is `BLAZE_ATTACH=dry`, which only logs. In `dry` the poller writes these lines to the log and, with the date, to `data/reports/attach_watch.log`:

```
READY ON NITRO    clip 20261107_0003J_EXP_VNR is on Nitro: ready for story 726521 "EXP VNR AGRI" (show 34498 07_11_14:00 PM Bulletin, row 148)
GOING TO ATTACH   clip 20261107_0003J_EXP_VNR (file 20261107_0003J_EXP_VNR.mxf, media 1105862, 50s) to story 726521 "EXP VNR AGRI" (show 34498 ..., row 148) | order=149 itemId=937639 | DRY RUN: nothing sent to Blaze
                  would send: POST /DataService/stories/726521/clips/  clipType=MEDIA&mosObjectId=1105862&...&order=149&itemId=937639
```
Each line appears once per clip (remembered in the ledger, so a restart does not repeat it). A `| CHECK: ...` tag means something is unconfirmed: the story format has no verified itemId rule (`BLAZE_VERIFIED_FORMATS`), the story has no script item, or it is linked in several shows. Other lines: `ALREADY IN STORY` (nothing to do) and `AMBIGUOUS` (two files carry the ID; the desk chooses).

The file is found by searching Blaze's media list for the clip ID (`title` filter), and exactly one match is required. `itemId` is the item with the lowest `arrangeOrder` in the story's first version; `order` is the row position + 1; `duration` is whole seconds, rounded down.

**Five-day check:** `python3 tools/blaze_poll.py summary 5` prints one line per day (what the tool would have attached against what the desk really attached) and the total. Read `attach_watch.log` for every CHECK line and every DISAGREE / TOOL_MISSED row in the daily CSV. Going live is a separate decision after that.

### Live attach (off by default) and the installation guide
**Open `docs/INSTALL.html`** for the full installation steps (Mac and Windows), the first checks, the 5-day dry watch and the go-live steps.
Live needs three settings together (`BLAZE_ATTACH=live`, `BLAZE_LIVE_SHOW_IDS`, `BLAZE_LIVE_CONFIRM=YES_ATTACH_FOR_REAL`); with any missing the poller refuses to start. A clip is attached for real only when every rule passes: its show is on the allowlist, it is on Nitro, exactly one settled file matches in Blaze, the story format is verified and there is no `CHECK` tag, the kill-switch file is absent and the hourly limit is not reached. It is attached **once** (the attempt is written to the ledger before the call), the story is read back, and anything unclear is handed to the desk (`NEEDS_DESK`) and never repeated. Three failures in a row stop live by themselves.
Commands: `blaze_poll.py live` (status), `undo <clip ID> [blazeClipId]` (remove a clip the tool attached), `live-retry <clip ID>` (allow one new attempt). Not sent: the `scriptDur` update the page sends after an attach or delete (unconfirmed): check the story duration in Blaze.

### Dashboard and report page (v9.2)
Open `http://<machine>:8080` for the story tracker (counts, filters, story cards, per-story history). The button **Tool vs desk report** opens the page the poller writes to `data/reports/agreement_YYYYMMDD.html` (also `/report` and `/report/YYYYMMDD`). See `docs/INSTALL.html` section 7A and `docs/CHANGES_v92.md`.

### Shows found automatically (v9.3)
`BLAZE_SHOW_IDS=auto` makes the poller ask Blaze for the broadcast day's shows and follow all of them (about 36 a day; shows near air time are read every pass, the others every 2 minutes). `python3 tools/blaze_poll.py shows` prints the list. With `auto`, live attach is allowed by time slot (`BLAZE_LIVE_MASTER_IDS`), and after a live attach the story's script duration is set the way the Blaze page does. See `docs/CHANGES_v93.md`.

### Complete-day polling and paged dashboard (v9.4)
Every show of the day is read every 15 s, several at a time; changes (new, removed, swapped, retitled, moved slugs; attachments added, removed, replaced) are detected and logged, snapshots survive a restart, and a failing show never blocks the others. `python3 tools/blaze_poll.py stats` prints the measured statistics; `python3 tools/bench_polling.py --root .` repeats the before/after benchmark on a simulated Blaze. The dashboard list is paged, searchable and filterable by show. See `docs/CHANGES_v94.md`.

### Merged release (v9.5.0), after-midnight look-ahead (v9.5.1), remembered settings and CSV export (v9.5.2), new-version handling (v9.6.0)
v9.5.0 merges the two v9.4.6 builds: the polling engine, ledger tables and server-side paging of the "venkat" build, and the deadline-bounded reads, completed-show handling, day close/open and dashboard features of the plain build. Details, measurements and the trade-offs: `docs/CHANGES_v95.md`.
New versions (v9.6.0): `BLAZE_VERSION_MODE=desk` (default) never attaches a `_V2`+ clip, the desk is told; `auto` attaches it and then removes the older version's clip (second call, only after the attach is verified). After-midnight shows (v9.5.1): `BLAZE_SHOW_LOOKAHEAD_HOURS=5` follows the next date's shows that start within 5 hours and before the broadcast day ends (05:00), so a 00:00 show is followed from the evening; `blaze_poll.py shows` lists them. The page remembers stories per page, filter, bulletin and view; **Export CSV** downloads the whole day's list (all pages) and **Print** prints the screen. Day control: `python3 tools/blaze_poll.py close-day [YYYYMMDD]` pauses reading the shows of a broadcast day (snapshots are kept, the status pill does not go red); `open-day [YYYYMMDD]` resumes it. The dashboard has a **By bulletin** view, shows the story name and bulletin time, searches every word across slug, story name, clip ID, story, slug and show IDs and the bulletin time, and tells the desk when a clip becomes ready on Nitro.

## Try everything on one machine (fake Blaze, fake Playout and Nitro folders): `tools/demo.py`
Nothing real is touched. `py tools\demo.py setup` once; then window 1 `demo_home\1_start_server.bat` and window 2 `demo_home\2_play.bat`. In window 2 you act as editor, converter and desk
(`story`, `export`, `convert`, `attach`, `rename`, `delete`, `expire`, `list`, `log`, `report`; type `help`). Web page: http://127.0.0.1:8090. `py tools\demo.py reset` starts again from nothing.

### Release 10.3.0: the **Ready feed is now a table** (newest first, search, click a story to open it, **Quick test attach** button on every row; see docs/CHANGES_v1030.md)

### Release 10.2.0: **Ready feed** (button / F key): a live, searchable list of clips that are ready (story, clip ID, MOS object ID, media name, status) with a toast + optional sound and desktop notification; optional chat message via `READY_WEBHOOK_URL` (see docs/CHANGES_v1020.md)

### Release 10.1.1: the 5 s refresh no longer rebuilds the page (inspect elements, select text, hold drop-downs open); **Pause refresh** button / P key (see docs/CHANGES_v1011.md)

### Release 9.13.1: why a clip is not attached (on its card), warning when autoid.env was edited but not applied, one poller at a time (see docs/CHANGES_v9131.md)

### Release 9.13 (restructured build)

Same behaviour and speed; cleaner code layout, versioned database schema, `selftest` fixed. Layout and rules for developers: `docs/ARCHITECTURE.md`. All release notes: `docs/CHANGELOG.md`. See `docs/CHANGES_v913_restructure.md`.

### Release 9.13: "Quick test attach" button on every story (see docs/CHANGES_v913.md)

Each story card has a **Quick test attach** button. It is enabled only when the story's **NITRO** step is green. Click it, answer **Yes** in the window, and the poller attaches that one clip to that story for real (even in `BLAZE_ATTACH=dry`), reads the story back, and the card shows the result. Safety checks stay on (verified format, kill switch file, one attempt per clip). `QUICK_TEST_BUTTON=0` removes the button.

### Release 9.12: `WATCHER_ENABLED=0` = no Playout / Nitro folders needed (see docs/CHANGES_v912.md)

### Release 9.11: live attach without the NAS, shared stories, review fixes
* `BLAZE_ATTACH_WHEN=media` (default): the file found in Blaze's media list is enough to attach, the NAS watcher is not needed. `watcher` also waits for the NAS watcher (state ON_NITRO).
* A story that sits in several bulletins has one clip ID per bulletin: when its file is in the story, every one of those IDs is marked attached (before, only the first).
* `blaze_poll.py report` and `shows` accept 20261113, 2026-11-13 and 13112026. ATTACHMENT CHANGED lines show the clip status.
* Still done by the desk: story formats other than 20 and 21 (not verified), linked stories, `_V2`+ versions. First live test: `BLAZE_ATTACH=live` with `QUICKTEST_STORY_ID=<one story>`, then empty that line and restart. Details: `docs/CHANGES_v911.md`.
#   S t o r i g e n  
 