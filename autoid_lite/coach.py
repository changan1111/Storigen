"""v10.12.0 Name coach. A pure function (no database, no network): the editor types the file name he is about to export, and the coach says whether the system will accept it,
what it would do (replace / add), and - if it is wrong - the exact name to use and WHY, in plain words. It only reads the plan that api_bot.plan_names already works out.
Rule book: DDMMYY_SLUG is the main clip; _U01, _U02 ... replace it; _V01, _V02 ... are added next to it; _V01_U01 ... replace the added clip V01. Two digits, next number only, 01-99."""
from __future__ import annotations
import re

MAXN = 99
EXTS = (".mxf", ".mov", ".mp4")
TAIL_RE = re.compile(r"((?:_[A-Za-z]\d*)+)$")                 # the trailing _V01 / _U2 / _V01_U02 pieces (any letter, to give a clear message)
PIECE_RE = re.compile(r"_([A-Za-z])(\d*)")


LAB_PAREN = re.compile(r"(_[UVuv]\d+)[ _\-]*\(([^()]*)\)", re.I)                          # v11.0.0: 111126_FIRE_V02 (byte) / (minibyte) / (tag): a label for people, ignored by the system
LAB_WORD = re.compile(r"(_[UVuv]\d+)[ _\-]+(mini[ _\-]?byte|byte|tag)$", re.I)


def _norm(s): return re.sub(r"[^A-Z0-9]+", "_", (s or "").upper()).strip("_")


def _result(ok, kind, messages, expected=None, fix=None, does=None):
    return {"ok": bool(ok), "kind": kind, "messages": messages, "expected": expected, "fix": fix, "does": does}


def check_name(plan, base, typed, suffix_on=True):
    res = _check_name(plan, base, typed, suffix_on); res["label"] = (LAB_PAREN.search(typed or "") or LAB_WORD.search((typed or "").strip()) or [None, None, ""])[2] if res else ""; return res


