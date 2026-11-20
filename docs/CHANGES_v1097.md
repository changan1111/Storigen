# v10.9.7

* **Script pane (middle): one box per text.** A Blaze story can have several items, each with its own Online text (text 1) and Anchor text (text 2). Until now all of them were joined into one block. Now the **Online script** tab shows every text 1 in its own box and the **Anchor script** tab every text 2 in its own box, each labelled with its item number (an item whose text is empty is left out and the others keep their numbers) and each with its own **Copy** button. The footer still totals the tab and has **Copy all**.
* **Word count and reading time.** Every box shows its words and the time to read them (for example `36 words · 0:14`). The footer shows words, characters, total time and the number of items.
* **Words per minute.** New input at the top of the pane (next to A- / A / A+). Type the reading speed; every time on the pane changes at once. It starts at 150 and is remembered in the browser.
* **Selection count.** Select any part of a script with the mouse or by touch: the footer shows `Selected: N words · m:ss` (the box headers and buttons are never counted, also when the selection runs over several boxes).
* **Under the hood.** New column `stories.script_items` (schema 12; the database upgrades by itself and keeps its data) holding the items as JSON; the poller sends them with the scripts (`items` in `POST /svc/scripts`; an older poller that does not send them leaves the stored items alone); `GET /api/clips/<id>/history` returns `clip.script_items`. The joined `online_script` / `anchor_script` are unchanged. A story read before this version is shown in one box until the poller reads it again (a few minutes after the restart).
* Tests: `tests/test_script_items.py` (including a headless-browser run, `tools/dev/check_script_items.js`). Version 10.9.7.

## Upgrade
Back up `data`, replace the program files, restart both services (the poller too), Ctrl+F5.
