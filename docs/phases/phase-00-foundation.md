# Phase 0 - Foundation

Status: done   Date: 2026-11-20   Gate: stage runner skips finished work and all tests pass - PASSED (7/7 tests; second pipeline run skipped the stage)

## 1. What we did
- Created the project layout: `config/`, `src/mpm/`, `scripts/`, `tests/`, `docs/`, `reports/`,
  `notebooks/`, and `data/{raw,interim,processed,features,splits}`, plus `models/` and `.state/`.
- Created a Python 3.13 virtual environment (`.venv`) and a `requirements.txt`.
- Initialized a Git repository on branch `main` with a `.gitignore` that keeps data, models,
  state and credentials out of version control.
- Wrote `config/config.yaml` (seed, paths, study-area/grid placeholders, Phase 1 gate values).
- Wrote the resume-safe stage runner (`src/mpm/runner.py`) and config loader (`src/mpm/config.py`).
- Wrote the entry point `scripts/run_pipeline.py` with one smoke stage.
- Wrote 7 tests (`tests/test_runner.py`), a development `Dockerfile` and `.dockerignore`.
- Wrote `PLAN.md`, `README.md`, and this documentation set.

## 2. What it does
- Every pipeline step is a *stage*: files in, files out. After a stage finishes, the runner stores
  a fingerprint (SHA-256 of input files plus parameters) in `.state/<stage>.json`.
- On each run a stage is skipped only if the fingerprint matches **and** all declared outputs exist.
- Outputs are written atomically (temp file, flush, fsync, rename).
- All settings live in one YAML file; the random seed is set from it.

## 3. Why it was necessary
The development machine crashes unpredictably, and training or processing steps will be slow.
Without a mechanism that remembers finished work, every crash would mean repeating hours of
processing. Starting with this structure also means later phases, Docker and GCP all run the same
entry point, so nothing has to be rebuilt later.

## 4. Concepts learned
- **Idempotent stage:** running it twice gives the same result as running it once, so re-running
  after a crash is always safe.
- **Fingerprint / content hash:** a short digest of the inputs; if it changes, the cached result is stale.
- **Atomic write:** write to a temporary file and rename, so a file is either complete or absent.
- **Reproducibility:** fixed seed and a single config file so results can be recreated.
- **Raw data is read-only:** later steps build from `data/raw`, never modify it.
- Geology link: none yet. This phase is infrastructure; geology enters in Phase 1.

## 5. Challenges faced and how we solved them
| Challenge | Impact | How we solved it |
|-----------|--------|------------------|
| Machine crashes at random | Lost work, repeated hours | Stage fingerprints + atomic writes + per-stage state files |
| A crash mid-write could leave a corrupt state or output file | A broken file could be mistaken for a finished result | Corrupt state JSON is treated as "not done"; outputs must exist; atomic writes |
| Python 3.11 not installed (system has 3.9 and 3.13) | Planned version unavailable; 3.9 is near end of life | Standardized on 3.13 locally and in the Docker base image |
| Docker Desktop engine was not running | Could not build or test the image | Wrote the Dockerfile now, deferred the build to Phase 11; noted in decisions |
| The first conversation lived in a private Gemini chat the tools could not open | Could not read the project background directly | Read the exported PDF of the chat instead |

## 6. Results and evidence
- `pytest -q`: 7 passed (skip when done, re-run on input change, re-run on parameter change,
  re-run if output deleted, no state after a crash, corrupt state tolerated, no partial file on error).
- First pipeline run executed `00_smoke`; second run printed `SKIP 00_smoke (up to date)`.

## 7. Decisions and trade-offs
- Own small runner instead of DVC or Airflow: fewer dependencies for Phase 0. We may adopt DVC
  later if data versioning becomes painful.
- Python 3.13 over installing 3.11: avoids an extra install; revisit if a library lacks wheels.
- Region not chosen yet: deliberately deferred to the Phase 1 positive-count gate.

## 8. Known limitations / open items
- Dockerfile is untested (engine was off).
- Fingerprints hash whole input files; for very large rasters we may switch to size + modified-time
  or a manifest hash.
- Nothing committed to Git yet.
- Stages must write atomically themselves; the runner cannot enforce it.

## 9. How to reproduce
```powershell
cd C:\Users\Lenovo\Desktop\mineral-exploration-using-AI
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
python scripts/run_pipeline.py     # run twice: the second run skips
```
