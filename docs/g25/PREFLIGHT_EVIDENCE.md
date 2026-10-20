# G25-0 Preflight Evidence (candidate/draft only — NOT frozen)

Status: evidence collection only. No model calls, no requests, no gold cases made.
No freeze claimed; no 96-case corpus claimed. All families below remain
candidate/draft until independent annotator + signoff. No JSON gold file is
tagged frozen.

Sources: outputs already delivered by `PreflightPanelsMixed`, `PreflightDemoPythonNative`,
`PreflightG15Gallery`. No commands re-run; sources untouched by this report.
Raw private receipts remain outside the repo (see §6).

Freeze pointers: protocol `docs/G25_PROTOCOL.md`, brief `docs/G25_RESEARCH_BRIEF.md`,
inventory `docs/g25/CANDIDATE_FIGURES.md`, schema `docs/g25/G25_0_FREEZE_SCHEMA.md`
(DRAFT), G24 audit `docs/g25/G24_CONTAMINATION.md` (all G24 families DEVELOPMENT;
no current repository family certified as independent unseen).

## 0. Preflight levels distinguished (exact condition per result)

- **L1 — strict `--probe` publication-level baseline PASS.** Fresh process, isolated
  temp-config copy, `--strict --probe <tmp>/out`, `EXIT 0` + `[QA] 无阻断项 ✓` +
  published outputs. This is the only publication-baseline level. Observed only for
  F3/F4 (8/8 each, both scopes). Nothing else in this report reaches L1.
- **L2 — descriptor/inventory positivity.** `style_identity.inventory(fig)` and/or
  `style_overlay.inventory(script,config,scope)` return `unique=True, eligible=True`
  descriptors with selector/fingerprint/current. Proves a target exists; proves
  nothing about engine acceptance, science/view/QA gates, or publication.
- **L3 — clone trial.** `resolve(desc)` + setter on an isolated clone + `canvas.draw()`
  (`APPLIED_CLONE`). Used for G15 sampled roles only. Science/view/QA gates and
  official `validate_candidate`/receipt were NOT run. L3 ≠ engine feasibility.
- **L4 — official existing-engine candidate trial.** `edit_plan`/`plan_context` dry
  trial on a staged copy (`saved=false`, `publication_verified=false` throughout),
  with live `inspect_candidate` receipt. Trial ≠ publication. Observed only for
  F9–F12 overlay (+ F9 native dry trials, both rejected).
- **L5 — independent validation.** Signed independent-annotator provenance +
  frozen official `validate_candidate` + science/view/QA receipt per intended case.
  **Not achieved for any family in this report.** Hence no unseen label anywhere.

`engine_feasibility` stays **UNKNOWN** wherever L5 (and for G15, also L4) is missing,
even when L2 is positive. Native leg REJECTED/absent + overlay L2-positive still =
UNKNOWN overall.

## 1. Fingerprints (as observed by preflight agents, 2026-10-19)

Engine env (all three): Python 3.14.0, matplotlib 3.10.8, numpy 2.3.3, backend Agg,
Windows-11-10.0.26200. Repo HEAD `fdc72f3…` (PanelsMixed: full
`fdc72f310c290aa80cf57288918cb66ec63858e3`).
G15 agent notes current HEAD ≠ G15 freeze `793aaa89…` — engine drift since G15 freeze,
recorded, not resolved.

- F3 `tests/fixtures/native_panels.py`: `ee5dcef1…a01c45`;
  `tests/fixtures/native_panels.yaml`: `ef2f85e1…9018add9b9`
  (`--inventory` echoed `config_revision ef2f85e18795`, matches file hash).
- F4 `tests/fixtures/native_mixed.py`: `b3f6f6fc…4c95bcc0b8f`;
  `tests/fixtures/native_mixed.yaml`: `9be7943a…f1110a1b47a2`
  (`--inventory` echoed `9be7943a661e`, matches).
