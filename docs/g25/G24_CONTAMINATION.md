# G24 Contamination Audit (G25-0 freeze input)

Status: audit only. No model calls, no new samples, no product changes.
G25-0 scope per `docs/G25_PROTOCOL.md`: G24's 24 items + all seen outputs are the
development/regression set and MUST NOT enter the unseen set.

## 1. Canonical G24 case list (all 24, from `tools/g24/blind_cases.json`)

Expected fields here are `expected.{route,status,reject_category}` per `score.py`
`load_cases()`; dispositions below are the frozen gold, not model outputs.

| ID | Session | Lang / category | Gold |
|---|---|---|---|
| R1-nmr-lift | fix_nmr_main | zh / native-layout | READY native 1 edit (`peak_label_lift_mm` = 3.0 mm) |
| R2-nmr-shift | fix_nmr_main | en / native-layout | READY native 1 edit (`peak_shifts_mm.main.7.26` = 1.0 mm) |
| R3-ftir-gap | fix_ftir_main | zh / native-layout | READY native 1 edit (`curve_gap_mm` = 2.0 mm) |
| R4-ftir-shift | fix_ftir_main | en / native-layout | READY native 1 edit (`shifts_mm.main.b` = 1.0 mm) |
| R5-compare-gap | fix_ftir_raw | zh / native-layout | READY native 1 edit (`compare_gap_mm` = 11.0 mm) |
| R6-priv-nmr-peakfont | priv_nmr_main | zh / native-style-unique | READY native 1 edit (`peak_font_pt` = 7.0 pt) |
| R7-priv-nmr-linewidth | priv_nmr_main | en / native-style-unique | READY native 1 edit (`line_width` = 1.0 pt) |
| R8-priv-ftir-labelfont | priv_ftir_main | zh / native-style-unique | READY native 1 edit (`label_font_pt` = 5.5 pt) |
| R9-ftir-multi | fix_ftir_main | zh / native-multi | READY native 2 edits (atomic same-route) |
| R10-main-overlay-multi | priv_ftir_main | en / overlay-multi | READY overlay 2 edits (x title 10 pt + x tick 9 pt) |
| R11-raw-overlay-multi | priv_ftir_raw | zh / overlay-multi | READY overlay 2 edits (x tick 9 pt + curve linewidth 1.2 pt) |
| R12-proc-overlay-multi | priv_ftir_proc | en / overlay-multi | READY overlay 2 edits (y title 10 pt + curve linewidth 1.2 pt) |
| R13-synth-curve | synth_errlegend | en / overlay-linewidth | READY overlay 1 edit (curve linewidth 1.5 pt) |
| F1-nmr-windows | fix_nmr_main | zh / sci-locked | REFUSE native LOCKED_SCIENCE |
| F2-ftir-bands | fix_ftir_main | en / sci-locked | REFUSE native LOCKED_SCIENCE |
| F3-show-ppm | priv_nmr_main | zh / sci-locked | REFUSE native LOCKED_SCIENCE |
| F4-synth-caps | synth_errlegend | en / unauthorized | REFUSE overlay UNAUTHORIZED |
| F5-synth-legend | synth_errlegend | en / unauthorized | REFUSE overlay UNAUTHORIZED |
| F6-nmr-huge-font | priv_nmr_main | zh / out-of-range | REFUSE native OUT_OF_RANGE (50 pt) |
| F7-raw-huge-tick | priv_ftir_raw | en / out-of-range | REFUSE overlay OUT_OF_RANGE (500 pt) |
| F8-wrong-panel | fix_ftir_proc | zh / scope-mismatch | REFUSE native SCOPE_MISMATCH |
| C1-no-number | priv_ftir_main | zh / clarify-missing | CLARIFY native (no number) |
| C2-which-peak | fix_nmr_main | en / clarify-missing | CLARIFY native (which peak + no value) |
| C3-which-axis | priv_ftir_raw | en / clarify-missing | CLARIFY overlay (x vs y unspecified) |

Counts: 13 READY / 8 REFUSE / 3 CLARIFY. Matches `docs/G24_REPORT.md` §freeze.

## 2. Session / script / config families (contamination units)

From `blind_cases.json` `sessions` (9 sessions, 5 script/config families):

