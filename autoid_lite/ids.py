"""ID format (v9.7, ID_FORMAT=name, the default): DDMMYY_STORY_NAME[_N][_Vn]  e.g. 111126_OPENING_MONTAGE
   (day, month, year, story name; _2, _3 ... only when the same name already has an ID that day; _V2 ... for a new version of the clip).
   ID_FORMAT=legacy keeps the old YYYYMMDD_NNNNC_SLUG[_Vn] (date, daily number, check letter, story slug, optional version).
   IDs issued earlier stay valid in either format."""
from __future__ import annotations
import os, re, datetime as dt

_CHK = "ACDEFGHJKLMNPRTUVWXY"  # 20 letters, no look-alikes (no B/I/O/Q/S/Z)

def make_slug(s, n=40):
    s = re.sub(r"[^A-Z0-9]+", "_", (s or "").upper()).strip("_")[:n].strip("_")
    return s or "STORY"

def broadcast_day(now, day_start="05:00"):
    """'Today' starts at day_start, not midnight."""
    h, m = (int(x) for x in day_start.split(":"))
    return (now - dt.timedelta(hours=h, minutes=m)).date()

def check_char(day, seq):
    """Weighted digit sum -> one letter. Catches single-digit typos and most swaps when an ID is typed."""
    digits = f"{day:%Y%m%d}{seq:04d}"
    return _CHK[sum(int(d) * (i + 1) for i, d in enumerate(digits)) % len(_CHK)]

def id_format(): return "legacy" if os.getenv("ID_FORMAT", "name").strip().lower() == "legacy" else "name"

NAME_MAX = 100

def name_id(day, slug, story_key=None):
    """DDMMYY_STORY_NAME: the story name made file-safe (capitals, digits and single underscores; at most 100 characters).
    A title with no letters or digits that can be used (e.g. only Tamil) takes the Blaze story number instead: DDMMYY_S<number>."""
    base = make_slug(slug, NAME_MAX) if re.search(r"[A-Za-z0-9]", slug or "") else "S" + re.sub(r"[^A-Z0-9]+", "", str(story_key or "").upper())[:20]
    return f"{day:%d%m%y}_{base if base != 'S' else 'STORY'}"
def norm_name(s):
    """Spaces, dashes and underscores are the same thing in a file name: '111126_HL CABINET - PLAN.mxf' and 111126_HL_CABINET_PLAN are one name. Capitals do not matter."""
    return re.sub(r"[^A-Z0-9]+", "_", (s or "").upper()).strip("_")
def name_base(name):
    """The name without its version: 111126_FIRE_V2 -> 111126_FIRE."""
    return re.sub(r"_V\d+$", "", name or "", flags=re.I)

def display_id(day, seq, slug, version=1, check=None):
    if check is None: check = os.getenv("CHECK_CHAR", "1") == "1"
    num = f"{seq:04d}" + (check_char(day, seq) if check else "")
    base = f"{day:%Y%m%d}_{num}_{make_slug(slug)}"
    return base if version == 1 else f"{base}_V{version}"
