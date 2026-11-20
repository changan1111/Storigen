"""v10.9.6, VERSION_SUFFIX=on: an update file (_U01) for a story whose plain clip was never attached (the editor saw an error clip and attached nothing) is simply attached:
there is nothing to remove, so nothing is deleted. The same file replaces the plain clip when it IS in the story (that case is in test_version_suffix.py)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_version_suffix import setup, seen, in_story, dels, by_name
from test_blaze_poll import media, clips, posts, set_state

def test_u01_with_no_plain_file_at_all_is_attached_and_nothing_is_deleted(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = base["name_id"]
    seen(s, n + "_U01"); f.medias = [media(1002, n + "_U01.mxf")]; p.cycle()
    assert in_story(f) == [n + "_U01.mxf"] and len(posts(f)) == 1 and not dels(f), (in_story(f), f.log)
    assert by_name(s)[n + "_U01"]["state"] == "ATTACHED"

def test_u01_after_a_plain_clip_that_the_desk_was_told_about_is_attached_and_nothing_is_deleted(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = base["name_id"]
    set_state(s, base["display_id"], "NEEDS_DESK"); f.medias = [media(1001, n + ".mxf")]
    seen(s, n + "_U01"); f.medias = [media(1001, n + ".mxf"), media(1002, n + "_U01.mxf")]; p.cycle()
    assert in_story(f) == [n + "_U01.mxf"] and len(posts(f)) == 1 and not dels(f), (in_story(f), f.log)

def test_u01_with_the_plain_file_in_blaze_but_not_in_the_story_is_attached_and_nothing_is_deleted(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = base["name_id"]
    set_state(s, base["display_id"], "ON_NITRO"); seen(s, n + "_U01"); f.medias = [media(1001, n + ".mxf"), media(1002, n + "_U01.mxf")]; p.cycle()
    assert in_story(f) == [n + "_U01.mxf"] and len(posts(f)) == 1 and not dels(f)


def test_the_plan_says_that_an_update_with_nothing_to_replace_is_attached_and_removes_nothing(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch, BLAZE_ATTACH="dry"); n = base["name_id"]
    seen(s, n + "_U01"); f.medias = [media(1002, n + "_U01.mxf")]; out = p.cycle()
    assert not posts(f) and not dels(f)


def test_the_header_with_the_tabs_is_sticky():
    """v10.9.6: the tab bar stays on screen while the page scrolls."""
    page = (pathlib.Path(__file__).resolve().parent.parent / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    assert ".hdr{position:sticky;top:0;z-index:30}" in page and '"--hh"' in page and "#feed.tab #flist th{top:var(--hh,0px)}" in page