- Shared: `tests/fixtures/_native.py`: `4a1f9733…7633c467f043d`;
  `tests/fixtures/fixture_data.py`: `748be819…7999e30173`, `SEED=20261010`,
  `SCIENCE_INPUTS=()` both families (generative in-memory payload).
- `tools/g24/blind_cases.json` file-bytes hash re-observed `28b12e76…388016514`
  (matches contamination doc §6).
- F9 `examples/demo/demo_figure.py` `dbe6890e…53bda3` · `demo.yaml` `4f4dc35b…9230b848`.
- F10 `examples/python_native/simple_figure.py` `fe298676…589e2642b`.
- F11 `examples/python_native/legacy_plain.py` `dba9f6f9…c8d0de886`.
- F12 `examples/statistics/statistical.py` `f5a05840…84e9d34cc` ·
  `statistical.yaml` `13ad0942…d645d7b8`.
- Engine files (demo agent): `edit_plan.py` `6fbf763c…231570adfa5`,
  `plan_context.py` `dbed3fec…4080fb96f2`, `agent_api.py` `20c38500…81d4c`,
  `inspector_style.py` `75fdb191…f9304d9586`, `runtime.py` `e1e14e4f…8799a83ce`,
  `style_overlay.py` `11edda8d…98066ad838`.
- G15 raw sources: all 8 sha256 match `tools/g15/inputs.json` exactly (via `sha256sum`):
  subplots `802f31d6…`, label `a99b7dd3…`, figlegend `589a20e8…`, barchart `f742b277…`,
  errorbar `9741f89b…`, scatter `e128daaa…`, eventcollection `12f9facb…`,
  annotation `1073f84b…`. Wrapper sha256 (full values in private JSON only):
  subplots `6265ca07…`, label `95436bd8…`, figlegend `29e64fed…`, barchart `dfabf65b…`,
  errorbar `1ceaf094…`, scatter `1a7ab6ec…`, ev `faa9bbff…`, ann `b5ee3f16…`.
- Repo cleanliness (G15 + demo agents): `git status --porcelain` / `git status -- examples/`
  show only pre-existing untracked `docs/UI/`, `docs/figpact-vnext-kit/`, `docs/g25/`,
  `docs/research/R7…`; `git diff --stat -- examples/` empty. None touched by preflights.
  (Hashes above are truncated as reported; full values live in private receipts, §6.)

## 2. Contamination boundary

- **G24: CONFIRMED clean for all families in this report.** G24 sessions
  (`blind_cases.json:614-695`) use only `native_ftir.py`, `native_nmr.py`,
  `${FTIR_ROOT}/plot_ftir.py`, `${NMR_ROOT}/08 NMR.py`, `tools/g24/fixtures.py`
  (R1–R13/F1–F8/C1–C3). Literal grep for
  `native_panels|native_mixed|fig_panels_native|fig_mixed_native|curve_lift_mm|panel_gap_mm|letter_inset`
  → 0 hits each; grep over `tools/g24/fixtures.py`, `results.json`,
  `case_validity.json`, `docs/G24_REPORT.md` for `panels|mixed|fig_panels|fig_mixed` →
  none. Demo agent: grep `tools/g24` for
  `figdemo|intent|legacy|statistics|demo_figure|simple_figure|legacy_plain|statistical` →
  no matches. G15 agent: grep over `tools/g24/`, `docs/G24_REPORT.md`,
  `case_validity.json`, `fixtures.py` for
  `g15|gallery|subplots_demo|barchart|scatter_with|errorbar_features|annotation_demo|eventcollection` →
  no matches. Hard no-cross-split rule satisfied everywhere.
- **Genuine model contamination beyond G24 (adverse, must be preserved):**
  G15 prior (`tools/g15/summary.json`): 0 editable candidates, 15/15 capability
  rejections, role-hint recall 9/19 — engine-eval prompt/declaration debugging, not
  G24 packets, but developers have seen and replayed these figures extensively.
  Deeper exposure for 3 G15 families: G16 protocol/report reused `B/barchart`
  (ylabel), `A/subplots_demo` fig07 (shared-x ticks), `B/errorbar` ax0 (curve lw) as
  implementation targets; G18 reuses barchart in live UI tests. G15 agent verdict:
  these three MUST be treated as prompt-exposed regardless of G24 cleanliness.
