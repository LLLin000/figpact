# G25 candidate figures inventory (G25-0, pre-freeze)

Status: evidence collection only. No model calls, no requests, no gold cases made.
G24 stays the dev-regression set; nothing below reuses a G24 session, G24 figure
family, or reworded G24 sample. All claims cite repo source lines; anything not
yet measured in an isolated preflight is marked **[UNVERIFIED]**.

Freeze pointers: protocol `docs/G25_PROTOCOL.md`, brief
`docs/G25_RESEARCH_BRIEF.md`, G24 gold `tools/g24/blind_cases.json`
(`frozen_sha256 660b0801…5d0a`, 24 cases), validity notes
`tools/g24/case_validity.json`, G24 report `docs/G24_REPORT.md`.

## Shared rules applied

- G25 runs on frozen samples before any model call; `Native`/`Overlay` single
  route + single scope per `PLAN_SCHEMA` (`figpact/edit_plan.py:35-51`); A/B1
  preserves exact facts/control IDs and only reorganizes presentation
  (`docs/G25_PROTOCOL.md:25-44`).
- Same-figure variants, homologous panels, or reworded samples MUST NOT cross
  the dev/unseen split (`docs/G25_PROTOCOL.md:12`). A family touched by any G24
  session is therefore ineligible in **all** its scopes, not just the used one.
- A Native control is authorized only by its contract record (`mutability`,
  exact `path` segments, `scopes`, `objects`, range) as exposed read-only by
  `plan_context.discover_native` (`figpact/plan_context.py:89-175`): only
  `EDITABLE` records in the requested scope are offered. Parameter-name
  mentions in source are never authorization.
- Overlay targets are only `axis.title`/`axis.tick`/`curve.linewidth`
  (`figpact/style_identity.py:61-68`), ranges `fontsize (0.5,100)`,
  `linewidth (0.05,20)` (`figpact/style_overlay.py:38-39`), resolved from
  real descriptors by `plan_context.discover_overlay`
  (`figpact/plan_context.py:188-270`). Caps, legend, bars, scatter, annotations
  are never targets (`figpact/style_identity.py:11-14`).

## Family verdicts (one row per source family, not per scope)

This is the initial contract inventory, not a current eligibility decision. `PREFLIGHT_EVIDENCE.md` §§3–7 and `CASE_BUDGET.md` supersede its preflight predictions: F3/F4 scale bars conflict with Overlay style authority; F9 Native paths dangle; F10/F11 share one geometry; F13/F16/F17 are DEVELOPMENT-only. All remaining technical candidates have UNKNOWN unseen status; **0 families are certified**.

