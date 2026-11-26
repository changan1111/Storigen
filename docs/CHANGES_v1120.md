# v11.2

## 1. Clips column: 0 until a clip is attached
A story whose clip ID is still waiting (or exporting, or on Nitro) showed **1** in the Clips column because the page counted the clip ID itself. The number is now the clips really in the story: attached and not replaced, plus clips added by hand in Blaze. A story with nothing attached says **0**.
It is worked out on the server for every setting (it used to need `VERSION_SUFFIX=on`), the "clips" sort uses the same number, and the Story Media Gallery header says e.g. "2 clips · 1 not attached" instead of counting the IDs that are still waiting.

## 2. The plain (base) clip takes a label too
`221126_ELECTION (byte).mxf`, `(minibyte)`, `(tag)` and `(del)` now match and attach exactly like `221126_ELECTION.mxf`, the same way `_V01 (byte)` / `_U01 (tag)` already did. Watcher, poller, clip list read from Blaze, Name coach and chat all ignore the label.
To keep the working flow safe the rule is narrow:
* only one of these words **inside brackets at the very end** of the plain name counts (`(byte)`, `(minibyte)` or `(mini byte)`, `(tag)`, `(del)`; capitals do not matter, several in a row are fine);
* a story called BYTE, TAG or DEL (`221126_MODI_BYTE`, `221126_FIRE_TAG`), a copy number (`221126_FIRE (2)`, `221126_FIRE_2`) and any other bracket text are not labels and are left exactly as before;
* a label in the middle of a plain name (`221126_FIRE (byte)_V01`) is not read; put it at the end;
* off when `VERSION_SUFFIX=off`, like the labels after a version.
Nothing is stored for the label.
Behind a version (`_V01`, `_U01`, `_V01_U01`) nothing changed and brackets are NOT required: any text in brackets is a label (`_V01 (del)`), and so are the plain words byte, minibyte and tag at the very end, separated by a space, `_` or `-` (`_V01 byte`, `_V01_byte`, `_V01-minibyte`, `_U01_tag`). Two limits: `del` is a label only in brackets (`_V01 (del)`, not `_V01_del`), and a plain word in the middle (`_V01_byte_U01`) is not read: use brackets there (`_V01 (byte)_U01`). On the plain clip brackets ARE required, because `_BYTE` / `_TAG` / `_DEL` can be part of a story name.

## 3. Chat: the label of each clip is shown
In the Clip assistant, the "In the story now" list, the Update picker ("Added clip V01 — 221126_ELECTION_V01 (minibyte)"), the Update help text and the "system has seen" check now show the (byte) / (minibyte) / (tag) / (del) label of every clip that has one, so V01 and V02 can be told apart. A clip with no label shows none; nothing is guessed.
The label is read back from the two places that still hold the name the editor typed: the file names the watcher saw, and Blaze's own clip titles (Blaze has the last word). A labelled clip that is in the registry is no longer listed under "Other clips (a different name)".

## Files
`ids.py`, `coach.py`, `watcher.py`, `api_blazeclips.py`, `api_bot.py`, `api_dashboard.py`, `common.py` (version), `web/index.html`, `electron/package.json`, `tools/standalone_shim.js` (sample page counts like the server), `tests/test_v11200.py` (new) and the four tests that pin the version number. `api_support.py` and `blaze/support.py` are unchanged.
