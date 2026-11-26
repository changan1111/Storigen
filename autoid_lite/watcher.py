"""Ingest watcher: polls the NAS Exports folder, waits until files are complete, validates with ffprobe,
matches the ID in the filename, copies to Nitro (checksum compared), archives the original,
quarantines anything unmatched or bad. Polling, not file events: events are unreliable on SMB shares."""
import datetime as dt, hashlib, json, logging, os, re, shutil, signal, socket, subprocess, sys, time, urllib.error, urllib.parse, urllib.request, uuid

REGISTRY = os.getenv("REGISTRY_URL", "http://127.0.0.1:8080"); KEY = os.getenv("SERVICE_API_KEY", "")
EXPORTS, NITRO, QUAR, ARCH = (os.getenv(k, d) for k, d in
                              (("EXPORTS_DIR", "/exports"), ("NITRO_DIR", "/nitro"), ("QUARANTINE_DIR", "/quarantine"), ("ARCHIVE_DIR", "/archive")))
STABLE = int(os.getenv("STABLE_SECS", "30")); POLL = int(os.getenv("POLL_SECS", "5")); MAX_TRIES = int(os.getenv("MAX_TRIES", "5"))
RETAIN = int(os.getenv("ARCHIVE_RETAIN_DAYS", "14")); WEBHOOK = os.getenv("ALERT_WEBHOOK_URL", "")
EXTS = tuple(os.getenv("EXTS", ".mov,.mp4,.mxf").split(","))
NEED_PROBE = os.getenv("FFPROBE_REQUIRED", "1") == "1"
# Concurrency / crash safety. Lock dir must be on storage every watcher instance can see (default: inside Exports, dot-prefixed so it is ignored).
LOCK_DIR = os.getenv("LOCK_DIR", os.path.join(EXPORTS, ".autoid-locks"))
LOCK_STALE = int(os.getenv("LOCK_STALE_SECS", "120"))     # a lock whose file has not been refreshed for this long (by OUR clock) is dead
PART_STALE = int(os.getenv("PART_STALE_SECS", "900"))     # a .part file that has not changed for this long, with no live owner, is deleted
CLEAN_EVERY = int(os.getenv("CLEAN_EVERY_SECS", "300")); CHUNK = 1 << 20; REFRESH_EVERY = 5
REQUIRE_NET_FS = os.getenv("REQUIRE_NETWORK_FS", "0") == "1"     # compose sets 1: refuse to run on plain local folders (unmounted NAS)
NET_FS = {"cifs", "smb", "smb3", "smbfs", "afpfs", "nfs", "nfs4", "ceph", "glusterfs", "lustre", "afs", "9p"}
HOST = socket.gethostname(); BUSY, DONE = "busy", "done"
# WATCH_MODE=observe: an existing job (not this watcher) converts the file and moves the finished MXF to Nitro. The watcher then ONLY WATCHES:
# it never copies, moves, archives or quarantines. EXPORTS_DIR = the Playout INBOX folder, INBOX_SUBDIRS = NEWS,PROGRAMS,PROMO,ADS,
# NITRO_DIR = the Nitro ONAIR folder (read only use). "File disappeared from the inbox" + "finished MXF found on Nitro" = ON_NITRO.
WATCH_MODE = os.getenv("WATCH_MODE", "observe")
SUFFIX_ON = os.getenv("VERSION_SUFFIX", "off").strip().lower() in ("on", "1", "yes", "true")      # v10.5.0: _U01 / _V01 at the end of a file name (see docs/CHANGES_v1050.md)
INBOX_DIRS = [d.strip() for d in os.getenv("INBOX_SUBDIRS", "").split(",") if d.strip()]
NITRO_EXTS = tuple(e.strip().lower() for e in os.getenv("NITRO_EXTS", ".mxf").split(",") if e.strip())
NITRO_DEPTH = int(os.getenv("NITRO_SCAN_DEPTH", "3"))            # folder levels below NITRO_DIR to search (ONAIR/<date>/<NEWS>/file = 2)
DONE_WAIT = int(os.getenv("DONE_WAIT_SECS", "900"))              # file gone from the inbox but no MXF on Nitro after this long: tell the desk
STUCK_SECS = int(os.getenv("INBOX_STUCK_SECS", "1800"))          # file still in the inbox after this long: conversion is probably failing
FORGET_SECS = int(os.getenv("OBSERVE_FORGET_SECS", "86400"))     # stop tracking a file that vanished and never reached Nitro
NITRO_SCAN_EVERY = int(os.getenv("NITRO_SCAN_EVERY_SECS", "15"))
NITRO_DATE_PATH = [p.strip() for p in os.getenv("NITRO_DATE_PATH", "").split("|") if p.strip()]     # e.g. %b-%y/%d-%m-%Y : the finished files sit in <NITRO_DIR>/Nov-26/12-11-2026/ ; only those day folders are scanned
NITRO_DAYS_BACK, NITRO_DAYS_AHEAD = int(os.getenv("NITRO_SCAN_DAYS_BACK", "1")), int(os.getenv("NITRO_SCAN_DAYS_AHEAD", "1"))
STATE_FILE = os.getenv("OBSERVE_STATE_FILE", os.path.join(os.getenv("DATA_DIR", "data"), "observe_state.json"))
_wall = time.time              # test seam for wall-clock time (stored in the state file)
_now = time.monotonic          # indirection so tests can move the clock; monotonic so NAS clock skew cannot matter
COPY_HOOK = None               # test seam: called after every copied chunk
log = logging.getLogger("watcher"); logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

