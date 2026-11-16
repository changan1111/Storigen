#!/usr/bin/env python3
"""Try the whole flow on ONE machine with a fake Blaze and fake Playout/Nitro folders. Nothing real is touched. Stdlib only.

  py tools\\demo.py setup     (once) makes demo_home\\ with fake folders, a demo autoid.env and two start files
  py tools\\demo.py reset   throws the demo away (all IDs, folders) so you can start again
  demo_home\\1_start_server   (window 1) starts Auto-ID: web page, folder watcher and the Blaze poller
  demo_home\\2_play           (window 2) starts the fake Blaze and a prompt where YOU act as editor, converter and desk
Open http://127.0.0.1:8090 and log in with the demo login that setup prints."""
from __future__ import annotations
import json, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
DEMO = Path(os.getenv("AUTOID_DEMO_HOME") or ROOT / "demo_home"); MARK = "# ---- demo overrides (written by tools/demo.py) ----"
PORT, BLAZE_PORT, SHOW = 8090, 8099, "34459"

def say(*a): print(*a, flush=True)
def py_cmd(): return "py" if os.name == "nt" else "python3"

# ---------------------------------------------------------------- setup
def setup():
    nas = DEMO / "nas"; inbox = nas / "Playout" / "INBOX"; nitro = nas / "Nitro" / "ONAIR"
    for d in [inbox / x for x in ("NEWS", "PROGRAMS", "PROMO", "ADS")] + [nitro]: d.mkdir(parents=True, exist_ok=True)
    env = DEMO / "autoid.env"; made = False
    if not env.exists():
        r = subprocess.run([sys.executable, str(ROOT / "autoid.py"), "init", "demo@local"], env={**os.environ, "AUTOID_HOME": str(DEMO)}, capture_output=True, text=True); made = r.returncode == 0
        if not made: raise SystemExit("init failed: " + r.stdout + r.stderr)
    text = env.read_text(encoding="utf-8"); text = text.split(MARK)[0].rstrip() + "\n"
    text += "\n%s\n" % MARK + "\n".join("%s=%s" % kv for kv in [
        ("LINK_MODE", "story_id"), ("WEB_HOST", "127.0.0.1"), ("WEB_PORT", PORT), ("AUTOID_TZ", ""), ("WATCH_MODE", "observe"), ("EXPORTS_DIR", inbox), ("INBOX_SUBDIRS", "NEWS,PROGRAMS,PROMO,ADS"),
        ("NITRO_DIR", nitro), ("REQUIRE_NETWORK_FS", 0), ("STABLE_SECS", 3), ("POLL_SECS", 2), ("DONE_WAIT_SECS", 120), ("INBOX_STUCK_SECS", 300),
        ("BLAZE_POLL", 1), ("BLAZE_URL", "http://127.0.0.1:%d" % BLAZE_PORT), ("BLAZE_SESSION_ID", "DEMO"), ("BLAZE_USERNAME", "demo"), ("BLAZE_SHOW_IDS", SHOW),
        ("BLAZE_POLL_SECS", 5), ("BLAZE_MEDIA_SETTLE_SECS", 5), ("BLAZE_RECONCILE_SECS", 10), ("BLAZE_OVERDUE_MIN", 1), ("BLAZE_ATTACH", "dry"),
        ("BLAZE_ONLY_FORMAT_IDS", "20,21,23,27"), ("BLAZE_IGNORE_TITLES", "OPEN MONTAGE,OPEN HEADLINE,BREAK,CLOSING MONTAGE,CLOSE HEADLINE")]) + "\n"
    env.write_text(text, encoding="utf-8")
    py = py_cmd()
    if os.name == "nt":
        (DEMO / "1_start_server.bat").write_text('@echo off\r\ncd /d "%s"\r\nset AUTOID_HOME=%s\r\n%s autoid.py run\r\npause\r\n' % (ROOT, DEMO, py), encoding="utf-8")
        (DEMO / "2_play.bat").write_text('@echo off\r\ncd /d "%s"\r\nset AUTOID_HOME=%s\r\n%s tools\\demo.py play\r\npause\r\n' % (ROOT, DEMO, py), encoding="utf-8")
    else:
        for n, c in (("1_start_server.sh", "autoid.py run"), ("2_play.sh", "tools/demo.py play")):
            f = DEMO / n; f.write_text('#!/bin/sh\ncd "%s"\nAUTOID_HOME="%s" %s %s\n' % (ROOT, DEMO, py, c), encoding="utf-8"); f.chmod(0o755)
    cfg = load_cfg(); say("Demo ready in %s" % DEMO)
    say("Web page   http://127.0.0.1:%d   login: %s   password: %s" % (PORT, cfg.get("ADMIN_EMAIL"), cfg.get("ADMIN_PASSWORD")))
    ext = ".bat" if os.name == "nt" else ".sh"; say("\nNow open two windows and start, in this order:\n  1) %s\n  2) %s" % (DEMO / ("1_start_server" + ext), DEMO / ("2_play" + ext)))

