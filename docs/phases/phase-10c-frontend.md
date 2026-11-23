# Phase 10c - Web frontend (Leaflet single-page site on the FastAPI)

Status: design written before building, 2026-11-21.   Audience (user's answer): "a smart and logical combination" of interview demo and geologist user.

## 1. What was asked
A custom HTML/JS site with an interactive Leaflet map (zoom, pan, click a point), served by the existing FastAPI so one Docker image runs both; Streamlit stays as a fallback. It should highlight the areas of interest (pop up the areas where the model ranks uranium context highest), give a clear visual representation, and show **on what basis** the model makes its inferences, ideally with solid geological reasoning.

## 2. What is and is not achievable (stated before building)
| Wanted | Achievable? | How |
|---|---|---|
| Interactive map, click a point | Yes | Leaflet, existing `/predict/point` |
| Highlighted areas of interest | Yes | Precomputed hot-spot polygons in three tiers (top 1 %, 5 %, 10 % of the study area) and a ranked list of the strongest clusters, each a popup with numbers |
| Basis of each inference | Yes, as **evidence** | Measured values at the clicked cell (eU, eTh, eK, 5 km mean uranium, geology unit, distance to fault, elevation), each compared with the whole survey, plus which model feature group drove the score |
| "Solid geological reasoning" | **Only partly** | The model knows one thing: the surroundings look like the surroundings of known occurrence cells. It has no geological understanding, so it cannot supply reasons of its own. The page will show a separate, clearly labelled **standard radiometric interpretation guide** (textbook rules such as the meaning of a high U/Th ratio), marked as general context and not as a model output |
| Proof of a deposit | No | The wording rule stays: ranking and labelled-positive density, never probability of a deposit |

## 3. Design decisions
| Decision | Why |
|---|---|
| Evidence, interpretation guide and model output are three visibly separate blocks in the panel | A reader must never mistake a textbook rule for something the model derived |
| Hot-spot **polygons** precomputed at build time (GeoJSON), not an image overlay | The grid is UTM 13N with grid convergence; an axis-aligned image on a lat/lon map would be shifted by kilometres. Polygons are reprojected exactly |
| Evidence values stored in a new `evidence.npz` (float16, about 40 MB) | The serving store deliberately holds no features; only the few values the panel needs are added |
| Areas ranked by number of top-1 % cells, then area | Favours compact strong clusters over big weak ones |
| Each area states whether it contains **known occurrences** | Areas with known occurrences are partly in-sample; areas without any are candidates but cannot be checked, so the page says so |
| No framework, no build step: `web/index.html`, `app.js`, `style.css`; Leaflet pinned from a CDN | One image, easy to read in an interview |
| All text from the API is inserted as text, never as HTML | Site names come from a public database; avoids script injection |
| The gate-G4 warning and the in-sample caveat are always visible | Honest limits stay on the page |

## 4. Acceptance checks (written first)
1. API: `/hotspots`, `/areas`, `/known` return valid data; `/predict/point` gains `evidence` and `reading`; old tests still pass.
2. Every polygon vertex falls inside the survey footprint's lon/lat bounds, and the top-1 % polygons contain at least 90 % of the top-1 % cell area (sanity check of the polygonisation).
3. In a browser: the map loads, tiers toggle, an area in the list flies to the map and opens a popup, a click shows evidence, a click outside the footprint shows a clear message, and no console errors occur.
4. Phone width (375 px) does not scroll horizontally.

Dated notes on deviations go below this line.

---

## 5. What was built (2026-11-21)
- **Build stage `10c_frontend_data`** (`src/mpm/frontend_data.py`, about 11 s): `models/final/evidence.npz` (24 MB, six float16 evidence values, geology unit and class per cell, survey quantiles) and `models/final/hotspots.json` (0.4 MB: three tiers of polygons, 23 ranked areas of interest, 199 known occurrences with names). Both come from the final map.
- **API additions:** `GET /hotspots`, `GET /areas`, `GET /known` (cached one hour; 503 with a clear message if the files are missing); `POST /predict/point` now also returns `evidence`, `nearest_known_occurrence` and `reading`. The site is served by the same FastAPI at `/` from `web/` (mounted last so API routes win).
- **Frontend** (`web/index.html`, `app.js`, `style.css`; Leaflet 1.9.4 from a CDN, no build step): street, terrain and satellite basemaps; red, orange and yellow tiers; numbered area markers with popups; known-occurrence layer; a ranked area list with a filter for areas with no known occurrence; click-anywhere point panel; a "Limits and method" tab with out-of-fold numbers, calibration bins and limitations; always-visible gate-G4 banner; dark mode; phone layout.
- **The point panel keeps four kinds of statement visibly separate:** measured evidence (with survey-percentile bars), what drove the model (feature groups), a textbook interpretation guide (labelled as not a model output, shown only when the data trigger a rule), and cautions.
- Streamlit app untouched, kept as a fallback.

## 6. Verification
- 6 new tests (`tests/test_frontend.py`), 64 pass in total: no-frontend-files fallback, guide rules (including that a quiet cell gets no textbook claim), static site does not shadow API routes, hot-spot structure and ranking, polygons cover at least 90 % of the cells they claim (measured 99.7-99.9 %), known-occurrence list lines up with stored positions, a real point returns evidence, and the site is served end to end.
- In the browser pane: map and basemap load; selecting Area 1 flies to it and opens its popup; clicking a hot-spot shows scores, evidence bars, drivers, guide and cautions; a click outside the footprint shows a clear message; no horizontal scroll at 375 px; no console errors apart from the intended 404 for the outside-footprint test.

## 7. Dated notes and deviations
- **Found while testing:** the first load fitted the map before its container had a size, which zoomed to level 18. Fixed by recalculating the map size before fitting and on every resize.
- **Label fix:** a peak at the very top printed "top 0.000 %"; now "<0.01 %". The tier chip now reads "in the top 10 % tier" so it is not mistaken for the score's exact rank.
- **Area size is the area of the top-5 % cells inside the cluster**, not the cluster's outline.

## 8. 🚩 Red flags and open items
1. **The geological guide is textbook general knowledge, not derived from this data.** I wrote the rules (U/Th ratio, all three high, sandstone setting, granitic source rock, near a fault). They are standard radiometric and Wyoming uranium context, but they have not been reviewed by a geologist. Have one check the wording before it is shown to anyone as more than a pilot.
2. **The panel shows evidence, not proof of "why".** At one test point the cell's own uranium was in the 99th survey percentile yet the model ranked it only in the top 6.4 %, because the model rewards high *surroundings* and gives point values a small or negative weight (Phase 9). The panel shows that honestly, which can look odd to a first-time reader.
3. **Areas with known occurrences are partly in-sample.** 10 of 23 areas contain known occurrences; the other 13 are candidates but cannot be checked against labels.
4. **Basemaps and Leaflet come from the internet** (OpenStreetMap, OpenTopoMap, Esri, unpkg). Offline use needs vendored copies; Esri and OpenTopoMap have usage terms to read before any public deployment.
5. **No authentication or rate limiting** (unchanged from Phase 10). `/hotspots` is 0.4 MB and cached for an hour.
6. **Not tested:** older browsers, screen-reader use beyond semantic markup, and tile-server outages.
7. **The Phase 11 image must include `web/` and the two new model files** (24 MB + 0.4 MB, on top of the 70 MB `serving.npz`).

## 9. Concepts learned
- A web map cannot take an image from a projected grid at face value; polygons are reprojected exactly, or the overlay is kilometres out.
- Static files mounted last: API routes registered first win.
- Separating evidence, model output and general guidance in the UI is an honesty feature, not just a layout choice.
- Insert API text with `textContent`, never as HTML.

## 10. How to run
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
.\.venv\Scripts\python.exe -m uvicorn mpm.api:app --app-dir src --port 8000
```
Then open http://127.0.0.1:8000/ (the API docs stay at /docs).

## 11. Dated note on what was not checked by hand (2026-11-21)
Acceptance check 3 listed "tiers toggle". I did not click the layer toggles in the browser; they are standard Leaflet layer-group switches and were not covered by an automated test. The other items in check 3 and check 4 were exercised as described in section 6.
