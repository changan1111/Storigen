# v10.4.0 - a story shared by several bulletins is attached once, every clip ID of it becomes ATTACHED

**Field case (16 Nov 2026):** `161126_DIST_CHN_MARINA_HORSE_ISSUE_HL`, Blaze story 734249, sits in six bulletins (shows 34820 to 34829). The tool refused to attach it ("CHECK: story is linked in shows ..."). The desk then attached it by hand in one bulletin: Blaze showed the clip in all six at once, but the four clip IDs in Auto-ID never turned ATTACHED (the read-back logged `confirm failed ... 'rows'`).

**What Blaze does:** a clip belongs to the *story*, not to a bulletin. One attach in any bulletin that holds the story shows the clip in every bulletin that holds it.

## What changed

1. **A shared story is no longer blocked.** The old CHECK flag is now only a note in the line: `SHARED story: it sits in shows ...; ONE attach in show X (the current bulletin) ...`.
2. **One attach, in the right bulletin.** The tool sends the attach through the *current* bulletin when the story is in it (it started less than 60 minutes ago), otherwise the *next future* bulletin, otherwise (everything has aired) the *latest* bulletin. Bulletins that already aired are attached too. Only followed shows that really hold the story are used.
3. **The row order comes from that bulletin.** Before, the row position was remembered per story, so for a shared story it came from whichever bulletin was read last (the log showed 27, 71, 17, 18 for one story). Now it is remembered per bulletin and story.
4. **Every clip ID of the story is marked ATTACHED.** After the attach, the tool reads the story back and marks each clip ID of the story with the same clip name and version, one per bulletin, but only when Blaze's own story read-back lists that bulletin among the story's shows. A bulletin Blaze does not list is left alone and logged once as `SHARED NOT SEEN` (the desk checks). The same marking happens when the file is already in the story ("already in story: nothing to do" now also marks ATTACHED). A file that sits in the story twice is still a DUPLICATE and is never marked.
5. **Read-back crash fixed.** When the desk attached by hand and the story had just been read, the confirm step failed with `KeyError: 'rows'`, so nothing turned ATTACHED. Fixed; a partial read leaves the item for the next full read.
6. **Newest version everywhere** (only with `BLAZE_VERSION_MODE=auto`): when two versions of a clip are ready for the same story, only the newest is attached; the older one is skipped ("Superseded"). In `desk` mode nothing changes: the desk owns versions above 1.

## Not changed

Dry mode is still the default and still sends nothing. Quick test attach, BLAZE_LIVE_SHOW_IDS and the Yes box behave as before (a shared story attached through another bulletin is still one attach to one story). No database change, no new setting.

## Tests

`tests/test_shared_story_attach.py` (10 tests: one POST for a shared story, every clip ID ATTACHED, current / next / latest bulletin, the bulletin's own row order, aired bulletins, a bulletin Blaze does not list, dry-run line, already-in-story, duplicate, the desk read-back without the crash, newest version). Two tests in `tests/test_blaze_poll.py` were changed on purpose: a linked story is now sent once and shown as a note instead of "NOT SENT".

## Upgrade

Replace the program files (keep `autoid.env` and `data`), restart the service, Ctrl+F5 once. Try it first with `BLAZE_ATTACH=dry`: the line for a shared story must say `SHARED story ... ONE attach in show ...`; then Quick test attach on one shared story, then live.
