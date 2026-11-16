# v10.3.0 - Ready feed as a table, with Quick test attach on every row

**Why:** the Ready feed of 10.2.0 was a narrow list of cards. The desk wanted it as a proper table, latest clip on top, and to be able to attach straight from it.

## What is new

**1. The Ready feed is an HTML table.** The panel is wider and shows one row per clip, **newest first** (the clip that became ready last is always the top row; new arrivals appear at the top by themselves):

| Ready at | Status | Story | Clip ID | Blaze story ID | MOS object ID | Media | Bulletin | Quick test |
|---|---|---|---|---|---|---|---|---|

Click a clip ID, story ID, MOS object ID or media name to copy it (the full value is in the tooltip). Status is a coloured tag, with the reason underneath for *Not sent* / *Needs desk* and the attach time for *Attached*. The header stays in view while the table scrolls. On a wide screen the **Quick test** column is pinned to the right edge so it is never scrolled out of sight; on a phone the table scrolls sideways.

**2. Search works as before** (story, clip ID, Blaze story ID, MOS object ID, media name, bulletin; every word must match) together with the All / Ready to attach / Attached / Needs attention filter. The summary line shows the counts and "newest first".

**3. Click a story (or anywhere on its row) to open that story.** This is now reliable: before, it only worked when the story happened to be in the bulletin, filter and search the main page was showing. Now the page switches to the story's bulletin, clears any filter and search that would hide it, opens it, and scrolls to it. If the story is no longer in the rundown a short message says so and no search is left behind.

**4. Quick test attach on every row.** The button is the same one as on the story card and uses the same Yes / No box and the same server checks, so nothing about the safety wall changes: Yes sends ONE real attach of that clip to its story (even while the tool is in dry mode), then the poller reads the story back. The row goes *Attach requested* -> *Attach sent* -> *Attached* by itself. When a click cannot attach (already attached, typed story, still converting, a test already running) the button is grey and a click says why. The Yes / No box now sits above the feed panel. It needs the same permission as on the card (attach) and `QUICK_TEST_BUTTON` not set to 0.

## Small server change

`GET /api/feed` items gained `blaze_rundown_id`, `position`, `state`, `qa_state` and `typed` (the page needs them to open the right bulletin and to decide the button). Nothing was removed or renamed, nothing new polls Blaze, no database change.

## Tests

`tests/test_ready_feed.py` (+1 test and the new fields), `tools/dev/check_refresh_dom.js` (feed section rewritten for the table: columns, newest first, search, filter, Quick test No / Yes, grey button reason, opening a story from another bulletin while the main list is narrowed, toast once, zero page changes while open, Esc / F). 368 tests pass; the DOM check passes in full.

## Upgrade

Replace the program files (keep `autoid.env` and `data`), restart the service, press Ctrl+F5 in the browser once. No new setting.

## Addendum: the feed no longer covers the dashboard

The feed used to be a full-height panel that could cover the story list. It now has three sizes (buttons at the top right of the feed; the choice is remembered in the browser):

* **Docked (default):** a panel along the bottom of the screen. The dashboard above it stays usable (the page leaves room and scrolls).
* **Minimized (▁):** one thin bar with the counts and the latest clip. Press ▲ to restore.
* **Maximized (☐):** the whole screen, as before. Press ❐ to restore.

Esc steps back (maximized -> docked, otherwise closes); F still opens and closes it. Clicking a story still closes the feed and opens that story. Page-only change: no server, setting or database change. Press Ctrl+F5 once.

Also: every feed row has a **View story ↗** button (same as clicking the title or the row). It shows that story in the dashboard and shrinks the feed to its bar instead of closing it; press the Ready feed button, ▲ or F to bring it back.
