"""Poller: the polling cycle, session recovery and the run loop."""
from __future__ import annotations
from pathlib import Path
import json
import os
import time
from .errors import LoginFailed, SessionExpired
from .. import config
from . import envcheck
from .scope import live_scope_text
from .util import say


class RunMixin:
    def cycle(self):
        """One polling round. Two rounds never run at the same time: a second call while one is running is skipped and counted."""
        if not self.lock.acquire(blocking=False): self.stats.overlaps += 1; say("polling round skipped: the previous round is still running"); return []
        try:
            t0 = time.monotonic(); self.stats.begin()
            ph = self.stats.phase; t = time.monotonic(); n = self.sync(); ph["sync"] = time.monotonic() - t
            t = time.monotonic(); self.identity() if not self.closed else None; ph["identity"] = time.monotonic() - t
            t = time.monotonic(); self.rows = self.fetch_rows(); self.ready(); plans = self.plan(); self.send_why(); ph["plan"] = time.monotonic() - t
            t = time.monotonic()
            try: self.read_scripts()
            except SessionExpired: raise
            except Exception as e:                                                       # v9.13.2: the scripts are a bonus: a problem here is said once and never stops the round
                if "scripts_err" not in self.said: self.said.add("scripts_err"); say("could not read the story scripts (%s: %s): polling goes on" % (type(e).__name__, e))
            ph["scripts"] = time.monotonic() - t
            if time.time() - self.last_rec >= self.c.reconcile: t = time.monotonic(); self.reconcile(); ph["reconcile"] = time.monotonic() - t; self.write_page(); self.last_rec = time.time()
            if time.time() - self.pinged > 60: self.b.ping(); self.pinged = time.time()
            self.finish_cycle(t0, n); self.daily(); return plans
        finally: self.lock.release()
    def settings_drift(self):
        """v9.13.1: autoid.env was edited after this poller started: it still runs the OLD values. Said once in the log, and on the dashboard through the heartbeat."""
        now = time.time()
        if now - getattr(self, "drift_at", 0) < 20: return getattr(self, "drift", [])
        self.drift_at = now
        try: self.drift = envcheck.differences(self.c.env_seen) if config.env_path().exists() else []
        except Exception: self.drift = []
        if self.drift and self.drift != getattr(self, "drift_said", None): self.drift_said = self.drift; say("SETTINGS CHANGED in autoid.env but NOT applied: %s. Restart the service to apply them." % "; ".join(self.drift))
        return self.drift
    def send_why(self):
        """v9.13.1: tell the dashboard why each waiting clip is not attached yet (only when it changed, and at least every 45 s so the dashboard knows the poller is alive)."""
        w = getattr(self, "why_map", None) or {}; sig = json.dumps(w, sort_keys=True); now = time.time()
        if sig == getattr(self, "why_sig", None) and now - getattr(self, "why_at", 0) < 45: return
        self.why_sig, self.why_at = sig, now
        try: self.a.call("/svc/why", {"why": w})
        except Exception: self.why_sig = None                                      # the dashboard did not get it: send again next round
    def ages(self, now=None):
        now = now or time.time(); return {sh: now - (self.last_ok.get(sh) or self.started) for sh in self.c.shows}
    def problem(self, ages):
        """What the monitoring page should show as a problem: shows not read for too long, or rounds that keep missing the target."""
        bits = []; stale = [] if self.closed else sorted((sh for sh, a in ages.items() if a > self.c.stale_secs), key=lambda sh: -ages[sh])      # a closed day is paused on purpose
        if stale: bits.append("%d of %d shows have not been read from Blaze for over %d s (%s%s)%s" % (len(stale), len(ages), self.c.stale_secs, ", ".join(stale[:3]), " ..." if len(stale) > 3 else "",
                                                                                                    ": " + str((self.store.polls().get(stale[0]) or {}).get("last_error") or "") if (self.store.polls().get(stale[0]) or {}).get("last_error") else ""))
        if self.slow_streak >= 3: bits.append("a polling round takes %.0f s, longer than the %d s target: updates arrive late" % (self.stats.cycle_s, self.c.poll))
        return "; ".join(bits) or None
    def finish_cycle(self, t0, n):
        now = time.time(); dur = time.monotonic() - t0; self.stats.end(dur, self.c.poll); ages = self.ages(now)
        self.slow_streak = self.slow_streak + 1 if dur > self.c.poll else 0
        if dur > self.c.poll and now - self.slow_said > 60: self.slow_said = now; say("POLL SLOW: this round took %.1f s, the target is %d s (%d show request(s), median %.0f ms)" % (dur, self.c.poll, len(self.stats.api_ms), sorted(self.stats.api_ms)[len(self.stats.api_ms) // 2] if self.stats.api_ms else 0))
        d = self.stats.as_dict(self.c.poll, ages, self.c.fresh_secs, self.c.stale_secs); prob = self.problem(ages)
        if now - self.log_at >= 60 or d["changed_stories"] or d["show_requests_failed"]:
            self.log_at = now; say("POLL %d shows (%d ok, %d failed), %d slugs, %d stories, round %.1f s of %d s, API median %s ms, %d changed, %d attachment change(s), %d over the freshness target%s" % (
                d["shows"], d["show_requests_ok"], d["show_requests_failed"], d["slugs"], d["stories"], d["cycle_s"], self.c.poll, d["api_ms_median"], d["changed_stories"], d["attachment_changes"], d.get("shows_over_target", 0), "" if not prob else "  PROBLEM: " + prob))
        try:
            rp = Path(self.c.reports); rp.mkdir(parents=True, exist_ok=True); polls = self.store.polls()
            body = json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "stats": d, "problem": prob, "shows": [{"id": sh, "title": (self.names.get(sh) or ("", 0))[0], "last_ok_age_s": round(ages[sh], 1), "fails": (polls.get(sh) or {}).get("fails", 0),
                                                                                                                 "last_error": (polls.get(sh) or {}).get("last_error")} for sh in self.c.shows]}, ensure_ascii=False, indent=1)
            tmp = rp / "poll_stats.json.tmp"; tmp.write_text(body, encoding="utf-8"); os.replace(tmp, rp / "poll_stats.json")
        except OSError: pass
        if now - getattr(self, "pruned", 0) > 86400: self.pruned = now; self.store.prune(now, self.c.snap_days)
        self.a.call("/svc/heartbeat", {"component": "blaze_poll", "detail": {"stories": n, "shows": len(self.c.shows), "attach": self.c.attach, "poll": d, "problem": prob,
                                                                                    "pid": os.getpid(), "began": getattr(self, "began", None), "differs": self.settings_drift()}})     # only after a good read: silence turns the page red
    def auto_login(self):
        """Log in again by itself (BLAZE_PASSWORD_HASH set, BLAZE_AUTOLOGIN not 0). -> True when a fresh session is now in use. At least BLAZE_LOGIN_MIN_SECS between tries, and after BLAZE_LOGIN_MAX_FAILS failures
        in a row it stops (a wrong hash sent again and again could lock the account) until a new cookie turns up in autoid.env or the program restarts. The call that failed is never repeated: the next round just uses the new session."""
        c = self.c
        if not c.autologin or self.login_fails >= c.login_max_fail or time.time() - self.login_at < c.login_gap: return False
        self.login_at = time.time()
        try: sid = self.b.login()
        except LoginFailed as e:
            self.login_fails += 1; say("LOGIN FAILED (%d of %d): %s" % (self.login_fails, c.login_max_fail, e))
            if self.login_fails >= c.login_max_fail: self.a.alert("Blaze poller: automatic login failed %d times in a row (%s). Automatic login is paused so the account is not locked. Fix BLAZE_PASSWORD_HASH or put fresh cookies into autoid.env." % (self.login_fails, e))
            return False
        self.login_fails = 0; saved = c.use_session(sid)
        say("logged in to Blaze again (session ending ...%s%s)" % (sid[-4:], ", saved in autoid.env" if saved else ", NOT saved: autoid.env could not be written, kept in memory only")); return True
    def session_problem(self, e, bad):
        """The Blaze cookie stopped working. 1) autoid.env holds a different one: use it. 2) a login is configured: log in again. 3) otherwise say so once and raise an alert. -> the new value of `bad`."""
        if self.c.reload_session(): self.login_fails = 0; say("a new session cookie was found in autoid.env: using it"); return False
        if self.auto_login(): return False
        if self.c.autologin and self.login_fails < self.c.login_max_fail: return True              # a login was tried and failed, or is waiting for its pause: the next round tries again, nothing more to say yet
        if not bad:
            say("PROBLEM: %s. Put fresh sessionId and username cookies into autoid.env (picked up automatically, no restart needed)%s." % (e, "" if self.c.autologin else ", or set BLAZE_PASSWORD_HASH so the program logs in by itself"))
            self.a.alert("Blaze poller: the Blaze session cookie is not valid any more. Put a fresh sessionId and username into autoid.env (picked up automatically, no restart).")
        return True
    def run(self):
        self.began = time.time(); say("blaze_poll started: %s  shows=%s  attach=%s%s  (attach lines go to %s)" % (self.c.blaze, "auto (the day's shows from Blaze)" if self.c.auto else ",".join(self.c.shows), self.c.attach,
            {"live": " LIVE " + live_scope_text(self.c) + ": REAL ATTACHES ARE SENT", "dry": " (nothing is sent to Blaze)", "off": ""}[self.c.attach], self.c.watchlog)); bad = False
        while True:
            t_start = time.monotonic()
            try:
                self.cycle()
                if bad: say("recovered"); bad = False
            except SessionExpired as e: bad = self.session_problem(e, bad)
            except Exception as e:
                if not bad: say("PROBLEM: %s: %s" % (type(e).__name__, e))
                bad = True
            time.sleep(max(1, self.c.poll - (time.monotonic() - t_start)))
