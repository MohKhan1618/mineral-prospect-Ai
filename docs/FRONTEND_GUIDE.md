# Frontend guide and demo script

For explaining the project to people who will never see the ML code. Everything here matches what the page and the validation records say; where a number appears, it comes from `docs/MODEL_CARD.md` or the Phase 8-10 reports.

---

## 1. What the project is (the introduction)

**One sentence:** a pilot map that ranks every 50 m cell of a surveyed part of Wyoming (South Pass - Granite Mountains) by how closely its radiometric surroundings resemble the surroundings of places where uranium has already been found.

**The problem it addresses.** Exploration geologists look at airborne measurements (gamma-ray and magnetic) to decide where to spend time. The area is large (about 8,600 km2 of valid cells) and the data are many layers deep. A ranking helps decide which patches to look at first.

**What goes in (all public data):**
| Data | What it tells us |
|---|---|
| USGS airborne survey, 2023, helicopter, 200 m line spacing | Gamma-ray counts for uranium (eU), thorium (eTh), potassium (eK); magnetic field |
| SRTM elevation | Terrain |
| USGS state geologic map (SGMC) | Rock type, contacts |
| Mapped faults | Structure |
| USGS MRDS uranium records | 199 known occurrence cells (about half are mines) used as the "answers" |

**What the model is:** a regularised logistic regression. It was trained to separate the 199 known-occurrence cells from a sample of 40,000 other cells. "Other" means *unlabeled*, not "no uranium", because undiscovered deposits are hiding in it.

**What comes out:** a score for every cell, turned into a percentile rank ("top 8.4 % of the study area"), shown on a map.

**What it is not:** a prediction that uranium is present, a resource estimate, or something to base drilling, investment or land decisions on.

---

## 2. How the page works (answering "where do the inputs come from?")

Your understanding is right, with one refinement.

- **There is no user input to the model.** The user never types data. The only thing the user supplies is a *location*: a click.
- **The model does not run when you click.** It was run once, ahead of time, on every one of the 3.45 million cells. The results were stored in a lookup file (`serving.npz`). A click converts the location to a grid cell and *looks up* that cell's stored score, evidence and drivers. This guarantees the page shows exactly what the model computed, and it is why the app is fast and small.
- The same stored data also produce the **coloured areas** drawn on load.

```
 Build time (once, in the pipeline)               Run time (every visit)
 ---------------------------------               ----------------------
 survey + geology + faults + MRDS                 browser loads the page
        |                                               |
 features per cell (49)                          loads polygons, areas, known points
        |                                               |
 train model, score all 3.45M cells               user clicks a point
        |                                               |
 store scores, ranks, drivers, evidence --------> API looks up that cell and returns it
```

---

## 3. The page, element by element

### 3.1 The header
- **Title and subtitle:** what the page is and the area it covers.
- **Limits & method button:** jumps to the tab that explains the method and its weaknesses.

### 3.2 The yellow banner (always visible)
"Pilot, not for decisions." It states that validation gate G4 was not met, meaning the model does **not clearly beat simply reading the raw uranium map**, and that the colours are a ranking, not a probability of a deposit. It stays on screen on purpose.

### 3.3 The map
| Element | What it does |
|---|---|
| **Basemap switch** (Street / Terrain / Satellite) | Changes the background so a user can see roads, relief or the ground itself |
| **Red / orange / yellow patches** | The ranking. **Red = top 1 %** of all cells, **orange = top 5 %**, **yellow = top 10 %**. Red sits on top of orange on top of yellow |
| **Numbered red circles** | The **areas of interest**: the 23 strongest clusters, numbered 1 to 23, strongest first. Click one for a popup |
| **Teal rings and dots** | The **known occurrences** (public USGS records). Filled dots are producers or past producers. They are the training labels |
| **Layer checkboxes** | Hot-spot tiers, Areas of interest, Known occurrences can each be switched on or off |
| **Legend** (bottom left) | Colour key |
| **Black dot + small popup** | The spot you last clicked and its tier |
| **Click anywhere inside the survey** | Fills the Selected point tab. Outside the survey you get "outside the surveyed footprint" (there is no score) |

