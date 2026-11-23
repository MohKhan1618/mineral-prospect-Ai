# Phase 13 - Wrap-up

Status: done (items below), teaching pass pending   Date: 2026-11-23

## 1. What we did
- `README.md` rewritten: purpose and disclaimer, live demo link (with the 2026-12-17 trial end), headline results, mermaid architecture
  diagram, repository map, run-from-clone instructions, raw-data rebuild instructions, deployment summary, short limits list.
- Model card (Phase 10, `docs/MODEL_CARD.md`), results (Phase 8/9 records and the model card), reproduction guide (README + phase records),
  owner overview (`docs/PROJECT_OVERVIEW.md`) are the other wrap-up documents.
- Full test suite re-run: 64 passed (about 67 s).
- Clean-clone check of the serving image (see phase-11 section 11).

## 2. Not done
- "Second region as an out-of-area generalisation test" (PLAN, optional, "if time"): **not done**. Transfer to another region remains untested.
- Rebuild from raw data on a fresh machine: untested.
- Cloud Build path (`cloudbuild.yaml`) untested; deployment used a locally built image.
- Geologist review of the guide wording; QGIS overlay and mind-map exercises (owner TO-DOs).
- Teaching pass: Lessons 1-5 delivered in chat; quizzes not yet passed. The "What I can explain" table stays as is until they are.

## 3. Red flags carried forward
G4 not met; local radiometrics only; clustered misses and the small district; map in-sample at the known cells; no API authentication or rate
limit; demo stops 2026-12-17 on the free trial; Leaflet and tiles need internet.

## 4. How to check
Open the README; run the Docker commands in it; `pytest -q`.