- **Independent-annotator provenance: ABSENT for every family.** F3/F4 are
  pre-existing seeded repo fixtures (caveat C1, `CANDIDATE_FIGURES.md:53-57`);
  F9–F12 are shipped examples; G15 are gallery replays. No family may be labelled
  unseen without signed independent provenance + L5.

## 3. F3 `fig_panels_native` + F4 `fig_mixed_native` (PanelsMixed)

Level reached: **L1 strict PASS (both families, both scopes)** + L2 inventory.
L4 session-level `discover_native/discover_overlay` not run (needs `FigureSession` +
overlay file); authorization judged from contract records + `style_overlay.inventory` +
`style_identity` descriptors (same authority those functions read). No `edit_plan`
trial — per ticket, strict dry probe only. L5 not reached.

- **L1:** `native_panels.py --config <tmp>/panels.yaml --strict --probe <tmp>/out` →
  EXIT 0: `[QA] main: 无阻断项 ✓`, `[QA] bare: 无阻断项 ✓`, published **8/8**
  (`fig_panels_native_{main,bare}.{png,pdf,svg,tiff}`). Same shape for
  `native_mixed.py` → EXIT 0, **8/8** (`fig_mixed_native_{main,bare}.*`).
  Procedural note (not a figure defect): first attempt with `/tmp/...` failed with
  `ConfigError: 配置文件不存在` (Windows box resolves to `D:\tmp\...`); reran via
  `C:/Users/Lin/...` temp dir, EXIT 0. Read-only `--list-params` + `--inventory`
  both EXIT 0.
- **F3** (2×2 micrographs, scopes `main`/`bare`): unique target YES (only 2×2
  fixed-seed grid, per-panel field widths a:52 / b:26 / c:13 / d:104 µm,
  `PANEL_GRID`, joint-aspect 1.3 hard gate `_check_aspect`, `native_panels.py:177-185`).
  Native READY-worthy controls YES — EDITABLE 11 (main) / 9 (bare): `canvas_w/h_mm`,
  `render_dpi`, `margin_left/bottom_mm`, `panel_w/h_mm` (joint pair — single-side edit
  rejected by aspect gate), `gap_x/y_mm`, `letter_inset_x/y_mm` (main-only). Locks
  correct: `panel_aspect`/`scale_bar_um`/`panel_field_um` LOCKED_SCIENCE;
  `margin_right/top_mm` FIXED_STYLE clearance gates. Contract `native_panels.py:485-575`,
  relations `:577-608`. Scope isolation real (bare has no letter params/nodes/relations).
  Science/QA hooks YES: `science_selfcheck` (pixels/extent/aspect/scale-bar/text) `[]`
  without fig; `--strict` passes both scopes; `science_manifest` keys `{nodes, science}`.
- **F3 Overlay conflict (preserved):** 4 eligible descriptors per scope, all
  `curve.linewidth` — **but every one is a scale bar**
  (`...scale_bar.{a,b,c,d}.linewidth`, `unique=True`, current 1.6 pt, identical via
  `style_identity.inventory(fig)` and `style_overlay.inventory(script,config,scope)`).
  QA problem: no `axis.title`/`axis.tick` (image-only Axes, as predicted); Overlay
  authorizes linewidth edits on objects the Native contract declares FIXED_STYLE
  (`scale_bar_lw_pt`, `:543-546`). **Overlay READY on this family would contradict the
  Native lock. Verdict: Native READY-capable; Overlay not READY-safe — at most
  negative-role (REFUSE/CLARIFY) or DRAFT_ONLY pending a scale-bar exclusion rule.**
