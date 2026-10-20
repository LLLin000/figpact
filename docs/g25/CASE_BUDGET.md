# G25-0 Case Budget — candidate allocation vs infeasibility (DRAFT, no freeze)

Status: **DRAFT candidate budget only**. No model calls, no requests written,
no gold cases created (`frozen = 0`). No freeze, no 96-case corpus claimed.
All counts below are **candidate capacity estimates** conditional on
independent-annotator provenance + per-case official preflight, unless marked
DEVELOPMENT/excluded.

Target (planning guidance only, from `docs/g25/G25_0_FREEZE_SCHEMA.md` §2.2):
`READY 48 / CLARIFY 16 / REJECT 16 / NO_OP 16 = 96`, across 12 independent
families (~8/family). `planned` ≠ `frozen`. This file asserts no frozen counts.

Sources used (only): `docs/g25/CANDIDATE_FIGURES.md` (F1–F20 definitions),
`docs/g25/G24_CONTAMINATION.md` (G24 exclusion units), completed preflight
reports in orchestration context: PreflightPanelsMixed (F3/F4), PreflightDemoPythonNative
(F9–F12), PreflightG15Gallery (F13–F20). No source edits made for this file.

## 1. Family ledger (one row per source family; scopes are NOT families)

| # | Source family | G24 status | G15/G16/G18 exposure | Preflight observed | Budget class |
|---|---|---|---|---|---|
| F1 | `tests/fixtures/native_nmr.py` | EXCLUDED — G24 `fix_nmr_main` all scopes | — | reference only | DEVELOPMENT, never unseen |
| F2 | `tests/fixtures/native_ftir.py` | EXCLUDED — G24 `fix_ftir_*` all 4 scopes | — | reference only | DEVELOPMENT |
| F3 | `tests/fixtures/native_panels.py` (`fig_panels_native`, `main`/`bare`) | clean vs G24 model packets (0 hits, PreflightPanelsMixed) | none known | Native READY-capable 11 (`main`)/9 (`bare`); strict `--probe` PASS 8/8 both scopes; Overlay 4 eligibles/scope but ALL scale-bar `curve.linewidth` shadowing Native FIXED_STYLE → not READY-safe | CANDIDATE-PENDING-ANNOTATOR (caveat C1: pre-existing fixture, not new independent figure); Native only |
| F4 | `tests/fixtures/native_mixed.py` (`fig_mixed_native`, `main`/`bare`) | clean vs G24 (same grep) | none known | Native READY-capable 9/7; strict PASS 8/8; Overlay 6/scope: 5 curve-panel (1 curve lw + 2 tick + 2 title, READY-worthy, single-curve so weak for ambiguity) + 1 scale-bar tainted, MUST exclude | CANDIDATE-PENDING-ANNOTATOR (caveat C1); Native + curve-panel Overlay only |
| F5 | `tests/fixtures/native_negatives.py` | not G24-selected, intentionally defective `publishable: False` | — | gate-test only | EXCLUDED from unseen (defective by design) |
| F6 | `examples/nmr/08 NMR.py` | EXCLUDED — G24 `priv_nmr_main` + private `${NMR_ROOT}` | — | reference only | DEVELOPMENT |
| F7 | `examples/ftir/plot_ftir.py` | EXCLUDED — G24 `priv_ftir_*` all scopes | — | reference only | DEVELOPMENT |
| F8 | `tools/g24/fixtures.py` (`fig_synth_errlegend`) | EXCLUDED — G24 `synth_errlegend` | — | reference only | DEVELOPMENT |
| F9 | `examples/demo/demo_figure.py` (`figdemo`, `main` only) | clean vs G24 (grep no match) | none known | Native BLOCKED (3 EDITABLE offered but dangling: pair→`INVALID_VALUE`, scalar→`UNSUPPORTED_PATH` under baseline yaml); Overlay 7 controls, dry trial +0.5pt → local PASS / whole FAIL (`draft_eligible`, inherited legend QA) → DRAFT_ONLY-class | CANDIDATE-PENDING-ANNOTATOR, overlay-only at most; Native 0 until contract/baseline fix; official `engine_feasibility` UNKNOWN |
| F10 | `examples/python_native/simple_figure.py` (`intent`, `main`) | clean vs G24 | geometry-twin of F11 (shared overlay axes fp `s189fc6349bb6`, identical curve/geometry) | Native-YAML unavailable by design (observed `AgentSession requires a config file`); Overlay 5 controls, trial +0.5 OK/PASS/PASS saved=false | CANDIDATE-PENDING-ANNOTATOR, overlay-only; counts as ONE geometry with F11, not two families |
| F11 | `examples/python_native/legacy_plain.py` (`legacy`, `main`) | clean vs G24 | geometry-twin of F10 (same fp) | Native-YAML unavailable + `read_layout_binding {}` by design (good REJECT-class for native requests); Overlay 5 controls, trial OK/PASS/PASS | CANDIDATE-PENDING-ANNOTATOR, overlay-only; NOT independent of F10 |
| F12 | `examples/statistics/statistical.py` (`statistics`, `main`) | clean vs G24 | none known | Native `parameters: []` verified absence (authority-negative, REFUSE-class for native requests); Overlay 6 controls (2 curves + 4 font), trial OK/PASS/PASS saved=false | CANDIDATE-PENDING-ANNOTATOR, overlay-only; official `engine_feasibility` UNKNOWN (trial≠publication, needs `validate_candidate` + science/view/QA receipt) |
| F13 | G15 A/subplots_demo (13 scopes) | clean vs G24 (no match) | PROMPT-EXPOSED — G16 reuse (fig07 shared-x ticks) + adverse G15 R0/R1 prior | Native ABSENT (`parameters: []`); Overlay 88 eligible/13 scopes w/ selector+fp (descriptor-positive; prior non-transfer: prior measured decl-AST discovery, not `style_identity` inventory); QA clone-only PASS | DEVELOPMENT only, EXCLUDE from unseen |
| F14 | G15 A/label_subplots (3 scopes) | clean vs G24 | G15 prior only, no G16/G18 reuse known | Native ABSENT; Overlay 8/scope tick-only, clone PASS | conditional eligible-candidate overlay-only single-scope-max, UNKNOWN unseen |
| F15 | G15 A/figlegend_demo (1 scope) | clean vs G24 | G15 prior only | Native ABSENT; Overlay 8 (tick+curve), clone PASS | conditional eligible-candidate overlay-only, UNKNOWN unseen |
| F16 | G15 B/barchart (1 scope) | clean vs G24 | PROMPT-EXPOSED — G16 + G18 reuse | Native ABSENT; Overlay 3 (tick+ylabel title), clone PASS | DEVELOPMENT only, EXCLUDE from unseen |
| F17 | G15 B/errorbar (ax0/ax1) | clean vs G24 | PROMPT-EXPOSED — G16 reuse + cross-scope alias (`_build_frozen` returns whole Figure for both scopes; stripped identities identical) | Native ABSENT; Overlay 4+4 but alias violates single-scope identity | DEVELOPMENT only (≤1 scope even for dev), EXCLUDE from unseen |
| F18 | G15 B/scatter (3 scopes) | clean vs G24 | G15 prior only | Native ABSENT; Overlay 2/scope tick-only, PathCollections correctly absent | conditional eligible-candidate overlay-only single-scope-max, UNKNOWN unseen |
| F19 | G15 C/eventcollection (1 scope) | clean vs G24 | G15 prior only | Native ABSENT; Overlay 4 (tick+curve), clone PASS | conditional eligible-candidate overlay-only, UNKNOWN unseen |
| F20 | G15 C/annotation (6 scopes) | clean vs G24 | G15 prior only | Native ABSENT; Overlay 17/6 scopes, true `figs[index]` isolation (unlike F17) | conditional eligible-candidate overlay-only ≤1 scope preferred, UNKNOWN unseen |