def _fs_type_mac(path, text=None):
    """Mac: `mount` lines look like  //user@nas/Playout on /Volumes/Playout (smbfs, nodev, nosuid, mounted by me)."""
    real = os.path.realpath(path); best, fst = -1, None
    if text is None:
        try: text = subprocess.run(["mount"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError): return None
    for line in text.splitlines():
        m = re.match(r"^.* on (.+) \((\w+)[,)]", line)
        if m and (real == m.group(1) or real.startswith(m.group(1).rstrip("/") + "/")) and len(m.group(1)) > best: best, fst = len(m.group(1)), m.group(2)
    return fst

def _fs_type_windows(path):
    """Windows: a UNC path (\\\\nas\\share) is a network share. Mapped drive letters are not visible to services, so use UNC paths for a service."""
    if path.startswith("\\\\") or path.startswith("//"): return "smb"
    return "local"

def fs_type(path, mountinfo="/proc/self/mountinfo"):
    """Filesystem type that actually backs `path` (longest matching mount point), or None if unknown. Linux, Mac and Windows."""
    if mountinfo == "/proc/self/mountinfo":
        if sys.platform == "darwin": return _fs_type_mac(path)
        if os.name == "nt": return _fs_type_windows(path)
    real = os.path.realpath(path); best, fst = -1, None
    try: lines = open(mountinfo).read().splitlines()
    except OSError: return None
    for line in lines:
        p = line.split()
        if "-" not in p: continue
        mp = p[4].replace("\\040", " "); i = p.index("-")
        if (real == mp or real.startswith(mp.rstrip("/") + "/")) and len(mp) > best: best, fst = len(mp), p[i + 1]
    return fst

def storage_problem():
    """None if all folders are usable, else a sentence for the alert. Catches the classic failure: the NAS share is not mounted,
    Docker silently shows an empty local folder, and 'delivered to Nitro' would mean 'copied to the VM disk'."""
    if WATCH_MODE == "observe":
        folders = [("Playout inbox", EXPORTS)] + [("Playout inbox " + d, os.path.join(EXPORTS, d)) for d in INBOX_DIRS] + [("Nitro", NITRO)]
    else: folders = [("Exports", EXPORTS), ("Nitro ingest", NITRO), ("Quarantine", QUAR), ("Archive", ARCH)]
    for label, d in folders:
        if not os.path.isdir(d): return "%s folder %s is missing" % (label, d)
        if REQUIRE_NET_FS and fs_type(d) not in NET_FS:
            return "%s folder %s is not a network share (filesystem: %s). The NAS/Nitro share is probably not mounted on this machine: mount it again, the watcher resumes by itself within a minute" % (label, d, fs_type(d))
    if WATCH_MODE == "observe":
        sd = os.path.dirname(STATE_FILE) or "."
        if not (os.path.isdir(sd) and os.access(sd, os.W_OK)): return "state folder %s is not writable" % sd
        return None
    if not os.access(NITRO, os.W_OK): return "Nitro ingest folder %s is not writable" % NITRO
    return None

def parse_name(name: str):
    """Legacy IDs (YYYYMMDD_NNNNC_...): only date + number are used to match; slug typos cannot break it. -> (day, seq, version, check)
    v9.7 IDs (DDMMYY_STORY_NAME[_N][_Vn]): the WHOLE name is the ID (capitals do not matter). -> ("NAME", NAME_IN_CAPITALS, version, None)"""
    stem = os.path.splitext(name)[0]
    if SUFFIX_ON:      # v11.0.0: 111126_FIRE_V01 (byte).mxf: whatever follows the version (byte / minibyte / tag) is a label for people and is ignored (stand-alone copy of ids.strip_label)
        stem = re.sub(r"(_[UV]\d+)[ _\-]+(?:mini[ _\-]?byte|byte|tag)$", r"\1", re.sub(r"(_[UV]\d+)[ _\-]*\([^()]*\)", r"\1", stem.strip()), flags=re.I).strip()
        stem = re.sub(r"(?:[ _\-]*\(\s*(?:mini[ _\-]?byte|byte|tag|del)\s*\))+\s*$", "", stem, flags=re.I).strip()      # v11.2.0: the plain clip too: 111126_FIRE (byte) / (minibyte) / (tag) / (del), in brackets only (a story called ..._BYTE is untouched)
    m = re.match(r"^(\d{8})_(\d{4})([A-Z])?(?:_|$)", stem)
    v = re.search(r"_V(\d+)$", stem)
    if m: return m.group(1), int(m.group(2)), int(v.group(1)) if v else 1, m.group(3)
    if re.match(r"^\d{6}[_ ]+[A-Za-z0-9]", stem):
        nm = re.sub(r"[^A-Z0-9]+", "_", stem.upper()).strip("_"); v = re.search(r"_V(\d+)$", nm)      # spaces, dashes and underscores are the same in a file name
        if SUFFIX_ON and (u := re.search(r"_([UV])(\d+)$", nm)): return "NAME", nm, (1000 if u.group(1) == "U" else 2000) + int(u.group(2)), None      # v10.5.0: _Un / _Vn (same numbers as ids.enc_version; the watcher is a stand-alone script, it imports nothing from the package)
        return "NAME", nm, int(v.group(1)) if v else 1, None
    return None

def key_query(key):
    """The /svc/match query string for a parsed name."""
    if key[0] == "NAME": return "name=" + urllib.parse.quote(key[1])
    return "day=%s&seq=%d&version=%d" % tuple(key[:3]) + ("&chk=" + key[3] if len(key) > 3 and key[3] else "")

def key_label(key): return key[1] if key[0] == "NAME" else "%s_%04d" % tuple(key[:2])

class LockLost(Exception):
    """Our claim on the file disappeared or was taken over mid-copy: stop immediately and leave the source untouched."""

MINE = set()                   # tokens of claims taken by THIS process life; a lock with our host+pid but another token is a leftover of a previous life
_OBS = {}                      # path -> (signature, first time seen with that signature): how long has it been unchanged, by our clock

def unchanged_for(key, sig):
    t = _now(); old = _OBS.get(key)
    if old is None or old[0] != sig: _OBS[key] = (sig, t); return 0.0
    return t - old[1]

def _pid_alive_windows(pid):
    """Windows: os.kill(pid, 0) would TERMINATE the process there (any signal but Ctrl-C/Ctrl-Break calls TerminateProcess), so ask the OS instead."""
    import ctypes
    k = ctypes.windll.kernel32; h = k.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h: return k.GetLastError() == 5                                          # access denied = it exists, we may not look; anything else = no such process
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259    # STILL_ACTIVE
    finally: k.CloseHandle(h)

def pid_alive(pid):
    if os.name == "nt": return _pid_alive_windows(pid)
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True
    except OSError: return True

def _read_lock(lp):
    try:
        with open(lp) as f: return json.load(f)
    except (OSError, ValueError): return {}          # missing, empty (creator is mid-write) or unreadable: judge by staleness only

def lock_is_dead(lp):
    """True if nobody is working under this lock. Same host: a dead pid (or our own pid with a token we never issued = previous life,
    e.g. after a container restart) is dead at once. Anything else: dead only after LOCK_STALE seconds with no refresh."""
    try: st = os.stat(lp)
    except FileNotFoundError: return True
    info = _read_lock(lp)
    if info.get("host") == HOST and isinstance(info.get("pid"), int):
        if info["pid"] == os.getpid():
            if info.get("token") not in MINE: return True
        elif not pid_alive(info["pid"]): return True
    return unchanged_for(lp, (st.st_mtime, st.st_size)) >= LOCK_STALE

class Claim:
    def __init__(self, path, token): self.path, self.token, self._last = path, token, _now()
    def refresh(self, force=False):
        """Heartbeat the lock (mtime) and make sure it is still ours. Raises LockLost if not."""
        if not force and _now() - self._last < REFRESH_EVERY: return
        if _read_lock(self.path).get("token") != self.token: raise LockLost("claim on %s was lost" % os.path.basename(self.path))
        os.utime(self.path, None); self._last = _now()
    def release(self):
        MINE.discard(self.token)
        if _read_lock(self.path).get("token") == self.token:      # never delete somebody else's lock
            try: os.unlink(self.path)
            except FileNotFoundError: pass

def _break_lock(lp):
    """Remove a lock judged dead. rename is atomic, so of several workers breaking the same lock exactly one wins."""
    try: before = os.stat(lp)
    except FileNotFoundError: return
    grave = "%s.stale.%s" % (lp, uuid.uuid4().hex[:8])
    try: os.rename(lp, grave)
    except FileNotFoundError: return                              # someone else broke it first
    try: after = os.stat(grave)
    except FileNotFoundError: return
    if (after.st_mtime, after.st_size) != (before.st_mtime, before.st_size):    # it was refreshed meanwhile: we grabbed a LIVE lock, put it back
        try: os.link(grave, lp)
        except OSError: pass
    try: os.unlink(grave)
    except FileNotFoundError: pass

def acquire(name):
    """Atomic claim on a source file name: O_CREAT|O_EXCL create of a lock file. Returns a Claim or None if someone else holds it."""
    os.makedirs(LOCK_DIR, exist_ok=True); lp = os.path.join(LOCK_DIR, name + ".lock"); token = uuid.uuid4().hex
    for _ in range(3):
        try: fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if not lock_is_dead(lp): return None
            log.warning("breaking dead lock on %s", name); _break_lock(lp); continue
        with os.fdopen(fd, "w") as f:
            json.dump({"host": HOST, "pid": os.getpid(), "token": token, "started": time.time()}, f); f.flush(); os.fsync(f.fileno())
        MINE.add(token); return Claim(lp, token)
    return None

PART_RE = re.compile(r"^\.(?P<name>.+?)(?:\.(?P<tok>[0-9a-f]{32}))?\.part$")    # .<name>.<token>.part  (or legacy .<name>.part)

def clean_stale():
    """Delete leftovers of crashed copies. A .part file goes only if (a) it has not changed for PART_STALE seconds AND (b) no live claim
    owns it. Locks of crashed workers whose source is gone are removed too. Nothing that does not match our own naming is ever touched."""
    n = 0
    for f in os.listdir(NITRO) if os.path.isdir(NITRO) else []:
        m = PART_RE.match(f); p = os.path.join(NITRO, f)
        if not m or not os.path.isfile(p) or os.path.islink(p): continue
        try: st = os.stat(p)
        except FileNotFoundError: continue
        lp = os.path.join(LOCK_DIR, m["name"] + ".lock")
        if os.path.exists(lp) and not lock_is_dead(lp) and (m["tok"] is None or _read_lock(lp).get("token") == m["tok"]): continue
        if unchanged_for(p, (st.st_mtime, st.st_size)) >= PART_STALE:
            try: os.remove(p); n += 1; log.warning("removed stale partial copy %s", f)
            except OSError as e: log.warning("could not remove %s: %s", f, e)
    for f in os.listdir(LOCK_DIR) if os.path.isdir(LOCK_DIR) else []:
        p = os.path.join(LOCK_DIR, f)
        if ".stale." in f and unchanged_for(p, 0) >= LOCK_STALE:
            try: os.remove(p)
            except OSError: pass
        elif f.endswith(".lock") and not os.path.exists(os.path.join(EXPORTS, f[:-5])) and lock_is_dead(p):
            try: os.remove(p); n += 1
            except OSError: pass
    for k in [k for k in _OBS if not os.path.exists(k)]: _OBS.pop(k, None)
    return n

def sha256(path, tick=None):
    h = hashlib.sha256(); last = _now()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
            if tick and _now() - last >= REFRESH_EVERY: tick(); last = _now()
    return h.hexdigest()

def copy_hashing(src, dst, tick):
    """Copy src to dst in one pass, hashing what was read, fsync before returning. Refreshes the claim while it works."""
    h = hashlib.sha256()
    with open(src, "rb") as i, open(dst, "wb") as o:
        for b in iter(lambda: i.read(CHUNK), b""):
            h.update(b); o.write(b); tick()
            if COPY_HOOK: COPY_HOOK(len(b))
        o.flush(); os.fsync(o.fileno())
    return h.hexdigest()

def api(path, payload=None):
    req = urllib.request.Request(REGISTRY + path, method="POST" if payload is not None else "GET",
                                 headers={"Content-Type": "application/json", "X-API-Key": KEY},
                                 data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=10) as r: return json.loads(r.read())

def alert(text):
    log.warning("ALERT %s", text)
    if WEBHOOK:
        try: urllib.request.urlopen(urllib.request.Request(WEBHOOK, data=json.dumps({"text": "Auto-ID: " + text}).encode(),
                                    headers={"Content-Type": "application/json"}), timeout=10)
        except Exception as e: log.warning("webhook failed: %s", e)

class RegistryUnavailable(Exception):
    """Registry could not be reached or answered 5xx. Transient: wait and retry, never count against the file."""

def report(did, state, required=False, **kw):
    """required=True: the registry MUST acknowledge, or this raises and the caller stops (the source file is not archived).
    required=False: best effort, used only for QUARANTINED where the file has already been moved aside."""
    if not did: return
    try: api("/svc/files", {"display_id": did, "state": state, **kw})
    except urllib.error.HTTPError as e:
        if e.code >= 500 and required: raise RegistryUnavailable("registry error %d while reporting %s" % (e.code, state))
        if required: raise
        log.warning("report %s failed: %s", state, e)
    except (urllib.error.URLError, OSError, ValueError) as e:
        if required: raise RegistryUnavailable("registry unreachable while reporting %s: %s" % (state, e))
        log.warning("report %s failed: %s", state, e)

def quarantine(path, reason, did=None):
    os.makedirs(QUAR, exist_ok=True)
    dest = os.path.join(QUAR, os.path.basename(path))
    if os.path.exists(dest): dest = "%s.%d" % (dest, int(time.time()))
    shutil.move(path, dest)
    with open(dest + ".reason.txt", "w") as f: f.write(reason + "\n")
    report(did, "QUARANTINED", nas_path=dest, error=reason)   # best effort: the file is already moved aside and the alert below fires
    alert("%s quarantined: %s" % (os.path.basename(path), reason))

def probe(path):
    """-> (ok, error_text, duration_seconds)"""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                             capture_output=True, text=True, timeout=120)
        dur = float(json.loads(out.stdout)["format"]["duration"]) if out.returncode == 0 else 0.0
        return out.returncode == 0 and dur > 0, out.stderr.strip()[:200], dur
    except Exception as e: return False, str(e), 0.0