- **F4** (FTIR curve + micrograph, `main`/`bare`): unique target YES (only
  curve-plus-image side-by-side; single curve `a`, 240 pts; `curve_lift_mm` ±4 mm pure
  display shift; neighbor-push `curve_panel_w_mm`; aspect lock 1.3). Native
  READY-worthy YES — EDITABLE 9 (main) / 7 (bare): `canvas_w/h_mm`,
  `margin_left/bottom_mm`, `curve_panel_w_mm`, `panel_gap_mm`, `curve_lift_mm`,
  `letter_inset_x/y_mm` (main-only). `panel_h_mm`/`image_panel_w_mm` DERIVED, styles
  FIXED, `image_field_width_um`/`scale_bar_um`/`panel_aspect` LOCKED. Contract
  `native_mixed.py:486-622`, relations `:625-655`. Science/QA hooks YES
  (`science_selfcheck` `[]`; `--strict` both scopes; manifest `{nodes, science}`).
- **F4 Overlay (preserved):** 6 eligible per scope, identical in bare/main: curve-panel
  `curve.a linewidth` (0.8 pt, real data curve), `tick.x`/`tick.y fontsize` (6.5 pt),
  `xlabel`/`ylabel fontsize` (7.5 pt) — all `unique=True`, in `ALLOWED_TARGETS`,
  in-range — **plus 1 scale-bar-as-curve** (`image_panel ...scale_bar.linewidth`,
  1.2 pt). Curve-panel subset is READY-worthy (exact-target cases; single-curve so
  weak for ambiguity cases); **scale-bar descriptor carries the same QA caveat as F3
  and MUST be excluded from Overlay READY gold** (shadows FIXED_STYLE `scale_bar_lw_pt`).
- Classification: **F3-Native ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR; F3-Overlay excluded
  from READY (negative/DRAFT_ONLY at most). F4-Native ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR;
  F4-Overlay curve-panel subset ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (exact-target only),
  scale-bar descriptor excluded.** Overall unseen UNKNOWN until annotator + L5.
  (`bare`-scope letter absence has no Overlay effect — letters are Native Text, never
  Overlay targets — confirmed by identical bare/main descriptor sets.)

## 4. F9–F12 demo / python-native / statistics (DemoPythonNative)

Level reached: **L4 official existing-engine candidate trial (overlay; staged copies,
`saved=false`)**, plus L2 inventories. No L1 strict probe. No L5. Python-native
source-edit route NOT trialed (writes journal — out of scope).

- **F9 `figdemo` (`examples/demo/demo_figure.py` + `demo.yaml`, `main` only):**
  hooks all present (`load_science` seeded rng42, `build_scene`, `layout_contract`,
  `science_manifest`, `prepare_config`). Native live: 3 EDITABLE rebuild controls
  (`peak_label_shifts_mm/main/peak.{alpha.2p06,beta.5p00,gamma.7p46}`, role=style,
  min/max ±10, current None — baseline yaml has empty map), 11 snapshot nodes
  (6 registered: 3 curves + 3 peak Texts; panel `main::panel.0`), pidx 3, dpi 100,
  calibrated False. **Dry trials both reject (dangling controls preserved):**
  pair `[1.0,0.5]` → `INVALID_VALUE` "必须是有限数字"; scalar `1.0` →
  `UNSUPPORTED_PATH` "在配置里不存在（悬空引用）". Cause: baseline lacks the keys;
  offered controls are dangling under current config — live-authorization failure, not
  model error. Overlay live: 7 controls (3 gid-bound `curve.linewidth` + tick x/y +
  xlabel/ylabel), 23 nodes, `issue_count` 0, axes `s445b3e47a722`. Dry trial +0.5 pt →
  **local PASS / whole FAIL**, `draft_eligible true`,
  `qa_delta.inherited ["gid:figdemo.main.legend"]`, saved=false.
  Classification: **UNKNOWN — Native BLOCKED (contract/baseline fix needed); Overlay
  DRAFT_ONLY-class.** Not unseen-eligible (no annotator provenance).
  UNKNOWNs: scalar-vs-pair contract semantics; whole-FAIL root cause beyond
  inherited-legend label (not diagnosed — no source edits allowed).
  (`demo.contract.yaml` perturbation digests exist checked-in but were not re-proven
  by live trial — trials rejected pre-science-check.)
