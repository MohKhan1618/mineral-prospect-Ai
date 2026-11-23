import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from fastapi.testclient import TestClient  # noqa: E402

from mpm.api import create_app  # noqa: E402
from mpm.serve import Store  # noqa: E402
from test_serving import _fake_dir, _lonlat  # noqa: E402

FINAL = ROOT / "models" / "final"
built = pytest.mark.skipif(not (FINAL / "hotspots.json").exists(), reason="frontend data not built")


def _ev(u, th, k, nbr, ratio, fault=5.0, cls="Sedimentary, undifferentiated"):
    sp = {"eU": u, "eTh": th, "eK": k, "mean_eU_5km": nbr, "u_over_th": ratio}
    return {"eU_cps": 30.0, "eTh_cps": 30.0, "eK_cps": 90.0, "mean_eU_5km_cps": 20.0, "u_over_th": 1.0,
            "approx_concentration": {"eU_ppm": 2.9, "eTh_ppm": 4.8, "eK_pct": 0.9, "u_over_th_ppm": 0.6},
            "distance_to_fault_km": fault, "elevation_m": 2000, "rock_class": cls, "rock_unit": "u",
            "survey_percentile": sp, "survey_median": {"eU": 15.0, "eTh": 25.0, "eK": 84.0, "u_over_th": 0.6}}


def _report(s):
    rows, cols = s.rows, s.cols
    return s.cell_report(0)


def test_without_frontend_files_point_still_works_and_hotspots_say_503(tmp_path):
    d, rows, cols = _fake_dir(tmp_path)
    s = Store(d)
    out = s.point(*_lonlat(rows[4], cols[4]))
    assert out["evidence"] is None and out["nearest_known_occurrence"]["distance_km"] >= 0
    assert [r["kind"] for r in out["reading"]].count("caution") >= 1       # the "cannot tell you" caution is always there
    c = TestClient(create_app(d))
    assert c.get("/hotspots").status_code == 503 and c.get("/areas").status_code == 503 and c.get("/known").status_code == 503


def test_reading_keeps_guide_separate_and_follows_the_rules(tmp_path):
    s = Store(_fake_dir(tmp_path)[0])
    rep = s.cell_report(0)
    hi_ratio = s.reading(rep, _ev(0.95, 0.4, 0.5, 0.97, 0.9), None)
    assert any(r["kind"] == "guide" and "relative to thorium" in r["title"] for r in hi_ratio)
    all_high = s.reading(rep, _ev(0.95, 0.95, 0.9, 0.97, 0.3), None)
    assert any(r["kind"] == "guide" and "all high" in r["title"] for r in all_high)
    quiet = s.reading(rep, _ev(0.4, 0.4, 0.4, 0.5, 0.5), None)
    assert not [r for r in quiet if r["kind"] == "guide"]                    # nothing unusual: no textbook claim is made
    sandstone = s.reading(rep, _ev(0.4, 0.4, 0.4, 0.5, 0.5, cls="Sedimentary, clastic"), None)
    assert any(r["kind"] == "guide" and "Sandstone" in r["title"] for r in sandstone)
    # model statements describe only feature groups; no geological claim is allowed inside a "model" item
    for r in hi_ratio + all_high + sandstone:
        if r["kind"] == "model":
            assert r["title"].startswith("Model driver:")
        assert r["kind"] in {"measured", "model", "guide", "caution"}


def test_static_site_is_served_and_api_routes_win(tmp_path, monkeypatch):
    d, rows, cols = _fake_dir(tmp_path)
    web = tmp_path / "w"
    web.mkdir()
    (web / "index.html").write_text("<title>site</title>", encoding="utf-8")
    monkeypatch.setenv("MPM_WEB_DIR", str(web))
    c = TestClient(create_app(d))
    assert "<title>site</title>" in c.get("/").text
    assert c.get("/health").json() == {"status": "ok"}                       # not shadowed by the static mount


