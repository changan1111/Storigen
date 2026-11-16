"""Review fixes on top of v9.7.4: the sign-in screen must really hide after sign-in, and rewriting autoid.env must not make it readable by other users."""
import os, re, pathlib, sys
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from autoid_lite import config

HTML = (pathlib.Path(__file__).resolve().parent.parent / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")

def test_the_sign_in_screen_hides_when_it_is_hidden():
    rule = re.search(r"#login\{[^}]*\}", HTML).group(0)
    assert "display:" in rule, "this test guards the id rule that sets display"
    assert re.search(r"#login\.hide\s*\{\s*display:\s*none", HTML) or re.search(r"#login:not\(\.hide\)", HTML), "an id rule beats .hide, so the sign-in screen would stay visible after signing in"

@pytest.mark.skipif(os.name == "nt", reason="file modes are a Unix thing")
def test_set_env_keeps_the_file_private(tmp_path):
    p = tmp_path / "autoid.env"; p.write_text("# c\nSERVICE_API_KEY=abc\nBLAZE_SESSION_ID=old\n"); os.chmod(p, 0o600)
    config.set_env({"BLAZE_SESSION_ID": "new", "BLAZE_X": "1"}, p)
    assert (p.stat().st_mode & 0o777) == 0o600 and p.read_text() == "# c\nSERVICE_API_KEY=abc\nBLAZE_SESSION_ID=new\nBLAZE_X=1\n" and not (tmp_path / "autoid.env.tmp").exists()

@pytest.mark.skipif(os.name == "nt", reason="file modes are a Unix thing")
def test_set_env_makes_a_new_file_private(tmp_path):
    p = tmp_path / "new.env"; config.set_env({"A": "1"}, p); assert (p.stat().st_mode & 0o777) == 0o600 and p.read_text() == "A=1\n"