- **F10 `intent` (`examples/python_native/simple_figure.py`, `main` only):**
  `LAYOUT_MM` 2 keys; `locate_layout_literal` → line 47
  `{'start':1258,'end':1268,'value':[0,0]}` for `intent.main.label.A`. No
  YAML/contract/manifest by design. Native-YAML route **unavailable, observed**
  `AgentSession requires a config file` (not guessed). Overlay: 5 controls (curve
  `intent.main.curve` + 4 font), 17 nodes, issues 0. Trial +0.5 →
  **OK, local PASS, whole PASS, qa clean, saved=false.** Science: analytic Gaussian,
  documented only, no engine manifest.
  Classification: **ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay trial-OK only;
  trial≠publication).** Blockers: annotator + freeze; **geometry-twin of legacy**
  (shared overlay axes fingerprint `s189fc6349bb6` — identical curve/geometry,
  different gids → same-geometry pair, MUST NOT count as two independent unseen samples).
  Python-native source-edit route exists but NOT trialed → UNKNOWN for that route.
- **F11 `legacy` (`examples/python_native/legacy_plain.py`, `main` only):**
  negative control by design: `read_layout_binding` → `{}`, `locate` → None. No
  YAML/contract/manifest. Native-YAML same observed unavailability. Overlay:
  5 controls (`legacy.main.curve` + 4 font), 17 nodes, same axes `s189fc6349bb6`,
  issues 0. Trial +0.5 → **OK/PASS/PASS, saved=false.**
  Classification: **native-no-authority as designed (good REJECT/negative-class
  candidate); overlay ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (trial-OK).**
  Blockers: annotator + freeze; not independent of simple (twin, same fingerprint).
- **F12 `statistics` (`examples/statistics/statistical.py` + `statistical.yaml`, `main`):**
  synthetic fixed arrays; `layout_contract` declares `parameters: []`, nodes
  `editable:false LOCKED_SCIENCE`. Native live opens fine (validated, rev `237a5a06…`)
  with **0 controls**, 13 nodes, pidx 0 — correctly offers nothing. Overlay: 6 controls
  (2 gid-bound curves + 4 font), 28 nodes, issues 0. Trial +0.5 → **OK/PASS/PASS,
  qa clean, saved=false.** Note: `build_figure_and_registry` uses `CONFIG={}` so
  yaml-less direct build would KeyError (code-observed, not executed); yaml-backed
  paths used throughout.
  Classification: **native AUTHORITY-negative by design (REFUSE-class for native
  requests); overlay ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (trial-OK).**
  Blockers: annotator + freeze only.
- Cross-cutting: panel identity native `main::panel.0` everywhere; overlay axes_keys
  `s445b3e47a722` (demo), `sb39814ea0b54` (stats), `s189fc6349bb6` (simple+legacy).
  Overlay node projection has no parent/scope (per protocol) — B-arm parent/scope claims
  would need an info-increment arm; not done. `overlay_sha256 ""` for fresh (nonexistent)
  overlay files is expected, not a failure. All four single-scope `main`, single-panel —
  none supplies the G25-priority "same text, different panel" split.

## 5. F13–F20 G15 gallery (G15Gallery)

Level reached: **L2 inventory positive (all families) + L3 clone trial (sampled roles
only). L1/L4/L5 NOT reached.** Native ABSENT everywhere (`layout_contract →
parameters: []`, EDITABLE 0 — exact lines `B/g15b_barchart_decl.py:87-93`,
`g15b_errorbar_decl.py:80-86`, `g15b_scatter_decl.py:80-86`,
`C/decl_ev/g15c_ev.py:103-117`, `C/decl_ann/g15c_ann.py:102-116`,
`A/wrap_*_r1.py:103-125`). Overlay-only at most. Official `engine_feasibility`
stays UNKNOWN (native leg REJECTED/absent; overlay leg descriptor-positive but
unaccepted; science/view/QA gates and official `validate_candidate`/receipt not run).

