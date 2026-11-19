# v10.7.0 - hardening of `_U01` / `_V01` (VERSION_SUFFIX=on): next number only, aired bulletins skipped, the desk is told, exact clip count

**Request:** take the v10.6.1 build as the base and fix the risky points of the update / added-clip feature. Nothing changes while `VERSION_SUFFIX=off` (the default).

## What was risky, and what is done
1. **A typo could make a clip ID.** `_U07` was accepted with no `_U01`..`_U06`. Now only the **next number of its kind** makes a clip ID (`_U01` first, then `_U02`; updates and added clips are counted separately; `_U02`, `_u2` and `_U2` are one name).
   A refused file stays "not in the registry" and the watcher's alert now says why (for example: *the next update for 111126_FIRE is U01*). The number is counted per clip name, so `111126_FIRE_2` does not use up the numbers of `111126_FIRE`.
2. **Bulletins that had already aired got a clip ID that would wait forever.** Stories of bulletins that started more than 60 minutes ago are now skipped (they keep what they have). If every bulletin of that name has aired, the newest one's story takes it.
3. **Lists were sorted by the stored number (1000+n / 2000+n),** so every update came before every added clip. The clip list (`/api/clips`, `/svc/clips`, the CSV) is now in the order things happened: the plain clip, then each change as it was created.
4. **"3 clips in this story" counted clip IDs,** including a clip an update had already replaced and clips not attached yet. It now counts the clips really in the story (attached and not replaced).

## What the desk is told (new)
* **A clip ID made from a file name** raises an alert (the same channels as the others): *UPDATE (replaces the story's main clip) detected ...* or *NEW CLIP (added beside the clips already in the story) ...*.
* **An added clip went in** and the story now holds several clips: event `MULTIPLE CLIPS` and an alert *Multiple clips: story ... now holds 2 clips ...*.
* **An update replaced a clip** (after the verified read-back): alert *UPDATED: clip ... replaced ...* and the older clip IDs (one per bulletin of that story) are marked **replaced**.
* **Dashboard:** the older clip's card says **REPLACED by U01**; the gallery row says **Replaced by U01**; Ready feed rows show **UPDATE U01** / **ADDED V01**; the "ready on Nitro" message names it (*UPDATED clip READY ...* / *ADDED clip READY ...*).

## Under the hood
* Two additive columns on `clip_ids` (schema 9): `replaced_at`, `replaced_by`. The program adds them by itself at start; nothing is deleted or changed. A database made by this version cannot be opened by an older program (it says so); keep a backup (`data/backups`) before upgrading, as always.
* New service call `POST /svc/replaced` (the poller uses it after a verified replace; only older clips of the SAME Blaze story are ever marked).
* `auto_versions` (the registration inside `/svc/match`) is unchanged in shape; the two new rules are inside it. The refusal reason travels as the 404's `detail`.
* Feed items now carry `label` (U01 / V01) and `kind` (update / added); clip rows carry `replaced_at`, `replaced_by`, `replaced_label`; the gallery's `story_clips` rows carry `replaced`, `replaced_by`. `story_clips` on a clip row now means *clips in the story*.
* The README no longer names the earlier product name (a branding test failed on it in the uploaded zip).

## Not changed (on purpose)
* The registration still happens when the watcher sees the file name (Playout inbox / export folder), inside `GET /svc/match`.
* An update still removes only the story's main clip, never an added one; with more than one possible main clip nothing is chosen.
* If a gap is real (a `_V01` that never passed the watcher), the next file is refused until `_V01` exists. The alert names the number the registry expects.

## Tests
`tests/test_version_suffix_hardening.py` (10 tests): next number only and the reason; similar names; aired bulletins skipped; all aired -> newest; order; alert on registration; Ready feed label; multiple-clips alert; update marks the old clip replaced, tells the desk, nothing repeated; the replaced call is checked.
`tests/test_version_suffix.py` test 11 was changed on purpose (the count now means clips in the story). Version pins moved to 10.7.0. Whole suite: **436 passed, 1 skipped** (needs jsdom).

## Upgrade
Back up `data`, replace the program files (keep `autoid.env` and `data`), restart both services, Ctrl+F5 once; the page header must say v10.7.0. Then, with `VERSION_SUFFIX=on` and `BLAZE_ATTACH=dry`: export `_V01` and `_U01` for a story already attached, read the log lines and the alerts, Quick test one, then live.