| # | Source family | FIGURE_ID / scopes | G24 use | G25-eligible | Native EDITABLE paths (contract lines) | Overlay roles (status) |
|---|---|---|---|---|---|---|
| F1 | `tests/fixtures/native_nmr.py` + `native_nmr.yaml` | `fig_nmr_native`, `main`/`annotated` | YES — `fix_nmr_main` (R1,R2,C2,F1) | **NO** — same-family leakage (all scopes, incl. `annotated`) | — (reference only) | — |
| F2 | `tests/fixtures/native_ftir.py` + `native_ftir.yaml` | `fig_ftir_native`, `main`/`annotated`/`compare_raw`/`compare_processed` | YES — `fix_ftir_main` (R3,R4,R9,F2), `fix_ftir_raw` (R5), `fix_ftir_proc` (F8) | **NO** — same-family leakage (all 4 scopes) | — (reference only) | — |
| F3 | `tests/fixtures/native_panels.py` + `native_panels.yaml` | `fig_panels_native`, `main`/`bare` | none | **CANDIDATE-PENDING-ANNOTATOR (C1), not certified unseen** | `canvas_w_mm/h_mm`, `render_dpi`, `margin_left/bottom_mm`, `panel_w/h_mm` (joint-aspect pair), `gap_x/y_mm`, `letter_inset_x/y_mm` (`main` only), `scale_*` FIXED, `panel_field_um`/`scale_bar_um`/`panel_aspect` LOCKED (`native_panels.py:485-575`) | Preflight found scale-bar `curve.linewidth` descriptors conflicting with Native FIXED_STYLE; excluded from Overlay READY |
| F4 | `tests/fixtures/native_mixed.py` + `native_mixed.yaml` | `fig_mixed_native`, `main`/`bare` | none | **CANDIDATE-PENDING-ANNOTATOR (C1), not certified unseen** | `canvas_w/h_mm`, `margin_left/bottom_mm`, `curve_panel_w_mm`, `panel_gap_mm`, `curve_lift_mm`, `letter_inset_x/y_mm` (`main` only); `panel_h_mm`/`image_panel_w_mm` DERIVED, styles FIXED, `image_field_width_um`/`scale_bar_um`/`panel_aspect` LOCKED (`native_mixed.py:486-621`) | Curve-panel descriptors positive; scale-bar descriptor MUST be excluded; official per-case feasibility UNKNOWN |
| F5 | `tests/fixtures/native_negatives.py` + `native_negatives.yaml` | `fig_negatives_native`, `main`/`annotated` | none (regression negative control) | **NO** — intentionally defective, `source.publishable: False` (`native_negatives.py:603-614`); defects `NO_EFFECT`/`EFFECT_MISMATCH`/`SCIENCE_PAYLOAD`/`TEXT_OVERLAP` (`native_negatives.py:1-41`) | — (gate-test only) | — |
| F6 | `examples/nmr/08 NMR.py` + `nmr.yaml` | `fig2_nmr`, `main` only | YES — `priv_nmr_main` (R6,R7,F3,F6) + private data root `${NMR_ROOT}` | **NO** — same-family leakage + private instrument-data dependency | — (reference only) | — |
| F7 | `examples/ftir/plot_ftir.py` + `ftir.yaml` | `fig2_ftir`, `main`/`annotated`/`compare_raw`/`compare_processed` | YES — `priv_ftir_main/proc/raw` (R8,R10,R11,R12,C1,C3,F7) | **NO** — same-family leakage (all 4 scopes) | — (reference only) | — |
| F8 | `tools/g24/fixtures.py` | `fig_synth_errlegend`, `main`, overlay-only by design (no `layout_contract`) | YES — `synth_errlegend` (R13,F4,F5) | **NO** — same-family leakage | native route absent by design (`fixtures.py:1-10`) | reference: `curve.linewidth` on `fig_synth_errlegend.main.curve.a` (R13); caps/legend unauthorized (F4,F5) |
| F9 | `examples/demo/demo_figure.py` + `demo.yaml` | `figdemo`, `main` | none | **CONDITIONAL — pending contract audit + preflight** | per-gid EDITABLE translate records exist (`demo_figure.py:347-366`) but full parameter/range/relation enumeration **not yet read** — **[UNVERIFIED]** | **[UNVERIFIED]** |
| F10 | `examples/python_native/simple_figure.py` | `intent`, `main` | none | **CONDITIONAL — overlay-only pending preflight** | native route absent (no `layout_contract`; layout lives in source `LAYOUT_MM`, not YAML) | **[UNVERIFIED]** — 1 curve + 2 labels; descriptor eligibility unknown |
| F11 | `examples/python_native/legacy_plain.py` | `legacy`, `main` | none | **CONDITIONAL — overlay-only pending preflight** | native route absent (no bindings by design) | **[UNVERIFIED]** |
| F12 | `examples/statistics/statistical.py` + `statistical.yaml` | `statistics`, `main` | none | **CONDITIONAL — overlay-only pending preflight** | `layout_contract` returns `parameters: []` (`statistical.py:50-55`) → Native offers zero controls | **[UNVERIFIED]** — 2 curves + errorbars + legend; errorbar caps/legend excluded by rule, data-line eligibility unknown |
| F13–F20 | `tools/g15/{A,B,C}` decl wrappers (8 upstream matplotlib gallery figures, `tools/g15/inputs.json`) | `g15*`, 30 R1 scopes | none in G24 model packets (G15 engine eval only) | **CONDITIONAL — overlay-only pending preflight; NATIVE ABSENT** | decl `layout_contract` returns `parameters: []` (e.g. `tools/g15/B/g15b_scatter_decl.py:78-86`) → Native offers zero controls | **[UNVERIFIED, with adverse prior]** — G15 R0/R1 found 0 editable candidates, 15/15 capability rejections, role-hint recall 9/19 (`tools/g15/summary.json`); preflight must prove ≥1 eligible descriptor per scope or the family is unusable |
| — | `examples/plate/*` | manifests, not figures | — | **NO** — out of scope: no Native/Overlay contract, no Artist identity (bitmap/vector inputs + unify plan) | — | — |

Caveat C1: F3/F4 are pre-existing seeded synthetic fixtures, not new independently authored figures. No G24 packet use was found, but absence of G24 exposure is not positive unseen provenance. They fail the current independent-annotator/new-figure gate and remain technical candidates only.

