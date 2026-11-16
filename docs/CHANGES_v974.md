# v9.7.4 - one media list per round, "still converting" is not "ready", new sign-in page

## 1. The Blaze file of every story: one list per round instead of one search per story (BLAZE_MEDIA_MODE=list, the default)
Before (v9.7.3 and older, still available as BLAZE_MEDIA_MODE=search): every waiting story got its own title search, each 30 to 120 seconds, at most 40 per 15-second round, and stories with the same
name searched the same thing again.
Now the poller does what the Blaze page does with an empty search box: `GET /DataService/mosobjects` with only mosId, fromDate and toDate (no title), 200 files per page, newest first. That is
1 request for about 200 files, up to BLAZE_MEDIA_MAX_PAGES (5) per round = the newest 1000 files of the last BLAZE_MEDIA_DAYS (2) days. Every story is matched against that list in code (same name rules as
before: capitals, spaces/dashes/underscores and the _Vn version suffix). Cost per round is the same for 10 stories or 600; stories with the same name cost nothing extra.
* **A story whose file is not in the list yet is looked at again every round** (the list is read again every round). Nothing to wait for, nothing to schedule.
* **List cut short** (Blaze has more files than were read): stories that ARE in the list are matched as usual; only the stories that are NOT in it are searched by title, as before.
* **List cannot be read** (error): every story falls back to the title search until the list works again; one log line says so, one says when it is back.
* **Slow Blaze:** the list read is bounded by the round deadline like every other read; a late answer is used next round, and the last list (at most a few rounds old) is used meanwhile.
* The search by title is no longer needed for the normal case, so it no longer matters whether Blaze's title search treats `_` as a space.

## 2. A file Blaze is still converting is not attached
In your capture Blaze lists a file while it is still being ingested as `status NEW`, `duration 0`, no proxy (lowres) and no thumbnail; finished files are `UPDATED` with a duration and a proxy (3 of 166
files were NEW). Until now only "not changed for 60 seconds" protected against that, so a conversion longer than a minute could have produced an attach with duration 0.
New state `converting`: the file is found but status is NEW or the duration is 0. The log says `file is in Blaze but Blaze is still converting it (status NEW): waiting, checked again next round`; it is
attached only after Blaze flips it to UPDATED with a duration (and the usual 60-second settle and, for live attach, ON_NITRO).

## 3. New sign-in page of the web app
The plain sign-in form is replaced: gradient background, centred card with the logo mark, labelled email and password fields with icons, show/hide password, a busy button ("Signing in…"), error and
"access blocked" messages in place, autofocus, keyboard Enter works, phone safe areas, light and dark mode, reduced-motion respected. Same element IDs and same login calls as before, so nothing else changed.
A browser is not available in the automated tests: they check the IDs, the markup and the script syntax, not the pixels.

## Settings (autoid.env)
`BLAZE_MEDIA_MODE=list|search`, `BLAZE_MEDIA_PAGE=200`, `BLAZE_MEDIA_MAX_PAGES=5` (see autoid.env.example). The v9.7.3 login settings are unchanged.

## Files
`tools/blaze_poll.py`, `autoid_lite/web/index.html`, `autoid_lite/server.py` (version), `autoid.env.example`, `tests/test_media_list_matching.py` (9 tests), `tests/test_signin_page.py` (4), `tests/test_blaze_poll.py` (fake Blaze: list failure and
total), `tests/test_poll_deadline_and_day_control.py` and `tests/test_clip_names_and_versions.py` (two tests pinned to the title-search path; version).
