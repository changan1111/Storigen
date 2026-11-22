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
# ---- v10.5.0: VERSION_SUFFIX=on: a file name ending _U01/_U02 (UPDATE: replaces the main clip) or _V01/_V02 (ADD: sits next to the clips already there).
# No schema change: the number stored in clip_ids.version is 1000+n for Un and 2000+n for Vn (an ordinary clip is 1, the old +Version numbers are 2..999).
SUF_RE = re.compile(r"_([UV])(\d+)$", re.I)
def suffix_on(): return os.getenv("VERSION_SUFFIX", "off").strip().lower() in ("on", "1", "yes", "true")
def enc_version(kind, n): return (1000 if kind.upper() == "U" else 2000) + int(n)
def kind_of(version):
    """'U' / 'V' for an encoded version, None for an ordinary clip or an old numbered version."""
    v = int(version or 1); return "U" if 1000 < v < 2000 or 10000 <= v < 20000 else "V" if 2000 < v < 3000 else None      # 10000+: an update OF an added clip (Karth_V01_U02)
def vlabel(version):
    """U02 / V01 for an encoded version, else the plain number."""
    v = int(version or 1)
    if 10000 <= v < 20000: return "V%02d_U%02d" % ((v - 10000) // 100, v % 100)
    k = kind_of(version); return "%s%02d" % (k, v % 1000) if k else str(version)
def un_of(version):
    """The update number of a U clip: 3 for 1003 (Karth_U03) and for 10103 (Karth_V01_U03)."""
    v = int(version or 1); return v % 100 if v >= 10000 else v % 1000
def chain_version(base, kind, n):
    """v10.9.9 (VERSION_SUFFIX=on): Karth_V01_U02 is the 2nd update OF the added clip Karth_V01, its own chain beside Karth_Un. Stored as 10000 + V*100 + U; None when a number is above 99.
    Every other name keeps enc_version (1000+n / 2000+n)."""
    m = kind.upper() == "U" and re.search(r"_V(\d+)$", base or "", re.I)
    if not m: return enc_version(kind, n)
    return 10000 + int(m.group(1)) * 100 + int(n) if int(m.group(1)) < 100 and int(n) < 100 else None
def split_suffix(name):
    """With VERSION_SUFFIX=on: 111126_FIRE_U02 -> ('111126_FIRE', 'U', 2); None when the name has no _U/_V suffix or the switch is off."""
    m = suffix_on() and SUF_RE.search(name or "")
    return None if not m else ((name or "")[:m.start()], m.group(1).upper(), int(m.group(2)))
def name_base(name):
    """The name without its version: 111126_FIRE_V2 -> 111126_FIRE (and _U02 / _V01 with VERSION_SUFFIX=on)."""
    return re.sub(r"_[UV]\d+$" if suffix_on() else r"_V\d+$", "", name or "", flags=re.I)

def display_id(day, seq, slug, version=1, check=None):
    if check is None: check = os.getenv("CHECK_CHAR", "1") == "1"
    num = f"{seq:04d}" + (check_char(day, seq) if check else "")
    base = f"{day:%Y%m%d}_{num}_{make_slug(slug)}"
    return base if version == 1 else f"{base}_{vlabel(version)}" if kind_of(version) else f"{base}_V{version}"
