# 3-pane layout (not yet given a version number)

* From 1000 px wide upwards the "3 panes" view shows **bulletins 15% | stories 35% | selected story 50%** side by side (`15fr 35fr 50fr`, so the ratio stays exact whatever the gaps). A click on a story fills the right pane; there is no pop-up and no dark overlay. Before the first click the right pane says "Select a story ...". Close (or Esc) clears the selection and keeps the pane.
* Previous / Next, arrow keys, J / K, N, Copy ID, Mark done, Quick test attach and the 5-second refresh work as before, now inside the right pane.
* Under 1000 px, and in the "One long list" view, nothing changes: bulletins | stories, and the details open as the pop-up. At 700 px and below the narrow time column from v9.16.1 stays. The layout switches by itself when the window is resized across 1000 px.
* The page is wider (100 rem instead of 70 rem) so the three columns have room. The middle column uses the same stacked row layout as a phone (time, headline, ID, chips), and the two script boxes stack in one column.
* Only `autoid_lite/web/index.html` changed. No server, API, database or poller change. `tests/test_three_pane_layout.py` is new.

## Sample dashboard without a server

`python3 tools/make_standalone.py --out demo.html` writes ONE html file with made-up stories (4 bulletins, 20 stories, every state). It is the real page with `tools/standalone_shim.js` placed in front of the page script; the shim answers the page's `/api/*` calls in the browser. Double-click the file to open it. Mark done / Quick test attach work on the sample data; one waiting clip moves on every 45 s so the "ready on Nitro" notice can be seen. Run the command again after any change to `index.html`.