def _check_name(plan, base, typed, suffix_on=True):
    """plan = api_bot.plan_names(...) of the story; base = the story's clip name (DDMMYY_SLUG); typed = what the editor typed or pasted."""
    name = (typed or "").strip()
    for e in EXTS:
        if name.lower().endswith(e): name = name[:-len(e)]; break
    if not name: return _result(False, "empty", ["Type or paste the file name first."])
    notes, label = [], ""
    lm = LAB_PAREN.search(name) or LAB_WORD.search(name)
    if lm: label = lm.group(2).strip(); name = LAB_WORD.sub(r"\1", LAB_PAREN.sub(r"\1", name)).strip()
    if label: notes.append("The label (%s) after the version is only for people: the system ignores it." % label)
    if " " in name: notes.append("The name has spaces. Clip names use underscores (_) instead of spaces.")
    m = TAIL_RE.search(name)
    tail = m.group(1) if m else ""
    stem = name[:len(name) - len(tail)] if tail else name
    pieces = [(a.upper(), b, a) for a, b in PIECE_RE.findall(tail)]
    fix_base = base
    if _norm(stem) != _norm(base):
        why = ["The name does not start with the story's clip name. It must start with: %s" % base]
        d, b = stem[:6], base[:6]
        if re.fullmatch(r"\d{6}", d or "") and d != b: why.append("The date part is %s but this story's date part is %s (DDMMYY)." % (d, b))
        elif not re.fullmatch(r"\d{6}", d or ""): why.append("A clip name begins with the date as six digits (DDMMYY).")
        else: why.append("The story part does not match. Copy it exactly from the Storigen row: the date and the file-safe story name.")
        return _result(False, "wrong_base", why, expected=base, fix=(base + tail) if tail else base)
    if not pieces:
        if plan.get("main"):
            cur = plan["main"].get("current")
            nxt = plan["main"].get("next_u_name")
            return _result(False, "exists", ["%s is already the main clip of this story%s." % (name, " (" + cur + ")" if cur and _norm(cur) != _norm(name) else ""),
                                              "To replace it, export %s. To add one more clip beside it, export %s." % (nxt or "(no update numbers left)", plan.get("next_v") or "(no added-clip numbers left)")],
                           expected=nxt, fix=nxt)
        return _result(True, "main", ["This is the plain clip name of the story: the first clip."] + notes, expected=base, does="first clip")
    for letter, digits, raw in pieces:
        if letter not in "UV": return _result(False, "invalid", ["_%s%s is not a rule-book ending. Only _U (update) and _V (added clip) are used." % (raw, digits)], expected=None)
        if not digits: return _result(False, "invalid", ["_%s needs a number: _%s01." % (letter, letter)], expected=None, fix=None)
        if len(digits) != 2: return _result(False, "digits", ["Use two digits: _%s%02d, not _%s%s." % (letter, int(digits), letter, digits)], fix=_rebuild(base, [(L, int(d)) for L, d, _ in pieces]))
        if int(digits) < 1: return _result(False, "invalid", ["Numbers start at 01: _%s01." % letter], fix=None)
    seq = [(L, int(d)) for L, d, _ in pieces]
    if any(raw != raw.upper() for _, _, raw in pieces): notes.append("Tip: write the letters in capitals (_%s) as in the rule book." % "".join(L + "%02d" % n for L, n in seq))
    if len(seq) > 2 or (len(seq) == 2 and seq[0][0] != "V") or (len(seq) == 2 and seq[1][0] != "U"):
        return _result(False, "invalid", ["The ending %s is not allowed. The only shapes are _Unn (replace the main clip), _Vnn (add a clip) and _Vnn_Unn (replace an added clip)." % "".join("_%s%02d" % p for p in seq)])
    if not suffix_on: notes.append("VERSION_SUFFIX is off on this server, so a name with _U or _V will not be picked up by itself. Ask the desk first.")
    main, added = plan.get("main"), {int(a["key"][1:]): a for a in plan.get("added", [])}
    if len(seq) == 1 and seq[0][0] == "U":
        n = seq[0][1]
        if not main: return _result(False, "no_main", ["This story has no main clip in the system yet, so there is nothing to update. Export %s first." % base], expected=base, fix=base)
        nxt = main.get("next_u")
        if nxt is None: return _result(False, "full", ["The update numbers of the main clip are used up (99). Ask the desk."])
        if n < nxt: return _result(False, "used", ["_U%02d is already used. The system keeps the update chain in order." % n, "The next update is %s." % main["next_u_name"]], expected=main["next_u_name"], fix=main["next_u_name"])
        if n > nxt: return _result(False, "skips", ["This skips a number. The system refuses a gap: U%02d must exist before U%02d." % (nxt, n), "Use %s." % main["next_u_name"]], expected=main["next_u_name"], fix=main["next_u_name"])
        return _result(True, "update", ["OK. This REPLACES the main clip. Clips added with _V stay."] + notes, expected=main["next_u_name"], does="replaces the main clip")
    if len(seq) == 1:      # _Vnn
        n, nxt = seq[0][1], plan.get("next_v_no")
        if nxt is None: return _result(False, "full", ["This story already has 99 added clips. Ask the desk."])
        if n < nxt: return _result(False, "used", ["_V%02d already exists in this story." % n, "To add another clip use %s. To replace V%02d use %s_V%02d_U%02d." % (plan["next_v"], n, base, n, (added.get(n) or {}).get("next_u") or 1)], expected=plan["next_v"], fix=plan["next_v"])
        if n > nxt: return _result(False, "skips", ["This skips a number. V%02d must be added before V%02d." % (nxt, n), "Use %s." % plan["next_v"]], expected=plan["next_v"], fix=plan["next_v"])
        return _result(True, "append", ["OK. This ADDS a clip next to the ones already there. Nothing is replaced.", "Do not use _V for a correction: the old clip would stay. To correct a clip use _U."] + notes, expected=plan["next_v"], does="adds a clip")
    (_, vn), (_, un) = seq      # _Vnn_Unn
    slot = added.get(vn)
    if not slot:
        have = ", ".join("V%02d" % k for k in sorted(added)) or "none"
        return _result(False, "no_v", ["V%02d does not exist in this story yet (added clips: %s)." % (vn, have), "Add it first with %s." % (plan.get("next_v") or "_V01")], expected=plan.get("next_v"), fix=plan.get("next_v"))
    nxt = slot.get("next_u")
    if nxt is None: return _result(False, "full", ["The update numbers of V%02d are used up (99). Ask the desk." % vn])
    if un < nxt: return _result(False, "used", ["_V%02d_U%02d is already used." % (vn, un), "The next update of V%02d is %s." % (vn, slot["next_u_name"])], expected=slot["next_u_name"], fix=slot["next_u_name"])
    if un > nxt: return _result(False, "skips", ["This skips a number. V%02d_U%02d must exist first." % (vn, nxt), "Use %s." % slot["next_u_name"]], expected=slot["next_u_name"], fix=slot["next_u_name"])
    return _result(True, "update_added", ["OK. This REPLACES only the added clip V%02d. Every other clip stays." % vn] + notes, expected=slot["next_u_name"], does="replaces V%02d only" % vn)


def _rebuild(base, seq): return base + "".join("_%s%02d" % p for p in seq)
