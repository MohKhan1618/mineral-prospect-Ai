import sys, json
import numpy as np
import rasterio
ROOT = r"C:\Users\Lenovo\Desktop\mineral-exploration-using-AI"
def load(p):
    with rasterio.open(p) as s:
        a = s.read(1).astype("float64"); nd = s.nodata
        t = s.transform
    if nd is not None: a[a == nd] = np.nan
    return a, t
U, t = load(ROOT + r"\data\interim\clean\U_FIN.tif")
TH, _ = load(ROOT + r"\data\interim\clean\TH_FIN.tif")
K, _ = load(ROOT + r"\data\interim\clean\K_FIN.tif")
G, _ = load(ROOT + r"\data\processed\geology_class.tif")
print("shape", U.shape, "origin", t.c, t.f, "cell", t.a)
bound = [340160.0, 344300.0]
x_east = lambda col: t.c + (col + 0.5) * t.a
y_north = lambda row: t.f + (row + 0.5) * t.e
# east strip: 332-352 km
c0 = int((332000 - t.c) / t.a); c1 = int((352000 - t.c) / t.a)
band = 2500.0
rows_out = []
ys = np.arange(4660000, 4696000, band)
w = int(1000 / t.a)   # 1 km windows
for y0 in ys:
    r0 = int((t.f - (y0 + band)) / -t.e); r1 = int((t.f - y0) / -t.e)
    r0 = max(r0, 0); r1 = min(r1, U.shape[0])
    if r1 <= r0: continue
    res = {}
    for name, A in (("U", U), ("TH", TH), ("K", K)):
        prof = np.nanmedian(A[r0:r1, c0:c1], axis=0)
        n = len(prof); best = (0, None, None, None)
        for i in range(w, n - w):
            L = np.nanmean(prof[i - w:i]); R = np.nanmean(prof[i:i + w])
            if np.isnan(L) or np.isnan(R) or min(L, R) <= 0: continue
            d = abs(R - L)
            if d > best[0]: best = (d, i, L, R)
        if best[1] is None: res[name] = None; continue
        d, i, L, R = best
        xs = x_east(c0 + i)
        res[name] = dict(x=float(xs), left=float(L), right=float(R), rel=float((R - L) / min(L, R)),
                         dist_to_boundary=float(min(abs(xs - b) for b in bound)))
    # geology class either side of the U step
    if res["U"]:
        ci = int((res["U"]["x"] - t.c) / t.a)
        gl = G[r0:r1, ci - w:ci]; gr = G[r0:r1, ci:ci + w]
        def mode(a):
            a = a[np.isfinite(a)]
            if a.size == 0: return None
            v, c = np.unique(a, return_counts=True); return [int(x) for x in v[np.argsort(-c)][:2]]
        res["geo_left"] = mode(gl); res["geo_right"] = mode(gr)
    rows_out.append((float(y0), res))
for y0, r in rows_out:
    u = r["U"]
    if not u: print(y0, "no data"); continue
    s = f"N{y0/1000:.1f}  U x={u['x']/1000:.2f}km  {u['left']:.1f}->{u['right']:.1f} ({u['rel']*100:+.0f}%)  dB={u['dist_to_boundary']/1000:.2f}km"
    for k in ("TH", "K"):
        v = r[k]; s += f" | {k} x={v['x']/1000:.2f} {v['rel']*100:+.0f}%" if v else ""
    s += f" | geo {r.get('geo_left')} / {r.get('geo_right')}"
    print(s)
json.dump(rows_out, open(ROOT + r"\reports\phase10b_east_step_bands.json", "w"), indent=1)
