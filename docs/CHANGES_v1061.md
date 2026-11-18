# v10.6.1 - Quick test on a clip the desk already attached; format 22

Two things seen on the desk.

## 1. Quick test attach said "Not sent" when the desk had already attached the file
The poller found the file in the story, sent nothing (correct), but reported the Quick test as **BLOCKED / Not sent** and the clip could stay Waiting.
* The clip is now marked **ATTACHED** at that moment, and the Quick test answer is **attached**: "the file was already in the story (the desk attached it): nothing was sent by the tool, and this clip ID is now marked ATTACHED". It is no longer a refusal.
* The poller called the file "already in the story" when EITHER of its two readings of Blaze showed it (story details, attachment identity), but marked the clip only from the story details. Both readings are now used (a file listed twice is still a duplicate and is never marked).
* When the clip still cannot be marked, the answer and the card's "why waiting" line say **why** ("BLAZE_CONFIRM=0 ...", "Blaze's story read does not list the file yet", the server's own reason), instead of a bare "Not sent".
* Nothing is sent to Blaze in this case, and a clip is still never sent twice.

## 2. Format 22 "not working"
Not a fault: the tool attaches only **verified story formats** (`BLAZE_VERIFIED_FORMATS`, default `20,21`), and this includes Quick test attach. A story of format 22 is held with "CHECK: itemId rule not yet verified for story format 22". The text now names the setting.
To use format 22: look at a format 22 story's `GOING TO ATTACH` line in the poller log and check that its `itemId` is the item the desk's own attach uses; then set `BLAZE_VERIFIED_FORMATS=20,21,22` (and add 22 to `BLAZE_ONLY_FORMAT_IDS` if that is set, or those stories get no IDs) and restart the service. The tool cannot check that rule by itself, so it stays your decision. `autoid.env.example` explains it.

## Tests
`tests/test_quick_test_already_in_story.py` (4 tests): desk attached first then Quick test, the reason text, the two readings, format 22 blocked and then allowed. Each fails on 10.6.0.

## Upgrade
Replace `autoid_lite/blaze/attach.py`, `autoid_lite/blaze/poller.py`, `autoid_lite/common.py` and `autoid_lite/web/index.html`, restart the service, Ctrl+F5 once. Settings are not touched. Check the version in the page header says v10.6.1.