def load_cfg():
    from autoid_lite import config
    return config.load_env(DEMO / "autoid.env")

# ---------------------------------------------------------------- play
class Play:
    def __init__(self):
        from fake_blaze import FakeBlaze, serve
        os.environ["AUTOID_HOME"] = str(DEMO); self.cfg = load_cfg(); self.fb = FakeBlaze(SHOW); self.srv = serve(self.fb, BLAZE_PORT)
        self.inbox, self.nitro = Path(self.cfg["EXPORTS_DIR"]), Path(self.cfg["NITRO_DIR"]); self.rows = []
    def svc(self, path):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), headers={"X-API-Key": self.cfg["SERVICE_API_KEY"]})
        with urllib.request.urlopen(req, timeout=5) as r: return json.loads(r.read())
    def refresh(self):
        try: self.rows = [r for r in self.svc("/svc/clips") if not r.get("deleted")]
        except Exception as e: self.rows = []; say("Cannot reach Auto-ID on port %d (%s). Is window 1 running?" % (PORT, e)); return False
        return True
    def files(self, did): return (self.inbox / "NEWS" / (did + ".mov")), self.nitro / time.strftime("%b-%y") / time.strftime("%d-%m-%Y") / "NEWS" / (did + ".mxf")
    def pick(self, a):
        if not self.refresh(): return None
        try: return self.rows[int(a) - 1]
        except (ValueError, IndexError): say("Give a row number from 'list'."); return None
    def media_of(self, did): return next((m for m in self.fb.medias if m["title"].startswith(did)), None)
    def do(self, line):
        w = line.split(None, 1); cmd = w[0].lower(); arg = w[1].strip() if len(w) > 1 else ""
        if cmd in ("help", "?"): say(HELP)
        elif cmd in ("list", "ls"):
            if not self.refresh(): return
            say("%-3s %-8s %-3s %-46s %-17s %-5s %-5s %-5s %s" % ("n", "story", "ver", "clip ID (file name without extension)", "state", "inbox", "nitro", "media", "attached"))
            for i, r in enumerate(self.rows, 1):
                inb, nit = self.files(r["display_id"]); s = self.fb.get(r["blaze_story_id"]); m = self.media_of(r["display_id"])
                att = "yes" if s and m and any(c["mos"] == m["id"] for c in s["clips"]) else "-"
                say("%-3d %-8s %-3s %-46s %-17s %-5s %-5s %-5s %s" % (i, r["blaze_story_id"], "V%d" % r["version"], r["display_id"], r["state"], "yes" if inb.exists() else "-", "yes" if nit.exists() else "-", "yes" if m else "-", att))
            say("(Blaze stories: %d in show %s)" % (len(self.fb.stories), SHOW))
        elif cmd == "blaze":
            for i, s in enumerate(self.fb.stories, 1): say("%2d  story %s  slug %s  format %s  clips %d  %s" % (i, s["story"], s["slug"], s["fmt"], len(s["clips"]), s["title"]))
        elif cmd in ("story", "new"):
            m = re.match(r"^(?:f=(\d+)\s+)?(.+)$", arg)
            if not m: return say("usage: story [f=21] <title>     (format 20 Anchor, 21 Anchor visual, 23 Package, 25 HeadLines, 27 Montage)")
            s = self.fb.add(m.group(2), int(m.group(1) or 20)); say("Blaze: created story %s (format %s). The poller sees it within ~5 seconds." % (s["story"], s["fmt"]))
        elif cmd == "rename":
            a = arg.split(None, 1)
            if len(a) < 2 or not self.fb.rename(a[0], a[1]): return say("usage: rename <story id> <new title>")
            say("Blaze: renamed. The clip ID must stay the same.")
        elif cmd == "delete":
            say("Blaze: story deleted." if self.fb.delete(arg) else "No such story id. Use 'blaze' to see them.")
        elif cmd == "export":
            r = self.pick(arg)
            if r: inb, _ = self.files(r["display_id"]); inb.parent.mkdir(parents=True, exist_ok=True); inb.write_bytes(b"\0" * 4096); say("Editor: exported %s into the Playout inbox." % inb.name)
        elif cmd == "convert":
            r = self.pick(arg)
            if not r: return
            inb, nit = self.files(r["display_id"])
            if inb.exists(): inb.unlink()
            nit.parent.mkdir(parents=True, exist_ok=True); nit.write_bytes(b"\0" * 8192); self.fb.add_media(nit.name, age=0); say("Converter: inbox file gone, MXF is on Nitro and in Blaze's media list.")
        elif cmd == "attach":
            r = self.pick(arg)
            if not r: return
            m = self.media_of(r["display_id"])
            if not m: return say("That file is not in Blaze's media list yet: run 'convert %s' first." % arg)
            c = self.fb.attach(r["blaze_story_id"], m["id"]); say("Desk: attached with the paperclip." if c else "Could not attach: story missing?")
        elif cmd == "expire": self.fb.expired = True; say("Blaze session now EXPIRED: the poller should log PROBLEM and the page should turn red after ~90 s.")
        elif cmd == "login": self.fb.expired = False; say("Blaze session valid again.")
        elif cmd == "wait": time.sleep(float(arg or 5))
        elif cmd == "log":
            f = DEMO / "data" / "logs" / ((arg or "blaze_poll") + ".log"); say("".join(f.read_text(encoding="utf-8", errors="replace").splitlines(True)[-18:]) if f.exists() else "no log %s yet (names: blaze_poll, watcher, server)" % f.name)
        elif cmd == "report":
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "blaze_poll.py"), "report"], env={**os.environ, "AUTOID_HOME": str(DEMO)}, capture_output=True, text=True); say(r.stdout + r.stderr)
        elif cmd in ("quit", "exit", "q"): return "quit"
        else: say("Unknown command. Type help.")

