# v9.16.0 - two panes and a popup

Dashboard layout only; nothing about IDs, polling, export, Nitro or attach changed.

* **Two separate panes, each scrolling on its own** (like the Blaze rundown): the left pane lists the whole day's bulletins, the right pane lists the stories of the selected bulletin. Scrolling one never moves the other.
* **Story rows carry the state on the left edge:** orange = ready on Nitro or waiting for the desk, red = needs the desk, green = attached.
* **A click on a story opens one popup** in the middle of the screen with the full details (buttons, both scripts, clip ID, history). Clicking another story replaces the content of the same popup; there are never two popups. It has Previous / Next (across bulletins), Next needing action, and closes with Close, Esc or a click outside it. The panel that docked on the right in 9.14.0 / 9.15.0 is replaced by this popup.
* On a phone the popup uses the whole screen.