Engine-feasibility key: strict `--probe` PASS (F3/F4 baseline publication gate)
≠ descriptor/inventory positivity ≠ clone-trial PASS ≠ official
`validate_candidate` + science/view/QA receipt. Per-case `engine_feasibility`
is **UNKNOWN** for every family today because no frozen request has been
trialed through the official engine path with raw receipt. F3/F4 strict PASS
and F10/F11/F12 overlay trial-OK do NOT upgrade any case to ACCEPTABLE.

## 2. Independence accounting (no double-counting)

- Two scopes/variations of one family ≠ two families. `main`/`bare` (F3/F4),
  13 scopes of F13, 6 of F20, 3 of F14/F18, 2 aliased scopes of F17 MUST NOT be
  counted as families. At most one scope per G15 family may contribute unseen
  cases (F17: zero scopes unseen — excluded).
- F10 + F11 = ONE candidate geometry (shared axes fingerprint
  `s189fc6349bb6`). Counting both as independent families is forbidden.
- F3/F4 caveat C1: pre-existing seeded fixtures, never in any model packet
  (hard split rule satisfied), but "independent annotator + new figures"
  preference unmet. They are at most ELIGIBLE_CANDIDATE-PENDING-ANNOTATOR, and
  the contamination audit declares no `ELIGIBLE_CANDIDATE` family yet.
