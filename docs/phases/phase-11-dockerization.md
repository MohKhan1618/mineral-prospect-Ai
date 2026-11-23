# Phase 11 - Dockerization

Status: done (local)   Date: 2026-11-23   Gate: image builds, runs as non-root, serves the web page and API, reports healthy.

## 1. What we did
- `Dockerfile.serve` (multi-stage, python:3.13-slim), `requirements-serve.txt` (5 pinned runtime packages), `.dockerignore` updated.
- The image holds `src/mpm`, `web/` and `models/final` (without the unused `logreg_final.joblib`). It leaves out training code,
  tests, pytest, streamlit, scikit-learn and pandas.
- The old `Dockerfile` (dev image running the pipeline) is kept unchanged.

## 2. What it does
`uvicorn mpm.api:app` on `$PORT` (default 8080), non-root user `app` (uid 10001), HEALTHCHECK on `/health` that fails unless the body says "ok".

## 3. Why it was necessary
Phase 12 (Cloud Run) deploys an image; it must be small, reproducible and contain the model files.

## 5. Challenges
| Challenge | How handled |
|---|---|
| Docker engine was off | Started Docker Desktop, waited for engine |
| `/health` returns HTTP 200 even when the model is missing | Healthcheck inspects the body, not the status code |

## 6. Results (2026-11-23)
- Build succeeded; image size **332 MB** (model files 97 MB of it).
- Container reached "healthy"; `/health` -> `{"status":"ok"}`; `/` -> 200; `/model-info`, `/predict/point` (-108.6, 42.5 -> percentile 0.665, "top 50%") and `/areas` returned data; process user is `app`.
- With `MPM_MODEL_DIR` pointing to a missing folder, `/health` returned `model_missing` (so the healthcheck command fails).
  I checked the status and the response only; I did not wait for Docker to flip that container to "unhealthy".
- Not done: I did not compare the container's scores with the local venv's, and I added no automated test for the image.

## 8. Open items
- No authentication or rate limit on the API (decision needed before Phase 12; see PLAN).
- The page's Leaflet and basemap tiles need internet access.
- Image not pushed anywhere.

## 9. How to reproduce
```
docker build -f Dockerfile.serve -t mpm-serve:phase11 .
docker run -p 8080:8080 mpm-serve:phase11
```
Open http://localhost:8080/

## 10. Gate G5 status
PLAN's G5 says "clean-clone Docker run reproduces the result". **Not fully met:** the image was built from this working folder, and
`models/final` is gitignored, so a fresh clone would not contain the model files. The image runs and serves the saved final model;
it does not retrain. Reproducing from raw data still needs `scripts/run_pipeline.py` with the downloaded data.

## 11. Gate G5 update (2026-11-23, Phase 13)
After the model files were committed with Git LFS, I cloned the GitHub repository into an empty folder, ran `docker build -f Dockerfile.serve`,
started the container and called `/health` (ok, container "healthy") and `/predict/point` at (-108.6, 42.5): logit -1.1445, percentile 0.665,
identical to the original image and to the Cloud Run service. **G5 is met for the serving image** (clean clone -> Docker -> same result).
It is **not** a rebuild from raw data: that path (download about 3 GB, convert grids, run the pipeline) has not been tested on a fresh machine.
