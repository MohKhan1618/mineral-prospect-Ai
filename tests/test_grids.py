import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.grids import check_alignment  # noqa: E402


def _row(layer, **kw):
    base = dict(layer=layer, rows=10, cols=20, cell_x_m=50.0, cell_y_m=50.0, epsg=32613, left=0.0, bottom=0.0)
    base.update(kw)
    return base


def test_aligned_grids_pass():
    check_alignment(pd.DataFrame([_row("a"), _row("b")]))


def test_shifted_origin_is_rejected():
    with pytest.raises(ValueError, match="left"):
        check_alignment(pd.DataFrame([_row("a"), _row("b", left=50.0)]))


def test_different_cell_size_is_rejected():
    with pytest.raises(ValueError, match="cell_x_m"):
        check_alignment(pd.DataFrame([_row("a"), _row("b", cell_x_m=12.7)]))
