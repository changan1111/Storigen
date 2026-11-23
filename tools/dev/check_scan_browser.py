"""v10.13.0: the browser scan, run for real in Chromium (Playwright) against a live Storigen server and the REAL Play-preview stream.
The detector is a stand-in (a tiny fake ONNX Runtime that reports a 'breast_exposed' box on every frame whose picture is mostly red), because no real model ships with Storigen.
So this proves everything around the model: asset serving, loading, frame grabbing, the letterbox maths, decoding + NMS, the sharpness measure, flags with pictures, the 'not clearance' wording,
the not-installed state, and that nothing is stored. It does NOT prove that a real model finds real content: try your model on known clips (docs/SCAN_SETUP.md).
usage: python3 tools/dev/check_scan_browser.py   (needs ffmpeg, playwright + chromium)"""
import json, os, pathlib, shutil, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests", ROOT / "tools"): sys.path.insert(0, str(p))
FAKE_ORT = """window.ort={env:{wasm:{}},Tensor:function(type,data,dims){this.type=type;this.data=data;this.dims=dims},
InferenceSession:{create:async function(url){window.__model_url=url;return{inputNames:['images'],outputNames:['output0'],run:async function(feeds){
 const f=feeds.images.data,N=320*320;let r=0;for(let i=0;i<N;i++)r+=f[i];r/=N;const o=new Float32Array(6*10);
 if(r>0.45){o[0]=160;o[10]=160;o[20]=120;o[30]=120;o[50]=0.9;o[1]=160;o[11]=160;o[21]=118;o[31]=118;o[51]=0.8}
 return{output0:{data:o,dims:[1,6,10]}}}}}}};"""
MANIFEST = {"name": "STAND-IN", "model": "fake.onnx", "input": 320, "labels": ["FACE", "BREAST_EXPOSED"], "flag": ["BREAST_EXPOSED"], "threshold": 0.35, "nms_iou": 0.45, "blur_var": 60, "bgr": False}

def make_clip(path):
    ff = shutil.which("ffmpeg")
    cmd = [ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:r=25:d=3,format=yuv420p", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=25:d=3,noise=alls=90:allf=t+u,format=yuv420p",
           "-f", "lavfi", "-i", "color=c=red:s=640x360:r=25:d=3,format=yuv420p", "-f", "lavfi", "-i", "sine=duration=9", "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a",
           "-c:v", "mpeg2video", "-q:v", "2", "-c:a", "pcm_s16le", "-ar", "48000", "-f", "mxf", str(path)]
    subprocess.run(cmd, check=True)