### 3.4 Right panel, tab 1: Areas of interest
A ranked list of the 23 clusters. Each card shows:
- **Number and name**, area in km2 (the area of the top-5 % cells inside it).
- **Badge:** "N known inside" or "no known occurrence".
- **Peak top %:** the best-ranked cell in the cluster.
- **Rock type**, average **eU, eTh, eK** in counts per second, and the **main driver** of the score.
- A sentence stating whether it is partly in-sample.
- **Selecting a card** zooms the map to it and opens its popup.
- **Checkbox "Only areas with no known occurrence inside"** shows the 13 candidate areas.

**How to read the badge (important):** the model was trained on the known occurrences. An area that contains them is partly "re-found" and proves little. An area with none is a more interesting candidate, **but nothing there can be checked against any label**.

### 3.5 Right panel, tab 2: Selected point (the main explanation)
Top to bottom:

1. **Big number, "Top 8.4 %":** the cell scores higher than 91.6 % of all cells in the survey.
2. **Tier chip, "in the top 10 % tier"** and **score bin:** which of the colour groups it falls in.
3. **Observed rate, "1.0 x 10^-4 known-occurrence cells per cell (1.8x the average cell)":** from the validation runs, how often known occurrences were found in cells with a score like this. Cells in this bin held known occurrences 1.8 times as often as an average cell. This is a **lower bound** (unlabeled cells may hide undiscovered deposits), **not the probability of a deposit**.
4. **Model disagreement, "low (descriptive only)":** how much four different model types and three training splits disagree about this cell. It is a hint, not a validated error bar.
5. **Block 1, Evidence (blue): what is measured here.** Bars show where this cell sits among the whole survey (a bar at 81 % means 81 % of the survey is lower). The vertical line is the median. Covers uranium (eU), the 5 km average uranium, thorium, potassium, the U/Th ratio, then plain-language lines, rock unit, distance to the nearest fault, elevation, and the **nearest known occurrence**.
6. **Block 2, What drove the model's score (orange):** which groups of inputs pushed the score up or down compared with a typical cell: *neighbourhood* (averages in the 1-5 km around), *radiometric* (the cell itself), *magnetic*, *terrain*, *structure*, *geology*. Numbers are in logit units; larger means stronger push.
7. **Block 3, Interpretation guide (purple): textbook, not a model output.** General radiometric rules of thumb that appear only when the data trigger them (for example a high U/Th ratio, all three radioelements high, a sandstone setting). The model did not use them.
8. **Block 4, Cautions (red):** what the model cannot tell you, plus cell-specific warnings (for example "this cell is a known training occurrence, its score is optimistic", near the survey edge, on loose cover).
9. **Footer:** the wording rule, cell centre coordinates, distance to the survey edge.

**Why four separate colours?** So nobody mistakes a general geology rule for something the model worked out.

### 3.6 Right panel, tab 3: Limits & method
The honest numbers (section 4 below), the calibration table, how to read the map, and the full limitations list.

---

## 4. Capabilities and limitations

### What it can do
- Rank any surveyed cell by radiometric resemblance to known occurrences, and show *why* in terms of measured values.
- **Out-of-fold performance** (validated by holding out whole 15 km map blocks, so near-duplicates never leak):
  - Looking only at the best-scored 5 % of the area finds about **61 %** of known occurrences (95 % interval 33-76 %); for the 101 non-producer occurrences about **43 %** (23-60 %). Random choice would find 5 %.
  - ROC-AUC about **0.86** (0.72-0.92).
  - Observed rate by score bin: top 0.1 % about 95 times the average cell, top 1 % about 40 times, top 5 % about 3.9 times, top 10 % about 1.8 times; the bottom half is below average.
- Clearly beats a hand-made geology rule (ROC-AUC 0.86 against 0.71).
- Reproducible: re-running the pipeline rebuilds everything; the saved model reloads bit-identically.

### What it cannot do
1. **It does not clearly beat the raw uranium count** (0.53 recall in the top 5 %, intervals overlap). The model adds modest value over simply reading the uranium map. This is the unmet **gate G4**.
2. **It is almost entirely a radiometric-neighbourhood ranking.** Shuffling those features drops recall in the top 5 % from 0.61 to about 0.10. Geology, terrain, magnetic and structure features added nothing measurable.
3. **It does not transfer to small or new districts.** A 13-occurrence district was found only at about 8-15 % (barely above the 5 % chance level).
4. **No geological understanding.** It cannot say why a deposit would exist.
5. **Training labels are imperfect:** half are mines, positions are approximate, and "unlabeled" includes undiscovered deposits.
6. **Radiometrics see only the top 30-50 cm of ground,** so mineralisation under cover is invisible.
7. **The map is in-sample at the 199 known cells.** Any "found X of 199" read directly off the final map is optimistic; only the out-of-fold numbers count.
8. **Not tested:** roads and infrastructure effects, other surveys or geology, small between-block survey offsets, any independent new discovery.
9. The "interpretation guide" text is general knowledge written for this page and **has not been reviewed by a geologist**.

