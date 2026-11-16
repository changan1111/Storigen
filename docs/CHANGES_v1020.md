# v10.2.0 - Ready feed: be told when a clip is ready instead of watching the NITRO chip

**Why:** during the trial someone had to keep an eye on the dashboard to see when a story's NITRO chip turned green. Now the program tells you.

## What is new

**1. Ready feed (dashboard).** A **Ready feed** button (badge = clips ready to attach; key **F**) opens a panel on the right that keeps itself up to date every 5 s. Each entry shows: time it became ready, status, **story name**, **clip ID**, **Blaze story ID**, **MOS object ID**, **media name**, bulletin. Click an ID to copy it; click the story name to open that story. It has a **search box** (story, clip, Blaze story ID, MOS object ID, media name, bulletin; every word must match) and a filter (All / Ready to attach / Attached / Needs attention), plus a summary line with the day's counts. Statuses: Ready to attach, Attach requested, Attach sent, Attached, Not sent (with the reason), Needs desk (with the reason).

**2. Notification when a clip becomes ready (in the page).** A toast appears with the story, clip ID and MOS object ID, once. Tick **"notify me"** in the feed to also get a sound and a desktop notification (the browser asks permission once). The first look at a day is never "news", so opening the page does not flood you. This works while the dashboard is open in any tab or window; it does not work with the page closed.

**3. Chat push (the "bot").** Set `READY_WEBHOOK_URL` in `autoid.env` (a Teams / Slack style incoming webhook that accepts `{"text": "..."}`) and the server posts one message the moment a clip becomes ready, whoever has the dashboard open:

`READY on Nitro: Rain alert coastal | clip 161126_RAIN_ALERT_COASTAL | MOS 4400255 | media 161126_RAIN_ALERT_COASTAL.mxf | Morning Bulletin`

One message per clip; a **replaced** file counts as news again; nothing for a clip already attached by the desk; a dead or slow webhook never delays or breaks the poller (the message is sent in the background). It has its own setting, separate from `ALERT_WEBHOOK_URL`, so the failure-alert channel stays quiet. Empty (the default) = no message. Restart to apply.

**"Ready" means** the file is in Blaze's media list, finished converting and settled (the same moment the NITRO chip turns green), not merely exported.

## How it works (small, on purpose)

* The poller already told the server, once per clip, when Blaze's media list has the file. It now also sends the file's **media name**, and the server stores it (new column `clip_ids.media_name`, schema version 8, added by itself on the first start). The server logs the event and sends the chat message **only when the media object is new for the clip**, so a repeat is silent.
* After the upgrade the poller tells each clip once more so today's clips get their media names. That backfill makes no new event and no chat message.
* New endpoint `GET /api/feed` (login required): `day`, `q`, `status` (all, ready, attached, problem), `limit` (1 to 300). Read only.
* Nothing new polls Blaze. No change to attaching, the safety wall, the Quick test button or any setting you already use.

## Cost (measured, 700-clip day)

`/api/feed` with the drawer closed: about 19 KB and 5 ms per refresh (it is how new arrivals are spotted); open: about 140 KB (300 entries) in one request. The poll benchmark is unchanged from 10.1.1 (same requests per round, same timings).

## Not included (say if you want them)

* Per-person subscriptions (for example only the editor of that story). The chat message goes to one channel.
* A message when the clip is **attached**, or when something **fails**; and email / WhatsApp / Telegram for the ready message (the webhook is the one channel built).
* Teams: if your Teams webhook does not accept the simple `{"text": ...}` form, use a Teams Workflows webhook that does, or ask for the card format. Please test with your own URL.

## Tests

`tests/test_ready_feed.py` (12 tests: fields, order, search, status words and counts, day scope, removed stories, limit, login, event de-duplication, the chat message once and never for an attached clip or with a dead webhook, the poller sending the media name and backfilling it, the 7 to 8 database upgrade, no `innerHTML` for names). `tools/dev/check_refresh_dom.js` gained the feed checks (drawer, rows, search, filter, toast once, NEW mark, zero page changes while open, Esc and F).

## Upgrade

Replace the program files (keep `autoid.env` and `data`), optionally add `READY_WEBHOOK_URL`, restart the service, press Ctrl+F5 in the browser once.
