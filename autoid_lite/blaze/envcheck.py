"""Has autoid.env changed since this poller started? The poller reads its settings once, at start. The dashboard warns when the file now says
something else, so nobody believes a change is live when the running poller still uses the old value."""
from __future__ import annotations
import os
from .. import config

WATCH = ("BLAZE_ATTACH", "BLAZE_ATTACH_WHEN", "BLAZE_SHOW_IDS", "BLAZE_LIVE_SHOW_IDS", "BLAZE_LIVE_MASTER_IDS", "QUICKTEST_STORY_ID", "QUICKTEST_SHOW_ID",
         "QUICKTEST_SLOT_ID", "BLAZE_VERSION_MODE", "VERSION_SUFFIX", "BLAZE_POLL_SECS", "BLAZE_MEDIA_SETTLE_SECS", "SUPPORT_MENU")      # the settings that decide what is attached and when; the session cookie is not here (it is re-read by itself)


def snapshot(env=None):
    e = os.environ if env is None else env; return {k: (e.get(k) or "").strip() for k in WATCH}


def differences(snap, file_env=None):
    """-> sentences, one per setting whose value in autoid.env is not what the running poller started with ([] = in step)."""
    cur = config.load_env() if file_env is None else file_env; out = []
    for k in WATCH:
        now = (cur.get(k) or "").strip(); was = snap.get(k, "")
        if now != was: out.append("%s: the running poller uses %s, autoid.env now says %s" % (k, was or "(not set)", now or "(not set)"))
    return out
