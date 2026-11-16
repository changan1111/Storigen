"""Poller settings (Cfg), read from autoid.env / the environment."""
from __future__ import annotations
from pathlib import Path
import os
import urllib.error, urllib.parse, urllib.request
from .. import config
from . import envcheck


# ---------------------------------------------------------------- settings
class Cfg:
    def __init__(self, env=None):
        e = env if env is not None else os.environ; g = lambda k, d="": (e.get(k) or d).strip(); self.env_seen = envcheck.snapshot(e)      # v9.13.1: what this poller started with (compared with autoid.env while it runs)
        self.blaze = g("BLAZE_URL", "http://10.1.10.101").rstrip("/"); self.sid = g("BLAZE_SESSION_ID"); self.user = g("BLAZE_USERNAME")
        pw = g("BLAZE_PASSWORD_HASH"); self.pw = urllib.parse.unquote(pw) if "%" in pw else pw       # exactly what the Blaze page sends as `password` (not the typed password); a percent-encoded copy from a capture is accepted
        self.autologin = g("BLAZE_AUTOLOGIN", "1") != "0" and bool(self.pw and self.user)             # log in again by itself when the session has expired
        self.login_gap = max(5, int(g("BLAZE_LOGIN_MIN_SECS", "60"))); self.login_max_fail = max(1, int(g("BLAZE_LOGIN_MAX_FAILS", "3")))   # never hammer a wrong password: Blaze may lock the account
        self.auto = g("BLAZE_SHOW_IDS").strip().lower() == "auto"        # auto: the poller asks Blaze for the day's shows (GET /shows?filter={fromDate,toDate}) instead of using a fixed list
        self.shows = [] if self.auto else [x.strip() for x in g("BLAZE_SHOW_IDS").split(",") if x.strip()]    # in auto mode the Poller keeps this list current
        self.days_ahead = max(0, int(g("BLAZE_SHOW_DAYS_AHEAD", "0"))); self.list_secs = max(5, int(g("BLAZE_SHOW_LIST_SECS", "60")))      # also follow tomorrow's shows; how often the day's list is asked again
        # complete-day monitoring: EVERY discovered show is read EVERY pass (bounded parallel requests); there is no hot or cold tier any more
        self.concurrency = min(16, max(1, int(g("BLAZE_CONCURRENCY", "6"))))        # simultaneous requests to Blaze (the Blaze page itself sent 8 slug requests within 2 seconds)
        self.retry_max = max(5, int(g("BLAZE_RETRY_MAX_SECS", "60")))              # a failing show is retried with a growing delay (poll interval, doubled each failure) up to this many seconds
        self.ignore_shows = [x.strip().upper() for x in g("BLAZE_IGNORE_SHOW_TITLES").split(",") if x.strip()]
        self.poll = max(5, int(g("BLAZE_POLL_SECS", "15"))); self.days = max(1, int(g("BLAZE_MEDIA_DAYS", "2")))
        self.version_mode = g("BLAZE_VERSION_MODE", "desk").lower()                             # v9.6: a clip of version 2 or higher ("+ Version"): desk = never attached by the tool, the desk does it; auto = attached, then the previous version's clip is removed
        if self.version_mode not in ("desk", "auto"): raise SystemExit("BLAZE_VERSION_MODE must be desk or auto (now %r)" % self.version_mode)
        self.lookahead_h = max(0, float(g("BLAZE_SHOW_LOOKAHEAD_HOURS", "5")))                 # v9.5.1: shows of the next calendar date that start within this many hours (and before the broadcast day ends) are followed already, so a 00:00 show is not missed
        self.deadline = max(1, int(g("BLAZE_CYCLE_DEADLINE_SECS", "0")) or self.poll)   # v9.5: a round waits this long for its parallel reads; a read still running then is NOT started again and its answer is used by a later round
        self.retries = min(3, max(0, int(g("BLAZE_REQUEST_RETRIES", "1"))))              # v9.5: quick retries of a read that failed for a network or 5xx reason (only while the round has time left)
        self.keep_completed = g("BLAZE_KEEP_COMPLETED", "1") == "1"                      # v9.5: a finished show that Blaze stops listing is still followed until the broadcast day closes
        self.hot_before = int(g("BLAZE_HOT_BEFORE_MIN", "60"))                           # v9.5: a show that started longer ago than this counts as finished
        self.snap_days = max(1, int(g("BLAZE_SNAPSHOT_KEEP_DAYS", "14")))                # v9.5: snapshots and change history older than this are pruned
        self.fresh_secs = max(1, int(g("BLAZE_FRESH_SECS", str(self.poll))))        # a show not read successfully for longer than this counts as over the freshness target
        self.stale_secs = max(self.fresh_secs, int(g("BLAZE_STALE_SECS", "90")))   # ...and for longer than this it is reported as a problem on the monitoring page
        self.ident_secs = max(15, int(g("BLAZE_IDENT_SECS", "120"))); self.ident_batch = max(10, int(g("BLAZE_IDENT_BATCH", "60")))   # attachment identity sweep: each story with clips is re-read this often (at most this many per pass)
        self.timeout = max(0.2, float(g("BLAZE_TIMEOUT_SECS", "15")))              # one request to Blaze is given up after this long (and the show is retried), it never blocks the other shows
        self.media_wait = int(g("BLAZE_MEDIA_WAIT_SECS") or max(0, int(g("BLAZE_MEDIA_RETRY_SECS", "30"))) * 4); self.media_batch = max(1, int(g("BLAZE_MEDIA_BATCH", "40")))   # clips with no file seen yet are searched in Blaze's media list this rarely, and at most this many per pass, oldest first
        self.scripts = g("BLAZE_SCRIPTS", "1") != "0"; self.script_secs = max(15, int(g("BLAZE_SCRIPT_SECS", "120"))); self.script_batch = max(5, int(g("BLAZE_SCRIPT_BATCH", "40")))      # v9.13.2: read every story's two script fields; each story again this often; at most this many reads per round (the first fill after a start runs in turns)
        self.info_secs = max(0, int(g("BLAZE_INFO_SECS", "60")))                    # the story details behind a plan line are re-read at most this often (an attachment change is noticed at once through layers A and B)
        self.recon_batch = max(10, int(g("BLAZE_RECON_BATCH", "60")))               # full story reads (layer C) per reconcile pass, oldest first, so 600+ stories are covered in turn and never stall a polling round
        self.sync_secs = max(30, int(g("BLAZE_SYNC_FULL_SECS", "300")))            # the registry is re-sent a show's stories at least this often even when nothing changed
        self.media_mode = g("BLAZE_MEDIA_MODE", "list").lower(); self.media_mode = self.media_mode if self.media_mode in ("list", "search") else "list"      # list (v9.7.4): read the day's media list once per round and match every clip in code; search: one title search per clip (v9.7.3 and older)
        self.media_page = max(10, int(g("BLAZE_MEDIA_PAGE", "200"))); self.media_max_pages = max(1, int(g("BLAZE_MEDIA_MAX_PAGES", "5")))                 # list mode: files per request, and at most this many requests per round (200 x 5 = the newest 1000 files)
        self.settle = int(g("BLAZE_MEDIA_SETTLE_SECS", "60")); self.attach = g("BLAZE_ATTACH", "dry").lower()
        self.when = g("BLAZE_ATTACH_WHEN", "media").lower()          # media = Blaze's media list is enough; watcher = also wait for ON_NITRO
        self.allow_empty = g("BLAZE_ALLOW_EMPTY") == "1"
        self.ignore = [x.strip().upper() for x in g("BLAZE_IGNORE_TITLES").split(",") if x.strip()]   # template rows that never get an ID
        self.manual_titles = [x.strip().upper() for x in g("BLAZE_NO_AUTO_ATTACH", "OPENING MONTAGE,END MONTAGE").split(",") if x.strip()]   # these stories get an ID and show in the tracker, but the DESK attaches them (never the tool)
        self.only_formats = {x.strip() for x in g("BLAZE_ONLY_FORMAT_IDS").split(",") if x.strip()}   # empty = every format; else only these story formats get IDs
        self.confirm = g("BLAZE_CONFIRM", "1") == "1"                # when Blaze already shows the clip in the right story, mark it ATTACHED in Auto-ID (read-back only)
        self.reconcile = max(10, int(g("BLAZE_RECONCILE_SECS", "60"))); self.overdue = int(g("BLAZE_OVERDUE_MIN", "15")) * 60
        self.ledger = g("BLAZE_LEDGER") or str(config.data_dir() / "blaze_ledger.db"); self.reports = g("BLAZE_REPORT_DIR") or str(config.data_dir() / "reports")
        self.autoid = "http://127.0.0.1:%s" % g("WEB_PORT", "8080"); self.key = g("SERVICE_API_KEY")
        self.heartbeat = g("BLAZE_HEARTBEAT", "page").lower()        # page = what the Blaze page does (GET every 60 s, PUT every 480 s, seen over 2.2 hours); get | put | both are also possible
        self.verified = {x.strip() for x in g("BLAZE_VERIFIED_FORMATS", "20,21").split(",") if x.strip()}   # story formats whose itemId rule is confirmed (20 = Anchor); others are logged with a CHECK note
        self.retry = max(0, int(g("BLAZE_MEDIA_RETRY_SECS", "30")))    # how often one clip's file is searched for again in Blaze's media list
        self.watchlog = g("BLAZE_WATCH_LOG") or str(Path(self.reports) / "attach_watch.log")
        self.live_shows = {x.strip() for x in g("BLAZE_LIVE_SHOW_IDS").split(",") if x.strip()}       # only these shows ever get a real attach
        self.live_masters = {x.strip() for x in g("BLAZE_LIVE_MASTER_IDS").split(",") if x.strip()}   # with BLAZE_SHOW_IDS=auto the show IDs change every day, so live is allowed by the show's masterId (the same time slot every day)
        self.live_scriptdur = g("BLAZE_LIVE_SCRIPTDUR", "1") == "1"                                  # after an attach, set the story's script duration to the clips' total, as the Blaze page does
        self.live_confirm = g("BLAZE_LIVE_CONFIRM") == "YES_ATTACH_FOR_REAL"                          # second lock: a typo or half-edited file cannot turn live on
        self.live_max = max(0, int(g("BLAZE_LIVE_MAX_PER_HOUR", "0"))); self.live_halt_after = max(1, int(g("BLAZE_LIVE_HALT_AFTER", "3")))        # live_max 0 = no hourly limit
        # QUICKTEST (v9.7.5): narrow real attaching while BLAZE_ATTACH=live. Nothing set = every followed show. Set a story and/or a show to test on just those; remove the lines to go fully live.
        self.qt_stories = {x.strip() for x in g("QUICKTEST_STORY_ID").split(",") if x.strip()}      # only these Blaze story IDs get a real attach
        self.qt_shows = {x.strip() for x in g("QUICKTEST_SHOW_ID").split(",") if x.strip()}          # only these show IDs ...
        self.qt_masters = {x.strip() for x in g("QUICKTEST_SLOT_ID").split(",") if x.strip()}        # ... or these time slots (masterId), for BLAZE_SHOW_IDS=auto where the show ID changes every day
        self.stopfile = g("BLAZE_LIVE_STOP_FILE") or str(config.data_dir() / "STOP_LIVE")             # kill switch: while this file exists nothing is sent
        self.full_recon = max(60, int(g("BLAZE_FULL_RECON_SECS", "600")))    # reconcile re-reads a story at least this often even when its clip count is unchanged (catches a swapped file)
        if self.heartbeat not in ("page", "get", "put", "both"): raise SystemExit("BLAZE_HEARTBEAT must be page, get, put or both (got %r)" % self.heartbeat)
        if self.attach not in ("off", "dry", "live"): raise SystemExit("BLAZE_ATTACH must be off, dry or live (got %r)" % self.attach)
        self.live_cap = self.live_max
        if self.attach == "live" and not self.auto and self.live_shows and not self.live_shows <= set(self.shows): raise SystemExit("BLAZE_LIVE_SHOW_IDS must be among BLAZE_SHOW_IDS (got %s, followed %s)" % (",".join(sorted(self.live_shows)), ",".join(self.shows)))

    def reload_session(self):
        """Read BLAZE_SESSION_ID / BLAZE_USERNAME again from autoid.env (a cookie refresher may have written new ones). True when they changed; an empty or missing value never replaces a working one."""
        try: v = config.load_env()
        except OSError: return False
        sid, user = (v.get("BLAZE_SESSION_ID") or "").strip(), (v.get("BLAZE_USERNAME") or "").strip()
        if not sid or (sid == self.sid and (not user or user == self.user)): return False
        self.sid, self.user = sid, user or self.user; return True

    def use_session(self, sid):
        """Switch to a session ID that a login returned and keep it in autoid.env too (only the BLAZE_SESSION_ID line is touched), so a restart or a one-off command uses the same session. -> True when the file was updated."""
        self.sid = sid
        try: config.set_env({"BLAZE_SESSION_ID": sid}); return True
        except OSError: return False