def process(path):
    """Claim the file, process it, release the claim. Returns BUSY if another worker holds it, DONE if it is already gone."""
    name = os.path.basename(path); claim = acquire(name)
    if claim is None: log.info("%s is being processed by another worker, skipping", name); return BUSY
    try:
        if not os.path.exists(path): return DONE          # another worker finished between our listing and our claim
        _process(path, claim); return None
    finally: claim.release()

def _process(path, claim):
    name = os.path.basename(path); key = parse_name(name)
    if not key: return quarantine(path, "no ID at start of filename (expected DDMMYY_STORY_NAME)")
    try: clip = api("/svc/match?" + key_query(key))
    except urllib.error.HTTPError as e:
        if e.code == 404: return quarantine(path, "ID %s is not in the registry%s" % (key_label(key), _why(e)))
        if e.code == 422: return quarantine(path, "check character does not match: ID was mistyped")
        raise
    did = clip["display_id"]
    dur = None
    if NEED_PROBE:
        ok, err, dur = probe(path)
        if not ok: return quarantine(path, "ffprobe rejected the file: " + err, did)
    src_hash = sha256(path, claim.refresh); size = os.path.getsize(path)
    report(did, "VERIFIED", required=True, nas_path=path, size=size, sha256=src_hash)
    dest = os.path.join(NITRO, name)
    if os.path.exists(dest):                      # idempotent: only ever created by the atomic replace below, so a mismatch is a genuinely different file
        if sha256(dest, claim.refresh) != src_hash: return quarantine(path, "a different file with this name is already on Nitro", did)
    else:
        tmp = os.path.join(NITRO, ".%s.%s.part" % (name, claim.token))    # unique per claim: two workers can never write the same partial file
        try:
            if copy_hashing(path, tmp, claim.refresh) != src_hash: raise IOError("source file changed while it was being copied")
            if sha256(tmp, claim.refresh) != src_hash: raise IOError("checksum mismatch after copy")   # verified BEFORE it gets its real name
            claim.refresh(force=True)                                      # still ours? (raises LockLost if not)
            os.replace(tmp, dest)                                          # atomic: Nitro never sees a half-written or unverified file
        except BaseException:                                              # includes LockLost and SIGTERM (SystemExit): leave no partial behind
            try: os.remove(tmp)
            except OSError: pass
            raise
    # The registry must acknowledge ON_NITRO BEFORE the source is archived. If it cannot, this raises, the source stays in
    # Exports, and the next poll finds the identical file already on Nitro (idempotent branch above), re-reports and archives.
    report(did, "ON_NITRO", required=True, nas_path=path, nitro_path=dest, size=size, sha256=src_hash, duration_s=dur)
    os.makedirs(ARCH, exist_ok=True)
    try: shutil.move(path, os.path.join(ARCH, "%d_%s" % (int(time.time()), name)))
    except FileNotFoundError:
        if os.path.exists(path): raise                                      # source vanished = another worker already archived it: fine
    log.info("%s -> Nitro (registry acknowledged)", name)

