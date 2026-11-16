#!/usr/bin/env python3
"""Auto-ID Linker (lite) launcher.   python3 autoid.py <command>

  init      create autoid.env with fresh secrets and the first admin login (safe to run again: never overwrites)
  run       start the server, the watcher (and the MOS gateway if MOS_ENABLED=1); restart anything that crashes; daily backup
  status    ask the running server whether everything is healthy
  doctor    check this machine and the settings, with plain-language advice
  selftest  start a throw-away copy on a free port and walk through the whole flow (about 5 seconds)
  backup    copy the database to data/backups now
Needs Python 3.9 or newer and nothing else (no pip packages, no Docker)."""
from __future__ import annotations
import datetime as dt, json, logging, logging.handlers, os, secrets, shutil, signal, socket, sqlite3, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from pathlib import Path

HOME = Path(__file__).resolve().parent
os.environ.setdefault("AUTOID_HOME", str(HOME)); sys.path.insert(0, str(HOME))
from autoid_lite import config                                                     # noqa: E402

def say(*a): print(*a, flush=True)

# ---------------------------------------------------------------- init
def cmd_init(argv):
    ep = config.env_path(); dd = config.data_dir(); dd.mkdir(parents=True, exist_ok=True)
    if ep.exists():
        say("%s already exists: left as it is. Edit it with any text editor." % ep); return 0
    admin = argv[0] if argv else "admin@autoid.local"; pw = secrets.token_urlsafe(9)
    text = (HOME / "autoid.env.example").read_text(encoding="utf-8").replace("__API_KEY__", secrets.token_urlsafe(24)).replace("__SESSION_SECRET__", secrets.token_urlsafe(48)) \
        .replace("__ADMIN_EMAIL__", admin).replace("__ADMIN_PASSWORD__", pw)
    ep.write_text(text, encoding="utf-8")
    try: os.chmod(ep, 0o600)
    except OSError: pass
    port = config.load_env(ep).get("WEB_PORT", "8080")
    say("Created %s\n\nOpen  http://%s:%s\nLogin  %s\nPassword  %s\n\nNext: edit the folder settings in autoid.env, then run  python3 autoid.py doctor" % (ep, socket.gethostname(), port, admin, pw))
    return 0

# ---------------------------------------------------------------- helpers
def base_url():
    return "http://127.0.0.1:%s" % os.environ.get("WEB_PORT", "8080")

def svc(path, port=None, key=None, timeout=5):
    req = urllib.request.Request("http://127.0.0.1:%s%s" % (port or os.environ.get("WEB_PORT", "8080"), path), headers={"X-API-Key": key or os.environ.get("SERVICE_API_KEY", "")})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read())

def port_free(port):
    s = socket.socket()
    try: s.bind(("0.0.0.0", port)); return True
    except OSError: return False
    finally: s.close()

# ---------------------------------------------------------------- run (supervisor)
def child_specs():
    py = sys.executable; specs = [("server", [py, "-m", "autoid_lite.server"])]
    if os.environ.get("WATCHER_ENABLED", "1") != "0": specs.append(("watcher", [py, str(HOME / "autoid_lite" / "watcher.py")]))      # v9.12: WATCHER_ENABLED=0 = no Playout / Nitro folders needed
    if os.environ.get("MOS_ENABLED") == "1": specs.append(("gateway", [py, str(HOME / "autoid_lite" / "gateway.py")]))
    if os.environ.get("BLAZE_POLL") == "1": specs.append(("blaze_poll", [py, str(HOME / "tools" / "blaze_poll.py"), "run"]))
    return specs

def log_to(name, logs):
    lg = logging.getLogger("child." + name); lg.propagate = False
    if not lg.handlers:
        h = logging.handlers.RotatingFileHandler(logs / (name + ".log"), maxBytes=5_000_000, backupCount=5, encoding="utf-8"); h.setFormatter(logging.Formatter("%(message)s")); lg.addHandler(h)
    lg.setLevel(logging.INFO); return lg

def pump(proc, lg):
    for line in proc.stdout:
        line = line.rstrip()
        lg.info(line if line[:4].isdigit() and line[4:5] == "-" else time.strftime("%Y-%m-%d %H:%M:%S ") + line)      # the watcher and gateway already stamp their lines

def backup_now(keep=14):
    dd = config.data_dir(); db = dd / "autoid.db"
    if not db.exists(): return None
    out_dir = dd / "backups"; out_dir.mkdir(exist_ok=True); dest = out_dir / ("autoid-%s.db" % dt.date.today().strftime("%Y%m%d"))
    src = sqlite3.connect(str(db), timeout=30); out = sqlite3.connect(str(dest))
    try: src.backup(out)
    finally: out.close(); src.close()
    for old in sorted(out_dir.glob("autoid-*.db"))[:-keep]: old.unlink()
    return dest

