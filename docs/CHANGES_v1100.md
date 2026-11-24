# v11.0.0

## 1. A filter that is on turns green
The Editor, Created by, User, Search, Status and Hide removed controls turn green while they hold a filter, the Editor / Created by header cells of the list too, and the top bar gets a green frame with a chip "Filter on: Editor ... - clear". Click the chip to clear every filter at once. Nothing is hidden unnoticed any more.

## 2. A label after the version is ignored (VERSION_SUFFIX=on)
`221126_ELECTION_V01 (byte).mxf`, `..._V02 (minibyte).mxf`, `..._V01_U01 (tag).mxf`, `..._V01 byte.mxf` all match and attach exactly like `..._V01`, `..._V02`, `..._V01_U01`.
Only the version is validated (next number, no gap). The text after it (in brackets, or the plain words byte / minibyte / tag) is a label for people and is dropped before matching, in the watcher, the Blaze poller, the clip list read from Blaze, the Name coach and the chat.
`_V01_U01` updates are not affected: the V01 clip is still replaced only by `_V01_U01`, `_V01_U02` ..., and a label may sit after V01 or at the very end (`_V01 (byte)_U01`, `_V01_U01 (byte)`).
A story whose name contains the word BYTE (`221126_BYTE`) is untouched: only text after a `_Vnn` / `_Unn` counts as a label. Nothing is stored in the database for the label.

## 3. Chat: byte or tag
After **Append** the chat asks "Is it a byte or a tag (mini byte)?" with a help text and gives the name with the label: `221126_ELECTION_V02 (byte)`, `..._V02 (minibyte)`, or without a label. "Check a file name" accepts the labelled names.
