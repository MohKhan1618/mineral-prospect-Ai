import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pytestmark = pytest.mark.skipif(not (ROOT / "models/final/serving.npz").exists(), reason="final model not built")


def _app():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120)


def test_app_pages_render_without_exception():
    at = _app().run()
    assert not at.exception
    for page in ("Point lookup", "Performance and limitations"):
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, page
    texts = " ".join(w.value for w in at.warning)
    assert "NOT met" in texts or "Gate G4" in texts


def test_point_lookup_outside_footprint_warns():
    at = _app().run()
    at.sidebar.radio[0].set_value("Point lookup").run()
    at.number_input[0].set_value(0.0)
    at.number_input[1].set_value(0.0)
    at.run()
    assert any("Outside the surveyed footprint" in w.value for w in at.warning)
