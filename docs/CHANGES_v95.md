# v9.6.0 (v9.5.0 merge of the two v9.4.6 builds, plus the after-midnight look-ahead, the desk conveniences and new-version handling)

Base: the **venkat** build (`autoid_lite_v9_4_6_venkat_.zip`). Ported in from the **plain** build (`autoid_lite_v9_4_6.zip`): the pieces where it was the stronger design. Both builds share the v9.3 watcher, gateway, security, and the **live attach write path, which is untouched** (it was identical in both; only the plain build added one read-only `observe()` call after an attach, which is not carried over).

## What came from which build

| Area | Taken from | In v9.5.0 |
|---|---|---|
| Polling engine (bounded batches, cheap identity read, page-style keep-alive, ledger tables with pruning) | venkat | unchanged base: ~76 requests per steady round instead of ~730 |
| Expired session answered as `404 authenticationFailed` | venkat | recognised: cookie hot-reload and alert work |
| Server-side paging, counts, `/svc/clips` default of 5000 | venkat | kept; `limit` is now validated (422 on a bad value, from plain) and capped at 20000 |
| Deadline-bounded parallel reads (`Fan`) | plain | every parallel phase (slug lists, identity, media search, story reads, reconcile) waits at most `BLAZE_CYCLE_DEADLINE_SECS`; a read still running is never started twice and its answer is used by a later round; results keep the order asked for |
| Quick retry of transient failures, monotonic timing | plain | `BLAZE_REQUEST_RETRIES` (default 1); durations and sleeps use the monotonic clock |
| Finished shows kept until the day closes | plain | `BLAZE_KEEP_COMPLETED=1`; `BLAZE_KEEP_COMPLETED=0` gives the venkat behaviour |
| Day control | plain | `blaze_poll.py close-day / open-day`; a closed day is paused, not reported as stale |
| Snapshot retention | both | `BLAZE_SNAPSHOT_KEEP_DAYS` (default 14; the plain build used 60) |
| Dashboard: story name, bulletin time, show/slug IDs, group-by-bulletin, ready-on-Nitro notice, extra filters, wide search | plain (features), venkat (server paging) | rebuilt on the server-paged API, see below |

## Changes made while merging (not in either build)
* The registry is called **after** the ledger transaction closes. The venkat build made those HTTP calls while a SQLite transaction was open.
* When a story's name is first learned or changes, the registry is sent the show again in the next round (the name arrives in the full story read; before, it would have waited up to `BLAZE_SYNC_FULL_SECS`).
* The story name is taken from the slug list when Blaze sends it, otherwise from the full story read already stored in the ledger.
* Stat cards at the top show the whole day (`day_counts`); chips, list and bulletin counts follow the search, filter and show.
* `/api/clips` filters: `all, action, nitro, attention, waiting, done`. Search: every word must match somewhere in slug title, story name, clip ID, Blaze story ID, slug ID, show ID, bulletin name or bulletin time (`14:30` or `1430`).
* Bulletin time search uses the **server's** local time zone; the page shows the browser's. They are the same on a newsroom LAN.
* Auto-ID database: two additive columns (`stories.story_title`, `rundowns.start_at`), added on start-up; an older server ignores them.

## Measured
Same harness (replays the response times of the real capture, 36 shows, 648 stories, 6 parallel):

| | initial round | steady round | busy round (6 changes) |
|---|---|---|---|
| plain v9.4.6 | — | 3.4 s idle, **40–56 s** when its ~650 media searches expire | — |
| venkat v9.4.6 | 6.4 s | 4.3–6.8 s | 6.2 s |
| **v9.5.0** | 6.6 s | **4.2–4.9 s** | 6.2 s, all 6 injected changes found |

