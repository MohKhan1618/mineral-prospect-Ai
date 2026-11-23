import numpy as np, rasterio, json, re
ROOT = r"C:\Users\Lenovo\Desktop\mineral-exploration-using-AI"
def load(p):
    with rasterio.open(p) as s:
        a = s.read(1).astype("float32"); nd = s.nodata; t = s.transform
    if nd is not None: a[a == nd] = np.nan
    return a, t
U, t = load(ROOT + r"\data\interim\clean\U_FIN.tif")
txt = open(r"C:\Users\Lenovo\AppData\Local\Temp\claude\59f50460aba3ffef\626a6499-8b55-47f8-8737-fcb66bdb5b6d\scratchpad\report.txt", encoding="utf-8", errors="ignore").read()
sec = txt[txt.find("Table 2-1"):txt.find("Figure 2.2")]
pts = re.findall(r"^\s*\d+\s+(\d{6})\s+(\d{7})\s", sec, flags=re.M)
bx = sorted({int(a) for a, b in pts}); by = sorted({int(b) for a, b in pts})
print("block edge eastings:", [b/1000 for b in bx]); print("block edge northings:", [b/1000 for b in by])
w = 20  # 1 km each side
LU = np.log(np.where(U > 0.5, U, np.nan))
res = []
for ci in range(w, U.shape[1] - w):
    L = LU[:, ci - w:ci]; R = LU[:, ci:ci + w]
    m = np.isfinite(L).sum(1) > 15; m &= np.isfinite(R).sum(1) > 15
    if m.sum() < 120: continue            # need >= 6 km of surveyed length
    d = (np.nanmean(R[m], 1) - np.nanmean(L[m], 1))
    # straightness: fraction of rows with the same sign and |d|>0.25 (about 28 % change)
    s = np.sign(np.nanmedian(d)); frac = float(np.mean((np.sign(d) == s) & (np.abs(d) > 0.25)))
    res.append((frac * min(m.sum()/200, 1), t.c + ci*50, float(np.nanmedian(d)), int(m.sum()*50)))
res.sort(reverse=True)
seen = []
print("top straight vertical step lines (score, easting km, median log-ratio, length km, nearest block edge km):")
for sc, x, d, ln in res:
    if any(abs(x - s) < 3000 for s in seen): continue
    seen.append(x)
    nb = min(bx, key=lambda b: abs(b - x))
    print(f"  {sc:.2f}  x={x/1000:.2f}  d={d:+.2f} ({(np.exp(d)-1)*100:+.0f}%)  len={ln/1000:.0f}  nearest block edge {nb/1000:.2f} ({abs(nb-x)/1000:.2f} km away)")
    if len(seen) >= 10: break