def backup_loop(stop):
    while not stop.wait(1800):
        try:
            if not (config.data_dir() / "backups" / ("autoid-%s.db" % dt.date.today().strftime("%Y%m%d"))).exists(): backup_now()
        except Exception as e: say("backup failed: %s" % e)

def cmd_run(argv):
    config.apply_env()
    if not config.env_path().exists(): say("No autoid.env yet: run  python3 autoid.py init  first."); return 2
    dd = config.data_dir(); logs = dd / "logs"; logs.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "DATA_DIR": str(dd), "REGISTRY_URL": base_url(), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    stop = threading.Event(); procs = {}; fails = {}
    def bye(*_): stop.set()
    signal.signal(signal.SIGINT, bye); signal.signal(signal.SIGTERM, bye)
    threading.Thread(target=backup_loop, args=(stop,), daemon=True).start()
    say("Auto-ID Linker starting. Logs: %s" % logs)
    def start(name, cmd):
        p = subprocess.Popen(cmd, cwd=str(HOME), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=pump, args=(p, log_to(name, logs)), daemon=True).start(); procs[name] = (p, time.time()); say("started %s (pid %d)" % (name, p.pid))
    specs = child_specs(); start(*specs[0])
    for _ in range(60):                                                              # the others need the server
        try:
            svc("/healthz"); break
        except Exception: time.sleep(0.5)
    for s in specs[1:]: start(*s)
    while not stop.wait(2):
        for name, cmd in specs:
            p, t0 = procs[name]
            if p.poll() is None: continue
            ran = time.time() - t0; fails[name] = 0 if ran > 60 else fails.get(name, 0) + 1; wait = min(60, 2 ** fails[name])
            say("%s stopped (code %s) after %ds: restarting in %ds" % (name, p.returncode, ran, wait))
            if stop.wait(wait): break
            start(name, cmd)
    for name, (p, _) in procs.items():
        if p.poll() is None: p.terminate()
    for name, (p, _) in procs.items():
        try: p.wait(10)
        except subprocess.TimeoutExpired: p.kill()
    say("stopped"); return 0

# ---------------------------------------------------------------- status / doctor / selftest / backup
def cmd_status(argv):
    config.apply_env()
    try: s = svc("/svc/status")
    except Exception as e: say("NOT RUNNING: cannot reach the server on port %s (%s)" % (os.environ.get("WEB_PORT", "8080"), e)); return 1
    for name, ok in sorted(s["checks"].items()): say("%-14s %s" % (name, "ok" if ok else "PROBLEM"))
    for p in s["problems"]: say("  - " + p)
    say("ALL OK" if not s["problems"] else "%d problem(s)" % len(s["problems"])); return 0 if not s["problems"] else 1

def cmd_doctor(argv):
    config.apply_env(); bad = [0]
    def ok(m): say("  ok    " + m)
    def no(m): bad[0] += 1; say("  FIX   " + m)
    say("Machine"); (ok if sys.version_info >= (3, 9) else no)("Python %s (needs 3.9 or newer)" % sys.version.split()[0])
    (ok if sqlite3.sqlite_version_info >= (3, 24) else no)("SQLite %s (needs 3.24 or newer)" % sqlite3.sqlite_version)
    say("Settings"); e = os.environ
    if not config.env_path().exists(): no("no autoid.env: run  python3 autoid.py init"); return 1
    ok("autoid.env found")
    (ok if len(e.get("SERVICE_API_KEY", "")) >= 16 and len(e.get("SESSION_SECRET", "")) >= 32 else no)("secrets are set (init fills them in)")
    mode = e.get("LINK_MODE", "placeholder"); (ok if mode in ("placeholder", "story_id") else no)("LINK_MODE=%s (placeholder or story_id)" % mode)
    if mode == "story_id":
        t = e.get("BLAZE_STORY_URL_TEMPLATE", ""); (ok if "{blaze_story_id}" in t else no)("BLAZE_STORY_URL_TEMPLATE needs {blaze_rundown_id} and {blaze_story_id} (the desk's Open in Blaze button)")
        if e.get("MOS_ENABLED") != "1": say("  note  LINK_MODE=story_id needs a feed: MOS_ENABLED=1 (and a MOS device entry in Blaze), or your own script calling /svc/stories")
    port = int(e.get("WEB_PORT", "8080")); up = False
    try: svc("/healthz", timeout=2); up = True
    except Exception: pass
    (ok if up or port_free(port) else no)("web port %d %s" % (port, "is served by Auto-ID" if up else "is free"))
    if e.get("WATCHER_ENABLED", "1") == "0": say("Folders"); say("  note  WATCHER_ENABLED=0: the Playout and Nitro folders are not used, the EXPORT and ON AIR steps are off (nothing to mount)")
    else:
        say("Folders (the watcher reads them)"); from autoid_lite import watcher as w
        folders = [("EXPORTS_DIR", e.get("EXPORTS_DIR", ""))] + [("  inbox " + d, os.path.join(e.get("EXPORTS_DIR", ""), d)) for d in w.INBOX_DIRS] + [("NITRO_DIR", e.get("NITRO_DIR", ""))]
        for label, d in folders:
            if not d or not os.path.isdir(d): no("%s = %s does not exist (is the share mounted?)" % (label, d)); continue
            t = w.fs_type(d)
            if e.get("REQUIRE_NETWORK_FS", "1") == "1" and t not in w.NET_FS: no("%s = %s is on a local disk (%s), not a network share: mount the NAS first, or set REQUIRE_NETWORK_FS=0 for a test" % (label, d, t))
            else: ok("%s = %s (%s)" % (label, d, t or "unknown"))
    if e.get("MOS_ENABLED") == "1":
        say("MOS gateway")
        for p in e.get("MOS_PORTS", "10540,10541").split(","): (ok if port_free(int(p)) or up else no)("MOS port %s is free (Blaze connects to it)" % p.strip())
    say("Time"); from autoid_lite import server as sv
    app = sv.App.__new__(sv.App); app.cfg = {"tz": e.get("AUTOID_TZ", "").strip(), "day_start": e.get("BROADCAST_DAY_START", "05:00")}; app._tz = None
    say("  note  machine time %s, broadcast day %s (the daily ID number restarts at %s)" % (app.now().strftime("%Y-%m-%d %H:%M"), app.today(), app.cfg["day_start"]))
    say("\n%s" % ("Everything checked is fine." if not bad[0] else "%d thing(s) to fix." % bad[0])); return 0 if not bad[0] else 1

