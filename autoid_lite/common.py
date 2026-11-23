"""Shared constants and helpers of the Storigen server: version, states, errors, request object, settings from the environment."""
from __future__ import annotations
from .config import data_dir
import os, re

APP_VERSION = "10.18.2"
from .states import STATES  # noqa: F401  (defined once in states.py)
HOLD = "STORY REMOVED: "        # attach_error prefix of every clip held because its Blaze story is no longer in the rundown
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_BODY = 5 * 1024 * 1024

def opt(v):
    """Optional ID from a JSON body -> text, or None when absent."""
    return None if v is None or v == "" else str(v)

class HttpError(Exception):
    def __init__(self, status, detail, **extra): self.status, self.detail, self.extra = status, detail, extra

def norm(s): return " ".join((s or "").split()).casefold()
def removed_message(why): return HOLD + why + ". Check Blaze before attaching; do not attach by story name."

def support_minutes(v, default=60):
    """v10.10.1: SUPPORT_QUEUE_MINUTES is a whole number of minutes, 1 to 1440. Text or nothing -> the default (60) instead of stopping the program; a number outside the range is pulled into it."""
    try: n = int(str(v).strip() or default)
    except ValueError: return default
    return min(1440, max(1, n))

def settings_from_env(env=None):
    e = env if env is not None else os.environ
    g = lambda k, d="": (e.get(k) if e.get(k) is not None else d)
    comps = [c.strip() for c in g("HEALTH_COMPONENTS", "").split(",") if c.strip()] or (["watcher"] if g("WATCHER_ENABLED", "1") != "0" else []) + (["gateway"] if g("MOS_ENABLED", "0") == "1" else []) + (["blaze_poll"] if g("BLAZE_POLL", "0") == "1" else [])
    if g("WATCHER_ENABLED", "1") == "0": comps = [c for c in comps if c != "watcher"]            # v9.12: a switched-off watcher is never checked, even if HEALTH_COMPONENTS lists it
    mode = g("LINK_MODE", "placeholder").strip().lower()
    if mode not in ("placeholder", "story_id"): raise SystemExit("LINK_MODE must be placeholder or story_id (got %r)" % mode)
    try: keep = int(g("AUTOID_KEEP_DAYS", "7").strip() or "7")
    except ValueError: raise SystemExit("AUTOID_KEEP_DAYS must be a whole number of days (7), or 0 to keep everything (got %r)" % g("AUTOID_KEEP_DAYS"))
    if not 0 <= keep <= 3650: raise SystemExit("AUTOID_KEEP_DAYS must be 0 (keep everything) or 1 to 3650 (got %d)" % keep)
    pat = g("AUTOID_PURGE_AT", "03:30").strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", pat): raise SystemExit("AUTOID_PURGE_AT must be a time like 03:30 (got %r)" % pat)
    return {"keep_days": keep, "purge_at": pat, "link_mode": mode, "api_key": g("SERVICE_API_KEY"), "secret": g("SESSION_SECRET"), "tz": g("AUTOID_TZ").strip(), "day_start": g("BROADCAST_DAY_START", "05:00"),
            "valid_required": g("VALID_UPTO_REQUIRED", "1") != "0", "session_secs": int(g("SESSION_SECONDS", "43200")), "story_url": g("BLAZE_STORY_URL_TEMPLATE"),
            "admin_contact": g("ADMIN_CONTACT").strip(), "components": comps, "watcher_enabled": g("WATCHER_ENABLED", "1") != "0", "blaze_silent": int(g("BLAZE_SILENT_SECS", "300")), "stale": int(g("STALE_SECS", "90")),
            "move_hint": int(g("MOVE_HINT_SECS", "600")), "cookie_secure": g("COOKIE_SECURE", "0") == "1", "allow_manual": g("ALLOW_MANUAL", ""), "quick_attach": g("QUICK_TEST_BUTTON", "1") != "0", "support": g("SUPPORT_MENU", "1") != "0", "support_wait_min": support_minutes(g("SUPPORT_QUEUE_MINUTES", "60")), "reports_dir": g("BLAZE_REPORT_DIR") or str(data_dir() / "reports"),
            "script_labels": [g("SCRIPT_LABEL_ONLINE", "Online script").strip() or "Online script", g("SCRIPT_LABEL_ANCHOR", "Anchor script").strip() or "Anchor script"] }      # v9.13.2: the names of the two script boxes

class Req:
    def __init__(self, method, path, q, body, headers, m=None):
        self.method, self.path, self.q, self.body, self.headers, self.m = method, path, q, body, headers, m or ()
        self.user = None; self.set_cookies = []; self.client = "?"
    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name: return v
        return None
