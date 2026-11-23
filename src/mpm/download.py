"""Resumable, checksum-recording downloader with a manifest.

* Downloads to `<dest>.part`; resumes with an HTTP Range request if the .part exists.
* Renames to `<dest>` only when complete, so a finished name always means a whole file.
* Records url, size, sha256 and timestamp in a manifest (data/raw/MANIFEST.json).
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from pathlib import Path

from .runner import atomic_write, file_hash

log = logging.getLogger("mpm.download")
UA = "mpm-research-pipeline/0.1"


def _remote_size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        n = r.headers.get("Content-Length")
        return int(n) if n else None


def download(url: str, dest: Path, expected_sha256: str | None = None, chunk: int = 1 << 20) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        log.info("exists, skipping download: %s", dest.name)
        return dest
    part = dest.with_name(dest.name + ".part")
    total = _remote_size(url)
    for attempt in range(1, 6):
        have = part.stat().st_size if part.exists() else 0
        if total is not None and have == total:
            break
        headers = {"User-Agent": UA}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                if have and r.status != 206:  # server ignored Range -> restart cleanly
                    have = 0
                    part.unlink(missing_ok=True)
                with open(part, "ab" if have else "wb") as fh:
                    while block := r.read(chunk):
                        fh.write(block)
                    fh.flush()
                    os.fsync(fh.fileno())
            break
        except Exception as e:  # network drop: retry, resuming from the .part file
            log.warning("download attempt %d failed: %s", attempt, e)
            time.sleep(2 * attempt)
    else:
        raise RuntimeError(f"could not download {url}")
    size = part.stat().st_size
    if total is not None and size != total:
        raise RuntimeError(f"size mismatch for {url}: {size} != {total}")
    digest = file_hash(part)
    if expected_sha256 and digest != expected_sha256:
        raise RuntimeError(f"checksum mismatch for {url}")
    os.replace(part, dest)
    return dest


def register(manifest: Path, name: str, url: str, path: Path, license_: str, note: str = "") -> None:
    manifest = Path(manifest)
    data = json.loads(manifest.read_text()) if manifest.exists() else {}
    data[name] = {
        "url": url,
        "file": str(Path(path).as_posix()),
        "bytes": Path(path).stat().st_size,
        "sha256": file_hash(Path(path)),
        "license": license_,
        "downloaded": time.strftime("%Y-%m-%d"),
        "note": note,
    }
    with atomic_write(manifest, "w") as fh:
        json.dump(data, fh, indent=2)