def cmd_selftest(argv):
    """A throw-away server on a free port with its own database: nothing of the real setup is touched."""
    from autoid_lite import server as sv
    tmp = Path(tempfile.mkdtemp(prefix="autoid-selftest-")); key, secret = "selftest-key-" + "x" * 10, "selftest-secret-" + "y" * 30
    res = []
    def check(name, cond): res.append(cond); say("  %s  %s" % ("PASS" if cond else "FAIL", name))
    app = sv.App(sv.settings_from_env({"SERVICE_API_KEY": key, "SESSION_SECRET": secret, "LINK_MODE": "placeholder", "HEALTH_COMPONENTS": "watcher"}), tmp / "t.db")
    app.bootstrap_admin({"ADMIN_EMAIL": "t@t.io", "ADMIN_PASSWORD": "selftest-pass"}); httpd = sv.serve(app, "127.0.0.1", 0); port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start(); cookie = [None]
    def call(method, path, body=None, svc_key=False):
        h = {"Content-Type": "application/json"}
        if svc_key: h["X-API-Key"] = key
        elif cookie[0]: h["Cookie"] = cookie[0]
        rq = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(rq, timeout=10) as r:
                if r.headers.get("Set-Cookie"): cookie[0] = r.headers["Set-Cookie"].split(";")[0]
                raw = r.read(); return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw)
        except urllib.error.HTTPError as ex: return ex.code, json.loads(ex.read() or b"null")
    say("Self-test (temporary copy on port %d)" % port)
    st, page = call("GET", "/"); check("web page is served", st == 200 and b"Storigen" in page)
    check("sign-in works", call("POST", "/api/login", {"email": "t@t.io", "password": "selftest-pass"})[0] == 200)
    st, c = call("POST", "/api/manual", {"rundown": "Test Bulletin", "story": "Self test story"}); did = (c.get("name_id") or c.get("display_id", "")) if st == 200 else ""; internal = c.get("display_id", "") if st == 200 else ""
    check("ID is created from rundown + story name: " + did, st == 200 and did.endswith("SELF_TEST_STORY"))
    check("same names again are flagged as a duplicate", call("POST", "/api/manual", {"rundown": "test  bulletin", "story": "SELF test story"})[0] == 409)
    check("the watcher can find the ID from a file name", bool(did) and call("GET", "/svc/match?name=" + did.lower(), svc_key=True)[0] == 200)
    for state in ("EXPORTING", "ON_NITRO"): call("POST", "/svc/files", {"display_id": internal, "state": state}, svc_key=True)
    clip = call("GET", "/api/clips")[1]["clips"][0]; check("file events move the clip to ON_NITRO", clip["state"] == "ON_NITRO")
    check("the desk can mark it done", call("POST", "/api/clips/%d/attached" % clip["id"])[0] == 200)
    check("a wrong API key is refused", call("GET", "/svc/status")[0] == 401)
    httpd.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
    say("SELF-TEST PASSED" if all(res) else "SELF-TEST FAILED"); return 0 if all(res) else 1

def cmd_backup(argv):
    config.apply_env(); d = backup_now(); say("backup written: %s" % d if d else "no database yet"); return 0

COMMANDS = {"init": cmd_init, "run": cmd_run, "status": cmd_status, "doctor": cmd_doctor, "selftest": cmd_selftest, "backup": cmd_backup}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS: print(__doc__); sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]))
