import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.labels import BACKGROUND, EXCLUDED, OUTSIDE, POSITIVE, build_label_raster, collapse_to_cells, disk_offsets  # noqa: E402
from mpm.splits import assign_folds, block_id_raster, block_table, cross_fold_neighbours  # noqa: E402


def test_disk_offsets_is_round():
    dr, dc = disk_offsets(3)
    assert (0, 0) in set(zip(dr, dc))
    assert (3, 3) not in set(zip(dr, dc))  # corner is outside a radius-3 disk
    assert len(dr) == 29


def test_collapse_keeps_strongest_status_and_one_row_per_cell():
    rec = pd.DataFrame({"dep_id": [1, 2, 3], "site_name": ["a", "b", "c"],
                        "dev_stat": ["Occurrence", "Producer", "Prospect"], "score": ["D", "B", None]})
    out = collapse_to_cells(rec, np.array([5, 5, 7]), np.array([5, 5, 7]), from_origin(0, 1000, 50, 50))
    assert len(out) == 2
    cell = out[out.row == 5].iloc[0]
    assert cell.n_records == 2 and cell.dev_stat == "Producer" and cell.is_producer and cell.best_score == "B"


def test_label_raster_codes_and_buffer():
    mask = np.ones((21, 21), dtype=bool)
    mask[:, 0] = False
    lab = build_label_raster(mask.shape, mask, np.array([10]), np.array([10]), buffer_cells=3)
    assert lab[10, 10] == POSITIVE
    assert lab[10, 12] == EXCLUDED and lab[10, 14] == BACKGROUND
    assert lab[0, 0] == OUTSIDE
    assert (lab == POSITIVE).sum() == 1


def test_block_ids_and_table():
    b = block_id_raster((10, 10), 5)
    assert set(np.unique(b)) == {1, 2, 3, 4}
    lab = np.ones((10, 10), dtype="uint8")
    lab[0, 0] = POSITIVE
    t = block_table(lab, b)
    assert t.n_valid.sum() == 100 and t.set_index("block_id").loc[1, "n_pos"] == 1


def test_assign_folds_balanced_and_complete():
    t = pd.DataFrame({"block_id": range(1, 21), "n_valid": 100,
                      "n_pos": [8, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]})
    a = assign_folds(t, 4, seed=1)
    assert a.block_id.nunique() == 20 and a.fold.notna().all()
    per_fold = a.groupby("fold").n_pos.sum()
    assert per_fold.max() - per_fold.min() <= 3  # total 48 positives, ideal 12 each
    assert not assign_folds(t, 4, seed=1).equals(assign_folds(t, 4, seed=2))
    assert assign_folds(t, 4, seed=1).equals(assign_folds(t, 4, seed=1))  # reproducible


def test_cross_fold_neighbours():
    pos = pd.DataFrame({"x": [0.0, 100.0, 50000.0], "y": [0.0, 0.0, 0.0]})
    assert cross_fold_neighbours(pos, np.array([0, 1, 1]), 2000) == 2 / 3
    assert cross_fold_neighbours(pos, np.array([0, 0, 1]), 2000) == 0.0
