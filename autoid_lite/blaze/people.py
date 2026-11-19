"""v10.9.0: who created a story and who it is assigned to, read from GET /stories/<id>/complete/ (storyComplete) and turned into Blaze usernames.

Blaze names a user by number (venkat = 363 ...). The table below is the list of the Blaze users; a story that carries only a number gets the username from it, a story that carries the
username itself keeps it. Add a user without touching the program: put {"364": "newuser"} into data/blaze_users.json (read again every minute, wins over the table).
Field names: the first of KEYS that the story carries is used. If your Blaze calls them something else, run `python3 tools/blaze_poll.py people <story id>` (prints what the story carries)
and set BLAZE_CREATED_KEYS / BLAZE_ASSIGNED_KEYS in autoid.env (comma separated, tried first). Reading only: nothing is ever written to Blaze."""
from __future__ import annotations
import json, os, time
from pathlib import Path

USERS = {
    363: "venkat", 358: "ramachandran", 355: "sowmiya", 354: "deepakkumar", 352: "thennarasan", 333: "abarna", 311: "ganesan", 310: "yogesh", 309: "vetri", 308: "vigneshs",
    307: "saravanan", 305: "saravananj", 209: "jayakumar", 208: "manikandanrn", 207: "deivamani", 206: "THIRUMALAIKUMAR", 204: "rengaraj", 203: "vigneshprabhu", 202: "gokulv",
    201: "gowris", 200: "ravikumard", 199: "maheswaran", 198: "karthik", 197: "VIJAYV", 196: "moorthi", 195: "magesh", 194: "manoj", 193: "damodharan", 192: "arulmurugan",
    191: "ramesh", 189: "moorthy", 188: "arunprasad", 187: "anandkumar", 178: "Rajasekar", 177: "vikie", 176: "Balakrishnan", 175: "arunganesh", 174: "test", 173: "vigneshr",
    172: "venkatesh", 171: "studio", 169: "manikandanc", 168: "sivasubramanian", 167: "aravindan", 166: "sriganesh", 165: "elayabharathi", 164: "vijayabaskar", 162: "sivasamy",
    161: "padmapriya", 159: "sumathi", 158: "nandhini", 157: "chithirarekha", 156: "kaviarasan", 155: "thillai", 154: "thangasuresh", 153: "socialmedia3", 152: "socialmedia2",
    151: "socialmedia1", 150: "rajeshkannan", 149: "voiceover", 148: "socialmedia", 147: "pavithra", 146: "vijay", 145: "murugesan", 144: "ramamoorthy", 143: "vadivel",
    142: "assignment", 141: "prabakaran", 140: "kavya", 139: "manikandan", 138: "vengatesan", 137: "ramar", 136: "ingest", 135: "mcr", 134: "pcr", 133: "anchor", 132: "arulselvam",
    131: "arun", 130: "clement", 129: "sushma", 128: "paari", 123: "saravanakumaran", 122: "nirma", 121: "mmuthu", 120: "kanraj", 119: "yashvanth", 118: "gokulnath", 117: "priya",
    116: "karthick", 115: "muthu", 114: "vignesh", 113: "vetriselvan", 111: "kathirvel", 109: "shalini", 108: "santhanakrishnan", 107: "karthavya", 106: "sriram", 105: "itadmin",
    104: "mageswari", 103: "sathish", 102: "admin",
}
KEYS = {
    "created": ("createdBy", "createdById", "createdByUserId", "createdUser", "createdUserId", "creator", "creatorId", "creatorUserId", "author", "authorId", "owner", "ownerId", "userId"),
    "assigned": ("assignedTo", "assignedToId", "assignedToUserId", "assignedUser", "assignedUserId", "assignee", "assigneeId", "assignedTo_id"),
}
NAME_KEYS = ("username", "userName", "loginName", "login", "name", "fullName", "displayName")
_extra = {"at": 0.0, "map": {}}


def _extra_users():
    """data/blaze_users.json ({"364": "newuser"}), re-read at most once a minute; a missing or broken file is ignored."""
    now = time.time()
    if now - _extra["at"] < 60: return _extra["map"]
    _extra["at"] = now
    try:
        from .. import config
        f = Path(os.environ.get("BLAZE_USERS_FILE") or (config.data_dir() / "blaze_users.json"))
        d = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        _extra["map"] = {str(k): str(v).strip() for k, v in d.items() if isinstance(d, dict) and str(v).strip()}
    except Exception: _extra["map"] = {}
    return _extra["map"]


def username(uid):
    """Blaze user number -> username, or None when the number is not in the list."""
    if uid is None or isinstance(uid, bool): return None
    k = str(uid).strip()
    return _extra_users().get(k) or (USERS.get(int(k)) if k.isdigit() else None)


def _one(v):
    """A field value -> (user id as text or None, username or None). A number or numeric text is an id; a dict is looked into (id / userId, and a name field); other text is taken as the username itself."""
    if isinstance(v, dict):
        uid = next((v[k] for k in ("id", "userId", "userID") if v.get(k) not in (None, "", 0)), None)
        nm = next((str(v[k]).strip() for k in NAME_KEYS if isinstance(v.get(k), str) and v[k].strip()), None)
        return (None if uid is None else str(uid)), nm
    if isinstance(v, bool) or v in (None, "", 0): return None, None
    if isinstance(v, (int, float)): return str(int(v)), None
    t = str(v).strip()
    return (t, None) if t.isdigit() else (None, t or None)


def _find(sc, keys):
    """The first of `keys` found on the story, then on its first version. -> (id, username)."""
    vs = sc.get("versions") or []; v0 = vs[0] if vs and isinstance(vs[0], dict) else {}
    for src in (sc, v0):
        for k in keys:
            if k in src:
                uid, nm = _one(src[k])
                if uid or nm: return uid, nm
    return None, None


def keys_for(kind):
    extra = tuple(x.strip() for x in (os.environ.get("BLAZE_%s_KEYS" % kind.upper()) or "").split(",") if x.strip())
    return extra + tuple(k for k in KEYS[kind] if k not in extra)


def people_of(sc):
    """storyComplete -> {"created_by", "created_by_id", "assigned_to", "assigned_to_id"}. The username comes from the list by id; a username the story carries itself is used when the id is not listed.
    A user the story names that is not in the list shows as "user <id>" so the filter still works and the gap is visible. Empty values are None."""
    out = {}
    for kind, name, idk in (("created", "created_by", "created_by_id"), ("assigned", "assigned_to", "assigned_to_id")):
        uid, nm = _find(sc if isinstance(sc, dict) else {}, keys_for(kind))
        out[idk] = uid; out[name] = username(uid) or nm or (("user %s" % uid) if uid else None)
    return out
