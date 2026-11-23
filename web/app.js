/* Uranium prospectivity pilot - single-page frontend. No build step; Leaflet is the only dependency.
 * All text from the API is inserted with textContent (never as HTML). */
"use strict";

const TIER_STYLE = {
  top10: { color: "#f6d55c", fillOpacity: 0.38, weight: 0, label: "Top 10 % of study area" },
  top5:  { color: "#f28a1f", fillOpacity: 0.5,  weight: 0, label: "Top 5 %" },
  top1:  { color: "#d7191c", fillOpacity: 0.65, weight: 1, label: "Top 1 %" },
};
const GROUP_TITLES = {
  measured: ["Evidence: what is measured here", "Values from the survey and maps at this spot, compared with the whole survey."],
  model: ["What drove the model's score", "Feature groups ranked by how far they moved this cell's score from a typical cell."],
  guide: ["Interpretation guide (textbook, not a model output)", "General radiometric rules of thumb. The model did not use or derive these."],
  caution: ["Cautions", "Read these before relying on the number."],
};

const $ = (s, r = document) => r.querySelector(s);
function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === false || v == null) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return n;
}
const fmtTop = (p) => { const t = (1 - p) * 100; return t < 0.01 ? "<0.01" : t < 0.1 ? t.toFixed(2) : t < 10 ? t.toFixed(1) : t.toFixed(0); };
const pctText = (x) => (x * 100).toFixed(0) + "%";
const sci = (x) => Number(x).toExponential(1).replace("e-", " x 10^-").replace("e+", " x 10^");
function tierOf(p) { return p >= 0.99 ? ["t1", "Top 1 %"] : p >= 0.95 ? ["t5", "Top 5 %"] : p >= 0.90 ? ["t10", "Top 10 %"] : ["t0", "Below the top 10 %"]; }


/* ---------- units and coordinates ----------
 * The survey grids are counts per second (cps). Geologists usually think in ppm (eU, eTh) and % (eK). These are rough
 * conversions with the survey sensitivities (contractor report Table 6-16), NOT calibrated concentrations.
 * Keep in step with SENS_* in src/mpm/serve.py (a test checks this). */
const SENS = { U: 10.4, Th: 6.2, K: 99.5 };
const ppmU = (cps) => cps / SENS.U;
const ppmTh = (cps) => cps / SENS.Th;
const pctK = (cps) => cps / SENS.K;
const f1 = (x) => Number(x).toFixed(1);
const f2 = (x) => Number(x).toFixed(2);

