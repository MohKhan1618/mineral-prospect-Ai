import numpy as np, rasterio
ROOT = r"C:\Users\Lenovo\Desktop\mineral-exploration-using-AI"
with rasterio.open(ROOT + r"\data\splits\block_id.tif") as s: B = s.read(1); t = s.transform
row = int((t.f - 4678000)/50)
b = B[row]; ch = np.where(np.diff(b) != 0)[0]
xs = [(t.c + (i+1)*50)/1000 for i in ch if 335000 < t.c + i*50 < 360000]
print("CV block-id changes along N4678 km, easting km:", [round(x,2) for x in xs])
col = int((355500 - t.c)/50); cb = B[:, col]; chr_ = np.where(np.diff(cb) != 0)[0]
print("CV block-id changes along E355.5 km, northing km:", [round((t.f - (i+1)*50)/1000,2) for i in chr_ if 4660000 < t.f - i*50 < 4695000])
# final map: straight vertical steps in serving pct
z = np.load(ROOT + r"\models\final\serving.npz", allow_pickle=True)
a, c, e, f = [float(v) for v in (z["transform"][0], z["transform"][2], z["transform"][4], z["transform"][5])]
G = np.full(tuple(z["shape"]), np.nan, dtype="float32"); G[z["rows"], z["cols"]] = z["pct"]
w = 10
best = []
for ci in range(w, G.shape[1]-w):
    L = G[:, ci-w:ci]; R = G[:, ci:ci+w]
    m = (np.isfinite(L).sum(1) > 8) & (np.isfinite(R).sum(1) > 8)
    if m.sum() < 100: continue
    d = np.nanmean(R[m], 1) - np.nanmean(L[m], 1)
    s = np.sign(np.median(d)); frac = float(np.mean((np.sign(d) == s) & (np.abs(d) > 0.1)))
    best.append((frac, c + ci*a, float(np.median(d)), m.sum()*50/1000))
best.sort(reverse=True); seen = []
print("final-map straight vertical steps (fraction of rows with |dpct|>0.1 same sign, easting, median dpct, length km):")
for fr, x, d, ln in best:
    if any(abs(x - s) < 3000 for s in seen): continue
    seen.append(x); print(f"  {fr:.2f}  x={x/1000:.2f}  d={d:+.3f}  len={ln:.0f}")
    if len(seen) >= 6: break
