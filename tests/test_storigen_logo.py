"""v9.8.1: Storigen branding: the supplied Storigen logo is embedded, the NewsFusion name is gone from the UI."""
import base64, io, pathlib, re
ROOT = pathlib.Path(__file__).resolve().parents[1]
S = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")

def test_981_01_logo_is_embedded_on_login_and_dashboard():
    imgs = re.findall(r'src="data:image/webp;base64,([A-Za-z0-9+/=]+)"', S)
    assert len(imgs) == 2 and imgs[0] == imgs[1]
    raw = base64.b64decode(imgs[0]); assert raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    assert 'alt="Storigen: Every Story is Connected."' in S and 'alt="Storigen"' in S

def test_981_02_logo_has_the_storigen_proportions():
    try: from PIL import Image
    except ImportError: return
    im = Image.open(io.BytesIO(base64.b64decode(re.search(r'base64,([A-Za-z0-9+/=]+)"', S).group(1))))
    assert im.width == 1200 and 4.0 < im.width / im.height < 5.2

def test_981_03_no_newsfusion_left_in_the_ui_or_code():
    for f in ("autoid_lite/web/index.html", "autoid_lite/server.py", "README.md"):
        assert "newsfusion" not in (ROOT / f).read_text(encoding="utf-8").lower()
    assert "NewsFusion" not in S and "<title>Storigen</title>" in S

def test_981_04_blaze_400_invalid_session_counts_as_expired():
    """Blaze answers an expired session with HTTP 400 {"errors":["invalid.sessionId"]}: that must start the re-login, not be a plain error."""
    import http.server, sys, threading
    sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT))
    import blaze_poll as bp
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(400); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b'{"errors":["invalid.sessionId"]}')
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = bp.Cfg({"BLAZE_URL": "http://127.0.0.1:%d" % srv.server_port, "BLAZE_SESSION_ID": "OLD", "BLAZE_USERNAME": "u", "BLAZE_SHOW_IDS": "1"})
        try: bp.Blaze(c).get("/DataService/shows/1/slugs"); raised = None
        except bp.SessionExpired as e: raised = e
        assert raised is not None
    finally: srv.shutdown()
