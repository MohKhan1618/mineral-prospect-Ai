import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from mpm.runner import Stage, atomic_write, run_stage  # noqa: E402


def make_stage(tmp_path, counter, params=None, inp=None, fail=False):
    out = tmp_path / "out.txt"

    def f():
        counter.append(1)
        if fail:
            raise RuntimeError("boom")
        with atomic_write(out, "w") as fh:
            fh.write("x")

    return Stage("s", f, inputs=[inp] if inp else [], outputs=[out], params=params or {})


def test_runs_once_then_skips(tmp_path):
    c = []
    st = make_stage(tmp_path, c)
    assert run_stage(st, tmp_path / "state") is True
    assert run_stage(st, tmp_path / "state") is False
    assert len(c) == 1


def test_reruns_when_input_changes(tmp_path):
    inp = tmp_path / "in.txt"
    inp.write_text("a")
    c = []
    st = make_stage(tmp_path, c, inp=inp)
    run_stage(st, tmp_path / "state")
    inp.write_text("b")
    assert run_stage(st, tmp_path / "state") is True
    assert len(c) == 2


def test_reruns_when_params_change(tmp_path):
    c = []
    run_stage(make_stage(tmp_path, c, params={"k": 1}), tmp_path / "state")
    assert run_stage(make_stage(tmp_path, c, params={"k": 2}), tmp_path / "state") is True


def test_reruns_when_output_deleted(tmp_path):
    c = []
    st = make_stage(tmp_path, c)
    run_stage(st, tmp_path / "state")
    (tmp_path / "out.txt").unlink()
    assert run_stage(st, tmp_path / "state") is True


def test_crash_leaves_no_state_so_it_reruns(tmp_path):
    c = []
    with pytest.raises(RuntimeError):
        run_stage(make_stage(tmp_path, c, fail=True), tmp_path / "state")
    assert not list((tmp_path / "state").glob("*.json")) if (tmp_path / "state").exists() else True
    assert run_stage(make_stage(tmp_path, c), tmp_path / "state") is True


def test_corrupt_state_file_is_treated_as_not_done(tmp_path):
    c = []
    st = make_stage(tmp_path, c)
    run_stage(st, tmp_path / "state")
    (tmp_path / "state" / "s.json").write_text("{not json")
    assert run_stage(st, tmp_path / "state") is True


def test_atomic_write_leaves_no_partial_file_on_error(tmp_path):
    target = tmp_path / "f.bin"
    with pytest.raises(ValueError):
        with atomic_write(target) as fh:
            fh.write(b"partial")
            raise ValueError
    assert not target.exists()
