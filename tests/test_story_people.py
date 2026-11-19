"""v10.9.0: who created a story and who it is assigned to (storyComplete, by Blaze user number -> username), shown on the dashboard and the Ready feed, with a username filter on both and a bulletin filter on the feed."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from test_blaze_poll import bp, env, live_env, ready_clip, posts, clips, slug       # noqa: F401  (fixtures)
from test_story_scripts import rows, row, spy, sent
from test_ready_feed import story_set, media_found, feed, sql                              # noqa: F401
from test_server import sid                                                                # noqa: F401
from autoid_lite.blaze import people as pe

def test_the_user_list_has_every_blaze_user_and_resolves_numbers():
    assert pe.username(363) == "venkat" and pe.username("102") == "admin" and pe.username("206") == "THIRUMALAIKUMAR" and pe.username(999999) is None and pe.username(None) is None
    assert len(pe.USERS) == 101 and len(set(pe.USERS.values())) == 101

def test_the_story_fields_are_understood_in_every_shape():
    f = lambda sc: pe.people_of(sc)
    assert f({"createdBy": 363, "assignedTo": 358}) == {"created_by_id": "363", "created_by": "venkat", "assigned_to_id": "358", "assigned_to": "ramachandran"}
    r = f({"createdBy": {"id": 355, "username": "other"}, "assignedTo": {"id": 777, "userName": "newbie"}})
    assert (r["created_by"], r["assigned_to"], r["assigned_to_id"]) == ("sowmiya", "newbie", "777")       # a listed number wins; an unlisted one keeps the name the story carries
    assert f({"createdBy": "364"})["created_by"] == "user 364"                                           # unknown number: visible, filterable, and a hint to add it to data/blaze_users.json
    assert f({"createdBy": "abarna"})["created_by"] == "abarna"                                         # a plain username is kept
    assert f({"versions": [{"createdBy": 333, "assignedToId": 311}]}) == {"created_by_id": "333", "created_by": "abarna", "assigned_to_id": "311", "assigned_to": "ganesan"}
    assert f({"title": "x"}) == {"created_by_id": None, "created_by": None, "assigned_to_id": None, "assigned_to": None} and f(None)["created_by"] is None

def test_field_names_can_be_set_in_the_env_file(monkeypatch):
    monkeypatch.setenv("BLAZE_CREATED_KEYS", "reporterId, madeBy")
    assert pe.people_of({"madeBy": 354})["created_by"] == "deepakkumar" and pe.people_of({"reporterId": 352, "createdBy": 363})["created_by"] == "thennarasan"

def test_the_user_file_adds_and_overrides_users(tmp_path, monkeypatch):
    f = tmp_path / "u.json"; f.write_text('{"364": "newuser", "363": "venkat2"}', encoding="utf-8"); monkeypatch.setenv("BLAZE_USERS_FILE", str(f)); pe._extra["at"] = 0
    assert pe.username(364) == "newuser" and pe.username(363) == "venkat2" and pe.username(355) == "sowmiya"
    f.write_text("{broken", encoding="utf-8"); pe._extra["at"] = 0; assert pe.username(364) is None and pe.username(363) == "venkat"      # a broken file is ignored

def test_the_poller_sends_the_people_and_the_dashboard_filters_by_username(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "AUTO ID 05", 14), slug(724905, "AUTO ID 03", 13), slug(724900, "AUTO ID 01", 12)]
    f.story_extra["724921"] = {"createdBy": 363, "assignedTo": 358}; f.story_extra["724905"] = {"createdBy": 358, "assignedTo": 333}; seen = spy(p)
    p.cycle(); a, b, c = row(s, 724921), row(s, 724905), row(s, 724900)
    assert (a["created_by"], a["assigned_to"]) == ("venkat", "ramachandran") and (b["created_by"], b["assigned_to"]) == ("ramachandran", "abarna") and c["created_by"] is None and c["assigned_to"] is None
    d = s.call("GET", "/api/clips")[1]; assert [(u["name"], u["created"], u["assigned"]) for u in d["users"]] == [("abarna", 0, 1), ("ramachandran", 1, 1), ("venkat", 1, 0)]
    ids = lambda q: sorted(x["blaze_story_id"] for x in s.call("GET", "/api/clips" + q)[1]["clips"])
    assert ids("?user=venkat") == ["724921"] and ids("?user=VENKAT") == ["724921"]                       # any letter case
    assert ids("?user=ramachandran") == ["724905", "724921"]                                            # creator OR assigned-to
    assert ids("?user=abarna") == ["724905"] and ids("?user=nobody") == [] and ids("?q=abarna") == ["724905"] and len(ids("")) == 3
    cnt = s.call("GET", "/api/clips?user=venkat&per_page=50")[1]; assert cnt["total"] == 1 and cnt["day_counts"]["all"] == 3 and sum(b["n"] for b in cnt["bulletins"]) == 1
    assert row(s, 724921)["created_by"] == "venkat" and s.call("GET", "/api/clips/%d/history" % a["id"])[1]["clip"]["assigned_to"] == "ramachandran"
    n = len(sent(seen)); p.cycle(); assert len(sent(seen)) == n                                         # nothing changed: nothing sent again

def test_a_reassignment_in_blaze_reaches_the_dashboard_and_a_missing_field_never_wipes_it(env):
    s, f, p = env; assert s.login()[0] == 200; f.slugs = [slug(724921, "AUTO ID 05", 14)]; f.story_extra["724921"] = {"createdBy": 363, "assignedTo": 358}
    p.cycle(); assert row(s, 724921)["assigned_to"] == "ramachandran"
    p.script_at.clear(); f.story_extra["724921"] = {"createdBy": 363, "assignedTo": 355}; p.cycle(); assert row(s, 724921)["assigned_to"] == "sowmiya" and row(s, 724921)["created_by"] == "venkat"
    p.script_at.clear(); f.story_extra["724921"] = {}; p.cycle(); assert (row(s, 724921)["created_by"], row(s, 724921)["assigned_to"]) == ("venkat", "sowmiya")

def test_the_service_call_takes_the_people_and_ignores_junk(sid):
    c = story_set(sid, 2)
    st, r = sid.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "700000", "online": "o", "anchor": "a", "created_by": "venkat", "created_by_id": 363, "assigned_to": "x" * 300}]})
    assert st == 200 and r["ok"]; x = next(i for i in sid.call("GET", "/api/clips")[1]["clips"] if i["blaze_story_id"] == "700000")
    assert x["created_by"] == "venkat" and len(x["assigned_to"]) == 80
    assert sid.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "700000", "online": "o", "anchor": "a"}]})[0] == 200      # an older poller (no people): nothing is wiped
    assert next(i for i in sid.call("GET", "/api/clips")[1]["clips"] if i["blaze_story_id"] == "700000")["created_by"] == "venkat"

def test_the_csv_has_the_two_columns_and_follows_the_username_filter(sid):
    import urllib.request
    story_set(sid, 2); sid.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "700001", "online": "", "anchor": "", "created_by": "abarna", "assigned_to": "yogesh"}]})
    get = lambda q: urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/clips.csv%s" % (sid.port, q), headers={"Cookie": sid.cookie}), timeout=10).read().decode("utf-8-sig")
    t = get("?user=yogesh"); assert t.splitlines()[0].endswith("Created by,Assigned to") and "abarna,yogesh" in t and "700000" not in t and "700001" in t
    assert "700000" in get("")

def test_the_feed_filters_by_bulletin_and_username_and_lists_the_choices(sid):
    c = story_set(sid, 3)
    sid.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "R2", "rundown_name": "Noon Bulletin", "stories": [{"blaze_story_id": "800000", "slug": "NOON 0", "story_title": "Noon story"}]})
    n = {x["blaze_story_id"]: x for x in sid.call("GET", "/api/clips")[1]["clips"]}
    for k in ("700000", "700001", "800000"): media_found(sid, n[k]["display_id"], "MOS-" + k, k + ".mxf")
    sid.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "700000", "online": "", "anchor": "", "created_by": "venkat", "assigned_to": "abarna"}, {"blaze_story_id": "700001", "online": "", "anchor": "", "created_by": "abarna"},
                                                  {"blaze_story_id": "800000", "online": "", "anchor": "", "created_by": "venkat", "assigned_to": "venkat"}]})
    ids = lambda q: sorted(i["blaze_story_id"] for i in feed(sid, q)["items"])
    assert ids("") == ["700000", "700001", "800000"] and ids("?bulletin=R1") == ["700000", "700001"] and ids("?bulletin=R2") == ["800000"] and ids("?bulletin=zzz") == []
    assert ids("?user=venkat") == ["700000", "800000"] and ids("?user=abarna") == ["700000", "700001"] and ids("?user=Venkat&bulletin=R1") == ["700000"] and ids("?q=abarna") == ["700000", "700001"]
    f = feed(sid, "?user=venkat&bulletin=R2"); i = f["items"][0]; assert (i["created_by"], i["assigned_to"]) == ("venkat", "venkat") and f["counts"]["all"] == 3         # counts stay for the whole day
    assert [(b["id"], b["name"], b["n"]) for b in f["bulletins"]] == [("R1", "Morning Bulletin", 2), ("R2", "Noon Bulletin", 1)] and [u["name"] for u in f["users"]] == ["abarna", "venkat"]

def test_the_page_has_the_filters_and_columns():
    t = (pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    for needle in ('id="userf"', 'id="fbul"', 'id="fusr"', 'qs.set("user",userf)', 'qs.set("bulletin",feed.fbul)', 'qs.set("user",feed.fusr)', '["Created by","Assigned to"]'[:0] or '"Created by"', '"Assigned to"', "function renderUsers"):
        assert needle in t, needle

def test_several_usernames_can_be_chosen_on_the_dashboard_and_the_feed(env, sid):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "AUTO ID 05", 14), slug(724905, "AUTO ID 03", 13), slug(724900, "AUTO ID 01", 12)]
    f.story_extra["724921"] = {"createdBy": 363, "assignedTo": 358}; f.story_extra["724905"] = {"createdBy": 333}; f.story_extra["724900"] = {"createdBy": 311, "assignedTo": 310}; p.cycle()
    ids = lambda q: sorted(x["blaze_story_id"] for x in s.call("GET", "/api/clips" + q)[1]["clips"])
    assert ids("?user=venkat,abarna") == ["724905", "724921"] and ids("?user=venkat%2C%20ABARNA%2C") == ["724905", "724921"]       # any of them, any letter case, spaces and a trailing comma are ignored
    assert ids("?user=yogesh,nobody") == ["724900"] and ids("?user=,") == ids("") and len(ids("?user=" + ",".join("u%d" % i for i in range(100)))) == 0
    assert ids("?user=venkat,ramachandran") == ["724921"]                                                  # one story, two of its people chosen: listed once
    t = s.call("GET", "/api/clips?user=venkat,yogesh&per_page=50")[1]; assert t["total"] == 2 and t["day_counts"]["all"] == 3
    c = story_set(sid, 3); n = {x["blaze_story_id"]: x for x in sid.call("GET", "/api/clips")[1]["clips"]}
    for k in ("700000", "700001", "700002"): media_found(sid, n[k]["display_id"], "MOS-" + k, k + ".mxf")
    sid.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "700000", "online": "", "anchor": "", "created_by": "venkat"}, {"blaze_story_id": "700001", "online": "", "anchor": "", "assigned_to": "abarna"}, {"blaze_story_id": "700002", "online": "", "anchor": "", "created_by": "yogesh"}]})
    fi = lambda q: sorted(i["blaze_story_id"] for i in feed(sid, q)["items"])
    assert fi("?user=venkat,abarna") == ["700000", "700001"] and fi("?user=venkat,abarna,yogesh") == ["700000", "700001", "700002"] and fi("?user=abarna,yogesh&bulletin=R1") == ["700001", "700002"]

def test_the_page_uses_a_tick_list_for_users():
    t = (pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    assert '<details id="userf" class="upick"' in t and '<details id="fusr" class="upick"' in t and 'input:checked' in t and 'c.type="checkbox"' in t and 'id="userf" aria-label' not in t

def test_the_user_list_has_a_type_to_search_box():
    t = (pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    assert t.count('class="ups"') == 2 and "function upFilter" in t and "No user matches" in t and 'e.key==="Enter"' in t and 'details.upick[open]' in t
