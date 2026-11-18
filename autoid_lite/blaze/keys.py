"""Pure matching helpers: file name -> clip key, media list indexing, judging hits, attach request bodies. No I/O."""
from __future__ import annotations
import datetime as dt
import re
import urllib.error, urllib.parse, urllib.request
from .errors import BlazeError
from ..ids import SUF_RE, enc_version, suffix_on


def parse_day(text):
    """A day typed by hand: 20261113, 2026-11-13 or 13112026 (DDMMYYYY). Anything else is a clear one-line error, not a traceback."""
    t = str(text).strip()
    for f in ("%Y%m%d", "%Y-%m-%d", "%d%m%Y", "%d-%m-%Y"):
        try: return dt.datetime.strptime(t, f).date()
        except ValueError: pass
    raise SystemExit("not a date: %r (use 20261113, 2026-11-13 or 13112026)" % t)

ID_RE = re.compile(r"^(\d{8}_\d{4}[A-Z]?)(?=_|\.|$)", re.I)                  # legacy: YYYYMMDD_NNNNC at the start of a file name
NAME_RE = re.compile(r"^\d{6}_[A-Z0-9][A-Z0-9_]*$")                        # v9.7: the whole file name without extension is the ID, DDMMYY_STORY_NAME[_N][_Vn]
VER_RE = re.compile(r"_V(\d+)$", re.I)

def ver_split(stem):
    """(name without its version ending, version). v10.5.0: with VERSION_SUFFIX=on, _Un and _Vn are two kinds (stored as 1000+n / 2000+n); off: only _Vn, as before."""
    m = (SUF_RE if suffix_on() else VER_RE).search(stem)
    if not m: return stem, 1
    return stem[:m.start()], (enc_version(m.group(1), m.group(2)) if suffix_on() else int(m.group(1)))


# ---------------------------------------------------------------- matching
def media_key(title):
    stem = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (title or "").strip()); m = ID_RE.match(stem)
    if not m: return name_key(stem)
    return (m.group(1).upper(), ver_split(stem)[1])

def name_key(stem):
    """v9.7 IDs match on the whole name (capitals do not matter), the version taken off the end: (BASE_NAME, version)."""
    stem = re.sub(r"[^A-Z0-9]+", "_", (stem or "").upper()).strip("_")           # spaces, dashes and underscores are the same in a file name
    if not NAME_RE.match(stem): return None
    return ver_split(stem)

def clip_secs(rows):
    """Total whole seconds of the clips in a story, None when one duration is unknown."""
    return None if any(x["dur"] is None for x in rows) else sum(int(x["dur"] // 1000) for x in rows)

def rkey(r):
    """The matching key of a registry row: its clip NAME (shared by every story with that name) and version."""
    return clip_key(r.get("name_id") or r["display_id"], r["version"])

def clip_key(display_id, version):
    m = ID_RE.match(display_id or ""); return (m.group(1).upper(), int(version or 1)) if m else name_key(display_id)

def show_ignored(title, patterns):
    """Show titles carry the date ("09_11_14:00 PM Bulletin"), so a show is ignored when its title CONTAINS a listed word (case does not matter)."""
    t = (title or "").upper(); return any(p in t for p in patterns)

def ignored(title, patterns):
    """Template rows (BREAK1, OPEN MONTAGE ...): the whole title equals a listed name, with an optional number after it."""
    t = re.sub(r"\s+", " ", (title or "").strip().upper())
    return any(t == p or re.fullmatch(re.escape(p) + r"\s*\d+", t) for p in patterns)

def age_secs(iso):
    try: return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError): return None

def media_pending(m):
    """Blaze lists a file while it is still being ingested and converted: status NEW, duration 0, no proxy and no thumbnail (captured 2026-11-12: 3 such files among 166, every finished one was UPDATED with a duration and a proxy)."""
    return str(m.get("status") or "").strip().upper() == "NEW" or not (isinstance(m.get("duration"), (int, float)) and m["duration"] > 0)

def judge(hits, settle):
    """-> (state, media). state: found | missing | ambiguous | converting (Blaze still converts it) | settling (changed less than `settle` seconds ago)"""
    if not hits: return "missing", None
    if len(hits) > 1: return "ambiguous", hits
    m = hits[0]
    if media_pending(m): return "converting", m
    a = age_secs(m.get("modifiedDate")); return ("settling" if a is not None and a < settle else "found"), m

def find_media(medias, key, settle):
    """-> (state, media) for one clip key in a list of Blaze files (see judge)."""
    return judge(list({m["id"]: m for m in medias if media_key(m.get("title") or m.get("description")) == key}.values()), settle)

def index_media(medias):
    """Blaze files by clip key, so that 600 clips can be matched against 1000 files without 600 x 1000 comparisons."""
    idx = {}
    for m in medias:
        k = media_key(m.get("title") or m.get("description"))
        if k: idx.setdefault(k, {})[m["id"]] = m
    return idx

def find_indexed(idx, key, settle): return judge(list((idx.get(key) or {}).values()), settle)

def attach_body(show, m, order, item_id):
    """The form fields Blaze's page sends to attach a clip (doc section 8 and 10). order = finalPosition + 1; duration = whole seconds, rounded down."""
    return {"clipType": "MEDIA", "mosObjectId": m["id"], "name": m["title"], "title": m["title"], "markIn": 0, "markOut": 0,
            "duration": int((m.get("duration") or 0) // 1000), "showId": show, "order": "?" if order is None else order, "itemId": item_id or "?"}

def attached_facts(row, m, item_id):
    """What Blaze holds for an attached clip, for the dashboard: the media object (mosObjectId), the story item, the clip length in whole seconds, Blaze's own clip id. `row` = the clip as the story read-back shows it ({} when unknown)."""
    dur = row.get("dur") if isinstance(row.get("dur"), (int, float)) else m.get("duration") if isinstance(m.get("duration"), (int, float)) else None
    item = row.get("item") if row.get("item") not in (None, "") else item_id
    return {"mos_object_id": str(m["id"]), "item_id": None if item in (None, "") else str(item), "duration_s": None if dur is None else int(dur // 1000), "blaze_clip_id": row.get("id")}

def attach_call(story_id, show, m, order, item_id):
    return "POST /DataService/stories/%s/clips/  %s" % (story_id, urllib.parse.urlencode(attach_body(show, m, order, item_id), safe="?"))

# ---------------------------------------------------------------- Auto-ID server
def transient(e):
    """Worth one quick retry: the network or Blaze hiccuped (timeout, reset, 5xx, half-sent JSON). Not a refusal, not an expired session."""
    return isinstance(e, (OSError, ValueError)) or (isinstance(e, BlazeError) and e.code >= 500)
