# v9.14.0 - compact rows and one side panel

Dashboard layout only. Nothing about IDs, polling, export, Nitro or attach changed.

* **Compact rows (default).** One line per story: time and row, headline, clip ID with Copy ID, rundown, state and the NITRO / ATTACHED steps, plus the start of the anchor script. A story takes about a quarter of the height of the old card, so about four times as many fit on a screen. The "Full cards" / "Compact rows" button next to Export CSV switches back to the old cards (remembered per browser).
* **One side panel.** Click a row (or View details on a card) and the details open in a panel on the right: headline, all buttons (Copy ID, + Version, Open in Blaze, Mark done, Quick test attach), both scripts, clip ID, history. Clicking another row updates the same panel; it never opens a second one. On screens wider than about 1500 px the panel docks beside the list; on smaller screens it slides over it.
* **Previous / Next in the panel.** They move through the list that is on screen (the current tab, search, show and bulletin), with "3 of 28" and the list row highlighted and scrolled into view. **Next needing action** jumps to the next story that is ready on Nitro or needs the desk.
* **Keys** (when not typing in a box): arrow down or J = next, arrow up or K = previous, N = next needing action, C = copy the ID, Esc = close.
* The panel keeps its scroll position through the 5-second refresh. The open story is kept in the address bar (#s123), so a reload or a pasted link opens the same story.
* The tabs are the existing filter chips (All, Ready on Nitro, Need attention, All action, Waiting, Done) with their counts.