@built
def test_real_hotspots_structure_and_nesting():
    s = Store(FINAL)
    h = s.hot
    assert set(h["tiers"]) == {"top1", "top5", "top10"}
    assert all(len(h["tiers"][t]["features"]) > 0 for t in h["tiers"])
    assert 5 <= len(h["areas"]) <= 25
    sc = [(a["cells_top1pct"], a["area_km2"]) for a in h["areas"]]
    assert sc == sorted(sc, key=lambda t: (-t[0], -t[1]))                    # ranked as documented
    assert [a["rank"] for a in h["areas"]] == list(range(1, len(h["areas"]) + 1))
    assert len(h["known"]) == s.pos_rc.shape[0] == 199
    for a in h["areas"]:
        assert a["known_occurrences_inside"] >= a["known_producers_inside"] >= 0
        assert 0 < a["max_percentile"] <= 1 and a["bbox"][0] < a["bbox"][2] and a["bbox"][1] < a["bbox"][3]


@built
def test_real_polygons_cover_the_cells_they_claim_and_known_list_matches_store():
    from shapely import contains_xy
    from shapely.geometry import shape
    from shapely.ops import unary_union
    s = Store(FINAL)
    for tier, thr in (("top1", 0.99), ("top5", 0.95), ("top10", 0.90)):
        sel = np.flatnonzero(s.pct >= thr)
        sub = sel[:: max(1, sel.size // 20000)]
        lon, lat = s.rc_to_lonlat(s.rows[sub], s.cols[sub])
        u = unary_union([shape(f["geometry"]) for f in s.hot["tiers"][tier]["features"]])
        assert contains_xy(u, lon, lat).mean() >= 0.9, tier                  # acceptance check 2 of the design note
        assert -110 < u.bounds[0] and u.bounds[2] < -106 and 41.5 < u.bounds[1] and u.bounds[3] < 43.5
    lon, lat = s.rc_to_lonlat(s.pos_rc[:, 0], s.pos_rc[:, 1])
    kn = s.hot["known"]
    assert max(abs(lon[i] - kn[i]["lon"]) for i in range(len(kn))) < 1e-4    # names line up with the stored positions


@built
def test_real_point_has_evidence_and_site_serves_end_to_end():
    c = TestClient(create_app(FINAL))
    a = c.get("/areas").json()["areas"][0]
    r = c.post("/predict/point", json=a["peak"])
    assert r.status_code == 200
    o = r.json()
    assert o["percentile"] >= 0.99 and o["evidence"]["eU_cps"] > 0
    assert {"measured", "model", "caution"} <= {x["kind"] for x in o["reading"]}
    sp = o["evidence"]["survey_percentile"]
    assert all(0 <= v <= 1 for v in sp.values())
    assert c.get("/hotspots").status_code == 200 and c.get("/known").status_code == 200
    page = c.get("/")
    if (ROOT / "web" / "index.html").exists():
        assert "Mineral Prospectivity Map" in page.text and c.get("/app.js").status_code == 200


def test_js_unit_constants_match_python():
    """The page converts cps to ppm / % with constants copied from serve.py; they must not drift apart."""
    import re
    from mpm import serve
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"const SENS = \{ U: ([\d.]+), Th: ([\d.]+), K: ([\d.]+) \}", js)
    assert m, "SENS constants not found in web/app.js"
    assert (float(m[1]), float(m[2]), float(m[3])) == (serve.SENS_U_CPS_PER_PPM, serve.SENS_TH_CPS_PER_PPM, serve.SENS_K_CPS_PER_PCT)


def test_reading_text_shows_ppm_and_percent(tmp_path):
    s = Store(_fake_dir(tmp_path)[0])
    ev = _ev(0.95, 0.5, 0.5, 0.5, 0.8)
    ev["approx_concentration"] = {"eU_ppm": 2.9, "eTh_ppm": 4.8, "eK_pct": 0.9, "u_over_th_ppm": 0.6}
    text = " ".join(r["text"] for r in s.reading(s.cell_report(0), ev, None) if r["kind"] == "measured")
    assert "about 2.9 ppm" in text and "about 4.8 ppm" in text and "about 0.9 %" in text and "in ppm terms" in text


@built
def test_real_evidence_has_consistent_approx_concentration():
    from mpm import serve
    s = Store(FINAL)
    ev = s.evidence(0)
    ac = ev["approx_concentration"]
    assert abs(ac["eU_ppm"] - ev["eU_cps"] / serve.SENS_U_CPS_PER_PPM) < 0.06
    assert abs(ac["eK_pct"] - ev["eK_cps"] / serve.SENS_K_CPS_PER_PCT) < 0.006
