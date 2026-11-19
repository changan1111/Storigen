"""v10.9.3: Blaze's plain media list holds only the NEWS group. PROGRAMS / PROMOS / ADS files were never in it, so their clips were never found and never attached. The poller now also reads the list once per group."""
import sys, pathlib, urllib.parse as up
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "tests"))
from test_blaze_poll import Fake, Srv, bp, slug, media, clips

def mk(tmp_path, **extra):
    s = Srv(tmp_path, "story_id"); f = Fake()
    cfg = bp.Cfg({"BLAZE_URL": "http://127.0.0.1:%d" % f.port, "BLAZE_SESSION_ID": "SID", "BLAZE_USERNAME": "u", "BLAZE_SHOW_IDS": "34427", "WEB_PORT": str(s.port), "SERVICE_API_KEY": "k" * 20,
                  "BLAZE_MEDIA_SETTLE_SECS": "60", "BLAZE_LEDGER": str(tmp_path / "ledger.db"), "BLAZE_REPORT_DIR": str(tmp_path / "reports"), "BLAZE_IGNORE_TITLES": "BREAK", "BLAZE_MEDIA_RETRY_SECS": "0", "BLAZE_INFO_SECS": "0", **extra})
    return s, f, bp.Poller(cfg)

def grp(m, g): m["objGroup"] = g; return m
def mos(f): return [up.unquote(x[1]) for x in f.log if x[1].startswith("/DataService/mosobjects")]

@pytest.fixture
def env(tmp_path): return mk(tmp_path)

def test_the_default_reads_the_plain_list_and_each_group():
    c = bp.Cfg({"BLAZE_URL": "http://x", "BLAZE_SESSION_ID": "S", "BLAZE_USERNAME": "u"}); assert c.media_groups == ["NEWS", "PROGRAMS", "PROMOS", "ADS"] and c.media_group_key == "objGroup"
    assert bp.Cfg({"BLAZE_URL": "http://x", "BLAZE_SESSION_ID": "S", "BLAZE_USERNAME": "u", "BLAZE_MEDIA_GROUPS": "NONE"}).media_groups == []

def test_a_programs_file_is_found_when_blaze_keeps_it_out_of_the_plain_list(env):
    s, f, p = env; f.group_key = "objGroup"; f.slugs = [slug(1, "PROGRAM VIS CLIP CHECK", 1), slug(2, "NEWS ONE", 2)]; p.cycle(); d = {r["blaze_story_id"]: r["display_id"] for r in clips(s)}
    f.medias = [grp(media(10, d["1"][:14] + "_PROGRAM VIS CLIP CHECK.mxf"), "PROGRAMS"), media(11, d["2"][:14] + "_NEWS ONE.mxf")]
    out = {o["story"]: o for o in p.cycle()}
    assert out["2"]["result"] == "found" and out["1"]["result"] == "found" and "mosObjectId=10" in out["1"]["note"] and "GOING TO ATTACH" in out["1"]["note"]

def test_without_the_groups_the_programs_file_is_not_found_the_old_behaviour(tmp_path):
    s, f, p = mk(tmp_path, BLAZE_MEDIA_GROUPS="NONE"); f.group_key = "objGroup"; f.slugs = [slug(1, "PROGRAM VIS CLIP CHECK", 1)]; p.cycle(); did = clips(s)[0]["display_id"]
    f.medias = [grp(media(10, did[:14] + "_PROGRAM VIS CLIP CHECK.mxf"), "PROGRAMS")]; assert p.cycle()[0]["result"] == "missing"

def test_promos_and_ads_too_and_the_request_names_the_group(env):
    s, f, p = env; f.group_key = "objGroup"; f.slugs = [slug(1, "PROMO A", 1), slug(2, "AD B", 2)]; p.cycle(); d = {r["blaze_story_id"]: r["display_id"] for r in clips(s)}
    f.medias = [grp(media(20, d["1"][:14] + "_PROMO A.mxf"), "PROMOS"), grp(media(21, d["2"][:14] + "_AD B.mxf"), "ADS")]; out = {o["story"]: o["result"] for o in p.cycle()}
    assert out == {"1": "found", "2": "found"}; q = mos(f); assert any('"objGroup":"PROMOS"' in x for x in q) and any('"objGroup":"ADS"' in x for x in q) and any('"objGroup":"PROGRAMS"' in x for x in q)

def test_a_blaze_that_ignores_the_filter_field_is_noticed_and_costs_one_request_per_group(tmp_path, capsys):
    s, f, p = mk(tmp_path); f.group_key = "somethingElse"; f.slugs = [slug(1, "A", 1)]; p.cycle(); did = clips(s)[0]["display_id"]; f.medias = [media(5, did[:14] + "_A.mxf"), grp(media(6, "191126_X.mxf"), "PROGRAMS")]
    n0 = len(mos(f)); out = p.cycle(); assert out[0]["result"] == "found"
    first = len(mos(f)) - n0; assert first <= 1 + 4 * 1, "plain list + at most one request per group"
    n1 = len(mos(f)); p.cycle(); assert len(mos(f)) - n1 == 2, "groups known to be ignored are not asked again: the plain list and NEWS (the one group this fake answers) only"
    txt = capsys.readouterr().out; assert "WARNING: group list(s)" in txt and "BLAZE_MEDIA_GROUP_KEY" in txt

def test_a_group_that_fails_does_not_hide_the_others(env):
    s, f, p = env; f.group_key = "objGroup"; f.slugs = [slug(1, "P", 1)]; p.cycle(); did = clips(s)[0]["display_id"]; f.medias = [grp(media(30, did[:14] + "_P.mxf"), "ADS")]
    real = p.b.get
    def flaky(path, params=None):
        if params and '"objGroup":"PROMOS"' in (params.get("filter") or ""): raise bp.BlazeError(400, "bad group")
        return real(path, params)
    p.b.get = flaky; assert p.cycle()[0]["result"] == "found"

def test_a_title_search_looks_inside_the_groups_when_the_plain_search_finds_nothing(tmp_path):
    s, f, p = mk(tmp_path, BLAZE_MEDIA_MODE="search"); f.group_key = "objGroup"; f.slugs = [slug(1, "PROGRAM VIS", 1)]; p.cycle(); did = clips(s)[0]["display_id"]
    f.medias = [grp(media(40, did[:14] + "_PROGRAM VIS.mxf"), "PROGRAMS")]; assert p.cycle()[0]["result"] == "found"

def test_the_media_command_and_the_new_groups_command_exist():
    src = (root / "tools" / "blaze_poll.py").read_text(encoding="utf-8"); assert '"groups"' in src and "media_pages(c.days" in src
    assert "BLAZE_MEDIA_GROUPS=NEWS,PROGRAMS,PROMOS,ADS" in (root / "autoid.env.example").read_text(encoding="utf-8")
