# v9.3: shows found automatically, and the Blaze capture put to use (changes on top of v9.2)

Built from `blaze-network-capture` (a Blaze Network Discovery capture of the rundown panel, a test story, and three manual attaches). 152 tests pass (141 from v9.2 + 11 new).

## What the capture settled
| Open point | Answer in the capture | What changed |
|---|---|---|
| The call that lists a day's shows | `GET /DataService/shows?filter={"fromDate":"DD/MM/YY","toDate":"DD/MM/YY"}&channelId=1` returns `shows[]` (id, title, startTime, slugCount, masterId...). 36 shows a day, one every 30 minutes from 06:00. Titles are not uniform ("6:30 AM" and "06:00 AM"), so the start time is used, never the title. | `BLAZE_SHOW_IDS=auto` (see below) and the `shows` command. |
| Keep-alive | The page sends `GET /sessions/<id>` every 60 s. No PUT was seen. | `BLAZE_HEARTBEAT` now defaults to `get`. |
| `order` | Three attaches to the story at row 11 all sent `order=12` (row + 1), not a clip counter. | Confirms the existing rule. |
| `itemId` | `939544` = the item with the lowest `arrangeOrder` of `versions[0]`, for story format 21 ("Anchor visual"). | `BLAZE_VERIFIED_FORMATS` now defaults to `20,21`. |
| `duration` | Media `64200` ms was sent as `duration=64`. | Confirms round-down to whole seconds. |
| `scriptDur` | After each attach the page sends `PUT /stories/<id>/versions/<versionId>` with `scriptDur=<clips' total seconds>&wpm=100` (64, 124, 277 for clips of 64, 60 and 153 s). | Live attach now sends it (see below). |
| Login | `POST /sessions` with `username` and `password` (form), 201, empty body. The cookies it sets are not in the capture. | Not used: the cookie is still renewed by hand. |

## Changes
- **Auto show discovery (`BLAZE_SHOW_IDS=auto`).** The poller asks Blaze for the broadcast day's shows (and `BLAZE_SHOW_DAYS_AHEAD` more days) every `BLAZE_SHOW_LIST_SECS` (60) and follows all of them. A reply with no shows never empties the list. New shows are logged as `NEW SHOW` (one summary line `NEW SHOWS 36 shows ...` when many appear at once). A fixed list of IDs still works. Words in `BLAZE_IGNORE_SHOW_TITLES` make a show ignored when they appear in its title.
- **Hot and cold shows.** Reading 36 shows every 15 seconds would be wasteful. Shows starting from 60 minutes ago to 3 hours ahead (`BLAZE_HOT_BEFORE_MIN`, `BLAZE_HOT_AHEAD_MIN`) are read every pass; the others every `BLAZE_COLD_SECS` (120) or at once when the show's story count in the list changes. A show whose start time cannot be read counts as hot. Note: the list's `modifiedTime` does not change when stories are added (all 05:40 in the capture), so only the story count is used as a trigger, with the timed read as the safety net for renames and reorders.
- **`blaze_poll.py shows [YYYY-MM-DD]`:** prints the day's shows with start, title, story count, `masterId`, hot or cold, and whether they are ignored.
- **Live by time slot.** Show IDs change every day, so with `auto` live is allowed by `BLAZE_LIVE_MASTER_IDS` (the show's `masterId`, the same slot every day; 13 is the 06:30 AM bulletin) or by fixed `BLAZE_LIVE_SHOW_IDS`. Live still needs all of: `BLAZE_ATTACH=live`, one of those two lists, and `BLAZE_LIVE_CONFIRM=YES_ATTACH_FOR_REAL`.
- **Script duration after a live attach.** The one new write: `PUT /stories/<id>/versions/<versionId>` (`scriptDur`, `wpm`), added to the write allow-list and only possible while `BLAZE_ATTACH=live`. It is sent only when the story's script time equals its clips' total so far (the captured case); a story that already has script time of its own is left alone and logged as `DURATION NOT SET`, because the page's formula for it was not captured. `BLAZE_LIVE_SCRIPTDUR=0` switches it off. `undo` puts the duration back in step the same way.
- Show IDs in `BLAZE_SHOW_IDS=auto` mode appear in the report and dashboard with their titles from the list.

## Not changed
The watcher, the gateway, the database, the live-attach rules (once per clip, read-back, hand-over to the desk on any doubt, kill switch, hourly limit, halt after 3 failures), and `BLAZE_ATTACH=dry` by default.

## Still open
- The reply to an expired session, how long a session lives, and the cookies set by login (the cookie is renewed by hand).
- `itemId` for Package and Montage stories; the `scriptDur` rule for stories with script text; Blaze's replies to a duplicate attach and to a locked story.
- **Not tried on your real Blaze, your real Nitro or a real Windows PC.** The tests use a fake Blaze built to the shapes in your capture.
