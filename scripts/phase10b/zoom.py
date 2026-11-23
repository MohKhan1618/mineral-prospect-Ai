import numpy as np, rasterio
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
ROOT = r"C:\Users\Lenovo\Desktop\mineral-exploration-using-AI"
SP = r"C:\Users\Lenovo\AppData\Local\Temp\claude\59f50460aba3ffef\626a6499-8b55-47f8-8737-fcb66bdb5b6d\scratchpad"
def load(p):
    with rasterio.open(p) as s:
        a = s.read(1).astype("float32"); nd = s.nodata; t = s.transform
    if nd is not None: a[a == nd] = np.nan
    return a, t
U, t = load(ROOT + r"\data\interim\clean\U_FIN.tif"); TH, _ = load(ROOT + r"\data\interim\clean\TH_FIN.tif")
S, _ = load(ROOT + r"\reports\maps\score_percentile_oof_logreg.tif")
x0, x1, y0, y1 = 346000, 360000, 4662000, 4694000
c0, c1 = int((x0 - t.c)/50), int((x1 - t.c)/50); r0, r1 = int((t.f - y1)/50), int((t.f - y0)/50)
ext = [x0/1000, x1/1000, y0/1000, y1/1000]
fig, ax = plt.subplots(1, 3, figsize=(16, 7))
for a, im_, ti, kw in ((ax[0], U, "U_FIN", dict(vmin=5, vmax=50)), (ax[1], TH, "TH_FIN", dict(vmin=10, vmax=100)), (ax[2], S, "score pct", dict(vmin=0.5, vmax=1, cmap="magma"))):
    h = a.imshow(im_[r0:r1, c0:c1], extent=ext, **kw); a.set_title(ti); plt.colorbar(h, ax=a, shrink=0.7)
    a.axvline(351.19, color="w", ls="--", lw=.8); a.axvline(359.105, color="r", ls="--", lw=.8)
fig.tight_layout(); fig.savefig(SP + r"\zoom.png", dpi=80); print("ok")
