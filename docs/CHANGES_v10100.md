# v10.10.0 - Quick Support: Add media / Delete media by hand

A new **Support** item (lifebuoy icon) in the left menu, for exceptions only. The note on the page says so: *"For exceptions only. Clips are attached automatically as soon as their file reaches Nitro, so please use these buttons only when something really needs fixing."*

## Add media
1. Choose the **bulletin**, then the **story** (a bulletin that has already aired is marked, and the Yes / No box warns again).
2. Choose the **clip** from the drop-down (search box on top). The list is the files the log has already found in Blaze's media list.
3. **Not in the list?** Type the correct name (`DDMMYY_STORY_NAME`) and press *Queue it*. The request waits (up to `SUPPORT_QUEUE_MINUTES`, default 60) and is attached as soon as the file appears in Blaze. A request still waiting can be cancelled.
4. Yes / No first. When the clip is attached a **notification** appears for everyone signed in (and the queue table shows Done).

## Delete media
Choose the bulletin and the story: the clips Blaze holds for that story are listed. Choose one, answer **Yes / No**, and it is deleted. It takes the clip **out of the story only**; the file stays in Nitro. If the story is in several bulletins the box says the clip disappears from all of them. The clip's ID on the dashboard becomes *Needs desk* ("deleted from the story by ..."), so the automatic attach never puts it back; *Add media* does.

## What did not change
Polling and the watcher are untouched. Requests are carried out by the poller AFTER the round and its heartbeat, in their own error guard; the media list the round already read is reused (an idle menu costs Blaze nothing); a title search for a waiting name runs at most every 30 s, 3 per round. The hourly cap and the "N attaches in a row failed" halt never count a Support request. The story-list requests of the delete picker are answered by a small read-only thread of their own.

## Safety (same rules as a confirmed Quick test)
Works while `BLAZE_ATTACH=dry` (an editor confirmed it); blocked while `BLAZE_ATTACH=off`, while the kill-switch file exists, for a bulletin the poller does not follow, for a story format whose itemId rule is not verified, and while an earlier attach of the same story is unclear. One attempt per request: WORKING is recorded before the call; after a restart a request that was WORKING is settled by reading the story, never sent again. Read-back must show exactly the one change. A delete is refused if the clip's name changed since the list was read. Every request, result and the user's name is in the event log (`support_*`); a failure or an expired queue also alerts the chat. Editor and admin may both use it.

## Settings
`SUPPORT_MENU=1` (0 removes it, the server answers 403), `SUPPORT_QUEUE_MINUTES=60`, `SUPPORT_LIST_SECS=2`. New table `support_jobs` (created by itself; cleaned with the other history by `AUTOID_KEEP_DAYS`).

## Tests
`tests/test_support_menu.py` (20 tests, against the fake Blaze) and `tools/dev/check_support_menu.js` (the real page in a headless DOM, end to end). `tools/dev/check_tabs.js` now expects the fifth tab.
