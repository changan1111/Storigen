"""Review fixes after the v9.8.1 field test: hand-typed report dates, readable ATTACHMENT CHANGED lines."""
import pathlib, sys, datetime as dt
import pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT))
import blaze_poll as bp

def test_982_01_report_day_accepts_the_formats_people_type():
    d = dt.date(2026, 11, 13)
    assert bp.parse_day("20261113") == bp.parse_day("2026-11-13") == bp.parse_day("13112026") == bp.parse_day("13-11-2026") == d

def test_982_02_bad_day_is_one_clear_line_not_a_traceback():
    with pytest.raises(SystemExit) as e: bp.parse_day("13/11")
    assert "not a date" in str(e.value)

def test_982_03_attachment_changed_line_shows_what_changed():
    seen = []; p = bp.Poller.__new__(bp.Poller); p.event = lambda kind, txt, *a, **k: seen.append((kind, txt)); p.where_story = lambda sid: "story " + sid
    p.store = type("S", (), {"log": lambda *a, **k: None})(); p.story_shows = {}; p.server_day = lambda: dt.date(2026, 11, 13)
    old = {"title": "X.mxf", "mos": "1", "id": "9", "dur": 5000, "status": "READY"}; new = dict(old, status="ON AIR")
    bp.Poller.attach_event(p, "7", {"kind": "ATTACH_CHANGED", "old": old, "new": new}, 0.0)
    assert "status READY" in seen[0][1] and "status ON AIR" in seen[0][1]