def run(report=print):
    from playwright.sync_api import sync_playwright
    from test_preview import clip_on_nitro
    from test_server import Srv
    tmp = pathlib.Path(tempfile.mkdtemp()); nit = tmp / "ONAIR" / "Nov-26" / "22-11-2026"; nit.mkdir(parents=True); clip = nit / "221126_SCAN.mxf"; make_clip(clip)
    scan = tmp / "scan"; os.environ["NITRO_DIR"] = str(tmp / "ONAIR"); os.environ["SCAN_MODEL_DIR"] = str(scan); os.environ.pop("GROQ_API_KEY", None)
    s = Srv(tmp, "placeholder"); assert s.login()[0] == 200; c = clip_on_nitro(s, clip, "Scan story"); base = "http://127.0.0.1:%d/" % s.port; res = []
    def ok(cond, msg): res.append(bool(cond)); report(("PASS " if cond else "FAIL ") + msg)
    with sync_playwright() as pw:
        br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1500, "height": 950}); errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append("console." + m.type + ": " + m.text[:200]) if m.type in ("error", "warning") and "401" not in m.text else None); pg.on("dialog", lambda d: d.accept())
        # ---- A. pure functions in the page
        pg.goto(base); pg.fill("#u", "admin@x.io"); pg.fill("#p", "adminpass1"); pg.keyboard.press("Enter"); pg.wait_for_selector("#nav", timeout=15000); pg.wait_for_timeout(800)
        pure = pg.evaluate("""()=>{const man={labels:['FACE','BREAST_EXPOSED','BUTT_EXPOSED'],flag:['BREAST_EXPOSED','BUTT_EXPOSED'],threshold:0.35,nms_iou:0.45},N=12,cf=new Float32Array(7*N),g=scanLetterbox(640,360,320);
          const put=(i,cx,cy,w,h,sc)=>{cf[0*N+i]=cx;cf[1*N+i]=cy;cf[2*N+i]=w;cf[3*N+i]=h;cf[4*N+i]=sc[0];cf[5*N+i]=sc[1];cf[6*N+i]=sc[2]};
          put(0,160,160,80,80,[0.9,0.8,0.1]);put(1,162,161,80,80,[0.1,0.6,0.1]);put(2,240,200,40,40,[0.1,0.1,0.9]);put(3,100,100,50,50,[0.99,0.1,0.1]);put(4,100,100,50,50,[0.1,0.2,0.2]);
          const d=scanDecode(cf,[1,7,N],man,g),bad=scanDecode(cf,[1,7,N],{...man,labels:['A','B']},g);
          const cl=scanDecode(Float32Array.from({length:7*N},(_,k)=>{const i=Math.floor(k/7),c=k%7;return cf[c*N+i]}),[1,N,7],man,g);
          const mk=(blur)=>{const c=document.createElement('canvas');c.width=300;c.height=200;const x=c.getContext('2d');for(let i=0;i<4000;i++){x.fillStyle='rgb('+(Math.random()*255|0)+','+(Math.random()*255|0)+','+(Math.random()*255|0)+')';x.fillRect(Math.random()*300,Math.random()*200,4,4)}
            if(!blur)return c;const c2=document.createElement('canvas');c2.width=300;c2.height=200;const y=c2.getContext('2d');y.filter='blur(10px)';y.drawImage(c,0,0);return c2};
          const sharp=scanSharp(mk(false),50,50,120,100),soft=scanSharp(mk(true),50,50,120,100),flat=(()=>{const c=document.createElement('canvas');c.width=c.height=100;const x=c.getContext('2d');x.fillStyle='#c33';x.fillRect(0,0,100,100);return scanSharp(c,10,10,60,60)})();
          return{letter:g,n:d.boxes.length,first:d.boxes[0],kept:d.boxes.map(b=>b.label),err:bad.err,clN:cl.boxes.length,sharp,soft,flat}}""")
        ok(pure["letter"]["px"] == 0 and pure["letter"]["py"] == 70 and pure["letter"]["nw"] == 320 and pure["letter"]["nh"] == 180, "letterbox: a 640x360 picture sits in the 320 square with 70 px bars top and bottom")
        ok(pure["n"] == 2 and pure["kept"] == ["BUTT_EXPOSED", "BREAST_EXPOSED"], "decode keeps only the flagged classes above the threshold and merges the duplicate box (NMS): %s" % pure["kept"])
        b = pure["first"]; ok(b and all(k in b for k in ("x", "y", "w", "h", "score", "label")) and b["x"] >= 0, "boxes come back in picture pixels")
        ok("lists 2 labels" in (pure["err"] or "") or "labels" in (pure["err"] or ""), "a manifest that does not match the model is reported: %s" % (pure["err"] or "")[:80])
        ok(pure["clN"] == pure["n"], "channels-last model output decodes the same as channels-first")
        ok(pure["sharp"] > 60 * 5 and pure["soft"] < pure["sharp"] / 10 and pure["flat"] < 5, "sharpness: textured %.0f, the same texture blurred %.1f, a flat patch %.2f" % (pure["sharp"], pure["soft"], pure["flat"]))
        # ---- B. the model is not installed
        cfg = pg.evaluate("cfg.scan"); ok(cfg and cfg["ready"] is False and "manifest.json" in cfg["missing"], "config says the scan model is missing: %s" % cfg)
        pg.get_by_text("Scan story").first.click(); pg.wait_for_selector("text=Preview (low resolution)", timeout=10000)
        btn = pg.locator("#detail button", has_text="Scan for nudity"); ok(btn.count() == 1 and btn.is_disabled() and "not installed" in (btn.get_attribute("title") or ""), "the button is disabled and explains why (never a false 'clean')")
        # ---- C. install the stand-in model and scan for real
        scan.mkdir(); (scan / "manifest.json").write_text(json.dumps(MANIFEST)); (scan / "fake.onnx").write_bytes(b"\0" * 10); (scan / "ort.min.js").write_text(FAKE_ORT)
        r = s.call("GET", "/api/scan/assets/manifest.json"); ok(r[0] == 200 and r[1]["name"] == "STAND-IN", "the manifest is served to a signed-in page")
        pg.reload(); pg.wait_for_selector("#nav", timeout=15000); pg.wait_for_timeout(1200); pg.get_by_text("Scan story").first.click(); pg.wait_for_selector("text=Preview (low resolution)", timeout=10000)
        btn = pg.locator("#detail button", has_text="Scan for nudity"); ok(btn.count() == 1 and btn.is_enabled(), "with the files in place the button is enabled")
        btn.click()
        try: pg.wait_for_selector("text=Scan finished", timeout=60000)
        except Exception:
            report("   TIMEOUT. panel: " + " | ".join(pg.locator("#detail").inner_text().split("\n")[:30])[:900]); report("   video: " + json.dumps(pg.evaluate("pv.node?{paused:pv.node.paused,t:pv.node.currentTime,rs:pv.node.readyState,rate:pv.node.playbackRate,err:pv.node.error&&pv.node.error.message,w:pv.node.videoWidth,src:pv.node.src}:null")))
            report("   scan: " + json.dumps(pg.evaluate("Object.values(SCAN).map(d=>({state:d.state,frames:d.frames,reached:d.reached,flags:d.flags.length,fatal:d.fatal,live:d.live,busy:d.busy}))"))); report("   errors: %s" % errs[:3]); raise
        t = pg.locator("#detail .insp").inner_text(); report("   panel: " + t.replace("\n", " | ")[:420])
        flags = pg.locator("#detail .scf"); n = flags.count(); ok(n == 2, "two flags: the sharp red section and the flat red section (got %d)" % n)
        txt = [flags.nth(i).inner_text().replace("\n", " ") for i in range(n)]
        ok(n >= 1 and "NOT BLURRED?" in txt[0] and ("0:03" in txt[0] or "0:04" in txt[0] or "0:02" in txt[0]), "the first flag is at about 0:03 and says NOT BLURRED?: %s" % txt[0][:90])
        ok(n == 2 and "looks soft or blurred" in txt[1] and ("0:06" in txt[1] or "0:07" in txt[1] or "0:05" in txt[1]), "the second flag (flat red, at about 0:06) is marked soft, for a person to check: %s" % txt[1][:90])
        ok(pg.evaluate("[...document.querySelectorAll('#detail .scf img')].every(i=>i.naturalWidth>100 && i.src.startsWith('data:image/jpeg'))"), "every flag has its picture, kept only in memory (data: URL)")
        ok("NOT cleared" in t and "not violence" in t and "preview" in t, "the finished panel says it is not clearance, not violence, low-resolution")
        ok(pg.evaluate("window.__model_url").endswith("/api/scan/assets/fake.onnx"), "the model was loaded from the Storigen server")
        pg.screenshot(path="/tmp/shots/scan_result.png")
        # go to a flag
        pg.locator("#detail .scf button").first.click(); pg.wait_for_timeout(500); ok(pg.evaluate("pv.node && pv.node.currentTime") is not None, "'go to' moves the player")
        ok(not errs, "no JavaScript error: %s" % errs[:2])
        br.close()
    before = sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file() and p.suffix not in (".db", ".wal", ".shm") and "t.db" not in p.name)
    ok(before == sorted(["ONAIR/Nov-26/22-11-2026/221126_SCAN.mxf", "scan/manifest.json", "scan/fake.onnx", "scan/ort.min.js"]), "nothing was written anywhere by the scan: %s" % before)
    return all(res)

if __name__ == "__main__":
    good = run(); print("SCAN CHECK", "OK" if good else "FAILED"); sys.exit(0 if good else 1)