---

## 5. A worked example from your screenshots

Cell near 42.4668, -107.7505:
- **Top 8.4 %**, "in the top 10 % tier", observed rate 1.8x the average cell, disagreement low.
- **Evidence:** eU 21.1 cps (above 81 % of the survey), 5 km average 21.2 cps (86 %), eTh 37.6 (82 %), eK 105.7 (85 %), U/Th 0.56 (about the survey median 0.59). Rock: sedimentary, clastic, Miocene rocks; fault 3.2 km away; elevation 1,929 m.
- **Nearest known occurrence:** "Allied Group Dead Horse 29", **0.0 km away**. So this click landed on a known training cell, and the panel correctly warns the score is in-sample.
- **Drivers:** neighbourhood +1.3, radiometric +0.4, geology +0.3. The surroundings (average uranium, thorium and potassium nearby) are what lifted it.
- **Guide:** a sandstone setting. **Caution:** the model cannot say why; this is a training cell.

**Demo tip:** do the first click on a known occurrence (to show the in-sample warning), then click a spot in an orange area **with no teal dot nearby**, so the example is not in-sample.

---

## 6. A 5-minute demo script

1. **(30 s) Frame it.** "This is a pilot that ranks places in a Wyoming uranium district by how much their radiometric surroundings look like known occurrences. It's a learning and portfolio project, and the yellow banner says it isn't for decisions."
2. **(45 s) The map.** Point out the legend, the three colours, the numbered areas, the teal known occurrences. "Red is the top 1 % of the survey, orange 5 %, yellow 10 %."
3. **(45 s) Areas of interest.** Open the list, select Area 1, then tick "no known occurrence inside" and select a candidate. "Areas with known occurrences are partly re-found. These are the ones we cannot check."
4. **(90 s) Click a point.** Walk the panel top to bottom: rank, observed rate ("a lower bound, not a probability"), evidence bars, drivers, then the purple guide ("textbook, not the model"), then cautions.
5. **(60 s) Limits tab.** "Looking at the best 5 % finds about 61 % of known occurrences, but the raw uranium map alone finds about 53 %. The difference is within the uncertainty. We report that openly."
6. **(30 s) Close.** "What I'd do next: more labels from other districts, tests on a held-out district, and a geologist reviewing the guide."

---

## 7. Questions people will ask

| Question | Honest answer |
|---|---|
| Does it find uranium? | It ranks areas by resemblance to known occurrences. It does not detect or predict deposits |
| How accurate is it? | Best 5 % of the area catches about 61 % of known occurrences (33-76 %), about 43 % for non-mine occurrences, in validation. That is about 12 times better than random, but not clearly better than the raw uranium map |
| Why not deep learning? | Only 199 clustered labels; a neural network would overfit and could not be explained. Future work |
| Why no "probability"? | Unlabeled cells include undiscovered deposits, so true probabilities cannot be learned. We report observed rates, a lower bound |
| Why do some high-uranium cells rank low? | The model rewards high *surroundings* more than the cell's own value (point values may be a little off their true position) |
| Is it ready for real use? | As a first-pass screening layer in the trained area, with caveats, yes. For decisions, no |
| Can it work elsewhere? | Untested; it did not transfer to small districts in this area |

---

## 8. Where things live (for you)
| Part | File |
|---|---|
| Page | `web/index.html`, `web/app.js`, `web/style.css` |
| API | `src/mpm/api.py` (`/hotspots`, `/areas`, `/known`, `/predict/point`, `/model-info`) |
| Lookup and evidence text | `src/mpm/serve.py` |
| Polygons, areas, evidence build | `src/mpm/frontend_data.py` |
| Model, scoring, stored artefacts | `src/mpm/final.py`, `models/final/` |
| Honest numbers | `docs/MODEL_CARD.md`, `docs/phases/phase-08-*.md`, `phase-09-*.md` |
| Run | `.\.venv\Scripts\python.exe -m uvicorn mpm.api:app --app-dir src --port 8000`, then http://127.0.0.1:8000/ |
