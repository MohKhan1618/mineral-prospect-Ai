# Phase 10b - East survey-block step check

Status: rule written before results, 2026-11-21.   Follows the red flag raised in [phase-10-final-model.md](phase-10-final-model.md) (item 3).

## 1. Question
In the east of the map the raw uranium grid (`U_FIN`) steps from about 14 to about 33 cps across one straight line (near easting 342.5 km), and the final score map has a straight-edged hot block there. Is the step a **real geological contact**, or an **acquisition / levelling artefact** between survey blocks?

## 2. What the contractor report gives us
- The survey was flown as six sub-blocks A01-A06, all at 200 m line spacing, with 400 m overlap between neighbours (report section 2, Tables 2-1 to 2-6, UTM 13N metres, same CRS as our grid).
- Three helicopters and three spectrometers (RS 5505, RS 5610, RS 6052) were used, calibrated on different dates.
- The A05 / A06 boundary lies at easting 340,160 m (south part, northing 4,662,680-4,677,735) and 344,300 m (north part, northing 4,677,735-4,693,820). The step lies between those two values.
- The data are described as microlevelled (Appendix F), but microlevelling only removes line-to-line noise inside a block; it does not guarantee agreement between blocks.

## 3. Rule (written before looking at the data)
Measure, in northing bands of 2.5 km across the east, the easting where the smoothed `U_FIN` profile changes most (largest absolute difference of 1 km mean on each side).

| Outcome | Condition |
|---|---|
| **Artefact supported** | In at least two thirds of the bands that show a step (relative jump >= 30 %), the step lies within 1 km of a block boundary from the report, **and** the same rock class (geology map) occurs on both sides of the step in those bands |
| **Real contact supported** | In at least two thirds of those bands the step lies more than 2 km from every block boundary, **or** the geology class changes at the step |
| **Inconclusive** | Anything else |

Also recorded, not part of the rule: the same test on thorium and potassium (an acquisition difference tends to move all three channels together; a uranium-only contact points to geology), and whether the step coincides with a mapped fault.

## 4. What happens after
- Artefact supported: raise the flag in the model card and the app, list the affected area, and decide **with the user** whether to mask it, level it, or keep it and warn. No silent re-run.
- Real contact supported: remove the flag, keep the note.
- Inconclusive: keep the flag, state what data would settle it (the flight-line databases, which we skipped).

Dated notes on any deviation go below this line.

---

## 5. Results (2026-11-21)
Scripts: `scripts/phase10b/` (`eastcheck.py` the pre-written band rule, `scan.py` whole-survey scan, `cv.py` CV-edge and final-map scan, `p342.py` direct profile, `zoom.py` plots). Figures: `reports/figures/phase10b_east_overview.png`, `phase10b_east_zoom.png`. Block edges were parsed from report Tables 2-1 to 2-6.

1. **Band rule, applied as written:** 14 northing bands of 2.5 km, 9 with a relative uranium jump of 30 % or more. 3 of 9 were within 1 km of a block edge, 5 of 9 were more than 2 km away. Neither reaches two thirds, so by the letter of the rule the outcome is **inconclusive**. The detected positions scatter between easting 344 and 351 km rather than lining up, and the three largest jumps are at the southern survey edge or next to water (U about 1-2 cps), which are not block effects.
2. **Whole-survey scan for straight vertical step lines in raw U** (log ratio at least 0.25 on the same sign over a long length): none exists. The straightest lines change U by only 8-19 %. The two that fall on a block edge (344.4 km, +10 % over 12 km; 340.4 km, -8 % over 15 km) are small.
3. **Direct profile at easting 342.5 km:** U changes gradually (for example 13 → 17 cps across 342 → 343 km in one band, 12 → 13 in the next). The "14 to 33 at one line" figure in the Phase 10 record **could not be reproduced**. The likely source was a comparison across the survey's no-data notch (x 336-346 km, northing 4680-4700 km), where the west side is empty and the east side is a genuinely high-uranium and high-thorium area (U 42-50 cps, TH also high, patchy shapes that follow geology, not a straight line).
4. **The straight-edged rectangle seen in the score map is a cross-validation artefact of the out-of-fold map.** Its edges (easting 354.85 km; northings 4684.4 and 4669.4 km) are exactly 15 km CV block edges, and the out-of-fold score is ranked within each fold, so adjacent blocks scored by different models and fold-ranked step against each other. The **final map** (the one the app and API serve) has no such step: the largest straight step in the final percentile map is 0.05 in percentile.
5. Thorium and potassium were not found to step with uranium at any block edge.

## 6. Conclusion
**No survey-block levelling artefact was found.** The red flag as I stated it in Phase 10 was a misreading (a no-data notch and the CV edges of the out-of-fold map), and it is withdrawn. Evidence is that no straight step exists in the raw grids, and the final map is smooth. Not tested: the flight-line databases (skipped) could still hold small between-aircraft offsets below the 8-19 % level, and a 10 % offset between blocks would not be detected by this scan.

## 7. Items that remain open (smaller than the withdrawn flag)
- 🚩 **Survey-edge notch at easting about 344 km, northing 4677-4694 km:** neighbourhood features near an edge average over fewer valid cells (already on the edge watch list). The hot area just east of the notch is partly an edge neighbourhood; it is not shown to be wrong, but its percentile is less reliable than the interior.
- ⚠ **The out-of-fold map (`reports/maps/score_percentile_oof_logreg.tif`) shows straight edges at CV block borders.** It is a validation object, not a product map. Do not read prospectivity into its block shapes.
- Between-aircraft offsets smaller than about 10 % remain untested.

## 8. Concepts learned
- A straight edge in a model map has several possible origins: the data (survey blocks), the model inputs (geology polygons), or the validation design (fold borders). Check them in that order with a test, not by eye.
- Percentile ranking within folds is not comparable across folds.
- Writing the rule first protected against forcing a conclusion: the rule came out inconclusive, and the additional scans were added as dated post-hoc evidence, not as a replacement result.

## 9. Dated note on a deviation from section 4 (2026-11-21)
Section 4 said an inconclusive rule outcome keeps the flag. The rule outcome was inconclusive, yet the flag is **withdrawn**. Reason: the rule's premise was a single straight step, and the post-hoc scans (sections 5.2-5.4) show the original flagged step does not exist in the data and that the straight edge came from the validation design. The withdrawal rests on those post-hoc scans, which were chosen after seeing the band results; a reader should weigh it as such. What is NOT excluded is a small between-block offset (under about 10 %), which stays listed as open.
