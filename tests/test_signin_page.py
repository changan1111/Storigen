"""v9.7.4: the sign-in page of the web app. A browser is not available in the tests, so this guards what can break silently: the element IDs the script uses, and the script itself."""
import re, shutil, subprocess, pathlib, pytest
PAGE = pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "web" / "index.html"

def text(): return PAGE.read_text(encoding="utf-8")

def test_every_element_the_script_looks_up_exists_exactly_once():
    s = text(); ids = re.findall(r'\bid="([^"]+)"', s)
    assert not {i for i in ids if ids.count(i) > 1}, "duplicate ids"
    assert not set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', s)) - set(ids), "the script uses an element that is not on the page"

def test_the_sign_in_form_has_what_the_login_code_and_the_browser_need():
    s = text(); block = s[s.index('<div id="login"'):s.index('<div id="app"')]
    for need in ('id="u"', 'id="p"', 'id="go"', 'id="lerr"', 'id="lblock"', 'id="peye"', 'type="submit"', 'autocomplete="username"', 'autocomplete="current-password"', 'for="u"', 'for="p"', 'lg-card'):
        assert need in block, need
    assert block.count("<div") == block.count("</div>") and block.count("<form") == block.count("</form>")

def test_the_old_plain_login_rule_is_gone():
    assert "#login{max-width:30rem;margin:15vh auto" not in text()

@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_page_script_has_no_syntax_error(tmp_path):
    js = re.search(r"<script>(.*)</script>", text(), re.S).group(1); f = tmp_path / "page.js"; f.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True); assert r.returncode == 0, r.stderr
