# v10.9.8

* **Selected-text count as a hover tip.** The words and reading time of the selected text (`12 words · 0:04`) now appear in a small badge right above the end of the selection, and go away when nothing is selected. They no longer sit in the footer of the script pane; the footer keeps the totals of the tab. The badge follows the selection while scrolling and uses the words-per-minute number at the top. The box headers and buttons are still never counted.
* Only `autoid_lite/web/index.html` changed in behaviour (plus the version number, docs and tests: `tests/test_script_items.py`, `tools/dev/check_script_items.js`). Version 10.9.8.

## Upgrade
Replace `autoid_lite/web/index.html` (and `common.py` for the version number), restart the server, Ctrl+F5. No database change, the poller is not touched.
