#!/usr/bin/env python3
"""Blaze DataService poller (LINK_MODE=story_id, no MOS, no licence). Stdlib only.

  python3 tools/blaze_poll.py run            follow the rundowns in BLAZE_SHOW_IDS (or, with BLAZE_SHOW_IDS=auto, every show of the broadcast day) forever (the supervisor starts this when BLAZE_POLL=1)
  python3 tools/blaze_poll.py shows [YYYY-MM-DD]   the day's shows as Blaze lists them (id, start, title, stories, last poll)
  python3 tools/blaze_poll.py stats          the last polling cycle's statistics (shows, slugs, stories, failures, timings, changes, stale shows)
  python3 tools/blaze_poll.py once           one pass, printed, then exit (best first test)
  python3 tools/blaze_poll.py show 34427     print what Blaze returns for a rundown (its name and its slugs)
  python3 tools/blaze_poll.py media [text]   print Blaze's Playout media list for the last BLAZE_MEDIA_DAYS days
  python3 tools/blaze_poll.py report [YYYYMMDD]   tool-vs-desk agreement for a day (also written daily to data/reports/ as CSV)
  python3 tools/blaze_poll.py map            print show ID / slug ID / story ID / clip ID for today (from the Auto-ID registry)
  python3 tools/blaze_poll.py live           live-attach status: switches, kill switch, what was sent in the last hour, last attempts
  python3 tools/blaze_poll.py undo <clip ID> [blazeClipId]   remove a clip this tool attached (DELETE), for a mistake
  python3 tools/blaze_poll.py live-retry <clip ID>           allow one new attempt for a clip whose attach failed
  python3 tools/blaze_poll.py summary [N]    tool-vs-desk agreement for the last N days (default 5): the "can we go live?" table
  python3 tools/blaze_poll.py scripts 732527   what the poller reads as the story's two script fields (text1 / text2), with the lengths
  python3 tools/blaze_poll.py probe 724921 [versionId]   print what Blaze returns for one story (to find itemId and order)

What a pass does:
 1. READ   GET /DataService/shows/<id>/slugs  -> story IDs and titles -> POST /svc/rundowns/sync (clip IDs are made from the story ID)
 2. READY  when a clip reaches Nitro it logs   READY ON NITRO  <clip ID> is on Nitro: ready for story <id> ...   (once per clip, also in data/reports/attach_watch.log)
 3. FIND   for clips still waiting, search Blaze's media list (GET /DataService/mosobjects, filter title=<clip ID>) and require exactly one file
 4. PLAN   log   GOING TO ATTACH  <clip ID> ... to story <id> ... order=.. itemId=..   plus the exact POST /DataService/stories/<id>/clips/ call. NOTHING IS SENT (BLAZE_ATTACH=dry).
This program only ever READS from Blaze (plus the same session keep-alive the Blaze page sends). It never creates, edits or deletes anything in Blaze.
LIVE ATTACH exists but is OFF unless BLAZE_ATTACH=live AND BLAZE_LIVE_SHOW_IDS AND BLAZE_LIVE_CONFIRM are all set (see docs/INSTALL.html). Then, for allowed shows only, a clip that is on Nitro, has exactly one
file in Blaze, a verified story format and no CHECK tag is attached once (ATTACHING / ATTACHED lines), read back, and handed to the desk (NEEDS_DESK) if anything is off. Kill switch: the file data/STOP_LIVE."""
from __future__ import annotations
import argparse, concurrent.futures, contextlib, datetime as dt, json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request  # noqa: F401
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from autoid_lite import config                                              # noqa: E402
from autoid_lite.blaze import ledger as bl, lock as plock, snapshot as snap                 # noqa: E402,F401
from autoid_lite.blaze.attach import AttachMixin  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.client import AutoId, Blaze  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.errors import BlazeError, LoginFailed, SessionExpired  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.keys import ID_RE, NAME_RE, VER_RE, age_secs, attach_body, attach_call, attached_facts, clip_key, clip_secs, find_indexed, find_media, ignored, index_media, judge, media_key, media_pending, name_key, parse_day, rkey, show_ignored, transient  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.loop import RunMixin  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.media import MediaMixin  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.poller import Poller  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.reports import ReportMixin  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.safety import ForbiddenCall, WRITE_ALLOWED, check_call  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.scope import live_scope_text  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.settings import Cfg  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.states import LIVE_STATES  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
from autoid_lite.blaze.util import say  # noqa: F401  (re-export: the tests and other tools use bp.<name>)    # noqa: E402
config.apply_env()

# ---------------------------------------------------------------- helpers for the first real tests
def dump(b, path, params=None):
    try: t = json.dumps(b.get(path, params), indent=1, ensure_ascii=False)
    except Exception as e: t = "FAILED: %s: %s" % (type(e).__name__, e)
    print("\n=== GET %s\n%s" % (path, t[:3500]))

