# v10.9.5 - editor name filter, tabs, editor in the feed's Assigned to column

# Editor name filter (on top of v10.9.4)

The video editors write their name in the **slug comment** in Blaze ("VD VIGNESH", "VD VIGNESH_sekar_karthik"). The dashboard now reads that comment, shows it as the story's **editor**, and can filter and search by it.

* **Stored per story:** new column `stories.editor` (schema 11, added by the normal migration; the data is kept). Filled from the slug list the poller already reads (`comment`), sent with the rundown sync. A comment changed or emptied in Blaze follows within one sync interval (`BLAZE_SYNC_SECS`); a Blaze list without the field never wipes a stored name. Text is trimmed and cut at 120 characters.
* **New picker "All editors"** next to "All users" in the header: tick one or more editors (type to narrow the list, Enter ticks the first match, Clear resets). Remembered in the browser (`autoid_editor`). It narrows the list, the bulletin list and its counts, and the CSV export, like the user filter. The match is the whole comment text, any letter case.
* **Top search** ("Search story / ID / keyword / editor") and the Ready feed search now also match the editor name.
* **Shown:** the row tooltip, the story detail ("Editor"), the Ready feed items (`editor`), and a new last CSV column **Editor**.
* **API:** `GET /api/clips` and `GET /api/feed` take `editor=name1,name2` and return `editors: [{name, n}]`; `POST /svc/rundowns/sync` stories take an optional `editor`.
* **Tests:** `tests/test_editor_filter.py` (5, one runs the real page in a headless DOM: `tools/dev/check_editor_filter.js`). Two older tests were updated for the new last CSV column and the third search box.

## Upgrade
Back up `data`, replace the program files, restart both services, Ctrl+F5. Editor names appear after the poller's next rundown sync (within `BLAZE_SYNC_SECS`, or at once when a show changes). The version is now 10.9.5 (`autoid_lite/common.py`, the page header, the tests).

# Tabs: Ready feed, Recent activity (1 / 2 / 4 hours), Users

The header menu now switches between real tabs; the one you are on is remembered in the browser (`autoid_tab`).

* **Rundown** - the stories, script and media as before (the **Stories** and **Media** buttons still jump to those panes).
* **Ready feed** - a page of its own, with its search, filters and list. The count badge stays on the tab. **Pin to bottom** (button in the feed) gives the old bottom panel over the Rundown tab, with its minimize / maximize / close; **Open as tab** brings it back. **F** and **Esc** still open and close it. Clicking a story in the feed goes to the Rundown tab and opens it.
* **Recent activity** - its own tab with **Show the last 1 hour / 2 hours / 4 hours** (1 hour first, remembered). It lists every event of that window, newest first (the time shows the date on hover, the details in full on hover). Up to 500 events; the count is shown, and when there are more, it says so.
* **Users** - the add-user form and the user list, its own tab, admins only (the old "Settings" link is gone). A person who may not use a tab never sees it, and a remembered tab they may not use falls back to the Rundown.
* Only the tab on screen asks the server for its data, so the Rundown refresh got lighter.
* **API:** `GET /api/events` takes `hours` (more than 0, at most 168) with `limit` (at most 500); without `hours` it works as before. New index on `events(time)`.
* **Tests:** `tests/test_tabs.py` (6, two run the real page as admin and as editor: `tools/dev/check_tabs.js`). `tools/dev/check_refresh_dom.js` now expects the feed to open as a tab and checks Pin to bottom before the old dock checks.

# Editor in the Ready feed's "Assigned to" column

Each Ready feed row now shows the editor (the name from the Blaze slug comment) in the **Assigned to** column, under the assigned Blaze user as a small "Editor: NAME" line. A story with an editor but no assigned user shows only the editor line; with neither, the cell shows "-" as before. The feed already carried `editor` in `GET /api/feed`, so there is no API or database change. Test: `test_feed_assigned_to_cell_shows_the_editor` in `tests/test_editor_filter.py`.
