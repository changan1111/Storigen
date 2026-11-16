"""Minimal MOS device. Listens on both MOS ports, answers heartbeats / machine-info / run-order
messages with acks, and sends story IDs to the registry. Raw traffic is logged to /data/mos_capture.log
(use it for checks A3/A4). To use Sofie's mos-connection instead, keep the same registry calls."""
import asyncio, codecs, datetime, json, logging, os, re, threading, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

REGISTRY = os.getenv("REGISTRY_URL", "http://127.0.0.1:8080")
KEY = os.getenv("SERVICE_API_KEY", "")
DATA = os.path.join(os.getenv("DATA_DIR", "data"), "gateway")
PORTS = [int(p) for p in os.getenv("MOS_PORTS", "10540,10541").split(",")]
log = logging.getLogger("mos"); logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
HEADER = {"mosID", "ncsID", "messageID"}
ACK_ONLY = {"roStoryInsert", "roStoryReplace", "roStoryAppend", "roStoryDelete", "roStoryMove", "roStorySwap", "roStorySend",
            "roItemInsert", "roItemReplace", "roItemDelete", "roItemMoveMultiple", "roReadyToAir", "roElementAction",
            "roMetadataReplace", "roDelete", "roCreate", "roReplace", "roStatus", "roItemStatus", "roStoryStatus"}

# ONLY_RUNDOWNS: IDs are made only for the rundowns listed here (comma separated; empty = every rundown Blaze sends). An entry matches a rundown
# when it equals its roID exactly, or when it appears (any letter case) in the rundown's NAME (roSlug), e.g. "9 PM BULLETIN". Per-story messages carry
# only the roID, so the name is learned from the full-rundown messages (roCreate / roReplace / roMetadataReplace) and kept on disk across restarts.
# Rundowns that do not match are still acknowledged to Blaze (it must get its roAck) but nothing is recorded.
ONLY = [x.strip() for x in os.getenv("ONLY_RUNDOWNS", "").split(",") if x.strip()]
NAMES_FILE = os.path.join(DATA, "rundown_names.json"); _NAMES = {}; _IGNORED = set()

def load_names():
    try:
        with open(NAMES_FILE) as f: _NAMES.update(json.load(f))
    except (OSError, ValueError): pass

def remember_name(body):
    ro, name = t(body, "roID"), t(body, "roSlug")
    if not (ro and name) or _NAMES.get(ro) == name: return
    _NAMES[ro] = name
    try:
        os.makedirs(DATA, exist_ok=True); tmp = NAMES_FILE + ".tmp"
        with open(tmp, "w") as f: json.dump(_NAMES, f)
        os.replace(tmp, NAMES_FILE)
    except OSError as e: log.warning("could not save rundown names: %s", e)

def allowed(ro):
    if not ONLY: return True
    name = _NAMES.get(ro, "")
    if any(e == ro or (name and e.lower() in name.lower()) for e in ONLY): return True
    if ro not in _IGNORED:
        _IGNORED.add(ro)
        log.info("rundown %s (%s) is not in ONLY_RUNDOWNS: ignored, no IDs made. If it should get IDs, add its roID (or part of its name) to ONLY_RUNDOWNS; "
                 "a rundown whose name has not been seen yet is matched by roID only until Blaze sends the full rundown", ro, name or "name not seen yet")
    return False

def t(el, tag, default=""):
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else default

def parse_mos(xml: str):
    root = ET.fromstring(xml)
    hdr = {k: t(root, k) for k in HEADER}
    body = next((c for c in root if c.tag not in HEADER), None)
    return hdr, body

def reply(hdr, inner: str) -> str:
    return ("<mos><mosID>%s</mosID><ncsID>%s</ncsID><messageID>%s</messageID>%s</mos>"
            % (escape(hdr["mosID"]), escape(hdr["ncsID"]), escape(hdr["messageID"]), inner))

def ro_ack(ro_id, status="OK"):
    return "<roAck><roID>%s</roID><roStatus>%s</roStatus></roAck>" % (escape(ro_id), status)

def machine_info(hdr):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return ("<listMachInfo><manufacturer>Auto-ID</manufacturer><model>Linker</model><hwRev>0</hwRev><swRev>1.0</swRev>"
            "<DOM>2026-01-01</DOM><SN>1</SN><ID>%s</ID><time>%s</time><opTime>%s</opTime><mosRev>2.8.3</mosRev>"
            "<supportedProfiles deviceType=\"MOS\"><mosProfile number=\"0\">YES</mosProfile><mosProfile number=\"1\">YES</mosProfile>"
            "<mosProfile number=\"2\">YES</mosProfile><mosProfile number=\"3\">NO</mosProfile><mosProfile number=\"4\">YES</mosProfile>"
            "<mosProfile number=\"5\">NO</mosProfile></supportedProfiles></listMachInfo>") % (escape(hdr["mosID"]), now, now)

