# v10.9.4 - keep 7 days, sort the rundown, Removed filter, "updated" stamp

Built on v10.9.3 (media groups). Nothing about attaching, matching or the poller's reading of Blaze changed.

## 1. History is kept for 7 days (configurable)
**Why:** `autoid.db` was never cleaned. Every story keeps its script text (Tamil takes 3 bytes a character), every clip its files, every change an event: the file only grew.

* `AUTOID_KEEP_DAYS` (default **7**; the last 7 broadcast days, today included; **0 = keep everything**). `AUTOID_PURGE_AT` (default 03:30, server clock). Both in `autoid.env`; restart to change.
* **What goes (older than the kept days):** files, clip IDs, the "renamed from" memory, stories with their script text, bulletins with no stories left, the day counters and the **event log**. A story with no clip left is deleted only when it has not been seen since the cut. Nothing from the kept days is touched.
* **Once a day** from `AUTOID_PURGE_AT` on (when the server was off at that time: when it starts), and on request: an admin sees **Clean up now** in the dashboard footer.
* **Safe:** before anything is deleted a copy of the database is saved in `data/backups` (newest 3 kept; no copy when there is nothing to delete). Deleting runs in small batches, each its own short transaction, so the dashboard and the poller never wait. The event log stays append-only: the lock is lifted only inside one delete transaction and is back before it ends (a test proves it).
* **Space comes back:** after a clean-up the WAL file is emptied, and the file is compacted (VACUUM) when 5 MB or a quarter of it is free. The first clean-up after the upgrade shrinks the file you have now.
* **The poller's file** `blaze_ledger.db`: snapshot and change history now follow the same number (they were 14 days; `BLAZE_SNAPSHOT_KEEP_DAYS` still wins if you set it: **remove that line from your autoid.env to let it follow**), and the ledger rows (`plan`, `seen`, `live`) older than the kept days + 1 are deleted with it (they were never cleaned).
* **Shown on the page:** "history kept 7 days" next to the date, the date picker starts at the oldest kept day, and the footer says the database size, the kept days, the clean-up time, what the last clean-up removed.
* `GET /api/retention` (view) and `POST /api/retention/run` (admin).

## 2. Sort the rundown
* Click **#**, **Story Title** or **Status** in the list header: ascending (▲), click again: descending (▼), a third click: back to the default order (needing action first, then the bulletin order). A "Sorted by ... · reset" button shows while a sort is on.
* The sort is made by the **server across the whole day**, not only the page on screen. **#**: row number (stories without one always last; the bulletins keep their order, the rows inside them follow the sort). **Story Title**: the title shown (story name, else slug), letter case ignored. **Status**: needing the desk first (Needs Desk, Quarantined, Ready, Submitted, Verified, Exporting, Waiting, Attached); descending reverses it.
* **Remembered in the browser** (like the status filter, the selected bulletin and the layout): it survives logout and a restart, until the browser's data is cleared. Another PC starts with the default order. The CSV export follows the same sort.

## 3. Removed stories
* New status filter **Removed (n)**: only the struck-out stories (Blaze no longer lists them).
* New switch **Hide removed**: leaves out the struck-out stories that need nothing from the desk. A struck-out story whose clip is still on Nitro, submitted, held or quarantined **stays visible**: it needs the desk. Remembered in the browser; off at first. Asking for the Removed filter wins over the switch.

## 4. "updated" stamp and lost connection
* "updated 14:32" (to the minute, so the page is not redrawn every 5 s) beside the line under the title. When the server cannot be reached, or nothing arrived for 20 s while refresh is on: the line turns red and says when the page was last updated; it clears by itself.

## Tests
`tests/test_retention_and_sort.py` (23 tests, one runs the real page against a real server in a headless DOM: `tools/dev/check_new_controls.js`, 20 checks). With each part deliberately broken (cut-off off by one day, event-log lock not restored, files left behind, hide switch off, hide also hiding stories that need the desk, descending ignored, ledger prune off, snapshot days not following) the tests fail. `tools/dev/check_refresh_dom.js` now ignores the one-a-minute stamp when it checks that an idle refresh changes nothing.

## Upgrade
Back up `data`, replace the program files (keep `autoid.env` and `data`), add `AUTOID_KEEP_DAYS=7` (and `AUTOID_PURGE_AT=03:30`) to `autoid.env` (the default is 7 even without the lines), delete the `BLAZE_SNAPSHOT_KEEP_DAYS=14` line, restart both services, Ctrl+F5 once; the header must say v10.9.4. The first clean-up runs at the set time (or press **Clean up now** as admin): it makes a copy in `data/backups` first. `python3 tools/db_usage.py data` shows where the space is, before and after.