/* UTM zone 13N (EPSG:32613, the project grid), WGS84, Krueger series; well under a metre in this zone. */
function toUTM13(lat, lon) {
  const a = 6378137.0, f = 1 / 298.257223563, k0 = 0.9996, lon0 = -105 * Math.PI / 180;
  const n = f / (2 - f), n2 = n * n, n3 = n2 * n, n4 = n3 * n;
  const A = a / (1 + n) * (1 + n2 / 4 + n4 / 64);
  const alpha = [n / 2 - 2 * n2 / 3 + 5 * n3 / 16, 13 * n2 / 48 - 3 * n3 / 5, 61 * n3 / 240];
  const phi = lat * Math.PI / 180, lam = lon * Math.PI / 180 - lon0;
  const e = Math.sqrt(f * (2 - f));
  const t = Math.sinh(Math.atanh(Math.sin(phi)) - e * Math.atanh(e * Math.sin(phi)));
  const xi = Math.atan2(t, Math.cos(lam));
  const eta = Math.atanh(Math.sin(lam) / Math.sqrt(1 + t * t));
  let E = eta, N = xi;
  alpha.forEach((al, i) => { const j = i + 1; E += al * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta); N += al * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta); });
  return { e: 500000 + k0 * A * E, n: k0 * A * N };
}
const fmtLL = (lat, lon) => `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
function fmtUTM(lat, lon) { const u = toUTM13(lat, lon); return `UTM 13N  E ${Math.round(u.e)}  N ${Math.round(u.n)}`; }
async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; }
  catch (_) { btn.textContent = "Copy failed"; }
  setTimeout(() => { btn.textContent = "Copy"; }, 1500);
}
/* A labelled coordinate line "label  lat, lon  [Copy]" plus the UTM line. Text only (no HTML). */
function coordBlock(label, lat, lon) {
  const btn = el("button", { class: "copy", type: "button", text: "Copy", title: "Copy as latitude, longitude (paste into Google Maps or a GPS)" });
  btn.addEventListener("click", (ev) => { ev.stopPropagation(); copyText(fmtLL(lat, lon), btn); });
  return el("div", { class: "coord" },
    el("span", { class: "clabel", text: label }), " ", el("span", { class: "cval", text: fmtLL(lat, lon) }), " ", btn,
    el("div", { class: "cutm", text: fmtUTM(lat, lon) }));
}

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) { const e = new Error(`${r.status}`); e.status = r.status; try { e.detail = (await r.json()).detail; } catch (_) {} throw e; }
  return r.json();
}

/* ---------- state ---------- */
const state = { areas: [], known: [], info: null, areaLayers: new Map(), marker: null };
let map, tierGroup, areaGroup, knownGroup;

/* ---------- tabs ---------- */
function showTab(name) {
  for (const t of ["areas", "point", "about"]) {
    const on = t === name;
    $("#t-" + t).setAttribute("aria-selected", on ? "true" : "false");
    $("#p-" + t).hidden = !on;
  }
}
for (const t of ["areas", "point", "about"]) $("#t-" + t).addEventListener("click", () => showTab(t));
$("#btn-about").addEventListener("click", () => { showTab("about"); $("#p-about").scrollTop = 0; });

/* ---------- map ---------- */
function setStatus(text) { const s = $("#map-status"); s.hidden = !text; s.textContent = text || ""; }

function initMap() {
  map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([42.4, -107.9], 8);
  const street = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" });
  const topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", { maxZoom: 17, attribution: "&copy; OpenTopoMap (CC-BY-SA), OpenStreetMap contributors" });
  const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 18, attribution: "Imagery &copy; Esri and contributors" });
  street.addTo(map);
  tierGroup = L.layerGroup().addTo(map);
  areaGroup = L.layerGroup().addTo(map);
  knownGroup = L.layerGroup().addTo(map);
  L.control.layers({ "Street": street, "Terrain": topo, "Satellite": sat },
    { "Hot-spot tiers": tierGroup, "Areas of interest": areaGroup, "Known occurrences": knownGroup },
    { collapsed: window.innerWidth < 900 }).addTo(map);
  const legend = L.control({ position: "bottomleft" });
  legend.onAdd = () => {
    const d = L.DomUtil.create("div", "legend");
    d.append(el("strong", { text: "Model ranking" }), el("br"));
    for (const k of ["top1", "top5", "top10"]) {
      d.append(el("i", { style: `background:${TIER_STYLE[k].color};opacity:${Math.min(1, TIER_STYLE[k].fillOpacity + 0.3)}` }), TIER_STYLE[k].label, el("br"));
    }
    d.append(el("i", { class: "dot" }), "Known occurrence (training label)");
    return d;
  };
  legend.addTo(map);
  const readout = L.control({ position: "bottomright" });
  readout.onAdd = () => { const d = L.DomUtil.create("div", "cursor-readout"); d.textContent = "Move the cursor over the map for coordinates"; state.readout = d; return d; };
  readout.addTo(map);
  map.on("mousemove", (e) => { state.readout.textContent = `${fmtLL(e.latlng.lat, e.latlng.lng)}   ${fmtUTM(e.latlng.lat, e.latlng.lng)}`; });
  map.on("click", (e) => queryPoint(e.latlng));
  if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe($("#map"));
}

function addTiers(data) {
  for (const k of ["top10", "top5", "top1"]) {          // widest first so the strongest sits on top
    const fc = data.tiers[k];
    L.geoJSON(fc, { style: () => ({ ...TIER_STYLE[k], fill: true, stroke: TIER_STYLE[k].weight > 0, interactive: false }) }).addTo(tierGroup);
  }
}

function areaUnits(a) {
  return `eU ${a.mean_eU} cps (about ${f1(ppmU(a.mean_eU))} ppm), eTh ${a.mean_eTh} cps (about ${f1(ppmTh(a.mean_eTh))} ppm), ` +
    `eK ${a.mean_eK} cps (about ${f2(pctK(a.mean_eK))} %); U/Th about ${f2(ppmU(a.mean_eU) / Math.max(ppmTh(a.mean_eTh), 0.1))} in ppm terms`;
}

function areaPopup(a) {
  const root = el("div");
  root.append(el("h4", { text: `${a.name}: ${a.area_km2} km² in the top 5 %` }));
  root.append(el("div", { class: "pm", text: `Peak score: top ${fmtTop(a.max_percentile)} % of the study area` }));
  root.append(el("div", { text: `Average: ${areaUnits(a)}` }));
  root.append(coordBlock("Peak cell", a.peak.lat, a.peak.lon));
  root.append(coordBlock("Centre", a.centre.lat, a.centre.lon));
  root.append(el("div", { text: `${a.main_rock_class}` }));
  root.append(el("div", { text: `Main driver: ${a.main_driver_group}` }));
  root.append(el("div", { text: a.known_occurrences_inside > 0
    ? `${a.known_occurrences_inside} known occurrence${a.known_occurrences_inside > 1 ? "s" : ""} inside (training labels, so partly re-found)`
    : "No known occurrence inside: cannot be checked against labels" }));
  return root;
}

function addAreas(areas) {
  for (const a of areas) {
    const icon = L.divIcon({ className: "", html: `<div class="num-icon">${a.rank}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] });
    const m = L.marker([a.peak.lat, a.peak.lon], { icon, title: a.name, keyboard: true }).addTo(areaGroup);
    m.bindPopup(() => areaPopup(a));
    state.areaLayers.set(a.rank, m);
  }
}