- G15 adverse prior (`summary.json`: 0 candidates, 15/15 rejections) does not
  transfer as an Overlay incapability finding, but G15/G16/G18 prompt exposure
  (F13/F16/F17) is genuine contamination beyond G24 and forces DEVELOPMENT-only
  regardless of descriptor positivity.

The ledger contains eleven candidate rows before merging F10/F11: F3, F4, F9, F10, F11, F12, F14, F15, F18, F19, F20. Merging the twin once leaves **at most 10 distinct candidate geometries**, not certified unseen families. All lack independent-annotator provenance and official per-case preflight; certified unseen families remain **0**.

## 3. 96-case target vs present support (infeasibility table)

Planned strata are targets only; `frozen = 0` in every cell.

| Stratum (planned) | Needs | Presently supportable (candidate, pre-annotator) | Gap |
|---|---|---|---|
| READY 48 | READY-worthy control + unique target + official ACCEPTABLE per case | F3 Native + F4 Native + F4 curve-panel Overlay + overlay tick/curve descriptors (F10/11/12, F14/15/18/19/20) are descriptor-positive, but ZERO cases have official ACCEPTABLE receipts; F9 Native blocked; F13/16/17 excluded; F17 aliased | 48 READY NOT supportable today — no family can supply frozen READY without annotator + official trial |
| CLARIFY 16 | ambiguous/under-specified axis/target with ≥2 live candidates | F4 single-curve is weak for ambiguity; overlay tick-only families (F14/F18) offer x-vs-y ambiguity shape but unproven; no frozen ambiguous-target inventory | NOT supportable — needs multi-curve/multi-panel ambiguous designs + proven candidate sets |
| REJECT 16 | LOCKED/NO_AUTHORITY/OUT_OF_RANGE/scope-mismatch with evidence | Shapes exist as CANDIDATE shapes only: F3/F4 LOCKED science fields, F11/F12 native-authority-negative, F9 dangling-path, scale-bar FIXED-vs-Overlay conflict, F17 alias — none frozen with receipts | NOT supportable — shapes identified, zero frozen with refusal receipts |
| NO_OP 16 | current-value equality with measured base value | Requires per-case `base_value` + no-op refusal receipt; none measured | NOT supportable — zero frozen |
| 12 families / ~8 each | 12 independent unseen families | 10 candidate geometries max; F13/F16/F17 are separately DEVELOPMENT-excluded; 0 with annotator signoff → certified unseen families **0** | Short by 12 certified families. The numerical candidate-capacity gap is 2 only if all 10 candidates pass every gate; that is not an unseen-certification forecast. |

No gold cases created. No `cases_gold.json`, no `preflight_evidence.json`,
no per-request `engine_feasibility` assigned.

## 4. Recommendation: which 12-family/96 strata are unsupported + what is needed

1. **Freeze nothing today.** The 12-family/96 plan is infeasible on verified
   evidence: 5 families DEVELOPMENT-excluded by exact G24 reuse (F1/F2/F6/F7/F8),
   1 excluded as defective-by-design (F5), 3 G15 families DEVELOPMENT-only by
   prompt exposure (F13/F16/F17), 1 geometry merge (F10/F11), and 0 families with
   independent-annotator provenance.
2. **Development preflight priorities only:** F3/F4 have strict baseline PASS, but require official per-case trials and scale-bar exclusions before any task-feasibility claim. Their pre-existing-fixture provenance does not meet the current unseen gate. F12/F10-or-F11 (one twin only) and F9-overlay may also inform development checks; successful trials alone cannot certify them unseen.
3. **G15 conditional pool:** F14/F15/F18/F19/F20 remain unverified candidates, one scope each. Prior study exposure requires explicit contamination review; F13/F16/F17 remain DEVELOPMENT-only. Do not assume clearing technical preflight makes any G15 family unseen.
4. **New independent families required:** the numerical capacity shortfall is at least 2 even if all 10 candidate geometries could qualify. Under the current positive-provenance gate none qualifies, so plan for 12 independently authored, contamination-cleared families unless evidence establishes eligibility otherwise. Each needs new script + config + data-source provenance, no prompt-debugging exposure, source fingerprints, isolated inventory/contract checks and official per-case receipts. Include multi-curve/multi-panel families for ambiguity strata; do not infer a case allocation from geometry counts.
5. **Annotator/signoff evidence needed before any `frozen` count:** independent-annotator
   role signoff, contamination-audit pass, representability-audit pass,
   per-case `preflight_evidence.json` entries (`model_called: false`,
   `isolated_copy: true`, fingerprints + `receipt_raw`), and
   `review_signoffs.json` all-pass per `G25_0_FREEZE_SCHEMA.md` §7. Until then
   every sample stays candidate/draft and every `engine_feasibility` stays UNKNOWN
   where an official receipt is absent.
