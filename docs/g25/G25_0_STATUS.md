# G25-0 status: BLOCKED

**Overall status: `BLOCKED`, not `COMPLETED`.** Preparation documents and consistency checks are complete; prerequisites for independent evaluation are not. Protocol artifacts remain DRAFT and unfrozen. Do not generate the 96-case gold, freeze a corpus, or call the evaluated model. Certified unseen families: **0**; frozen cases: **0**.

## Completed preparation evidence

- `G24_CONTAMINATION.md`: all G24 families/cases, prompt rounds, private evidence boundaries, contamination rules and hashes. All G24 source families are DEVELOPMENT and excluded from unseen.
- `CANDIDATE_FIGURES.md`: 20 source families inventoried with route/scope/contract evidence and explicit UNKNOWNs.
- `G25_0_FREEZE_SCHEMA.md`: DRAFT artifact/field/provenance/invariant schema; no freeze signoffs.
- `PREFLIGHT_EVIDENCE.md`: actual isolated preflight results, graded by evidence level. F3/F4 strict `--probe` baseline PASS; no L5 independent-annotator + frozen-request official validation for any family.
- `AB_PREFLIGHT_DESIGN.md`: DRAFT no-model A/B1 equivalence and optional B2 design.
- `CASE_BUDGET.md`: DRAFT candidate feasibility; 12-family/96-case plan not supportable today.

## Verified blockers

1. **Independent annotator provenance absent.** F3/F4 are pre-existing seeded fixtures; F9-F12 shipped examples; G15 figures have prior G15/G16/G18 exposure or G15 study history. No family is certified unseen.
2. **Twelve independent families unavailable.** The ledger has eleven candidate rows; merging F10/F11 once leaves at most 10 distinct candidate geometries. None is certified unseen. The numerical capacity gap of 2 does not reduce the current shortfall of 12 certified families.
3. **Gold feasibility unverified.** No frozen request has an official candidate receipt. Inventory positivity, clone mutation, strict baseline publication, and trial-only overlay results are distinct evidence levels; none alone is gold for all tasks.
4. **Known route/control conflicts.** F3/F4 Overlay sees scale bars as `curve.linewidth`, although Native contracts lock scale-bar style. F9 Native EDITABLE paths are dangling against the baseline config. G15 errorbar has cross-scope aliasing. F9's overlay dry trial is only draft-eligible due to inherited QA. These cannot be silently presented as simple READY positives.
5. **Strata not demonstrated.** No frozen multi-curve/multi-panel independent family supports the intended ambiguity/CLARIFY set; no measured no-op receipts; no 48 READY, 16 CLARIFY, 16 REJECT, 16 NO_OP gold labels.
6. **A/B mechanism not run.** No per-sample A/B packet bytes or equivalence checker results exist. Current protocol distinguishes same-fact presentation B1 from added-information B2; neither was generated.
7. **Historical raw evidence: `EVIDENCE_UNAVAILABLE`.** F3/F4 temporary probe receipts were deleted; G15 receipt locations are not fully recorded (see `PREFLIGHT_EVIDENCE.md` §6). Preserve historical narrative observations with this limitation. Do not reconstruct missing first-run receipts or replace them with new ones. A later rerun proves current behavior only and must carry its own run identity and timestamp.

## What exists and what does not

Candidate artifacts are not frozen data: no `cases_gold.json`, no `preflight_evidence.json` per candidate case, no signed `review_signoffs.json`, no finalized `model_config.placeholder.json`, no `freeze_record.json`, no immutable unseen split. Do not compute or report first-pass accuracy, confidence intervals, or model safety rates.

The 96-case / 12-family plan and 48/16/16/16 allocation are an unfrozen design proposal, not a statistical threshold. Do not fill slots using multiple scopes, wording variants, or changed values from the same family. A smaller final design requires an explicit protocol amendment, including revised sample size, family dependence and analysis assumptions, before the first formal model call; it cannot inherit the original design's statistical guarantees.

## Next work: G25-S — independent source and annotation admission

G25 evaluation work is paused. G25-S is a source-feasibility pilot, not completion of G25 or permission to run the evaluated model. First seek 2–3 genuinely independent candidate families; do not generate replacement FTIR/NMR tasks with the current agents or repeat G24 fixtures to satisfy independence.

Preferred sources are scripts supplied by other researchers or independent third-party public research repositories. Record original author, intended use, license, acquisition provenance and original bytes. Matplotlib Gallery sources require same-source/variant and prior G15/G24/development-exposure checks. Swapped data, colors or labels in the same script retain their parent-family relationship and are not independent families.

Admission has three separate gates: **source certification → control authority and representability review → independent gold signoff**. Missing any gate leaves a family in the candidate pool, not the certified count. From acquisition onward retain original script/data/dependency hashes, environment versions, actual inventory, independent annotations, isolated preflight receipts and eventual freeze records. Successful runtime checks alone do not certify independence.