function addKnown(known) {
  for (const k of known) {
    L.circleMarker([k.lat, k.lon], { radius: k.producer ? 5 : 3.5, color: "#0aa", weight: 2, fillColor: "#0aa", fillOpacity: k.producer ? 0.85 : 0.1 })
      .bindTooltip(`${k.name} (${k.status}${k.producer ? ", producer" : ""})`).addTo(knownGroup);
  }
}

/* ---------- areas tab ---------- */
function renderAreas() {
  const only = $("#only-new").checked;
  const list = $("#area-list");
  list.replaceChildren();
  for (const a of state.areas.filter((x) => !only || x.known_occurrences_inside === 0)) {
    const badge = a.known_occurrences_inside > 0
      ? el("span", { class: "badge known", text: `${a.known_occurrences_inside} known inside` })
      : el("span", { class: "badge new", text: "no known occurrence" });
    const card = el("button", { class: "area-card", type: "button", onclick: () => flyToArea(a) },
      el("div", { class: "rank", text: a.rank }),
      el("div", {},
        el("div", {}, el("strong", { text: a.name }), " ", badge),
        el("div", { class: "meta", text: `${a.area_km2} km² · peak top ${fmtTop(a.max_percentile)} % · ${a.main_rock_class}` }),
        el("div", { class: "meta", text: `Average ${areaUnits(a)} · driver: ${a.main_driver_group}` }),
        el("div", { class: "meta mono", text: `Peak ${fmtLL(a.peak.lat, a.peak.lon)} · ${fmtUTM(a.peak.lat, a.peak.lon)}` }),
        a.known_occurrences_inside === 0
          ? el("div", { class: "meta", text: "Candidate: nothing here can be checked against labels." })
          : el("div", { class: "meta", text: "Partly in-sample: the model was trained on the known occurrences here." })));
    list.append(el("li", {}, card));
  }
  if (!list.children.length) list.append(el("li", { class: "hint", text: "No areas match this filter." }));
}
$("#only-new").addEventListener("change", renderAreas);