| Session | Script | Config | Scope | Routes |
|---|---|---|---|---|
| fix_nmr_main | `tests/fixtures/native_nmr.py` | `tests/fixtures/native_nmr.yaml` | main | native+overlay |
| fix_ftir_main | `tests/fixtures/native_ftir.py` | `tests/fixtures/native_ftir.yaml` | main | native+overlay |
| fix_ftir_raw | same `native_ftir.py/yaml` | same | compare_raw | native+overlay |
| fix_ftir_proc | same `native_ftir.py/yaml` | same | compare_processed | native+overlay |
| priv_nmr_main | `${NMR_ROOT}/08 NMR.py` → default `examples/nmr` | `${NMR_ROOT}/nmr.yaml` | main | native+overlay |
| priv_ftir_main | `${FTIR_ROOT}/plot_ftir.py` → default `examples/ftir` | `${FTIR_ROOT}/ftir.yaml` | main | native+overlay |
| priv_ftir_raw | same priv FTIR | same | compare_raw | native+overlay |
| priv_ftir_proc | same priv FTIR | same | compare_processed | native+overlay |
| synth_errlegend | `tools/g24/fixtures.py` (FIGURE_ID `fig_synth_errlegend`, no native contract) | null | main | overlay only |

Prompt/schema/model-repair rounds (from `results.json` `round_history` + `docs/G24_REPORT.md`):
round 1 = original first round (all fail-closed on missing literal `science`/`view`
preserve words; 0/24); round 2 = prompt/schema clarified, same-run drift
(`context-probe` evidence), 10/24, not a benchmark; round 3 = completion expired,
no outcomes; round 4 = corrective isolated rerun (per-session fresh process, same
original workspace), 16/24 strict. Round 1 outputs are the frozen first-round
evidence; round 4 is a labelled retest, never a replacement first round.
Model backend: host `completion` `default` selector; no named-model claim
(`results.json` limitations). Held-out CLI smoke (`peak_font_pt` 7.2 pt +
`canvas_w_mm` 68 mm) is also seen development output, not unseen evidence.

## 3. Known invalid gold (do NOT fix in place)

From `tools/g24/case_validity.json` (pre-inference audit, gold unchanged):
- `R11-raw-overlay-multi`: upper raw Axes has no visible x-tick target; request
  also under-specifies which of five raw curves. Gold accepting any curve is defective.
- `R12-proc-overlay-multi`: five processed curves, gold accepts any one without
  disambiguation and lacks a panel-specific selector.
Post-inference mismatches retained as evidence (`docs/G24_REPORT.md`, `results.json`
limitations): R8 live config exposes no `label_font_pt` control despite
source-level declaration (model REFUSE has evidence); R13 requests 1.5 pt = current
value (engine rejects no-op); R2/R5/R6 correct bindings rejected on real
range/science/canvas grounds; C3 gold CLARIFY vs model REFUSE scored inconsistent.

## 4. Private-evidence boundary

Public in repo: `tools/g24/{blind_cases.json,case_validity.json,results.json,
run_blind.py,score.py,fixtures.py}`, `docs/G24_REPORT.md`.
Private, outside the repo (per `docs/G24_REPORT.md` §rerun, MUST NOT be
reconstructed or inlined into G25 gold): `g24/blind-final/`,
`contract-round2/`, `isolated-round3/`, `isolated-round4/`,
`context-probe/probe.json`, `cli-smoke/` — i.e. raw request packets, model
replies, engine receipts, drift diagnostics, CLI artefacts. `run_blind.py`
`--output` must always point at a fresh private directory; trials and
`official-style.json` absence / `source_unchanged` checks live there.

## 5. Exact exclusion rules for G25 unseen

1. All 24 case IDs above are DEVELOPMENT; no verbatim reuse, paraphrase, or
   translation of any G24 request may enter the unseen set.
2. Same-figure / same-panel / same-data variants are excluded: any sample built
   from `tests/fixtures/native_nmr.py`, `tests/fixtures/native_ftir.py`,
   `examples/nmr/08 NMR.py`, `examples/ftir/plot_ftir.py`, or
   `tools/g24/fixtures.py` (including other scopes, rewordings, value swaps, or
   the CLI-smoke NMR request) is DEVELOPMENT, not unseen.
3. All G24 model-reply texts, packets, engine receipts, and gold edits/bindings
   are seen; tuning prompts, schemas, or thresholds on them is development.
4. A family is unseen ONLY with positive evidence: new script + new config +
   new data source, built by an independent annotator, never used in prompt
   debugging, with recorded source fingerprint and a real inventory/contract
   pre-check (per `docs/G25_PROTOCOL.md` §4). Absence from this file is not
   evidence. Everything below not marked ELIGIBLE_CANDIDATE stays out.
5. Cross-scope bundles, dual Native+Overlay atomic requests, or anything not
   expressible in one current-route/one-scope `PLAN_SCHEMA` stay capability-
   boundary samples (expected REFUSE/CLARIFY or excluded from READY denominator);
   see protocol `schema_representability` freeze.

## 6. Public manifest hashes (SHA256 of file bytes, 2026-10-19)

