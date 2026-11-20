# v10.9.6

* **Ready feed: editor filter.** New **All editors** picker next to **All users** in the feed (tick one or more; type to narrow the list). It narrows the feed list and its count; the search box and the other filters still work with it. It uses the `editor` parameter that `GET /api/feed` already had.
* **Desktop app (Electron).** New folder `electron/` with a small window app for Mac and Windows that shows the dashboard from the server. Step-by-step: `electron/INSTRUCTIONS.md`.
* **Tabs stay on screen.** The header with the tabs (Rundown, Ready feed, Recent activity, Users) is now fixed at the top while the page scrolls. The bulletin list and the feed's column headings sit just below it.
* **An update (`_U01`) for a story that has no older clip.** If the plain clip was never attached (for example the editor saw an error clip and attached nothing), the `_U01` file is attached as the story's clip and nothing is deleted, because there is nothing to remove. This already worked in the code; it is now covered by tests (`tests/test_u01_without_base.py`: no plain file at all, plain clip handed to the desk, plain file in Blaze but not in the story) and the plan line says so: "UPDATE (U01): the story holds no older clip of this name, so it is attached as the story's clip and nothing is removed". With an older clip in the story, the update still replaces it (attach, read back, then remove the old one) as before.
* Version 10.9.6 (`autoid_lite/common.py`, page header, tests). Nothing else changed.

## Upgrade
Back up `data`, replace the program files, restart both services, Ctrl+F5.
