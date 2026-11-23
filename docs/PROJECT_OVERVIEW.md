# Mineral Prospectivity Pilot: Uranium, South Pass - Granite Mountains, Wyoming

**Owner:** Mohsin   **Status:** all phases complete (0-13); deployed to Google Cloud Run (free-trial account, stops 2026-12-17 unless upgraded). Teaching pass and quizzes still pending.
**Rule for this file:** every statement must stay true. The "What I can explain" table in section 6 is updated only when a
lesson quiz has actually been passed.

## 1. What this project is
A pilot that ranks every 50 m cell of an 8,630 km² area of Wyoming by how closely its radiometric, geological and structural
surroundings resemble the surroundings of 199 known uranium occurrences. It uses public data only (USGS airborne survey,
SRTM elevation, state geology map, mapped faults, USGS MRDS occurrence records). It is a learning and portfolio pilot, not a
tool for drilling, investment or land decisions.

## 2. Why I built it
I have a geology degree and work as a full-stack engineer and ML practitioner. I wanted an end-to-end project that joins the
two: from raw geoscience data through honest validation to a deployed, explainable web map, tied to an AI/ML
uranium-discovery internship posting.

## 3. What I did (the work I own)
- **Defined the whole scope**, from data collection to deployment: validation, preprocessing, feature extraction, model
  selection, training, cross-validation, bias/variance checks, evaluation (ROC-AUC, PR-AUC, precision, recall, top-k % lift),
  tuning, model saving, Docker, GCP.
- **Set the working rules:** decision rules written before results, red flags raised in chat and in the records, phase
  records and a decision log for every step, no deployment without my explicit go-ahead, and a full from-scratch teaching
  pass so I can defend everything.
- **Did the hands-on data inspection myself:** downloaded and extracted the data, opened the radiometric grids in the
  Geosoft Viewer, read the histogram and values, exported the grids and re-checked them; explored the MRDS records in Jupyter.
- **Approved or rejected every phase and every decision rule**, including accepting that validation gate G4 was not met.
- **Proposed two extensions of my own:** clustering as an alternative or complement to the classifier, and stacking the two.
  Both were run under rules written first, and both were rejected on the evidence.
- **Chose the frontend's purpose and audience** (an interactive map that shows the areas of interest and the evidence behind
  each score, for both a demo and a geologist audience).
- **Own the GCP account, billing and credentials.**

## 4. How it was built
I built it with Claude Code as an AI coding assistant. It wrote the code, ran the training and experiments, and proposed the
specific modelling and validation techniques (positive-unlabeled framing, spatial block cross-validation with a 2 km buffer,
block bootstrap, recall in the top 5 %, the model ladder, the logistic-regression choice by a pre-written rule). I reviewed
and approved these, and the decision log records the reasons. Where the code or a result came from the assistant, the phase
records say so.

## 5. Results (honest numbers)
- 199 positive cells (98 are mine records), 3,452,181 cells, 44 features used.
- Chosen model: logistic regression. Out-of-fold, 15 km spatial blocks: ROC-AUC 0.86 [0.72, 0.92], recall in the top 5 % of
  the area 0.61 [0.33, 0.76] (non-producers 0.43). The raw uranium reading alone gets 0.83 and 0.53.
- **Validation gate G4 was not met:** the model does not clearly beat the raw uranium baseline. The product is described as a
  radiometric-uranium ranking with modest added value.
- Clustering alone found 26 % (non-producers) in the top 5 %, and adding it to the model or stacking it gave no gain. Both
  were rejected.
- Scores are a ranking of similarity to known occurrences, not the probability of a deposit.

## 6. What I can explain (updated only after a quiz is passed)
| Area | Status |
|---|---|
| Problem and how geologists explore (Lessons 1-3) | Lessons delivered; quiz not yet passed |
| Data, labels, features (Lesson 4) | Delivered; quiz not yet passed |
| What the model learns, validation, score meaning (Lesson 5) | Delivered; first self-check needs a re-answer |
| Results, gate G4, limits | Pending |
| Running the app and demo | Pending |

## 7. Limits
Radiometrics are local; positives sit in two main districts; mine records are about half the labels; the survey sees only the
top half-metre, while the target deposits are buried; no groundwater, redox, radon or drilling data; the map is in-sample
at the 199 known cells; the geological guide text has not been reviewed by a geologist; no authentication on the API.

## 8. Where to look
| For | See |
|---|---|
| Phase-by-phase records | `docs/phases/` |
| Every decision and reason | `docs/decisions.md` |
| Who did which part of the data inspection | `docs/data_inspection_journal.md` |
| The web page, demo script | `docs/FRONTEND_GUIDE.md` |
| Model purpose and limits | `docs/MODEL_CARD.md` |
| Clustering and stacking experiments | separate folder `mineral-exploration-using-AI-clustering` (own Git repo) |