function flyToArea(a) {
  const b = a.bbox;
  map.flyToBounds([[b[1], b[0]], [b[3], b[2]]], { padding: [50, 50], maxZoom: 13, duration: 0.8 });
  const m = state.areaLayers.get(a.rank);
  if (m) setTimeout(() => m.openPopup(), 900);
}

/* ---------- point query ---------- */
async function queryPoint(latlng) {
  showTab("point");
  setStatus("Looking up this spot…");
  if (state.marker) state.marker.remove();
  state.marker = L.circleMarker(latlng, { radius: 8, color: "#fff", weight: 3, fillColor: "#111", fillOpacity: 1 }).addTo(map);
  try {
    const out = await getJSON("/predict/point", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lon: latlng.lng, lat: latlng.lat }) });
    setStatus("");
    renderPoint(out);
    const [cls, label] = tierOf(out.percentile);
    state.marker.bindPopup(`<div class="pm"><b>${label}</b> of the study area<br>Click the details panel for the evidence.</div>`).openPopup();
  } catch (e) {
    setStatus("");
    $("#point-empty").hidden = false;
    $("#point-body").hidden = true;
    $("#point-empty").replaceChildren(el("p", { text: e.status === 404
      ? "This spot is outside the surveyed footprint, so there is no score for it. Click inside the survey."
      : `Could not get a result (${e.status || "network error"}${e.detail ? ": " + e.detail : ""}).` }));
    state.marker.bindPopup("No score here").openPopup();
  }
}

function barRow(label, frac, text, mid = true) {
  return el("div", { class: "bar-row" }, el("span", { text: label }),
    el("div", { class: "track", title: `${pctText(frac)} of the survey is lower` }, el("div", { class: "fill", style: `width:${Math.max(2, frac * 100)}%` }), mid ? el("div", { class: "mid" }) : null),
    el("span", { class: "num", text }));
}

