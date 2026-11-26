"""v10.14.0: Add media inside the dashboard, right next to Delete: the Quick Support 'Add media' (search a clip Blaze already holds, or type its name to queue it) for the story that is open.
It sends the SAME request as Quick Support (POST /api/support/add, Yes first), so api_support.py is unchanged and the poller applies the same rules. The last test drives the real page in Chromium."""
import json, pathlib, shutil, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pytest
from test_blaze_poll import bp, env, live_env, ready_clip, posts, watch_lines, clips, media, slug
from test_quick_test_button import dry, run
from test_support_menu import add, jobs, job, ready_dry, state, attached

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")

def test_the_page_has_the_button_next_to_delete_and_reuses_the_support_request():
    for t in ("function addWhy(", "function addBtn(", "async function addMedia(", "➕ Add media", "/api/support/media", "/api/support/add", "supPicker(\"Search the clip…\"", "Yes, attach", "Yes, queue it", "Type the correct name and queue it"): assert t in PAGE, t
    assert "pl.append(delBtn(x,c),addBtn(c))" not in PAGE and 'ha.append(el("span","gn",att+" clip"' in PAGE and "addBtn(c)" in PAGE[PAGE.index("function gallery("):PAGE.index("function startPreview(")], "v10.17.0: ONE Add media per story, in the gallery header; each clip card has only Delete"
    assert 'const dl=el("span","delrow");dl.append(delBtn(c,c),addBtn(c));' in PAGE, "beside Delete in the single preview box"
    assert 'if(c.state!=="ATTACHED"&&cfg.support!==false){const ab=addBtn(c)' in PAGE, "and in the story's buttons while there is no attached clip (nothing to delete there)"
    seg = PAGE[PAGE.index("/* ===== v10.14.0: Add media"):PAGE.index("/* ===== v10.12.0: Insights")]
    assert "innerHTML" not in seg and "confirm:true" in seg and seg.count('post("') == 1 and 'post("/api/support/add"' in seg, "one write, the Support add request, always with Yes"
    for why in ("SUPPORT_MENU=0", "Your role is not allowed to attach clips", "no real Blaze story ID"): assert why in seg, why

def test_the_story_the_dashboard_has_carries_what_the_support_request_needs(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); assert not posts(f)
    c = [x for x in clips(s) if x["display_id"] == did][0]; assert c["blaze_rundown_id"] == "34427" and c["blaze_story_id"] == "724921" and c["state"] != "ATTACHED"
    m = s.call("GET", "/api/support/media")[1]["media"]; assert m and m[0]["media_id"] == "1103586" and m[0]["name"], "what the search list shows"
    st, body = s.call("POST", "/api/support/add", {"rundown": c["blaze_rundown_id"], "story": c["blaze_story_id"], "media_id": m[0]["media_id"], "confirm": True}); assert st == 200, "exactly what the dashboard sends"
    assert job(s, body["id"])["by_user"], "recorded with the user's name"
    run(p); assert [x["mosObjectId"] for x in posts(f)] == ["1103586"] and state(s, did) == "ATTACHED"
    st, body = s.call("POST", "/api/support/add", {"rundown": c["blaze_rundown_id"], "story": c["blaze_story_id"], "media_id": m[0]["media_id"]}); assert st == 400, "never without the Yes"

def _browser_ok():
    try: from playwright.sync_api import sync_playwright
    except ImportError: return False
    try:
        with sync_playwright() as pw: pw.chromium.launch().close()
    except Exception: return False
    return True