G24 leakage map (why F1/F2/F6/F7/F8 are out, all scopes): sessions
`tools/g24/blind_cases.json:614-695` — `fix_nmr_main→native_nmr.py`,
`fix_ftir_{main,raw,proc}→native_ftir.py`,
`priv_nmr_main→${NMR_ROOT}/08 NMR.py`,
`priv_ftir_{main,proc,raw}→${FTIR_ROOT}/plot_ftir.py`,
`synth_errlegend→tools/g24/fixtures.py`. Case IDs R1–R13/F1–F8/C1–C3 cover
these families; `annotated` scopes of F1/F2/F7 are same-`FIGURE_ID` variants
and equally excluded. Known gold defects R11/R12 (upper-panel tick/curve
ambiguity, `tools/g24/case_validity.json`) MUST NOT be recycled as G25 cases.

## Per-family detail (eligible + conditional only)

### F3 `fig_panels_native` — 2×2 micrographs, scopes `main` (letters) / `bare`
- Script/config: `tests/fixtures/native_panels.py` / `native_panels.yaml`;
  `SCOPES` (`native_panels.py:52`), `FIGURE_ID` (`:50`), science: seeded
  `fixture_data.micrograph` + `panel_field_width_um`/`SCALE_BAR_UM`/aspect 1.3
  (`native_panels.py:236-342`).
- Native contract (`native_panels.py:465-619`): EDITABLE = `canvas_w_mm`,
  `canvas_h_mm`, `render_dpi`, `margin_left_mm`, `margin_bottom_mm`,
  `panel_w_mm` + `panel_h_mm` (joint pair, `_check_aspect` hard gate
  `:177-185`), `gap_x_mm` (moves `col_right`), `gap_y_mm` (moves `row_top`),
  `letter_inset_x_mm`/`letter_inset_y_mm` (`main` only, `:557-575`).
  FIXED_STYLE = `margin_right_mm`, `margin_top_mm` (read-only clearance gates),
  `scale_bar_lw_pt`, `letter_font_pt`. LOCKED = `panel_aspect`,
  `scale_bar_um`, `panel_field_um`. Relations `panels.contain_*`,
  `equal_*`, `gap_*`, `align_*` (`:577-608`).
- Science/QA hooks: `science_selfcheck` (pixels/extent/aspect/scale-bar/text,
  `:695+` per module pattern), strict CLI `--strict/--probe`
  (`tests/fixtures/_native.py:491-528`); publishable positive fixture
  (`tests/fixtures/__init__.py`, `test_fixture_behavior.py:118-122`).
- Overlay: **[UNVERIFIED]** image-only Axes; likely zero Overlay targets —
  preflight decides whether this family can supply Overlay or negative
  (no-target → CLARIFY/REFUSE) cases.
- G25 fit: multi-panel scope-identity + joint-bound (aspect pair) + `bare`
  scope-isolation (letters absent) cases; single-route single-scope plans only.

### F4 `fig_mixed_native` — FTIR curve + micrograph side by side, `main`/`bare`
- Script/config: `tests/fixtures/native_mixed.py` / `native_mixed.yaml`;
  `SCOPES` (`:52`), curve `a` + image `a`, aspect lock
  (`native_mixed.py:169-211`).
- Native contract (`:471-622`, `658-692`): EDITABLE = `canvas_w_mm`,
  `canvas_h_mm`, `margin_left_mm`, `margin_bottom_mm`, `curve_panel_w_mm`
  (pushes image panel), `panel_gap_mm`, `curve_lift_mm` (±4 mm),
  `letter_inset_x/y_mm` (`main` only). DERIVED = `panel_h_mm`,
  `image_panel_w_mm`; FIXED = `render_dpi`, `margin_top/right_mm`,
  `axis/tick/letter_font_pt`, `line_width`, `scale_bar_lw_pt`; LOCKED =
  `image_field_width_um`, `scale_bar_um`, `panel_aspect`.
  Relations `mixed.contain_*`, `panel_gap`, `panels_align_y`, letter aligns
  (`:625-655`).
- Science/QA hooks: `science_selfcheck` (`:696-802`), strict CLI as above.
- Overlay: **[UNVERIFIED]** — curve panel may yield `axis.title`/`axis.tick`/
  `curve.linewidth`; image panel likely none. Multi-candidate-curve ambiguity
  is limited (single curve `a`): good for exact-target cases, weak for
  ambiguous-target cases.
- G25 fit: cross-panel scope + neighbor-push (`curve_panel_w_mm` moves image
  panel) + `bare` isolation cases.