HELP = """Act as the editor, the converter and the desk:
  list                  Auto-ID's clips: story, version, clip ID, state, and where each file is (one story can have several versions: V1, V2 ...)
  blaze                 stories in the fake Blaze
  story [f=21] <title>  create a story in Blaze (format 20 default)
  rename <id> <title>   rename a story        delete <id>   delete a story
  export <n>            editor exports the file named with clip n's ID into the Playout inbox
  convert <n>           conversion done: inbox file gone, MXF on Nitro and in Blaze's media list
  attach <n>            the desk attaches it by hand with the paperclip (read-back should mark it ATTACHED)
  expire / login        make Blaze's session expire / valid again
  log [name]            last lines of blaze_poll (default), watcher or server
  report                tool-versus-desk agreement
  wait <secs>   quit"""

def play():
    p = Play(); say("Fake Blaze is running on port %d (show %s). Web page: http://127.0.0.1:%d\n%s" % (BLAZE_PORT, SHOW, PORT, HELP))
    while True:
        try: line = input("demo> ").strip()
        except (EOFError, KeyboardInterrupt): break
        if not line: continue
        try:
            if p.do(line) == "quit": break
        except Exception as e: say("error: %s: %s" % (type(e).__name__, e))

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "setup": setup()
    elif c == "reset":
        import shutil; shutil.rmtree(DEMO, ignore_errors=True); say("Removed %s. Close the two demo windows first, then run setup again." % DEMO)
    elif c == "play": play()
    else: print(__doc__)