def purge_archive():
    cut = time.time() - RETAIN * 86400
    for f in os.listdir(ARCH) if os.path.isdir(ARCH) else []:
        p = os.path.join(ARCH, f)
        if os.path.isfile(p) and os.path.getmtime(p) < cut: os.remove(p)

_ALERTED = {}
def alert_once(key, text, every=900):
    if time.time() - _ALERTED.get(key, 0) > every: _ALERTED[key] = time.time(); alert(text)

def beat(nas_ok, problem=None):
    try: api("/svc/heartbeat", {"component": "watcher", "detail": {"nas_ok": nas_ok, "problem": problem}})
    except Exception as e: log.warning("heartbeat failed: %s", e)

# ---------- observe mode: watch only, never touch a file ----------
def _why(e):
    """v10.7.0: the registry's reason for a 404 (for example 'the next update for 111126_FIRE is U02'), as ': reason'; empty for the plain 'no such clip id'."""
    try: d = json.loads(e.read()).get("detail") or ""
    except Exception: d = ""
    return (": " + d) if d and d != "no such clip id" else ""

def match(key):
    """Registry lookup for a parsed filename key (day, seq, version, check). Raises HTTPError 404 (unknown) / 422 (bad check letter)."""
    return api("/svc/match?" + key_query(key))