### F9 `figdemo` — synthetic demo, `main` (conditional)
- `FIGURE_ID`/`SCOPES` (`demo_figure.py:27-29`); `layout_contract`
  (`demo_figure.py:347+`) builds per-gid EDITABLE records (`:355-366`) —
  full path/range/relation list **[UNVERIFIED: contract tail not yet read]**.
- Do not list controls until the tail is read and a preflight packet confirms
  them. If confirmed, family offers synthetic multi-curve + peak-label cases
  independent of F1/F4.

### F10/F11 python-native (conditional, overlay-only)
- No `layout_contract` in either module (grep: no hits); `build_scene` +
  `build_figure_and_registry` exist. Native route absent by design.
- Overlay inventory possible in principle (rendered Axes + lines + texts) but
  descriptor eligibility/current values **[UNVERIFIED]**.

### F12 statistics (conditional, overlay-only)
- `layout_contract` returns zero parameters (`statistical.py:50-55`) →
  Native offers zero controls (verified absence, not a guess).
- Overlay: 2 connected lines + errorbar caps + legend on one Axes; caps/legend
  excluded by rule; whether either data line is an eligible `curve.linewidth`
  target is **[UNVERIFIED]**.

### F13–F20 G15 gallery wrappers (conditional, overlay-only, adverse prior)
- Source truth: 8 upstream files + sha256 (`tools/g15/inputs.json:6-15`);
  decl wrappers replay the FULL frozen source per build (e.g.
  `tools/g15/B/g15b_scatter_decl.py:50-71`) and declare no Native parameters.
- Evidence status: `tools/g15/summary.json` — 0 accepted edits from 15 legal
  intents, role-hint recall 9/19, "no proof of zero false rejection".
  G25 preflight must clear the blocker: ≥1 `eligible:true` descriptor per
  intended scope with recorded `selector`/`fingerprint`/`current`, or the
  family contributes no READY cases (compare-only/REFUSE roles at most).

## Can the repo support 12 independent families / 96 cases?

**No — not on verified evidence today.** Certified unseen families: **0**. F3/F4 have strict baseline probe PASS, not case-specific feasibility or unseen certification. The ledger contains eleven technical candidate rows; F10/F11 merge to one geometry, leaving at most 10 candidate geometries. F13/F16/F17 are DEVELOPMENT-only. Candidate capacity is not an approved unseen split.

Do not freeze F3/F4 or allocate 16 cases from them. Obtain independent-annotator/new-figure provenance, retained official per-case receipts, contamination signoffs and the complete freeze package first. The 12-family/96-case target remains unmet; do not reach it by counting scopes or wording variants as families. See `CASE_BUDGET.md` for current accounting and `G25_0_STATUS.md` for blockers.

## Isolated preflight commands/paths (no model, no writes to sources)

Run each session in a fresh process with a copied config + fresh overlay file
in an empty dir (G24 isolation pattern, `docs/G24_REPORT.md:27-34`):

```bash
# 1. Native contract packet (read-only; stdout is the packet when no --response)
python tests/fixtures/native_panels.py --list-params
python tests/fixtures/native_panels.py --inventory   # layout contract JSON
python tests/fixtures/native_mixed.py --list-params
python tests/fixtures/native_mixed.py --inventory

# 2. Strict + science/QA on an isolated copy (never the shipped yaml)
cp tests/fixtures/native_panels.yaml  <probe>/panels.yaml
python tests/fixtures/native_panels.py --config <probe>/panels.yaml --strict --probe <probe>/out
cp tests/fixtures/native_mixed.yaml   <probe>/mixed.yaml
python tests/fixtures/native_mixed.py --config <probe>/mixed.yaml --strict --probe <probe>/out

# 3. G25-style packet + trial skeleton (adapt tools/g24/run_blind.py:41-67, never reuse its gold)
python -m figpact.edit_plan --route auto --script tests/fixtures/native_panels.py \
  --config <probe>/panels.yaml --scope main --overlay <probe>/official-style.json \
  --request '<frozen request text>'
# then trial the frozen first-response file with --response <resp.json> (trial only,
# saved=false, publication_verified=false); record config/script/engine fingerprints
# and the raw receipt alongside the sha256 of every input.
```

Preflight record per case (freeze with the sample): script/config sha256,
engine revision, config + overlay bytes, live packet hash, control-ID set,
`engine_feasibility` (ACCEPTABLE/DRAFT_ONLY/REJECTED/UNKNOWN) with raw
receipt, science/view/QA state, and the reason for any UNKNOWN. Parameter
names alone never authorize — every control cites the contract line above.