- Inventory probe: fresh-process `build_figure_and_registry(scope)` +
  `layout_contract(scope)` + `style_identity.inventory(fig, scope)` per scope.
  Full-scope coverage: A-subplots 13/13, A-label 3/3, A-figlegend 1/1, B-bar 1/1,
  B-err 2/2, B-scat 3/3, C-ev 1/1, C-ann 6/6. All `current` finite (ticks uniform 10.0,
  lw 1.5 unless noted).
- L3 clone probe: `resolve(fig2, desc, scope)` + setter on isolated clone +
  `canvas.draw()` succeeded (`APPLIED_CLONE`, `n_artists_resolved ≥ 1`) for sampled
  roles: bar title/tick, ev curve, figlegend curve, scatter tick, subplots fig07 tick,
  label fig00 tick.
- Per-family (eligible = `unique=True, eligible=True`, selector+fingerprint present):
  - F13 A/subplots_demo (13 scopes): 88 eligible total (e.g. fig00 3 = 2 tick + 1 curve;
    fig07 5; fig12 6; fig04/fig11 also expose `axis.title`, 4 each).
    → **DEVELOPMENT only (EXCLUDE from unseen)** — G16 target reuse = prompt-exposed.
  - F14 A/label_subplots (3 scopes): 8 eligible/scope, all `axis.tick`.
    → **ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only, single scope max;
    unseen UNKNOWN)** — needs official L4 trial + annotator signoff.
  - F15 A/figlegend_demo (1 scope): 8 eligible (4 tick + 4 curve).
    → **ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only; unseen UNKNOWN)** —
    same conditions.
  - F16 B/barchart (main): 3 eligible (2 tick + 1 `axis.title` ylabel, current 10.0).
    → **DEVELOPMENT only (EXCLUDE from unseen)** — G16+G18 reuse.
  - F17 B/errorbar (ax0, ax1): 4 eligible each (3 tick + 1 curve, lw 1.5) —
    **but cross-scope alias (preserved): `_build_frozen()` returns the whole Figure 1
    for both scopes; stripped descriptor identities are identical except the mutable
    registry gid suffix. Both scopes expose the same figure's both axes → violates
    single-scope identity.**
    → **DEVELOPMENT only, at most 1 scope even for dev; EXCLUDE from unseen** —
    alias + G16 reuse.
  - F18 B/scatter (3 scopes): 2 eligible/scope, all `axis.tick`; PathCollections
    correctly absent (not targets).
    → **ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only, single scope max;
    unseen UNKNOWN).**
  - F19 C/eventcollection (main): 4 eligible (2 tick + 2 curve).
    → **ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only; unseen UNKNOWN).**
  - F20 C/annotation (6 scopes): fig0 3, fig1 3, fig2 2, fig3 3 (curve lw 3.0),
    fig4 2, fig5 4; per-scope `figs[index]` selection → true figure isolation
    (unlike errorbar).
    → **ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only, ≤1 scope preferred;
    unseen UNKNOWN).**
- Rationale: G15 adverse prior (0 candidates under R0/R1 wrapper-AST discovery) does
  NOT transfer to Overlay `style_identity` inventory — the prior measured
  declaration-form discovery, and current probes find authorized descriptors. But
  prior + G16/G18 reuse means no family can be claimed unseen without a fresh
  independent annotator, a frozen official `validate_candidate` + science/view/QA
  receipt per intended case, and single-scope discipline (errorbar fails the last
  even for dev).

## 6. Private receipt locations (no guessing)

- PanelsMixed: fresh-process probes against isolated temp-config copies; temp dir
  **removed afterwards**. No exact temp path was supplied to the parent —
  **source-receipt location unavailable** (do not guess). Evidence in this report is
  limited to the delivered summary (fingerprints, EXIT codes, QA lines, 8/8 counts).