Dashboard API, 720 stories: plain returns 321 KB per refresh (paged in the browser); v9.5.0 returns 20–38 KB per page.
Tests: 190 (plain 189, venkat 177). New in `tests/test_poll_deadline_and_day_control.py`: deadline fan-out (slow read not started twice, harvested later), retry, expired session not retried, close/open day, story name and bulletin time through the registry and search, filters, limit validation. `test_17` was rewritten for the keep-completed rule (the old rule remains tested with `BLAZE_KEEP_COMPLETED=0`). A search for two words (`story 042`) now matches both words anywhere (it also finds a clip whose ID contains `0042`), as in the plain build.
The dashboard page was also run in a simulated browser (jsdom) against real API output: list view, by-bulletin view (auto-selects the bulletin with clips ready), ready counter in the title.

## Not verified here
No real Blaze, Nitro or Windows PC was available: the numbers above come from the fake Blaze and the capture-derived latencies. The browser smoke test is jsdom, not a real browser. The plain build's own benchmark could not be run on the merged poller (it shares module names with the test fixtures), so the plain-build timings above come from the venkat harness.

## Operating notes
* First start after upgrading: the stories table and rundowns table gain a column each; nothing else to do. Old snapshots are kept (14 days).
* If Blaze is slow, `late_reads` in `blaze_poll.py stats` and a watch-log line show rounds that hit the deadline.
* `docs/CHANGES_v94.md` is the venkat build's change log; `docs/CHANGES_v94_plain_zip.md` is the plain build's.

## v9.5.1: shows just after midnight are followed from the evening on
**The gap (present in both v9.4.6 builds and in 9.5.0):** the poller asks Blaze for the shows of the current broadcast day's *calendar date* only. The broadcast day runs from `BROADCAST_DAY_START` (default 05:00) to the next 05:00, so at 23:30 a 00:00 show is on the next calendar date and was not followed until the day rolled over at 05:00, hours after it aired. (This assumes Blaze lists a show under the date of its start time; `blaze_poll.py shows` shows what your Blaze does. If it already lists the 00:00 show under the earlier date, nothing changes.)

**The fix:** `BLAZE_SHOW_LOOKAHEAD_HOURS` (default 5, 0 = off). The poller also reads the next date's list (one extra request per show-list refresh) and follows the shows that start **within that many hours from now and before the broadcast day ends**. At 21:00 it follows shows up to 02:00; at 00:00 up to 05:00; a 05:30 show is never taken early, it arrives with the normal list when the day rolls over at 05:00. Those shows keep the current broadcast day's date in the registry, which is right: they air inside it.
* At the 05:00 rollover the early-followed shows appear in the new day's normal list and simply continue (their history, snapshots and IDs are untouched). A show listed for a day is now recorded under that day, so "keep completed shows until the day closes" also works for them.
* The look-ahead never breaks the normal list: if its request fails the poller says so once and carries on. It is not used when `BLAZE_SHOW_DAYS_AHEAD` is set (that follows the whole next date).
* `blaze_poll.py shows` prints the look-ahead shows after the day's list, marked "followed early".
* The server's `/svc/status` now reports `day_ends` (with the UTC offset of `AUTOID_TZ`, or of the machine when no zone is set). Two bugs in my first version of this were caught by tests before release: a day end without an offset (look-ahead silently off) and one without `AUTOID_TZ`'s offset (5.5 h out for Asia/Kolkata).
* Tests: 196 (6 new: window, day-end limit, off switch, failure isolation, rollover hand-over, time-zone offset).

