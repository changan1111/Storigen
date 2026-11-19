# v10.9.0 - created by / assigned to, username filter (dashboard + Ready feed, one or several users), bulletin filter (Ready feed)

**Request:** show who created each story and who it is assigned to, filter the dashboard by username, and give the Ready feed a bulletin filter and a username filter. Nothing else changes.

## What you see
* **Dashboard:** a new **username** tick list beside the bulletin drop-down: tick one or several users ("All users" when none is ticked; the list holds every Blaze user who created or was assigned a story that day, with counts). A story matches when ANY ticked user **created it or is assigned to it** (a story is listed once). The list has a **type-to-search box** at the top (any part of a username, any letter case; Enter ticks the first match; Esc closes only the list), so nobody scrolls through 100 names. The bulletin list and its counts follow the filter; the top cards still count the whole day. The choice is remembered like the bulletin choice. The story card and the details pane show **Created by** and **Assigned to**; the story row's tooltip shows both. Search (`q`) also finds a username. **Export CSV** follows the filter and has two new last columns: *Created by*, *Assigned to*.
* **Ready feed:** a **bulletin** drop-down and a **username** drop-down next to the status filter; two new columns **Created by** and **Assigned to**; search also finds a username. Counts at the top stay for the whole day. The notification for a newly ready clip is never hidden by these filters.

## Where the names come from
* The poller already reads `GET /stories/<id>/complete/` for the scripts. The same read now also takes the creator and the assignee and sends them with the scripts (`POST /svc/scripts`: `created_by`, `created_by_id`, `assigned_to`, `assigned_to_id`). Reading only; nothing is written to Blaze.
* Blaze names a user by number. `autoid_lite/blaze/people.py` holds the list of the 101 Blaze users you gave (venkat = 363 ... admin = 102). A user not in the list shows as `user <number>`; add it to `data/blaze_users.json` (`{"364": "newuser"}`, read again every minute) or to the table.
* Timing: a story's people appear with its scripts: a new story in the next polling round, existing stories within a few minutes of the first start (BLAZE_SCRIPT_BATCH per round), then every BLAZE_SCRIPT_SECS (a reassignment in Blaze reaches the dashboard that soon). A story that carries neither field keeps what is stored (nothing is wiped).
* **The Blaze field names are not in any capture we have** (`createdBy` / `assignedTo` and a few other spellings are tried, on the story and on its first version). Check once with `python3 tools/blaze_poll.py people <story id>`: it prints every user-like field of the story and what the poller would store. If the names differ, set `BLAZE_CREATED_KEYS` / `BLAZE_ASSIGNED_KEYS` in autoid.env.

## API
* `GET /api/clips?user=<name>[,<name>...]` (any letter case, up to 60 names); response adds `users: [{name, created, assigned, n}]`; each clip row has `created_by`, `assigned_to`. `/api/clips.csv` accepts `user`.
* `GET /api/feed?bulletin=<Blaze show id>&user=<name>[,<name>...]`; response adds `bulletins: [{id, name, start, n}]` and `users`; each item has `created_by`, `assigned_to`.
* `GET /api/clips/<id>/history` -> `clip.created_by`, `clip.assigned_to`.

## Under the hood
* Schema 10 (additive): `stories.created_by`, `created_by_id`, `assigned_to`, `assigned_to_id`. Added automatically at start; nothing is deleted. A database made by this version cannot be opened by an older program: keep a backup (`data/backups`) before upgrading, as always.

## Tests
`tests/test_story_people.py` (13 tests, including several users at once and the search box): user table, every field shape, env field names, user file, poller -> dashboard -> filter, reassignment and no-wipe, service call, CSV, feed filters and choices, page. `tests/test_blaze_poll.py`'s fake Blaze can now carry extra story fields. `tools/dev/check_refresh_dom.js` pins the two new feed columns. Whole suite: 448 passed, 1 skipped (jsdom); `tests/test_preview.py::test_the_switch_and_the_missing_ffmpeg_are_reported` also fails on the uploaded v10.7.0 in this environment (not related).

## Upgrade
Back up `data`, replace the program files (keep `autoid.env` and `data`), restart both services, Ctrl+F5 once; the page header must say v10.9.0. Run `python3 tools/blaze_poll.py people <a story id>` once to confirm the field names.
