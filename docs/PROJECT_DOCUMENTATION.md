# Project Documentation - Mineral Prospectivity Mapping (Uranium)

Living document, updated at the end of every phase.

## 1. Purpose
A CPU-only, crash-safe machine-learning pipeline that ranks map cells by relative uranium
favorability from public geoscience data, with a web app deployed on GCP. It is a learning and
demonstration project: it ranks areas worth a closer look, it does not discover deposits.

## 2. Problem statement
Uranium exploration is slow and expensive; geologists combine many weak clues (geology,
radiometrics, magnetics, structure, topography). We test whether an ML model can combine those
layers to rank cells, and we measure honestly how well it does when known occurrences are few.

## 3. Documentation map
| Document | Purpose |
|----------|---------|
| `PLAN.md` | Phase plan, gates, crash-safety rules |
| `docs/PROJECT_DOCUMENTATION.md` | This file: overview, status, architecture, glossary |
| `docs/phases/phase-NN-*.md` | One record per phase: what, why, challenges, results |
| `docs/phases/TEMPLATE.md` | Template for a phase record |
| `docs/decisions.md` | Chronological decision log |
| `docs/data_inspection_journal.md` | Who inspected what, with which tool, and what it showed |
| `docs/data_catalog.md` | (Phase 1) every dataset: source, license, format, resolution |
| `docs/model_card.md` | (Phase 10) model purpose, data, metrics, limits |
| `docs/PROJECT_OVERVIEW.md` | Owner-voice overview: what I did, how it was built with AI assistance, results, what I can currently explain |
| `docs/FRONTEND_GUIDE.md` | (Phase 10c) plain-language tour of the web page, capabilities and limits, 5-minute demo script, likely questions |
| `reports/` | Generated validation, evaluation reports and figures |

## 4. Phase status
| Phase | Name | Status | Record |
|-------|------|--------|--------|
| 0 | Foundation | Done | [phase-00](phases/phase-00-foundation.md) |
| 1 | Framing, region, positive-count gate | Done (extents to confirm in Phase 2) | [phase-01](phases/phase-01-framing-and-gate.md) |
| 2 | Data collection | Done (flags carried to Phase 3) | [phase-02](phases/phase-02-data-collection.md) |
| 3 | Raw validation and EDA | Done | [phase-03](phases/phase-03-raw-validation-eda.md) |
| 4 | Preprocessing and master grid | Done | [phase-04](phases/phase-04-preprocessing-master-grid.md) |
| 5 | Labels and spatial splits | Done (flags carried to Phase 8) | [phase-05](phases/phase-05-labels-splits.md) |
| 6 | Feature engineering | Done (flags carried to Phase 7/8) | [phase-06](phases/phase-06-feature-engineering.md) |
| 7 | Baselines and model training | Done | [phase-07](phases/phase-07-models-training.md) |
| 8 | Cross-validation and rigorous evaluation | Done, **G4 not met** (see record) | [phase-08](phases/phase-08-evaluation.md), [rule](phases/phase-08-decision-rule.md) |
| 9 | Interpretation, calibration, uncertainty | Done, with caveats (see record) | [phase-09](phases/phase-09-interpretation.md), [rule](phases/phase-09-decision-rule.md) |
| 10 | Final model, API and app | Done, with caveats (see record) | [phase-10](phases/phase-10-final-model.md), [model card](MODEL_CARD.md) |
| 10b | East survey-block step check | Done: step not found, flag withdrawn (see record) | [phase-10b](phases/phase-10b-east-block-check.md) |
| 10c | Web frontend (Leaflet, areas of interest, evidence panel) | Done, with caveats (see record) | [phase-10c](phases/phase-10c-frontend.md) |
| 11 | Dockerization | Done (332 MB image, non-root, healthy; clean-clone check passed) | [phase-11](phases/phase-11-dockerization.md) |
| 12 | GCP deployment | Deployed (public, Cloud Run; trial ends 2026-12-17) | [phase-12](phases/phase-12-gcp-deploy-prep.md) |
| 13 | Wrap-up | Done (README, diagram, records); second region not done; teaching pass pending | [phase-13](phases/phase-13-wrap-up.md) |

## 5. Architecture (current)
```
config/config.yaml --> scripts/run_pipeline.py --> stages (src/mpm/*)
                                 |                     |
                        .state/<stage>.json     data/{raw,interim,processed,features,splits}
                        (fingerprints)          models/  reports/
```
Each stage: files in, files out, skipped when its fingerprint and outputs are unchanged.

## 6. Environment
Windows 11, Python 3.13 virtual environment (`.venv`), 8 GB RAM, Intel i5-1035G1, no NVIDIA GPU.
CPU-only methods, float32 and tiled raster processing.

## 7. Glossary (grows each phase)
Geology and ML terms are added as they are introduced, each with the link between the two.
- **Idempotent stage** (Phase 0): safe to run twice.
- **Fingerprint** (Phase 0): hash of inputs and settings used to detect stale results.
- **Positive / unlabeled** (Phase 1): known occurrences are positives; all other cells are unlabeled, not proven barren.
- **Prevalence** (Phase 1): fraction of positive cells; the score a random model gets on PR-AUC.
- **Raster picture vs data** (Phase 2): an RGB GeoTIFF is a coloured image, not measurements.
- **Red flag** (Phase 2 on): a risk I raise in chat and record in the phase record, marked with a flag.
- **Master grid / mask** (Phase 4): the one grid every layer is aligned to, and the cells valid in all layers.
- **Spatial block CV** (Phase 5): whole map blocks go to one fold so near-identical neighbours never sit in both train and test.
- **Excluded buffer** (Phase 5): cells near a positive, kept out of the unlabeled background.
- **Log-ratio** (Phase 6): log of a ratio with +1 added to both parts; defined at zero and symmetric.
- **Neighbourhood feature** (Phase 6): mean/std of a layer in a window (1 km, 5 km) around each cell.
- **Feature-major matrix** (Phase 6): features.npy, one row per feature, one column per valid cell.
- **Buffered spatial CV** (Phase 7): training cells within 2 km of a test positive are removed, so no training cell is a near-copy of a test positive.
- **Recall@top p% / lift** (Phase 7): share of positives found when only the best-scored p% of cells are examined; lift = that divided by p.
- **Out-of-fold score map** (Phase 7): each cell scored by a model that never saw its block.
- **Block bootstrap** (Phase 8): resample whole map blocks (with their positives) to get honest confidence intervals for clustered data.
- **Inclusive evaluation** (Phase 8): the ring around positives counts as unlabeled, so look-alike cells are scored.
- **Leave-one-district-out** (Phase 8): hold out an entire uranium district; the hardest, most realistic transfer test.
- **Nested CV** (Phase 8): hyper-parameters chosen by an inner spatial CV that never sees the outer test blocks.
- **MRDS** (Phase 1): USGS Mineral Resources Data System, the occurrence-point source (2022 snapshot).

## 8. Reproduce from scratch
See the "How to reproduce" section of each phase record; Phase 11 adds a one-command Docker run.

- **Permutation importance** (Phase 9): shuffle one feature (or group) in held-out cells and measure how much the ranking worsens.
- **Calibration** (Phase 9): do predicted probabilities match observed rates? Here only the labelled-positive rate, a lower bound.
- **Moran's I** (Phase 9): measures whether neighbouring values are alike; used on model misses to see if they cluster in space.
