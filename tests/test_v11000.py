"""v11.0.0: (byte)/(minibyte)/(tag) label after the version is ignored; filter headers go green; the chat asks byte or tag."""
import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from autoid_lite import ids, coach
from autoid_lite.blaze import keys
from autoid_lite.api_blazeclips import parse_clip_name
ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")

@pytest.fixture(autouse=True)
def on(monkeypatch): monkeypatch.setenv("VERSION_SUFFIX", "on")

@pytest.mark.parametrize("raw,clean", [("111126_FIRE_V01 (byte)", "111126_FIRE_V01"), ("111126_FIRE_V02 (minibyte)", "111126_FIRE_V02"), ("111126_FIRE_V01_U01 (tag)", "111126_FIRE_V01_U01"),
    ("111126_FIRE_V01 (byte)_U01", "111126_FIRE_V01_U01"), ("111126_FIRE_V01 byte", "111126_FIRE_V01"), ("111126_FIRE_U02 (byte)", "111126_FIRE_U02"), ("111126_BYTE", "111126_BYTE"), ("111126_FIRE_V01", "111126_FIRE_V01")])
def test_label_is_dropped_only_after_a_version(raw, clean): assert ids.strip_label(raw) == clean

def test_split_and_keys_ignore_the_label():
    assert ids.split_suffix(ids.norm_name("111126_FIRE_V02 (byte)")) == ("111126_FIRE", "V", 2)
    assert keys.ver_split("111126_FIRE_V01 (minibyte)") == ("111126_FIRE", 2001) and keys.media_key("111126_FIRE_V01 (byte).mxf") == keys.media_key("111126_FIRE_V01.mxf")
    assert parse_clip_name("111126_FIRE_V01_U01 (tag).mxf") == parse_clip_name("111126_FIRE_V01_U01.mxf") == ("111126_FIRE", 10101)

def test_label_is_ignored_when_the_switch_is_off(monkeypatch):
    monkeypatch.setenv("VERSION_SUFFIX", "off"); assert ids.strip_label("111126_FIRE_V01 (byte)") == "111126_FIRE_V01 (byte)"

def test_watcher_parse_name():
    import importlib, autoid_lite.watcher as w; importlib.reload(w)
    assert w.parse_name("111126_FIRE_V01 (byte).mxf") == w.parse_name("111126_FIRE_V01.mxf") == ("NAME", "111126_FIRE_V01", 2001, None)
    assert w.parse_name("111126_FIRE_V01_U01 (minibyte).mxf")[1:3] == ("111126_FIRE_V01_U01", 1001)

def test_coach_accepts_labelled_names():
    plan = {"main": {"current": "111126_FIRE", "next_u": 1, "next_u_name": "111126_FIRE_U01"}, "added": [{"key": "V01", "next_u": 1, "next_u_name": "111126_FIRE_V01_U01"}], "next_v": "111126_FIRE_V02", "next_v_no": 2}
    r = coach.check_name(plan, "111126_FIRE", "111126_FIRE_V02 (byte).mxf"); assert r["ok"] and r["kind"] == "append" and r["label"] == "byte"
    assert coach.check_name(plan, "111126_FIRE", "111126_FIRE_V03 (byte)")["kind"] == "skips"          # the number is still validated
    assert coach.check_name(plan, "111126_FIRE", "111126_FIRE_V01 (byte)_U01")["kind"] == "update_added"

def test_page_has_green_filters_chip_and_byte_or_tag_question():
    assert "function paintFilters" in PAGE and "paintFilters();readyNotice" in PAGE and ".fon" in PAGE and 'id="fchip"' in PAGE
    assert "Is it a byte or a tag (mini byte)?" in PAGE and "botAppendName" in PAGE and '(minibyte)' in PAGE
