# Phase 10 - Final model, saving, serving

Status: done   Date: 2026-11-21
Code: `src/mpm/final.py`, `src/mpm/serve.py`, `src/mpm/api.py`, `app/streamlit_app.py`; pipeline stage `10_final_model`. Tests: 9 new (58 pass in total). Model card: [MODEL_CARD.md](../MODEL_CARD.md).

## 1. What we did
- **Refit on all data:** logistic regression (the Phase 8 choice, default hyper-parameters) on all 199 positives plus 40,000 random unlabeled cells outside the 2 km ring. Saved with its preprocessor as one `joblib` object.
- **Serving store** (`serving.npz`, 70 MB): per-cell final logit, within-map percentile, Phase 9 disagreement, per-group linear contributions, distance to survey edge, cover flag, grid geometry and known occurrences. The API and app need neither the 677 MB feature file nor scikit-learn.
- **FastAPI:** `GET /health`, `GET /model-info`, `POST /predict/point` (lon/lat), `POST /predict/bbox` (summary and the top cells). Responses give percentile, score bin, **labelled-positive density with interval** from the out-of-fold bins, uncertainty level, top three driver groups, warnings, and a disclaimer. Outside the footprint gives 404, invalid input 422, missing model 503.
- **Streamlit app:** map layers (score percentile, disagreement, neighbourhood contribution), threshold slider, known-occurrence overlay, point lookup, and a performance-and-limitations page that opens with "gate G4 not met".
- **Metadata and model card:** inputs hashed, versions, honest out-of-fold metrics, calibration bins, limitations.

## 2. Design decisions (made before building)
| Decision | Why |
|---|---|
| Report calibrated **bin rates** from Phase 9 out-of-fold data, not the model's probabilities | The Platt map was poor in the tails; bin rates are observed |
| Quote only out-of-fold performance; label the map and the known cells as in-sample | The final model has seen every positive |
| Return top driver **groups**, not single features | Storing 49 contributions per cell costs 340 MB; groups cost 41 MB. Groups are also the unit Phase 9 could defend. Deviation from PLAN.md "top features" |
| Precompute everything, no model at request time | Small image and fast responses for Phase 11/12 |
| Wording rule built into every response: "labelled-positive density, not a deposit probability" | Avoid overclaiming |

## 3. Verification
- Real model reload is bit-identical; serving logits match the model code path (`atol 1e-4`) on 3,000 random cells; percentile is monotone in the score.
- Synthetic-store tests cover round trip, bins, invalid cells, bbox, validation errors, missing model.
- Streamlit `AppTest`: all three pages render, outside-footprint lookup warns.
- Looked at the real app in the browser pane: map, threshold slider, performance page render correctly.
- Real API call at a known occurrence returned percentile 0.993, bin "top 1 %", and the in-sample warning.

## 4. Known limitations / red flags
### 🚩 Red flags
1. **The final map is in-sample at the known occurrences.** In the app the top 5 % holds 134 of 199 occurrences (67 %), more than the out-of-fold 61 %; never quote that number as performance. The app says so next to it.
2. **Bin rates are from out-of-fold models and applied to the final model's percentile.** The final model uses all data so the mapping is slightly off; the error is not measured.
3. ~~Possible survey-block step in the east.~~ **Withdrawn after the Phase 10b check (2026-11-21):** it was a misreading; see [phase-10b-east-block-check.md](phase-10b-east-block-check.md). Remaining small items are listed there.
4. **Carried from earlier phases:** G4 not met; local radiometrics only; clustered misses; `mag_IGRF` coefficient; edge watch item; cover; roads untested.
5. **Uncertainty is descriptive,** shown with that label.
6. **No authentication, rate limiting or input size limits beyond validation;** fine for a local pilot, to be decided in Phases 11 and 12.
7. `models/final/` is 70 MB and `serving.npz` is built from the in-repo data; the image size decision belongs to Phase 11.

## 5. Concepts learned
- **Serving store:** precompute at build time so serving is a lookup; guarantees train/serve consistency by construction, which the reproducibility test then checks.
- **Train/serve skew** and how to test for it.
- **In-sample vs out-of-fold** reporting for a refit model.
- **Pydantic validation** gives 422 automatically; a lazy loader gives a clear 503 instead of a crash.
- **`AppTest`** exercises a Streamlit script headlessly.

## 6. How to run
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
.\.venv\Scripts\python.exe -m uvicorn mpm.api:app --app-dir src --port 8000
.\.venv\Scripts\streamlit.exe run app\streamlit_app.py
```
