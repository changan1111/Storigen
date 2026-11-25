# v11.1

## Add media: "Full scan" check box
In the Add media dialog a new check box, **Full scan: search all media in Blaze**, is OFF by default, so the normal list, typed-name queue and automatic attach work exactly as before.
With it ON, type at least 3 characters of the clip name and press **Scan Blaze**: every file in Blaze whose name contains that text is listed (up to 100; type more to narrow), and the editor picks one. Attaching it is the normal Add media request (Yes first, same poller rules and read-back, only that exact file id).
The same check box is in the Support menu's Add media screen (bulletin, story, clip).
The scan only searches; it sends nothing to Blaze that changes anything. It looks back `BLAZE_FULLSCAN_DAYS` days (default 365).
New files: `autoid_lite/api_fullscan.py`, `autoid_lite/blaze/fullscan.py`. `api_support.py` and `blaze/support.py` are unchanged.

## Faster attach for a clip that is on Nitro ON AIR
A file in Nitro ON AIR is final and does not grow, so for a clip the watcher has seen there (state ON_NITRO) the 60 s settle wait (`BLAZE_MEDIA_SETTLE_SECS`) is skipped. Blaze must still have converted the file. `BLAZE_SETTLE_ON_NITRO=0` brings the old wait back. Needs the NAS / Nitro watcher to be running (`WATCHER_ENABLED=1`).