- `tools/g24/blind_cases.json`: `28b12e7622fc997cb9660392a684435993eb00ba4110f66340eef9f388016514`
- `tools/g24/case_validity.json`: `573ae6a27a0e422a942dd5e23da896e91772ee2a1e8bc49188122fa3534d923c`
- `tools/g24/results.json`: `57087c28f325ea12bc0956705311feb99ba115a9a55983f02cd78f36da9901d6`
- `docs/G24_REPORT.md`: `4ff71aa1772bbceaa2b2066c977d1359a97ef5d7e6a930a4b8af0b1770bc9e84`
- `tools/g24/run_blind.py`: `8c1a33b49f19f1026ca0462c3aa14c055cf36c7b5610e4b0a86d1e023375fa8a`
- `tools/g24/score.py`: `7af4db40dff726eb9fd815ea400abea28e8825888b9223b56383efb114019f51`
- `tools/g24/fixtures.py`: `62ad24358bda1f23833f3129819b141dfa5425e20306b9edb46bdba4f5faf80e`

Note: `blind_cases.json:frozen_sha256` (`660b0801…5a`) is the canonical hash of
the `cases` array per `score.canonical_cases_sha` (sorted-keys JSON), NOT the
file-bytes hash above; `load_cases()` enforces it. Do not "fix" the mismatch —
they are different quantities.

## 7. Machine-readable contamination table

```json
{
  "version": "g25-0-contamination-v1",
  "default": "DEVELOPMENT",
  "families": [
    {"family": "fixture-nmr (tests/fixtures/native_nmr.py+yaml, scope main)", "source": "tests/fixtures/native_nmr.py", "g24_cases": ["R1-nmr-lift", "R2-nmr-shift", "F1-nmr-windows", "C2-which-peak"], "reason": "G24 native-layout/sci-locked/clarify prompts, packets, replies, receipts all seen", "status": "DEVELOPMENT"},
    {"family": "fixture-ftir (tests/fixtures/native_ftir.py+yaml; scopes main/compare_raw/compare_processed)", "source": "tests/fixtures/native_ftir.py", "g24_cases": ["R3-ftir-gap", "R4-ftir-shift", "R5-compare-gap", "R9-ftir-multi", "F2-ftir-bands", "F8-wrong-panel"], "reason": "G24 native prompts/packets/replies seen across all three scopes", "status": "DEVELOPMENT"},
    {"family": "private-nmr (examples/nmr/08 NMR.py+nmr.yaml, scope main)", "source": "examples/nmr/08 NMR.py", "g24_cases": ["R6-priv-nmr-peakfont", "R7-priv-nmr-linewidth", "F3-show-ppm", "F6-nmr-huge-font"], "reason": "private figure + CLI-smoke NMR figure; requests, packets, replies seen", "status": "DEVELOPMENT"},
    {"family": "private-ftir (examples/ftir/plot_ftir.py+ftir.yaml; scopes main/compare_raw/compare_processed)", "source": "examples/ftir/plot_ftir.py", "g24_cases": ["R8-priv-ftir-labelfont", "R10-main-overlay-multi", "R11-raw-overlay-multi", "R12-proc-overlay-multi", "F7-raw-huge-tick", "C1-no-number", "C3-which-axis"], "reason": "private figure; overlay multi/clarify/out-of-range prompts seen; R11/R12 gold defective but still seen", "status": "DEVELOPMENT"},
    {"family": "synthetic errorbar+legend (tools/g24/fixtures.py, fig_synth_errlegend)", "source": "tools/g24/fixtures.py", "g24_cases": ["R13-synth-curve", "F4-synth-caps", "F5-synth-legend"], "reason": "G24-built synthetic fixture; linewidth/caps/legend prompts seen", "status": "DEVELOPMENT"}
  ],
  "eligible_or_unknown": []
}
```

No `ELIGIBLE_CANDIDATE` family is declared: no replacement figure with
independent-annotator + source-fingerprint + pre-check evidence exists yet.
`UNKNOWN` applies to any future-proposed family until that evidence lands; it
MUST NOT be treated as unseen.

`ELIGIBLE_CANDIDATE` here means the unseen-provenance gate has passed. Labels such as `CANDIDATE-PENDING-ANNOTATOR` or `conditional eligible-candidate` in the inventory/preflight/budget describe technical candidates only, not this certification; their unseen status remains UNKNOWN.

## 8. Blockers / next evidence needed (G25-0 exit)

1. Independent annotator(s) and brand-new figure scripts/data (not derived from
   any family in §7), with per-sample source fingerprints.
2. Real inventory/contract pre-check on isolated copies (no model call), with
   config/data/engine/environment fingerprints and raw receipts in a private dir.
3. Frozen sample list, gold (with `schema_representability`, NO_OP/REJECT mapping,
   scope/target/binding/value/feasibility fields), scorer, prompt/schema, model
   config, split list, stop thresholds — each SHA256-recorded before first run.
4. A/B (or A/B1/B2) payload equivalence check procedure per protocol; field
   provenance for every hint; pre-registered metrics and wrong-scope rates.
