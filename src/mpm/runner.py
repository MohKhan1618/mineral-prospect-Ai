"""Resume-safe stage runner.

A *stage* is one pipeline step: files in -> files out. The runner records a fingerprint
(hash of input files + parameters) after a stage finishes. On the next run, if the
fingerprint is unchanged and every declared output exists, the stage is skipped.

Crash behaviour:
  * Crash during a stage -> no state file written -> the stage runs again next time.
  * Crash after a stage -> its state file is already on disk -> it is skipped.
  * Stages that write big outputs must write atomically (use `atomic_write`) so a crash
    never leaves a half-written file that looks finished.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

log = logging.getLogger("mpm.runner")


@dataclass
class Stage:
    name: str
    func: Callable[[], None]
    inputs: list[Path] = field(default_factory=list)
    outputs: list[Path] = field(default_factory=list)
    params: dict = field(default_factory=dict)


@contextmanager
def atomic_write(path: Path, mode: str = "wb") -> Iterator:
    """Write to a temp file, fsync, then rename. Readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, mode) as fh:
        yield fh
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def file_hash(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def fingerprint(inputs: Iterable[Path], params: dict) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(params, sort_keys=True, default=str).encode())
    for p in sorted(Path(x) for x in inputs):
        h.update(str(p).encode())
        h.update(file_hash(p).encode() if p.exists() else b"MISSING")
    return h.hexdigest()


def _state_path(state_dir: Path, name: str) -> Path:
    return Path(state_dir) / f"{name}.json"


def is_done(stage: Stage, state_dir: Path) -> bool:
    sp = _state_path(state_dir, stage.name)
    if not sp.exists():
        return False
    try:
        saved = json.loads(sp.read_text())
    except json.JSONDecodeError:
        return False  # corrupt state (crash mid-write) -> treat as not done
    if saved.get("fingerprint") != fingerprint(stage.inputs, stage.params):
        return False
    return all(Path(o).exists() for o in stage.outputs)


def run_stage(stage: Stage, state_dir: Path, force: bool = False) -> bool:
    """Run a stage unless it is already done. Returns True if it actually ran."""
    if not force and is_done(stage, state_dir):
        log.info("SKIP  %s (up to date)", stage.name)
        return False
    log.info("RUN   %s", stage.name)
    t0 = time.time()
    fp_before = fingerprint(stage.inputs, stage.params)
    stage.func()
    missing = [str(o) for o in stage.outputs if not Path(o).exists()]
    if missing:
        raise RuntimeError(f"Stage {stage.name} did not produce: {missing}")
    with atomic_write(_state_path(state_dir, stage.name), "w") as fh:
        json.dump(
            {
                "fingerprint": fp_before,
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "seconds": round(time.time() - t0, 2),
            },
            fh,
            indent=2,
        )
    log.info("DONE  %s (%.1fs)", stage.name, time.time() - t0)
    return True


def run_pipeline(stages: list[Stage], state_dir: Path, force: bool = False) -> None:
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    for st in stages:
        run_stage(st, state_dir, force=force)
