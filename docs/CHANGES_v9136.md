# v9.13.6

* **Quick test attach is never hidden.** It is on every story card. When the clip cannot be attached yet it looks dimmed and a click shows the reason instead of doing nothing: "Yet to reach Nitro ..." (NITRO step not green), "Already attached ...", the typed-story (placeholder) message, a story removed from the rundown, or a quick test already running. When the clip is ready a click opens the same Yes / No box as before; nothing about the attach itself changed.
* `QUICK_TEST_BUTTON=0` still removes the button.