function renderPoint(o) {
  const [cls, tier] = tierOf(o.percentile);
  const body = $("#point-body");
  body.replaceChildren();
  $("#point-empty").hidden = true;
  body.hidden = false;
  body.append(el("div", { class: "score" },
    el("div", { class: "big", text: `Top ${fmtTop(o.percentile)} %` }),
    el("div", {}, el("span", { class: `chip ${cls}`, text: cls === "t0" ? tier : `in the ${tier.toLowerCase()} tier` }), " ", el("span", { class: "hint", text: `score bin: ${o.bin}` })),
    el("span", { class: "hint", text: "Observed rate" }),
    el("span", { text: `${sci(o.labelled_positive_density)} known-occurrence cells per cell (${o.lift_vs_average_cell.toFixed(1)}x the average cell)` }),
    el("span", { class: "hint", text: "Model disagreement" }),
    el("span", { text: `${o.uncertainty.level} (descriptive only)` })));
  body.append(coordBlock("Cell centre", o.cell_centre.lat, o.cell_centre.lon));
  body.append(el("p", { class: "hint", text: "The observed rate is from out-of-fold validation: the share of known occurrence cells found in cells with this score. It is a lower bound, not the probability of a deposit." }));

  const ev = o.evidence;
  if (ev) {
    const g = el("div", { class: "group measured" }, el("h3", { text: GROUP_TITLES.measured[0] }), el("div", { class: "why", text: GROUP_TITLES.measured[1] }));
    const sp = ev.survey_percentile;
    g.append(el("div", { class: "bars" },
      barRow("Uranium (eU)", sp.eU, `${ev.eU_cps} cps ≈ ${f1(ppmU(ev.eU_cps))} ppm`),
      barRow("U, 5 km mean", sp.mean_eU_5km, `${ev.mean_eU_5km_cps} cps ≈ ${f1(ppmU(ev.mean_eU_5km_cps))} ppm`),
      barRow("Thorium (eTh)", sp.eTh, `${ev.eTh_cps} cps ≈ ${f1(ppmTh(ev.eTh_cps))} ppm`),
      barRow("Potassium (eK)", sp.eK, `${ev.eK_cps} cps ≈ ${f2(pctK(ev.eK_cps))} %`),
      barRow("U / Th ratio", sp.u_over_th, `${ev.u_over_th} (cps) ≈ ${f2(ev.approx_concentration.u_over_th_ppm)} (ppm)`)));
    g.append(el("div", { class: "hint", text: "Bar = share of the whole survey that is lower than this cell. The vertical line is the survey median." }));
    g.append(el("div", { class: "hint", text: "The survey grids are in counts per second (cps). ppm and % values are approximate conversions with the survey sensitivities (U 10.4 cps/ppm, Th 6.2 cps/ppm, K 99.5 cps/%), not calibrated concentrations. For orientation, crustal averages are about 2.7 ppm U, 10 ppm Th, 2.3 % K, and U/Th about 0.27 (ppm basis)." }));
    for (const r of o.reading.filter((x) => x.kind === "measured")) g.append(item(r));
    body.append(g);
  }

  const drivers = o.top_drivers;
  const mg = el("div", { class: "group model" }, el("h3", { text: GROUP_TITLES.model[0] }), el("div", { class: "why", text: GROUP_TITLES.model[1] }));
  const maxAbs = Math.max(...drivers.map((d) => Math.abs(d.contribution_vs_typical_cell)), 0.01);
  mg.append(el("div", { class: "bars diverge" }, drivers.map((d) => {
    const v = d.contribution_vs_typical_cell;
    return el("div", { class: "bar-row" }, el("span", { text: d.group }),
      el("div", { class: "track" + (v < 0 ? " neg" : "") }, el("div", { class: "fill", style: `width:${Math.max(3, Math.abs(v) / maxAbs * 100)}%` })),
      el("span", { class: "num", text: (v > 0 ? "+" : "") + v.toFixed(1) }));
  })));
  for (const r of o.reading.filter((x) => x.kind === "model")) mg.append(item(r));
  body.append(mg);

  for (const kind of ["guide", "caution"]) {
    const rows = o.reading.filter((x) => x.kind === kind);
    if (!rows.length) continue;
    const g = el("div", { class: `group ${kind}` }, el("h3", { text: GROUP_TITLES[kind][0] }), el("div", { class: "why", text: GROUP_TITLES[kind][1] }));
    rows.forEach((r) => g.append(item(r)));
    body.append(g);
  }
  body.append(el("p", { class: "hint", text: o.disclaimer }));
  body.append(el("p", { class: "hint", text: `Distance to survey edge ${o.distance_to_survey_edge_km.toFixed(1)} km. Cell size 50 m.` }));
  $("#p-point").scrollTop = 0;
}
function item(r) { return el("div", { class: "item" }, el("b", { text: r.title }), el("span", { text: r.text })); }