def test_add_media_works_in_the_real_dashboard(env, tmp_path):
    if not _browser_ok(): pytest.skip("needs playwright with a chromium browser")
    from playwright.sync_api import sync_playwright
    s, f, p, e, did = ready_dry(tmp_path); c = [x for x in clips(s) if x["display_id"] == did][0]; res = []; day = did[:4] + "-" + did[4:6] + "-" + did[6:8]
    def ok(cond, msg): res.append(bool(cond)); assert cond, msg
    with sync_playwright() as pw:
        br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1500, "height": 950}); errs = []; pg.on("pageerror", lambda x: errs.append(str(x)))
        pg.goto("http://127.0.0.1:%d/" % s.port); pg.fill("#u", "admin@x.io"); pg.fill("#p", "adminpass1"); pg.keyboard.press("Enter"); pg.wait_for_selector("#nav", timeout=15000)
        pg.evaluate("d=>{const i=document.querySelector('#day');i.value=d;i.dispatchEvent(new Event('change',{bubbles:true}))}", day); pg.wait_for_timeout(1500)
        title = c.get("slug") or c.get("story_title") or "AUTO"; pg.locator("#list, #rows, body").first.wait_for(); pg.get_by_text(title, exact=False).first.click(); pg.wait_for_timeout(800)
        btn = pg.locator("#detail button.addb").first; ok(btn.count() == 1 and btn.is_enabled(), "the Add media button is on the open story")
        btn.click(); pg.wait_for_selector(".addm [role=dialog], .addm >div", timeout=10000)
        ok("Add media" in pg.locator(".addm").inner_text() and "1103586" in pg.locator(".addm").inner_text(), "the dialog lists the media Blaze holds (MOS 1103586)")
        import os
        if os.environ.get("SHOT"): pg.screenshot(path=os.environ["SHOT"])
        # cancel posts nothing
        pg.locator(".addm button", has_text="Cancel").click(); pg.wait_for_timeout(300); ok(pg.locator(".addm").count() == 0 and not jobs(s), "Cancel closes the dialog and queues nothing")
        # search + pick + Yes
        btn.click(); pg.wait_for_selector(".addm"); pg.fill(".addm input[type=search]", "zzz-no-such-clip"); ok("No match" in pg.locator(".addm").inner_text(), "the search filters the list")
        pg.fill(".addm input[type=search]", ""); pg.locator(".addm .spi").first.click(); ok(pg.locator(".addm button.ok").inner_text() == "Attach clip", "a picked clip says Attach clip")
        pg.locator(".addm button.ok").click(); pg.wait_for_selector("text=Attach this clip to the story?", timeout=5000)
        pg.get_by_role("button", name="No", exact=True).click(); pg.wait_for_timeout(300); ok(not jobs(s) and pg.locator(".addm").count() == 1, "No at the question sends nothing and keeps the dialog")
        pg.locator(".addm button.ok").click(); pg.wait_for_selector("text=Attach this clip to the story?"); pg.get_by_role("button", name="Yes, attach").click(); pg.wait_for_selector(".toast", timeout=8000); pg.wait_for_timeout(400)
        j = jobs(s); ok(len(j) == 1 and j[0]["kind"] == "ADD" and j[0]["state"] == "QUEUED" and j[0]["by_user"] and j[0]["media_id"] == "1103586", "one ADD request is queued with the user's name: %s" % j)
        ok(pg.locator(".addm").count() == 0 and "Attach requested" in pg.locator("#toasts").inner_text(), "the dialog closed and a toast says it was requested")
        run(p); ok([x["mosObjectId"] for x in posts(f)] == ["1103586"] and state(s, did) == "ATTACHED", "the poller attached it (same rules as Quick Support)")
        # attached now: the button sits beside Delete
        pg.reload(); pg.wait_for_selector("#nav"); pg.evaluate("d=>{const i=document.querySelector('#day');i.value=d;i.dispatchEvent(new Event('change',{bubbles:true}))}", day); pg.wait_for_timeout(1500)
        pg.get_by_text(title, exact=False).first.click(); pg.wait_for_timeout(1000)
        ok(pg.locator("#detail .delb").count() >= 1 and pg.locator("#detail .delb + .addb").count() >= 1, "with a clip attached, Add media sits right next to Delete")
        # a typed name that is not valid is explained and the dialog stays open
        pg.locator("#detail .addb").first.click(); pg.wait_for_selector(".addm"); pg.fill(".addm input[type=text]", "bad name!"); pg.locator(".addm button.ok").click(); pg.wait_for_selector("text=Queue this clip?"); pg.get_by_role("button", name="Yes, queue it").click()
        pg.wait_for_selector(".addm .supwarn:not(.hide)", timeout=8000); ok("not valid" in pg.locator(".addm .supwarn:not(.hide)").inner_text() and pg.locator(".addm").count() == 1, "an invalid typed name is explained in the dialog: " + pg.locator(".addm .supwarn:not(.hide)").inner_text()[:80])
        ok(len(jobs(s)) == 1, "nothing extra was queued by the invalid name")
        ok(not errs, "no JavaScript error: %s" % errs[:2]); br.close()