- DemoPythonNative: isolated copies under
  `C:/Users/Lin/AppData/Local/Temp/g25preflight_diobsobx/` (staged `demo/`,
  `native_simple/`, `native_legacy/`, `stats/` + `receipts/` with 9 JSON receipts).
  Fresh process per probe. **No model calls, no tests/builds/formatters, no commits.
  Sources untouched.** Raw JSON receipts stay in that private dir, outside the repo.
- G15Gallery: all probes ran in fresh processes with outputs only under private
  `Temp/g15pre/` as reported (raw receipts retained there, outside repo). Exact
  absolute temp path was not supplied — **absolute source-receipt location unavailable**;
  quoted relative path `Temp/g15pre/` only. No repo writes; no requests/gold created;
  no model calls.

## 7. Classification rollup (route-level; family unseen = UNKNOWN everywhere)

| Family | Native | Overlay | Unseen |
|---|---|---|---|
| G24 F1/F2/F6/F7/F8 | DEVELOPMENT (seen) | DEVELOPMENT (seen) | NO |
| F3 panels | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (L1 PASS, 11/9 EDITABLE, QA hooks) | EXCLUDED from READY (scale-bar conflict; negative/DRAFT_ONLY at most) | UNKNOWN (C1 + no annotator) |
| F4 mixed | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (L1 PASS, 9/7 EDITABLE, QA hooks) | curve-panel ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (exact-target only); scale-bar EXCLUDED | UNKNOWN (C1 + no annotator) |
| F9 demo | UNKNOWN (BLOCKED — dangling controls, both dry trials reject) | UNKNOWN (DRAFT_ONLY-class; local PASS / whole FAIL, inherited legend) | UNKNOWN |
| F10 simple | UNKNOWN (YAML route unavailable; source-edit route untrialed) | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (L4 trial-OK; twin caveat) | UNKNOWN (twin + no annotator) |
| F11 legacy | UNKNOWN by design (no authority; REJECT-class candidate) | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (L4 trial-OK; twin caveat) | UNKNOWN (twin + no annotator) |
| F12 statistics | AUTHORITY-negative by design (0 controls; REFUSE-class) → ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR as native-REJECT only | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (L4 trial-OK) | UNKNOWN |
| F13 subplots | ABSENT (DEVELOPMENT-role N/A) | DEVELOPMENT only (G16-exposed) | EXCLUDED |
| F14 label | ABSENT | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only, 1 scope max; needs L4+L5) | UNKNOWN |
| F15 figlegend | ABSENT | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only; needs L4+L5) | UNKNOWN |
| F16 barchart | ABSENT | DEVELOPMENT only (G16+G18-exposed) | EXCLUDED |
| F17 errorbar | ABSENT | DEVELOPMENT only (cross-scope alias + G16-exposed; ≤1 scope even for dev) | EXCLUDED |
| F18 scatter | ABSENT | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only, 1 scope max; needs L4+L5) | UNKNOWN |
| F19 eventcoll. | ABSENT | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only; needs L4+L5) | UNKNOWN |
| F20 annotation | ABSENT | ELIGIBLE-CANDIDATE-PENDING-ANNOTATOR (overlay-only, ≤1 scope; needs L4+L5) | UNKNOWN |

Blockers to any freeze: (1) independent annotator(s) + signoff for every intended
case; (2) L5 frozen official `validate_candidate` + science/view/QA receipt per case
(G15 needs L4 first); (3) F9 native contract/baseline fix (or drop native for F9);
(4) scale-bar exclusion rule before any F3/F4 overlay READY gold; (5) single-scope
discipline (errorbar alias; simple/legacy twin counted once); (6) contamination
manifest + family registry + gold + scorer + prompt/schema + model-config + split
list + thresholds, each SHA256-recorded before first run (per freeze schema §5–§7).