def inbox_files():
    """[(path, name)] of candidate files in the Playout inbox folders. Hidden (dot) files are not listed, so a file the conversion job hides
    simply 'disappears'. A listing error RAISES: the caller aborts the whole poll, so an NAS hiccup can never look like 'everything finished'."""
    out = []
    for sub in INBOX_DIRS or [""]:
        d = os.path.join(EXPORTS, sub)
        for n in os.listdir(d):
            if n.startswith(".") or not n.lower().endswith(EXTS): continue
            p = os.path.join(d, n)
            if os.path.isfile(p): out.append((p, n))
    return out

def scan_nitro(wanted):
    """One bounded walk of the Nitro folder. -> {(day, seq, version): (path, size, mtime)} for finished files whose name carries a wanted ID."""
    found = {}
    def roots():
        if not NITRO_DATE_PATH: return [NITRO]
        os.listdir(NITRO)                                                      # the share itself must answer (an unmounted NAS raises here, it never looks like 'nothing arrived')
        today = dt.datetime.fromtimestamp(_wall()).date(); out = []
        for k in range(-NITRO_DAYS_BACK, NITRO_DAYS_AHEAD + 1):
            for pat in NITRO_DATE_PATH:
                p = os.path.join(NITRO, (today + dt.timedelta(days=k)).strftime(pat))
                if os.path.isdir(p) and p not in out: out.append(p)
        return out
    def walk(d, depth):
        for e in os.scandir(d):
            if e.name.startswith("."): continue
            if e.is_dir(follow_symlinks=False):
                if depth < NITRO_DEPTH: walk(e.path, depth + 1)
            elif e.name.lower().endswith(NITRO_EXTS):
                k = parse_name(e.name)
                if k and k[:3] in wanted:
                    st = e.stat(); found[k[:3]] = (e.path, st.st_size, st.st_mtime)
    for r in roots(): walk(r, 0)
    return found

