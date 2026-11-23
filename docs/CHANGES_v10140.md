# v10.14.0 - Add media in the dashboard, next to Delete

## What it adds
An **➕ Add media** button right next to **🗑 Delete**, on the story that is open in the dashboard (Rundown tab):
* beside Delete in the Preview box and on every clip card of the story gallery;
* in the story's button row (with Copy ID / + Version / Quick test attach) while the story has no attached clip yet, which is exactly when you need it.

It opens the same thing as Quick Support > Add media, for **this** story (no need to pick the bulletin and story again):
1. a **search box** over the clips Blaze already holds (the last `BLAZE_MEDIA_DAYS` days, newest first: file name, MOS ID, when it was found);
2. or **type the correct name** (`DDMMYY_STORY_NAME`) if the file is not in the list yet: it is queued and attached as soon as the file appears in Blaze (it waits up to the Support wait time);
3. **Yes / No** before anything is sent ("Attach this clip to the story?" or "Queue this clip?"), with the "bulletin has already aired" warning when it applies;
4. a toast says it was requested, and the result appears with the Support queue notifications, as for Delete.
An error (name not valid, clip already queued, file no longer in the list) is explained inside the dialog and nothing is lost.

## Same rules as Quick Support (nothing new on the server)
The button sends the existing `POST /api/support/add` with `confirm: true`. **`api_support.py` is unchanged**: the Blaze poller carries the request out under the same safety rules, it is recorded with the user's name, and everyone signed in sees it in the queue. The button is greyed out, with the reason, when `SUPPORT_MENU=0`, when the user's role cannot attach, or when the story has no real Blaze story ID (a manual placeholder story has nothing to attach to in Blaze).

## Version
v10.14.0 (page header, `APP_VERSION`, Electron package, sample page, tests).

## Tested
`tests/test_add_media_dashboard.py` (3 tests): the page wiring (one write only, always with Yes); the exact request the dashboard builds from the story's own data is accepted, queued with the user's name, attached by the poller, and refused without the Yes; and the whole flow in real Chromium on a live server: the button on the open story, the list of Blaze media, search with no match, Cancel (queues nothing), No at the question (queues nothing, dialog stays), pick + Yes (one ADD request queued, toast, poller attaches), the button beside Delete once attached, an invalid typed name explained inside the dialog with nothing extra queued, no JavaScript error. Not tested here: a live Blaze (the existing fake Blaze of the test-suite is used, as for Quick Support).
