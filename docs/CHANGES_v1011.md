# v10.1.1 - the automatic refresh no longer disturbs the page

**Problem:** the dashboard refreshes every 5 s. Each refresh threw away and rebuilt the story list, the counters, the script pane, the Media & IDs pane, the warnings and the events table, even when nothing had changed. An element opened in the browser's inspector, a text selected for copying, or an open drop-down disappeared within seconds.

**Fix (dashboard page only; no server, API, database or poller change):**

* **A part of the page is touched only when its data changed.** The counters, the rundown list, the warning banner, the events and user tables, the bulletin drop-down data and the two detail panes each compare their data with what is already shown and do nothing when it is the same. Measured on the real page code: 8 refreshes with unchanged data made **280 changes to the page before, 0 now**.
* **Story rows are reused.** A row is rebuilt only when that story's own data (or its selected state) changed; the other rows stay the same elements, so the one you are inspecting survives other stories changing.
* **Script box and buttons stay put** while a story is open and unchanged; its scroll position and your text selection are kept.
* **A ticking warning** such as "poller last seen 47s ago" now updates its text in place instead of being replaced.
* **New: Pause refresh** (button under the date, or the **P** key). While paused nothing is fetched on its own; the header says "refresh paused". Resume refreshes at once. Your own actions (filters, search, opening a story) still work while paused.
* Version 10.1.1 (`common.py`, the page header, `/api/config`).

**Tests:** `tests/test_refresh_keeps_dom.py` (5 checks on the page code, plus one that runs the page in a headless DOM when node and jsdom are installed; it is skipped otherwise). `tools/dev/check_refresh_dom.js` is that headless check: it proves zero changes while the data is unchanged, that real changes still arrive and rebuild only the changed row, that Pause and the P key work, and that a ticking warning is updated in place. One-time setup for it: `cd tools/dev && npm install jsdom`. Operators do not need it.

**Upgrade:** replace `autoid_lite/web/index.html` and `autoid_lite/common.py` (or copy the whole folder, keeping `autoid.env` and `data`), then restart the service and reload the page in the browser (Ctrl+F5 once).
