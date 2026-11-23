import numpy as np, rasterio
ROOT = r"C:\Users\Lenovo\Desktop\mineral-exploration-using-AI"
with rasterio.open(ROOT + r"\data\interim\clean\U_FIN.tif") as s: U = s.read(1).astype("float32"); t = s.transform; nd = s.nodata
if nd is not None: U[U == nd] = np.nan
z = np.load(ROOT + r"\models\final\serving.npz", allow_pickle=True)
G = np.full(tuple(z["shape"]), np.nan, dtype="float32"); G[z["rows"], z["cols"]] = z["pct"]
import warnings; warnings.filterwarnings("ignore")
for ya, yb in ((4663000, 4668000), (4668000, 4673000), (4673000, 4676000), (4676000, 4680000), (4680000, 4686000), (4686000, 4693000)):
    r0, r1 = int((t.f - yb)/50), int((t.f - ya)/50)
    out = []
    for xa in range(338000, 350000, 1000):
        c0, c1 = int((xa - t.c)/50), int((xa + 1000 - t.c)/50)
        u = U[r0:r1, c0:c1]; g = G[r0:r1, c0:c1]
        out.append("%4.0f/%.2f" % (np.nanmean(u), np.nanmean(g)) if np.isfinite(u).sum() > 100 else "  nodata ")
    print(f"N{ya/1000:.0f}-{yb/1000:.0f}  x=338..349 km  U/pct: " + " ".join(out))