## v9.5.2: the browser remembers its settings; CSV export and print
* **Remembered in the browser (kept after the tab or browser is closed):** stories per page, the filter chip, the chosen show or bulletin, the List / By bulletin view, and the "beep when a clip becomes ready" box. A remembered show that does not exist on the day being viewed is dropped at once. Not remembered, on purpose: the search text and the page number (a stale search or page would hide stories). Unknown or damaged stored values fall back to the defaults.
* **Export CSV:** `GET /api/clips.csv` (button next to the search). Everything of the chosen day that matches the search and the filter, all pages (in the by-bulletin view: all bulletins; in the list view the chosen show too). Columns: Clip ID, State, Version, Slug, Story name, Bulletin, Bulletin time, Show ID, Story ID, Slug ID, Row, Created, Removed from rundown, Note. UTF-8 with a BOM so Excel reads it; a text starting with `=`, `+`, `-` or `@` is written as plain text so Excel never runs it as a formula. Same login and permission as the dashboard; every export is written to the activity log (`clips_exported`: user, day, rows, filter, show, search).
* **Print:** prints what is on screen (the controls are hidden). Choose 200 per page for the longest page; for the whole day use the CSV.
* Tests: 198 (2 new for the export: whole list not one page, Excel-safe cells, filters, login, log). The page was run in a simulated browser: defaults, remembered values, a stale remembered show, junk stored values, and the export and print buttons.

## v9.6.0: new versions of a clip (`BLAZE_VERSION_MODE`)
A *new version* is a clip the desk made with "+ Version": same date and number, ID ending `_V2`, `_V3`… (the name part of a file never matters; only the ID and `_Vn`). What the tool does with it is one setting:

| | `desk` (default) | `auto` (needs `BLAZE_ATTACH=live`) |
|---|---|---|
| New file `…_V2` on Nitro and in Blaze | **not attached.** Log: `NEW VERSION READY`; the card goes to NEEDS_DESK with "New version ready… attach it by hand and remove the older version's clip" (only for shows the tool is live for); the dashboard banner appears | attached with the normal live attach and read-back (the same locks: live shows, confirm word, kill switch, hourly limit, halt after failures) |
| The older version's clip in the story | untouched (the desk removes it) | removed by a **second call** (`DELETE …/stories/<id>/clips/<clipId>`), **only after** the attach was read back as exactly one new clip, then read back again: the old clip gone, the new file present, same clip count; then the story's script duration is set to the clips' total as the page does (when the old rule "script time = clips' total" held) |
| Dry run (`BLAZE_ATTACH=dry`) | logs `NEW VERSION READY` | logs what it WOULD do: the attach call, and "then, only if the read-back is exactly right: DELETE …" |

Auto mode is deliberately conservative and leaves the clip to the desk when: the story is linked in several shows; the story holds more than one older version; the format or item rules are unverified; live is blocked in any other way; the older clip is no longer in the story. Order is never reversed: a failed or refused attach leaves the story with its old clip, never without a clip. At most one attach and one delete per clip, also across restarts (the clip is ATTACHED afterwards, so it is not planned again). If anything goes wrong after the attach (kill switch appears, delete refused or unclear, read-back not as expected) the story keeps **both** clips, the log says `REPLACE INCOMPLETE … remove clip N by hand`, the desk is alerted, and the ledger marker `replace:<clip ID>` shows `INCOMPLETE: …` (`done` when complete).
Other additions: a story that already has clips gets "this one is ADDED, it does not replace them" in the plan line; the dashboard banner and title counter now also count clips that need the desk; `blaze_poll.py live` shows the version mode.
**Bug fixed (present in 9.5.0 to 9.5.2):** the parallel media searches were keyed by the clip ID's date+number prefix, so a clip and its `_V2` (same prefix) collapsed into one search and one of them could be missed. They are now keyed per clip ID row; a regression test covers it. Nothing was live, but anyone running 9.5.0 to 9.5.2 with versions should upgrade.
Tests: 207 (new: desk mode, auto mode, dry run, refused attach never deletes, failed delete keeps both clips and alerts, kill switch between attach and delete, two older versions left to the desk, setting validation, the search regression).
**Not verified:** how a real Blaze reacts to a second clip on a story and to the DELETE. The fake Blaze models them; the attach form and the DELETE call are the ones captured from the Blaze page. Run `auto` in dry mode first, then on one low-risk show, with `BLAZE_VERSION_MODE=desk` as the fallback.
