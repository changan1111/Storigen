# v10.9.6

* **Ready feed: editor filter.** New **All editors** picker next to **All users** in the feed (tick one or more; type to narrow the list). It narrows the feed list and its count; the search box and the other filters still work with it. It uses the `editor` parameter that `GET /api/feed` already had.
* **Desktop app (Electron).** New folder `electron/` with a small window app for Mac and Windows that shows the dashboard from the server. Step-by-step: `electron/INSTRUCTIONS.md`.
* Version 10.9.6 (`autoid_lite/common.py`, page header, tests). Nothing else changed.

## Upgrade
Back up `data`, replace the program files, restart both services, Ctrl+F5.