The pilot only checks trusted execution of the original script, auditable controls and independent annotatability. Public scripts must be reviewed and run in isolation before execution. Do not call the evaluated model or claim a frozen evaluation sample from pilot activity.

## Re-entry gate for G25

Resume only when the first independently sourced batch has passed source certification, real control/representability review and independent annotation signoff, with reproducible isolated preflight receipts. Then amend or retain the sample-size/statistical design using the observed source supply and family dependence; freeze the complete package before the first formal model call. Until then G25-0 remains `BLOCKED`.

Other figpact development may continue separately, including FTIR scope/legend limitations, statistical-object controls and usability. Every figure used for development or prompt debugging must enter the contamination ledger and remain excluded from future unseen claims. Do not expand G25 protocol documentation or rerun old fixtures merely to create apparent evaluation progress.

## Publication boundary

Historical preparation checkpoint: the user's GitHub `master` lookup returned 404 before the local artifacts were published. G25-S was subsequently committed and pushed to `origin/master` as [`74ea67a`](https://github.com/LLLin000/figpact/commit/74ea67a), and the user independently confirmed remote access. The earlier 404 is historical, not the current publication state. G25-S2 changes are separate from that published baseline; no newer commit/push is claimed here.

## Preparation validation (not freeze verification)

Two read-only scout audits identified the off-by-one geometry count, stale F3/F4 eligibility/freeze advice, two G24 case-family misattributions, the candidate/certified label collision, and the missing explicit NO_OP representability constraint. These were corrected. No reviewer-agent audit completed; both reviewer jobs failed with an unavailable-model error.

At the preparation checkpoint, the read-only Python structural check passed: contamination JSON parsed with five DEVELOPMENT families; G24 contained 24 cases; eleven candidate ledger rows merged to ten geometries; seven preparation Markdown documents existed; no gold/signoff/freeze package existed. No model evaluation or new runtime preflight had been run at that checkpoint. The later user-authorized G25-S runtime stress run is recorded separately below; it does not upgrade historical preflight evidence or certify unseen families.

SHA256 snapshots of preparation dependencies only (not a freeze record or signoff; this status file is intentionally excluded):

| File | SHA256 |
|---|---|
| `AB_PREFLIGHT_DESIGN.md` | `421219689b59ca4e22094aef1510765f72fba802a5e9c06ec66fef1177b630bd` |
| `CANDIDATE_FIGURES.md` | `2e78dda5d93b03716564f9df04149cb1291689bc4e43882f2ed17b4a0355e3b4` |
| `CASE_BUDGET.md` | `b086b9fca3c6ddfeb05a9f9a6991cc714026a8afc9edf4b2d144a7a056d5059d` |
| `G24_CONTAMINATION.md` | `30546b46b85ad6a8e6281c330fe2ee194191fc316ba2ea19ef08c9607047bdc3` |
| `G25_0_FREEZE_SCHEMA.md` | `f48a4dd5d7b5b30652a75e03309af10c11907a0e08ba2e23d9b86dd990edb233` |
| `PREFLIGHT_EVIDENCE.md` | `d26ebe7f75f4576592e64d777b4f596ec2b70ea592db541bde05336578005e64` |

## G25-S external-source development stress run

User-authorized sourcing and runtime stress probes are complete; **formal G25-0 remains BLOCKED**. See `G25S_STRESS_REPORT.md` and `../../tools/g25s/runs/summary.json` (repository path: `tools/g25s/runs/summary.json`). Downloaded original scripts, pinned revisions/licenses, raw results and baseline PNGs are retained.

The development contamination ledger is `tools/g25s/runs/summary.json:source_records`: all 26 script versions (24 repository/upstream paths) are `DEVELOPMENT_EXPOSED`, with no independent signoff. They cannot later be relabeled unseen. Of 26 script versions, 23 rendered 51 Figures; 129 candidate probes and 130 structural plan-negative checks ran. Candidate errors, baseline incompatibilities and context failures remain in the denominator and report. No model evaluation, formal gold/freeze, product fix, source-style repair, official Overlay save or publication occurred.

## G25-S2 compatibility acceptance

G25-S2 compatibility fixes and regression checks are complete; **formal G25 remains BLOCKED**. See `G25S2_COMPATIBILITY_REPORT.md`. All 26 DEVELOPMENT_EXPOSED source versions were rerun; every original candidate retained its target/base/value (129/129 matched, no missing), with uncaught candidate exceptions 12→0. Context creation is 50/51, not universal support; 14 Figures still have no authorized targets.

Final regressions: Python 694 passed / 7 skipped / 120 subtests, Chromium 28 passed, Node 54 passed. Isolated NMR Strict PASS / FTIR Strict FAIL semantics remain unchanged. The final run preserved unknown/nonfinite geometry refusals, no-op/range refusals, scientific mutation counterexamples and all original G25-S records. No independent source certification, gold freeze or model A/B evaluation was performed. This acceptance checkpoint preceded publication; subsequent G25-S2 commit/push state is recorded by repository history and the push receipt, not by changing the evaluation status.
