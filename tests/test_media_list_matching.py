"""v9.7.4: the day's media list is read ONCE per round and every clip is matched in code; a file that is not there (or still converting) is simply looked at again next round."""
import sys, pathlib, urllib.parse as up
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "tests"))
from test_blaze_poll import Fake, bp, slug, media, env, clips      # env: Srv + Fake + Poller (legacy IDs, settle 60 s)

def mos_calls(f): return [up.unquote(x[1]) for x in f.log if x[1].startswith("/DataService/mosobjects")]
def titled(f): return [x for x in mos_calls(f) if '"title"' in x]

def test_n_stories_cost_one_list_request_per_round_not_n_searches(env):
    s, f, p = env; f.slugs = [slug(100 + i, "STORY %d" % i, i + 1) for i in range(30)]; p.cycle(); rows = clips(s); assert len(rows) == 30
    f.medias = [media(5000 + i, r["display_id"][:14] + "_STORY.mxf") for i, r in enumerate(rows[:20])]; before = len(mos_calls(f))
    out = p.cycle(); assert len(mos_calls(f)) - before == 1 and not titled(f), "one request for 30 stories, and it has no title filter"
    assert sum(1 for o in out if o["result"] == "found") == 20 and sum(1 for o in out if o["result"] == "missing") == 10
    assert "assetsPerPage=200" in mos_calls(f)[-1] and "pageNo=1" in mos_calls(f)[-1] and '"mosId":"QuickEdge"' in mos_calls(f)[-1]

def test_a_file_that_is_not_there_yet_is_found_in_the_next_round(env):
    s, f, p = env; f.slugs = [slug(1, "A", 1)]; p.cycle(); did = clips(s)[0]["display_id"]
    out = p.cycle(); assert out[0]["result"] == "missing"                                  # conversion not finished: no file in Blaze's list yet
    f.medias = [media(77, did[:14] + "_A.mxf")]; out = p.cycle(); assert out[0]["result"] == "found" and "mosObjectId=77" in out[0]["note"]
    assert len(titled(f)) == 0

def test_a_file_blaze_is_still_converting_is_not_attached_until_it_is_finished(env):
    s, f, p = env; f.slugs = [slug(1, "A", 1)]; p.cycle(); did = clips(s)[0]["display_id"]
    m = media(88, did[:14] + "_A.mxf", secs_ago=600, ms=0); m["status"] = "NEW"; f.medias = [m]                      # as captured: status NEW, duration 0, listed for 10 minutes already
    out = p.cycle(); assert out[0]["result"] == "converting" and "GOING TO ATTACH" not in out[0]["note"] and "still converting" in out[0]["note"]
    f.medias = [media(88, did[:14] + "_A.mxf")]; out = p.cycle(); assert out[0]["result"] == "found" and "GOING TO ATTACH" in out[0]["note"]       # UPDATED with a duration: finished

def test_a_zero_length_file_counts_as_not_finished_even_when_it_says_updated():
    assert bp.media_pending({"status": "UPDATED", "duration": 0}) and bp.media_pending({"status": "NEW", "duration": 5000}) and not bp.media_pending({"status": "UPDATED", "duration": 5000})

def test_when_the_list_is_cut_short_only_the_clips_not_in_it_are_searched_by_title(env):
    s, f, p = env; f.slugs = [slug(1, "A", 1), slug(2, "B", 2)]; p.cycle(); rows = {r["blaze_story_id"]: r["display_id"] for r in clips(s)}
    f.medias = [media(1, rows["1"][:14] + "_A.mxf")]; f.media_total = 900                  # Blaze says 900 files, only 1 could be read
    out = {o["story"]: o for o in p.cycle()}; assert out["1"]["result"] == "found"
    k1, k2 = bp.clip_key(rows["1"], 1)[0], bp.clip_key(rows["2"], 1)[0]            # the poller's own search keys, whatever CHECK_CHAR other tests set
    t = titled(f); assert len(t) == 1 and '"title":"%s"' % k2 in t[0] and k1 not in " ".join(t), "A was in the list: no search. B may be beyond it: searched by title"

def test_when_the_list_cannot_be_read_every_clip_falls_back_to_the_title_search(env, capsys):
    s, f, p = env; f.slugs = [slug(1, "A", 1)]; p.cycle(); did = clips(s)[0]["display_id"]; f.medias = [media(5, did[:14] + "_A.mxf")]; f.fail_list = True
    out = p.cycle(); assert out[0]["result"] == "found" and titled(f)
    assert "media list could not be read" in capsys.readouterr().out
    f.fail_list = False; n = len(titled(f)); p.cycle(); assert len(titled(f)) == n and p.list_err is False

def test_search_mode_is_still_there(env):
    s, f, p = env; p.c.media_mode = "search"; f.slugs = [slug(1, "A", 1)]; p.cycle(); p.cycle(); assert titled(f)
    assert bp.Cfg({"BLAZE_SHOW_IDS": "1", "BLAZE_MEDIA_MODE": "SEARCH"}).media_mode == "search" and bp.Cfg({"BLAZE_SHOW_IDS": "1"}).media_mode == "list" and bp.Cfg({"BLAZE_SHOW_IDS": "1", "BLAZE_MEDIA_MODE": "x"}).media_mode == "list"

def test_media_pages_reads_page_after_page_until_the_total_is_in():
    c = bp.Cfg({"BLAZE_SHOW_IDS": "1", "BLAZE_MEDIA_GROUPS": "NONE"}); b = bp.Blaze(c); pages = {1: [{"id": 1}, {"id": 2}], 2: [{"id": 3}, {"id": 4}], 3: [{"id": 5}]}; asked = []
    def get(path, params=None): asked.append(params["pageNo"]); return {"results": {"medias": pages.get(params["pageNo"], []), "totalResults": 5}}
    b.get = get; ms, total, complete = b.media_pages(2, per_page=2, max_pages=5)
    assert [m["id"] for m in ms] == [1, 2, 3, 4, 5] and total == 5 and complete and asked == [1, 2, 3]
    asked.clear(); ms, total, complete = b.media_pages(2, per_page=2, max_pages=2); assert len(ms) == 4 and not complete and asked == [1, 2]       # capped: reported as incomplete

def test_the_index_matches_exactly_like_the_plain_search():
    ms = [{"id": 1, "title": "121126_FIRE_ON_BEACH.mxf", "status": "UPDATED", "duration": 9000}, {"id": 2, "title": "121126_FIRE_ON_BEACH_V2.mxf", "status": "UPDATED", "duration": 9000},
          {"id": 3, "title": "121126 TWO WORDS.mxf", "status": "UPDATED", "duration": 9000}, {"id": 4, "title": "121126_TWO_WORDS.mxf", "status": "UPDATED", "duration": 9000}, {"id": 5, "title": "junk"}]
    idx = bp.index_media(ms)
    for t in ("121126_FIRE_ON_BEACH.mxf", "121126_FIRE_ON_BEACH_V2.mxf", "121126_TWO_WORDS.mxf", "121126_NOTHING.mxf"):
        k = bp.media_key(t); a, b = bp.find_media(ms, k, 0), bp.find_indexed(idx, k, 0)
        assert a[0] == b[0] and (a[1] == b[1] if a[0] != "ambiguous" else {x["id"] for x in a[1]} == {x["id"] for x in b[1]})
    assert bp.find_indexed(idx, bp.media_key("121126_TWO_WORDS.mxf"), 0)[0] == "ambiguous"      # a space and an underscore are the same name: two files, the desk must choose
