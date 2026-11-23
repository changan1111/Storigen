# v10.17.0 - Add media once per story, hand-added clips on the dashboard, the chat sees the real clip list, violence check made visible

## 1) Add media on every clip
* Each clip card has only **Delete** (that belongs to one clip).
* There is **one Add media per story**, in the gallery header.
* A story with a single clip keeps its one Add media in the normal button row, even when that clip is already attached.

## 2) Dashboard not showing manually added media
* The dashboard only listed clips Storigen had made IDs for. Support reads the story from Blaze, so it saw everything.
* The poller now reports the **full clip list of each story** to the server (`/svc/story_clips`, kept in the new table `story_blaze_clips`). It does so after every Support add, delete or list, and during its normal story reads (only when the list changed, or every 10 minutes).
* A clip that is in Blaze but not in the registry shows as an **Added by hand** card with a working **Delete**, and counts in the story's clip total. These cards have no preview or quality checks: Storigen does not hold the file.
* When a Support add or delete finishes, the open story redraws by itself.

## 3) Chatbot only saw the base clip
* When you pick a story the server first asks Blaze for the real clip list (the same read-only LIST request the Delete button uses, answered by the poller, up to 8 seconds).
* That list is merged with the registry **before** the next `_U` / `_V` names are worked out. A hand-added `_V01` leads to `_V02`. Clips with another name are listed apart and never change the numbering.
* If Blaze does not answer, the chat falls back to what the poller last saw and says so. If the poller is not running it does not wait at all.
* "Check a file name" uses the same plan, so it knows about hand-added clips too.

## 4) Violence check with Groq
* The button is **🛡 Violence check (AI)** (it is the v10.16.0 AI standards check) and it is now **always shown** on a clip. When it is greyed out its tooltip says why: the admin switch is off (**Users > Features > AI standards check**), `GROQ_API_KEY` is empty, or the clip is not on Nitro yet.
* "Groq could not be reached from the Storigen machine" means the machine cannot open https://api.groq.com (port 443). The message now adds the reason (name not found, no answer in time, secure connection refused, connection refused). Ask IT to allow `api.groq.com`, or set `GROQ_PROXY` in autoid.env. Describe with AI uses the same connection, so it will work again at the same moment.

## Tested, and what is not
`tests/test_v10170.py`: the name logic (hand-added `_V01` -> `V02`, `_U` and `_V01_U01` placed, other names kept apart), the server report and dedupe, the gallery data with a hand card, the clip total, the poller report, and the page. **Not tested: the real Blaze and the real Groq** (no access from the build machine).