def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except (OSError, ValueError): return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True); tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f: json.dump(state, f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)

_LAST_SCAN = [-1e18, {}]      # [wall time of the last Nitro walk, its result]: walking a big share every 5 s would be wasteful
def observe_tick(state):
    """One poll. state: path -> entry, saved to disk by the caller. Flow per file:
    in the Playout inbox -> EXPORTING (reported once the file stops growing); gone from the inbox -> look for the finished MXF on Nitro;
    MXF found and its size has stopped changing -> ON_NITRO (the registry must acknowledge). Gone but no MXF after DONE_WAIT_SECS -> NEEDS_DESK + alert."""
    now = _wall(); present = dict(inbox_files()); live = set(present)
    for p, n in present.items():
        e = state.get(p)
        if e is None or e.get("gone_at"):                                  # new file, or the same path came back
            k = parse_name(n)
            e = state[p] = {"name": n, "key": list(k) if k else None, "did": None, "first": now, "exporting": False, "gone_at": None, "flagged": False, "stuck": False, "retry_at": 0}
        if not e["key"]:
            alert_once("noid:" + p, "%s is in the Playout inbox but its name has no ID at the start (expected DDMMYY_STORY_NAME). It will not be linked." % n); continue
        if not e["did"] and now >= e["retry_at"]:
            try: e["did"] = match(e["key"])["display_id"]
            except urllib.error.HTTPError as ex:
                if ex.code in (404, 422):
                    e["retry_at"] = now + 60
                    alert_once("badid:" + p, "%s: %s" % (n, ("ID %s is not in the registry" % key_label(e["key"]) + _why(ex)) if ex.code == 404 else "check character does not match: ID was mistyped"))
                else: alert_once("registry", "registry error %d, Playout files are being tracked but not reported" % ex.code)
            except (urllib.error.URLError, OSError, ValueError) as ex: alert_once("registry", "registry unreachable: %s" % ex)
        try: st = os.stat(p)
        except FileNotFoundError: live.discard(p); continue
        if e["did"] and not e["exporting"] and unchanged_for(p, (st.st_size, st.st_mtime)) >= STABLE:
            report(e["did"], "EXPORTING", nas_path=p); e["exporting"] = True
        if now - e["first"] > STUCK_SECS and not e["stuck"]:
            e["stuck"] = True; alert("%s has been in the Playout inbox for over %d min: the conversion may be failing (check the conversion job)" % (n, (now - e["first"]) // 60))
    gone = {p: e for p, e in state.items() if p not in live}
    for p, e in list(gone.items()):
        if not e.get("gone_at"): e["gone_at"] = now; log.info("%s left the Playout inbox, waiting for the MXF on Nitro", e["name"])
        if e["key"] and not e["did"]:                                      # never resolved (registry was down, or the ID is bad): one more try
            try: e["did"] = match(e["key"])["display_id"]
            except urllib.error.HTTPError as ex:
                if ex.code in (404, 422): state.pop(p, None); gone.pop(p); continue    # bad ID, already alerted: nothing to link
            except (urllib.error.URLError, OSError, ValueError): pass                    # transient: keep the entry, try again next poll
        if not e["key"] or now - e["gone_at"] > FORGET_SECS: state.pop(p, None); gone.pop(p)
        elif not e["did"]: gone.pop(p)                                                   # keep tracking, but nothing to report yet
    if gone:
        wanted = {tuple(e["key"][:3]) for e in gone.values()}
        if now - _LAST_SCAN[0] >= NITRO_SCAN_EVERY: _LAST_SCAN[0] = now; _LAST_SCAN[1] = scan_nitro(wanted)
        found = _LAST_SCAN[1]
        for p, e in list(gone.items()):
            hit = found.get(tuple(e["key"][:3]))
            if hit:
                path, size, mtime = hit; live.add("nitro:" + path)
                if unchanged_for("nitro:" + path, (size, mtime)) < STABLE: continue          # Nitro is still writing it
                try: report(e["did"], "ON_NITRO", required=True, nas_path=p, nitro_path=path, size=size)
                except (RegistryUnavailable, urllib.error.HTTPError, OSError) as ex: alert_once("registry", "could not report ON_NITRO for %s: %s" % (e["did"], ex)); continue
                log.info("%s -> on Nitro at %s (registry acknowledged)", e["did"], path); state.pop(p, None)
            elif now - e["gone_at"] > DONE_WAIT and not e["flagged"]:
                e["flagged"] = True; msg = "%s left the Playout inbox but no finished MXF with that ID is on Nitro after %d min (deleted? conversion failed?)" % (e["name"], DONE_WAIT // 60)
                report(e["did"], "NEEDS_DESK", nas_path=p, error=msg); alert(msg)
    for k in [k for k in _OBS if k not in live]: _OBS.pop(k, None)

def observe_main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    state, last_beat = load_state(), 0
    log.info("watcher mode=observe inbox=%s%s nitro=%s (read only use: nothing is copied, moved or deleted)", EXPORTS, INBOX_DIRS or "", NITRO)
    while True:
        problem = storage_problem()
        if time.time() - last_beat > 30: beat(problem is None, problem); last_beat = time.time()
        if problem: alert_once("storage", "watcher paused: " + problem); time.sleep(POLL); continue
        try: observe_tick(state); save_state(state)
        except RegistryUnavailable as e: alert_once("registry", "registry unavailable: %s" % e)
        except Exception as e: log.error("poll error (NAS down?): %s", e)
        time.sleep(POLL)

def main():
    if WATCH_MODE == "observe": return observe_main()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # docker stop: unwind, so claims are released and partial copies removed
    seen, tries, last_purge, last_beat, last_clean = {}, {}, 0, 0, 0
    while True:
        if time.time() - last_clean > CLEAN_EVERY:
            try: clean_stale()
            except Exception as e: log.warning("stale cleanup failed: %s", e)
            last_clean = time.time()
        problem = storage_problem()
        if time.time() - last_beat > 30:
            beat(problem is None, problem); last_beat = time.time()
        if problem:                                       # never touch files while storage looks wrong
            alert_once("storage", "watcher paused: " + problem); time.sleep(POLL); continue
        try:
            names = [n for n in os.listdir(EXPORTS) if n.lower().endswith(EXTS) and not n.startswith(".")]
            for n in names:
                p = os.path.join(EXPORTS, n)
                try: st = os.stat(p)
                except FileNotFoundError: continue
                sig = (st.st_size, st.st_mtime)
                if seen.get(p, (None,))[0] != sig: seen[p] = (sig, time.time()); continue
                marker = os.path.exists(p + ".done")
                if not marker and time.time() - seen[p][1] < STABLE: continue   # still being written
                try:
                    if process(p) == BUSY: continue                 # someone else has it: look again next poll, no retry counted
                    seen.pop(p, None); tries.pop(p, None)
                    if marker and os.path.exists(p + ".done"): os.remove(p + ".done")
                except RegistryUnavailable as e:        # registry outage is not the file's fault: keep waiting, never quarantine
                    log.warning("%s waiting for registry: %s", n, e); alert_once("registry", "registry unavailable, files are waiting in Exports: %s" % e)
                except Exception as e:                  # transient: retry next poll, then give up
                    tries[p] = tries.get(p, 0) + 1; log.warning("%s attempt %d failed: %s", n, tries[p], e)
                    if tries[p] >= MAX_TRIES and os.path.exists(p): quarantine(p, "gave up after %d tries: %s" % (MAX_TRIES, e))
            for p in [p for p in seen if not os.path.exists(p)]: seen.pop(p, None)
        except Exception as e: log.error("poll error (NAS down?): %s", e)
        if time.time() - last_purge > 3600:
            try: purge_archive()
            except Exception: pass
            last_purge = time.time()
        time.sleep(POLL)

if __name__ == "__main__": main()
