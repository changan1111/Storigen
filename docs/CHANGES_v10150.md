# v10.15.0 - Missing-clip board and Bulletin smoke test (each switched on / off from the page)

Two new items in the left menu. Both only **read** Storigen's own record of the day (which the Blaze poller keeps up to date): they send nothing to Blaze and never touch the poller's safety wall.

## Missing-clip board (menu: Missing)
Stories that have **no clip attached yet**, grouped by bulletin, soonest bulletin first.
* Each bulletin shows its start time and a **live countdown** ("starts in 18 min 32 s", "started 3 min ago"). It ticks by itself every second; the page does not rebuild.
* A bulletin that starts in **less than 20 minutes** (or is already on air) goes **red**: red header, red bar on every row, red countdown. The 20 is a setting (1 to 240), changed on the page.
* **➕ Add media** is on every row, one click: it opens the same dialog as the open story's Add media (v10.14.0: search the clips Blaze holds, or type a name to queue it; Yes / No before anything is sent). Same request, same rules, recorded with the user's name.
* Each row says how far the story's file got: *No file yet*, *File seen, still converting*, *File is in Blaze, not attached yet*, *Attach sent, being checked*, *Needs the desk*; and *Add media requested* when someone already asked.
* The menu item carries a badge: red with the number of stories in the red, otherwise the number of stories still missing a clip.
* Bulletins that have already aired are left out (tick "also show bulletins that have already aired" to see them; they are never red). A bulletin with no start time is listed last and is never red.

## Bulletin smoke test (menu: Smoke test)
Pick a bulletin (the next one to start is preselected), press **Quick test**:
* a verdict (**✔ All 14 stories have a clip attached** / **✖ 3 of 14 stories have no clip attached**);
* a **horizontal bar graph**: stories in the bulletin (full bar) and stories with a clip attached;
* the stories without a clip, each with Add media;
* when it was checked, and a warning if the Blaze poller has not reported lately (the numbers may then be out of date).

## What counts as "has a clip"
A story has a clip when one of its clip IDs is **ATTACHED** and was not replaced by an update. A clip that is only on Nitro or whose attach was sent does not count yet; a clip deleted from the story in Quick Support does not count. Stories typed by hand (no real Blaze story) and stories removed from the rundown are not counted. Every real story of a bulletin is counted: Storigen cannot know that a story is meant to have no clip (an anchor read), so such a story shows as missing.

## On / off from the page, not from autoid.env
**Users > Features** (admin): a switch for each feature and the red limit in minutes. Stored in the database (new `settings` table, created by itself), so there is nothing to edit and no restart: every signed-in user's menu follows within about 5 seconds, and a person who has a switched-off tab open is sent back to the Rundown. Both are **on** until an admin switches them off. Editors see the features but cannot change the switches. Every change is written to the activity log (`feature_changed`, with who and from / to). The server answers 403 for a switched-off feature.

## API
`GET /api/features` (everyone signed in; also the menu badge numbers), `POST /api/features` (admin: `missing_board`, `smoke_test` true / false, `missing_minutes` 1 to 240), `GET /api/missing?day=&aired=1`, `GET /api/smoke?day=` (the bulletins for the picker) and `GET /api/smoke?rundown=<Blaze show id>` (the test). `/api/config` carries `features`. New file `autoid_lite/api_features.py`; `api_support.py` is unchanged.

## Version
v10.15.0 (page header, `APP_VERSION`, Electron package, sample page, tests).

## Tested
`tests/test_missing_board_and_smoke_test.py` (20 tests, mutation-checked): the switches (default on, admin only, bad input refused, kept after a restart, logged), the board (order, red / not red at the limit and after the admin changes it, on air, aired, no start time, what counts as a clip, typed stories, Add media requested, badge numbers), the smoke test (counts, per bulletin, unknown bulletin, poller age), that neither view writes anything, and the real page in a headless DOM against a live server (menu and badge, red board with ticking countdown and no rebuild on refresh, the Add media dialog opens from a row, Quick test and its bars, an admin switching features off and an editor's open page following, the limit changed, a bad limit refused, a remembered tab of a switched-off feature falling back). `tools/dev/check_missing_smoke.js` is that page check. `tools/dev/check_tabs.js` now expects the real tab list. Not tested here: a live Blaze (the views read only the registry).
