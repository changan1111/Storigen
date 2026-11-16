"""v9.7.5: the Storigen logo is on the sign-in page and the dashboard header; the old Auto-ID mark is gone."""
import pathlib
S = (pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")

def test_logo_on_login_and_dashboard():
    login = S[S.index('<div id="login"'):S.index('<div id="app"')]; app = S[S.index('<div id="app"'):]
    assert "data:image/webp;base64," in login and "data:image/webp;base64," in app.split("</div></div>")[0]

def test_old_branding_is_gone():
    for old in ("AUTO-ID", "lg-mark", 'class="logo"', "<title>Auto-ID Linker"): assert old not in S
    assert "<title>Storigen</title>" in S