def call(path, payload=None, method="POST"):
    req = urllib.request.Request(REGISTRY + path, method=method, headers={"Content-Type": "application/json", "X-API-Key": KEY},
                                 data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def actions_for(body):
    """Translate a run-order message into registry calls: [(path, payload)]."""
    tag = body.tag; ro = t(body, "roID"); out = []
    if tag in ("roCreate", "roReplace"):
        # The message holds the COMPLETE rundown, so it goes to the registry as ONE call: stories listed are created/refreshed, stories of this
        # rundown that are not listed are removed and their clips held for the desk. Never split this into per-story calls.
        if ro:
            out.append(("/svc/rundowns/sync", {"blaze_rundown_id": ro, "rundown_name": t(body, "roSlug") or None,
                        "stories": [{"blaze_story_id": t(s, "storyID"), "slug": t(s, "storySlug")} for s in body.findall("story") if t(s, "storyID")]}))
        else: log.warning("%s without roID ignored", tag)
    elif tag in ("roStoryInsert", "roStoryAppend"):
        for s in body.findall("story"):
            out.append(("/svc/stories", {"blaze_rundown_id": ro, "blaze_story_id": t(s, "storyID"), "slug": t(s, "storySlug")}))
    elif tag == "roStoryReplace":
        old = t(body, "storyID")
        for s in body.findall("story"):
            new = t(s, "storyID")
            if old and new and old != new:
                out.append(("/svc/stories/rename", {"blaze_rundown_id": ro, "old_id": old, "new_id": new}))
            out.append(("/svc/stories", {"blaze_rundown_id": ro, "blaze_story_id": new, "slug": t(s, "storySlug")}))
    elif tag == "roStoryDelete":
        for s in body.findall("storyID"):
            out.append(("/svc/stories/delete", {"blaze_rundown_id": ro, "blaze_story_id": (s.text or "").strip()}))
    # roStoryMove only re-orders stories inside one rundown, so the rundown/story association does not change: nothing to record.
    # (A move BETWEEN rundowns arrives as roStoryDelete + roStoryInsert; the registry flags that case for the desk.)
    elif tag == "roDelete":
        out.append(("/svc/stories/delete", {"blaze_rundown_id": ro}))
    return out

ID_RE = re.compile(r"^(?:\d{8}_\d{4}[A-Z]?(?:_|$)|\d{6}[_ ]+[A-Za-z0-9])")      # legacy YYYYMMDD_NNNNC_... or DDMMYY_STORY_NAME

def confirmations(body):
    """Read-back: Blaze tells us which objects sit in which story (items carry an objID). Our clip IDs start with YYYYMMDD_NNNN or DDMMYY_NAME, so
    any item whose objID looks like one is a confirmation that THAT clip is in THAT story. Returns registry calls."""
    ro = t(body, "roID"); out = []
    def add(story_id, item):
        oid = t(item, "objID")
        if story_id and oid and ID_RE.match(oid):
            out.append(("/svc/attach/confirm", {"display_id": oid, "blaze_rundown_id": ro, "blaze_story_id": story_id, "source": "mos_item"}))
    for s in body.findall("story"):
        for it in s.findall("item"): add(t(s, "storyID"), it)
    for it in body.findall("item"): add(t(body, "storyID"), it)      # roItemInsert / roItemReplace carry storyID + item at top level
    return out

START = time.time(); LAST_MOS = [None]
SPOOL = os.path.join(DATA, "spool.jsonl"); DEAD = os.path.join(DATA, "spool.dead.jsonl")
MAX_REPLAY_TRIES = int(os.getenv("SPOOL_MAX_TRIES", "40"))      # replay runs every 15 s, so 40 tries = 10 minutes
NO_RETRY = {400, 404, 409, 410, 422}                            # the registry understood the call and refused it: repeating cannot help
_ORDER = threading.Lock()                                       # registry calls must reach the registry in the order Blaze sent them

def spool(path, payload, tries=0):
    with open(SPOOL, "a") as f: f.write(json.dumps([path, payload, tries]) + "\n")

def dead_letter(path, payload, why):
    log.error("registry call dropped (%s): %s %s", why, path, json.dumps(payload)[:300])
    with open(DEAD, "a") as f: f.write(json.dumps({"time": datetime.datetime.now().isoformat(timespec="seconds"), "why": why, "call": [path, payload]}) + "\n")

def _lines(path):
    if not os.path.exists(path): return []
    with open(path) as f: return [l for l in f if l.strip()]

def deliver(path, payload):
    """Send one registry call IN ORDER. While older calls wait in the spool, new ones queue behind them: a stale full-rundown snapshot
    replayed after a newer message would otherwise remove stories that exist."""
    with _ORDER:
        if _lines(SPOOL): spool(path, payload); return
        try: call(path, payload)
        except urllib.error.HTTPError as e:
            if e.code in NO_RETRY: dead_letter(path, payload, "HTTP %d" % e.code)
            else: log.warning("registry call failed (%s), spooled: HTTP %d", path, e.code); spool(path, payload)
        except Exception as e:
            log.warning("registry call failed (%s), spooled: %s", path, e); spool(path, payload)

def replay_spool():
    """Registry was down: retry the queue head-first and in order. Safe because the calls are idempotent. A call the registry keeps
    failing is dead-lettered after MAX_REPLAY_TRIES so it cannot block everything behind it; the health banner turns red when that happens."""
    with _ORDER:
        items = []
        for l in _lines(SPOOL):
            it = json.loads(l); items.append((it[0], it[1], it[2] if len(it) > 2 else 0))     # older spool lines have no try counter
        if not items: return
        rest = list(items)
        while rest:
            p, d, n = rest[0]
            try: call(p, d)
            except urllib.error.HTTPError as e:
                if e.code in NO_RETRY: dead_letter(p, d, "HTTP %d" % e.code)
                elif n + 1 >= MAX_REPLAY_TRIES: dead_letter(p, d, "HTTP %d after %d tries" % (e.code, n + 1))
                else: rest[0] = (p, d, n + 1); break
            except Exception:
                if n + 1 >= MAX_REPLAY_TRIES: dead_letter(p, d, "unreachable after %d tries" % (n + 1))
                else: rest[0] = (p, d, n + 1); break
            rest.pop(0)
        if rest != items:       # rewrite atomically; a crash here only means some idempotent calls are repeated
            tmp = SPOOL + ".tmp"
            with open(tmp, "w") as f:
                for p, d, n in rest: f.write(json.dumps([p, d, n]) + "\n")
            os.replace(tmp, SPOOL)
        if not rest and os.path.exists(SPOOL): os.remove(SPOOL)

def handle(xml: str) -> str:
    LAST_MOS[0] = time.time()
    hdr, body = parse_mos(xml)
    if body is None: return ""
    tag = body.tag
    if tag == "heartbeat":
        return reply(hdr, "<heartbeat><time>%s</time></heartbeat>" % datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
    if tag == "reqMachInfo": return reply(hdr, machine_info(hdr))
    remember_name(body)
    acts = [(p, d) for p, d in actions_for(body) if allowed(d.get("blaze_rundown_id", ""))]
    for path, payload in acts + confirmations(body): deliver(path, payload)
    if tag in ACK_ONLY: return reply(hdr, ro_ack(t(body, "roID")))
    log.info("unhandled MOS message: %s", tag)
    return ""

async def client(reader, writer):
    peer = writer.get_extra_info("peername"); log.info("connect %s", peer)
    dec = codecs.getincrementaldecoder("utf-16-be")(errors="replace"); buf = ""
    try:
        while data := await reader.read(65536):
            buf += dec.decode(data)
            while "</mos>" in buf:
                msg, buf = buf.split("</mos>", 1); msg = msg.strip() + "</mos>"
                with open(os.path.join(DATA, "mos_capture.log"), "a", encoding="utf-8") as f:
                    f.write("[%s] %s\n%s\n\n" % (datetime.datetime.now().isoformat(timespec="seconds"), peer, msg))
                try: resp = await asyncio.to_thread(handle, msg)
                except ET.ParseError as e: log.warning("bad XML: %s", e); continue
                if resp:
                    writer.write(resp.encode("utf-16-be")); await writer.drain()
    finally:
        log.info("disconnect %s", peer); writer.close()

async def main():
    os.makedirs(DATA, exist_ok=True); load_names()
    if ONLY: log.info("ONLY_RUNDOWNS active: IDs are made only for %s", ONLY)
    servers = [await asyncio.start_server(client, "0.0.0.0", p) for p in PORTS]
    log.info("listening on %s", PORTS)
    async def replayer():
        while True:
            await asyncio.sleep(15); await asyncio.to_thread(replay_spool)
    async def beat():
        while True:
            d = {"last_mos_age": None if LAST_MOS[0] is None else time.time() - LAST_MOS[0], "uptime": time.time() - START,
                 "spool_pending": len(_lines(SPOOL)), "spool_dead": len(_lines(DEAD))}
            try: await asyncio.to_thread(call, "/svc/heartbeat", {"component": "gateway", "detail": d})
            except Exception as e: log.warning("heartbeat failed: %s", e)
            await asyncio.sleep(30)
    await asyncio.gather(replayer(), beat(), *[s.serve_forever() for s in servers])

if __name__ == "__main__":
    asyncio.run(main())