def ensure_session(c, b):
    """No session cookie yet, but a login is configured: log in now. -> True when there is a session to use."""
    if c.sid: return True
    if not c.autologin: return False
    try: sid = b.login()
    except LoginFailed as e: raise SystemExit("PROBLEM: %s" % e)
    saved = c.use_session(sid); say("logged in to Blaze (session ending ...%s%s)" % (sid[-4:], ", saved in autoid.env" if saved else "")); return True

def main(argv=None, _again=False):
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")      # a Windows console is not UTF-8: story titles in any script must not crash the commands
    except (AttributeError, OSError, ValueError): pass
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["run", "once", "show", "media", "probe", "scripts", "map", "report", "summary", "live", "quicktest", "undo", "live-retry", "shows", "stats", "close-day", "open-day"]); ap.add_argument("args", nargs="*"); a = ap.parse_args(argv)
    if a.cmd == "run" and os.environ.get("BLAZE_POLL_NO_LOCK") != "1":          # v9.13.1: one poller at a time (before anything logs in: a second login can replace the first one's session)
        try: plock.acquire(config.data_dir() / "blaze_poll.lock")
        except plock.AlreadyRunning as e: raise SystemExit("blaze_poll is already running (%s). Only one poller may run at a time. Stop the other one first (launchctl unload ~/Library/LaunchAgents/com.autoid.lite.plist, then pkill -f blaze_poll.py) and start again." % e)
    c = Cfg()
    b = Blaze(c)
    if not ensure_session(c, b): raise SystemExit("Set BLAZE_SESSION_ID and BLAZE_USERNAME in autoid.env (cookies of a logged-in Blaze tab), or BLAZE_USERNAME and BLAZE_PASSWORD_HASH so the program logs in by itself.")
    try:
        if a.cmd == "show":
            sid = a.args[0] if a.args else (c.shows[0] if c.shows else None) or raise_("give a show id"); dump(b, "/DataService/shows/%s" % sid); dump(b, "/DataService/shows/%s/slugs" % sid)
            print("\nparsed:", json.dumps(b.slugs(sid), ensure_ascii=False)[:1500])
        elif a.cmd == "media":
            ms = b.media(c.days); txt = (a.args[0].lower() if a.args else "")
            for m in ms:
                if txt in (m.get("title") or "").lower(): print(m["id"], m.get("objGroup"), "%ds" % ((m.get("duration") or 0) // 1000), m.get("modifiedDate"), m.get("status"), m.get("title"), "->", media_key(m.get("title")))
        elif a.cmd == "probe":
            s = a.args[0]; dump(b, "/DataService/stories/%s" % s); dump(b, "/DataService/stories/%s/versions" % s); dump(b, "/DataService/stories/%s/complete/" % s)
            dump(b, "/DataService/stories/%s/clips/" % s)
            if len(a.args) > 1: dump(b, "/DataService/stories/%s/versions/%s/items/" % (s, a.args[1])); dump(b, "/DataService/stories/%s/versions/%s" % (s, a.args[1]))
        elif a.cmd == "scripts":      # v9.13.5: what the poller reads as the two script fields of one story
            s = a.args[0]; raw = (b.get("/DataService/stories/%s/complete/" % s) or {}).get("storyComplete") or {}; vs = raw.get("versions") or []
            for vi, v in enumerate(vs):
                for it in v.get("items") or []: print("version[%d] item %s: keys=%s  text1=%d chars  text2=%d chars" % (vi, it.get("id"), sorted(it), len(it.get("text1") or ""), len(it.get("text2") or "")))
            print("versions: %d   items in versions[0]: %d" % (len(vs), len((vs[0].get("items") or []) if vs else [])))
            t = b.story_info(s)["scripts"]; print("the poller stores: online=%d chars, anchor=%d chars" % (len(t["online"]), len(t["anchor"])))
        elif a.cmd == "map":
            rows = AutoId(c).call("/svc/clips"); print("%-8s %-9s %-9s %-4s %-30s %s" % ("show", "slug", "story", "pos", "clip ID", "title"))
            for r in rows: print("%-8s %-9s %-9s %-4s %-30s %s" % (r["blaze_rundown_id"], r.get("slug_id") or "-", r["blaze_story_id"], r.get("position") or "-", r["display_id"], r["slug"]))
        elif a.cmd == "report":
            print(Poller(c).report(parse_day(a.args[0]) if a.args else None))
        elif a.cmd == "shows":
            p = Poller(c); d = parse_day(a.args[0]) if a.args else p.server_day(); lst = b.day_shows(d, d + dt.timedelta(days=c.days_ahead)); p.show_meta = {x["id"]: x for x in lst}; polled = p.store.polls()
            print("Blaze lists %d show(s) for %s%s:" % (len(lst), d.isoformat(), " (+%d day(s))" % c.days_ahead if c.days_ahead else ""))
            for x in lst: print("  %-7s %s  %-28s %3s stories  master %-4s %s%s" % (x["id"], (x["start"] or "")[11:16], x["title"], x["slugs"], x["master"], ("last read %ds ago" % (time.time() - polled[x["id"]]["last_ok"])) if (polled.get(x["id"]) or {}).get("last_ok") else "not read yet", "  (ignored)" if show_ignored(x["title"], c.ignore_shows) else ""))
            if c.lookahead_h > 0 and not c.days_ahead and not a.args:
                try:
                    la = [x for x in p.lookahead(d) if x["id"] not in {y["id"] for y in lst}]
                    print("Look-ahead (next date's shows that start within %g h and before the broadcast day ends): %d show(s)" % (c.lookahead_h, len(la)))
                    for x in la: print("  %-7s %s  %-28s %3s stories  master %-4s  (followed early)" % (x["id"], (x["start"] or "")[11:16], x["title"], x["slugs"], x["master"]))
                except Exception as e: print("Look-ahead could not be read: %s: %s" % (type(e).__name__, e))
        elif a.cmd == "stats":
            f = Path(c.reports) / "poll_stats.json"
            if not f.exists(): print("no statistics yet: the poller writes %s after its first round" % f)
            else:
                j = json.loads(f.read_text(encoding="utf-8")); d = j["stats"]; print("Polling statistics at %s%s" % (j["time"], ("\n  PROBLEM: " + j["problem"]) if j.get("problem") else ""))
                for k, v in d.items(): print("  %-26s %s" % (k, v))
                late = [x for x in j["shows"] if x["last_ok_age_s"] > c.fresh_secs]
                print("  shows over the %ds freshness target: %d%s" % (c.fresh_secs, len(late), "".join("\n    %s %s: last read %ss ago%s" % (x["id"], x["title"], x["last_ok_age_s"], (" (" + x["last_error"] + ")") if x.get("last_error") else "") for x in late[:15])))
        elif a.cmd in ("close-day", "open-day"):
            led = bl.Ledger(c.ledger); day = a.args[0] if a.args else Poller(c).server_day().strftime("%Y%m%d"); key = "closed:" + day
            if a.cmd == "close-day": led.put(key, time.strftime("%Y-%m-%d %H:%M:%S")); print("broadcast day %s is closed: the poller pauses reading the shows within one round (snapshots are kept); `open-day %s` resumes it." % (day, day))
            else: led.delete(key); print("broadcast day %s is open again: polling resumes within one round." % day)
        elif a.cmd == "live": print(live_status(c))
        elif a.cmd == "quicktest": print(quicktest(c, a.args))
        elif a.cmd == "undo": print(undo(c, b, a.args))
        elif a.cmd == "live-retry":
            if not a.args: raise_("give a clip ID")
            led = bl.Ledger(c.ledger); row = led.live_of(a.args[0])
            print("no live attempt is recorded for %s" % a.args[0] if not row else ("%s is %s: not cleared (it is not a failed attempt). Use undo first if a clip must be removed." % (a.args[0], row["status"]) if row["status"] == "SENT" else "cleared: %s may be tried once more (its state must be ON_NITRO again)" % (led.live_clear(a.args[0]) and a.args[0])))
        elif a.cmd == "summary": print(Poller(c).summary(int(a.args[0]) if a.args else 5))
        elif a.cmd == "once": p = Poller(c); plans = p.cycle(); say("stories synced; %d clip(s) checked" % len(plans))
        else: Poller(c).run()
    except SessionExpired as e:
        if not _again and c.autologin and a.cmd in ("show", "media", "probe", "scripts", "map", "shows"):          # a read-only one-off command with an expired cookie: log in and run it once more (never for commands that can write)
            try: saved = c.use_session(b.login()); say("logged in to Blaze again%s" % (" (saved in autoid.env)" if saved else "")); return main(argv, _again=True)
            except LoginFailed as le: raise SystemExit("PROBLEM: %s; %s" % (e, le))
        raise SystemExit("PROBLEM: %s" % e)
    return 0

def quicktest(c, a_args):
    """`blaze_poll.py quicktest [story ID]`: what real attaching is set to do, and for one story: what the registry knows and what was sent. Read only."""
    led = bl.Ledger(c.ledger); stop = Path(c.stopfile); lines = ["BLAZE_ATTACH=%s" % c.attach, "scope: " + (live_scope_text(c) if c.attach == "live" else "nothing is sent (BLAZE_ATTACH=%s); set BLAZE_ATTACH=live to attach: it would then be %s" % (c.attach, live_scope_text(c))),
        "kill switch %s: %s    sent in the last hour: %d%s" % (stop, "PRESENT, nothing is sent" if stop.exists() else "absent", led.live_count_since(time.time() - 3600), (" of %d" % c.live_cap) if c.live_cap else "")]
    if a_args:
        sid = a_args[0]; lines.append("story %s: %s" % (sid, "INSIDE the scope" if not c.qt_stories or sid in c.qt_stories else "outside the scope (QUICKTEST_STORY_ID is another story: a real attach is refused)"))
        try: rows = [r for r in AutoId(c).call("/svc/clips") if str(r["blaze_story_id"]) == sid]
        except Exception as e: rows = []; lines.append("  could not read the registry: %s" % e)
        for r in rows: lines.append("  %-34s %-16s show %s row %s  %s" % (r["display_id"], r["state"], r["blaze_rundown_id"], r["position"], r["slug"]))
        if not rows: lines.append("  no clip ID for this story today yet")
        for r in led.live_rows(200):
            if str(r["story_id"]) == sid: lines.append("  sent %s  %-12s %s media %s clip %s" % (time.strftime("%m-%d %H:%M:%S", time.localtime(r["sent_at"])), r["status"], r["display_id"], r["media_id"], r["blaze_clip_id"] or "-"))
    return "\n".join(lines)

def live_status(c):
    led = bl.Ledger(c.ledger); stop = Path(c.stopfile); n = led.live_count_since(time.time() - 3600)
    on = c.attach == "live"
    lines = ["new versions (clip _V2 and up): %s" % ("auto: attached, then the older version's clip is removed" if c.version_mode == "auto" else "desk: never attached by the tool; the desk attaches and removes the old clip (BLAZE_VERSION_MODE=desk)"),
             "live attach: %s" % ("ON %s (a real attach is sent when every rule passes)" % live_scope_text(c) if on else "OFF (BLAZE_ATTACH=%s)" % c.attach),
             "  kill switch file %s: %s" % (stop, "PRESENT, nothing is sent: " + stop.read_text(encoding="utf-8", errors="replace").strip() if stop.exists() else "absent"),
             "  verified story formats: %s   sent in the last hour: %d (limit %s)   halt after %d failures in a row" % (",".join(sorted(c.verified)) or "none", n, c.live_cap or "none", c.live_halt_after), "  last attempts:"]
    for r in led.live_rows(20): lines.append("    %s  %-12s %-30s story %s media %s clip %s %s" % (time.strftime("%m-%d %H:%M:%S", time.localtime(r["sent_at"])), r["status"], r["display_id"], r["story_id"], r["media_id"], r["blaze_clip_id"] or "-", r["error"] or ""))
    return "\n".join(lines + (["    none yet"] if not led.live_rows(1) else []))

def undo(c, b, args):
    """Remove a clip this tool attached. Only for clips in the live table; the Blaze clip ID comes from the table (or the second argument when the read-back found several)."""
    if not args: raise_("give a clip ID: undo <clip ID> [blazeClipId]")
    led = bl.Ledger(c.ledger); row = led.live_of(args[0])
    if not row: return "no live attach is recorded for %s: undo only removes clips this tool attached" % args[0]
    ids = [args[1]] if len(args) > 1 else [x for x in (row["blaze_clip_id"] or "").split(",") if x]
    if len(ids) != 1: return "need exactly one Blaze clip id (recorded: %s). Give it: undo %s <blazeClipId>" % (row["blaze_clip_id"] or "none", args[0])
    info0 = b.story_info(row["story_id"]); rep = b.delete_clip(row["story_id"], ids[0]); led.live_finish(args[0], "UNDONE", ids[0], "removed by hand"); note = "check the story's duration in Blaze."
    if c.live_scriptdur:
        info1 = b.story_info(row["story_id"]); secs = lambda rows: None if any(x["dur"] is None for x in rows) else sum(int(x["dur"] // 1000) for x in rows); s0, s1 = secs(info0["rows"]), secs(info1["rows"])
        if None not in (s0, s1) and info1["version_id"] and info0["version"]["scriptDur"] == s0:
            try: b.set_script_dur(row["story_id"], info1["version_id"], s1, info0["version"]["wpm"]); note = "the story's script duration was set to %d s (the clips' total), as the page does." % s1
            except ForbiddenCall: note = "the story's script duration was NOT updated (needs BLAZE_ATTACH=live): set it to %d s in Blaze." % s1
    return "removed Blaze clip %s from story %s. Blaze said: %s\n%s" % (ids[0], row["story_id"], json.dumps(rep), note[0].upper() + note[1:])

def raise_(msg): raise SystemExit(msg)

if __name__ == "__main__": sys.exit(main())