/* ---------- about tab ---------- */
function renderAbout(info) {
  const b = $("#about-body");
  b.replaceChildren();
  b.append(el("h2", { text: "What this is" }),
    el("p", { text: "A regularised logistic regression that scores every 50 m cell of the airborne-survey footprint by how closely its surroundings resemble the surroundings of 199 known uranium occurrence cells (USGS MRDS records)." }),
    el("p", {}, el("strong", { text: "In one sentence: " }), "it ranks areas by their local radiometric uranium context. It does not understand geology and it does not predict deposits."));

  b.append(el("h3", { text: "How good is it (out-of-fold, spatial validation)" }));
  const rows = (info.out_of_fold_performance_inclusive_phase8 || []).filter((r) => ["logreg", "single_rad_U", "prevalence"].includes(r.model) && r.positives === "all");
  const names = { logreg: "Logistic regression (this model)", single_rad_U: "Raw uranium value alone", prevalence: "Chance" };
  const t = el("table", {}, el("thead", {}, el("tr", {}, el("th", { text: "Method" }), el("th", { class: "r", text: "ROC-AUC" }), el("th", { class: "r", text: "Found in best 5 %" }))));
  const tb = el("tbody");
  for (const r of rows) {
    tb.append(el("tr", {}, el("td", { text: names[r.model] }), el("td", { class: "r", text: Number(r.roc_auc).toFixed(2) }),
      el("td", { class: "r", text: `${pctText(r.recall_top5pct)}` + (r.recall_top5pct_lo != null ? ` (${pctText(r.recall_top5pct_lo)} to ${pctText(r.recall_top5pct_hi)})` : "") })));
  }
  t.append(tb);
  b.append(t, el("p", { class: "hint", text: "The model does not clearly beat the raw uranium value: their intervals overlap (gate G4 not met). Intervals are 95 % block-bootstrap and still optimistic because the positives sit in two districts." }));

  b.append(el("h3", { text: "Observed rate by score bin (out-of-fold)" }));
  const t2 = el("table", {}, el("thead", {}, el("tr", {}, el("th", { text: "Score bin" }), el("th", { class: "r", text: "Rate" }), el("th", { class: "r", text: "x average" }))));
  const tb2 = el("tbody");
  for (const r of info.calibration_bins_out_of_fold_phase9 || []) tb2.append(el("tr", {}, el("td", { text: r.bin }), el("td", { class: "r", text: sci(r.observed_rate) }), el("td", { class: "r", text: Number(r.lift_vs_prevalence).toFixed(1) })));
  t2.append(tb2);
  b.append(t2);

  b.append(el("h3", { text: "How to read the map" }),
    el("ul", { class: "tight" },
      el("li", { text: "Red, orange and yellow are the top 1 %, 5 % and 10 % of the study area by score." }),
      el("li", { text: "Numbered markers are the strongest clusters. Areas with known occurrences inside are partly in-sample: the final model was trained on them." }),
      el("li", { text: "Areas with no known occurrence are the interesting candidates but cannot be checked against labels." }),
      el("li", { text: "Click anywhere to see the evidence: measured values, the model's drivers, and a separate textbook guide." })));

  b.append(el("h3", { text: "Known limitations" }));
  const ul = el("ul", { class: "tight" });
  for (const l of info.limitations || []) ul.append(el("li", { text: l }));
  b.append(ul);
  b.append(el("p", { class: "hint", text: `Model fitted ${info.created_utc} on ${info.n_train_positives} occurrence cells and ${Number(info.n_train_background).toLocaleString()} sampled background cells; ${info.features_used} features. Public data only (USGS airborne survey, SRTM, SGMC geology, MRDS). Not for investment, drilling or land decisions.` }));
}

/* ---------- start ---------- */
async function main() {
  initMap();
  try {
    const [hs, ar, kn, info] = await Promise.all([getJSON("/hotspots"), getJSON("/areas"), getJSON("/known"), getJSON("/model-info")]);
    state.areas = ar.areas; state.known = kn.known; state.info = info;
    addTiers(hs); addAreas(state.areas); addKnown(state.known);
    const b = tierGroup.getLayers().reduce((acc, l) => acc.extend(l.getBounds()), L.latLngBounds([]));
    map.invalidateSize();                       // the container may have had no size yet when the map was created
    if (b.isValid()) { state.home = b; map.fitBounds(b, { padding: [20, 20], maxZoom: 11 }); }
    renderAreas(); renderAbout(info);
    setStatus("");
  } catch (e) {
    setStatus(e.status === 503 ? "Model files are missing on the server. Run the pipeline first." : "Could not load map data.");
    $("#area-list").replaceChildren(el("li", { class: "hint", text: "Unavailable." }));
  }
}
main();
