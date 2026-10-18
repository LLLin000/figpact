# G15-C appendix: commands, logs, artifact map

Freeze: `793aaa89b39af49d2421e2a2840751cf757ba959`. Upstream: Matplotlib v3.10.7
immutable commit `4aeb773422464799998d900198b35cb80e94b3e1`.
Truth: `tools/g15/inputs.json` (parent-unified) — each C file roles d=2
(axis.tick + curve.linewidth); legal intents d=2 (ticks 8pt, curve 0.8pt).

## Raw sources (bytes frozen)
- `tools/g15/C/raw/eventcollection_demo.py` sha256 `12f9facb…d88d88a`
- `tools/g15/C/raw/annotation_demo.py` sha256 `1073f84b…e7af1e186d1e0d1d90`
- License shared at `tools/g15/LICENSE.matplotlib.txt` + `NOTICE.txt` (parent-saved).

## R1 declarations (per-scope, protocol-compliant)
- `tools/g15/C/decl_ev/g15c_ev.py` (SCOPES main), `tools/g15/C/decl_ann/g15c_ann.py`
  (SCOPES fig0..fig5). Each build reruns the FULL raw text in order, selects its
  figure, registers ONLY that figure's real artists; contract nodes derive from the
  real registry; parameters []. Previous single-scope cross-registry run is
  harness-invalid, excluded from the main table.

## Pipeline entry
`D:/programs/Python/python.exe -B -X utf8 tools/g15/C/run_c.py [--output-dir DIR]`
(env: `PYTHONPATH=<repo>`, `PYTHONDONTWRITEBYTECODE=1`, `MPLBACKEND=Agg`).
Output dir default: `<repo>/../figpact-archive/g15-frozen/C` (D: fallback).
Per condition: CLI `contract discover` -> confirm-all -> `contract verify` ->
`plate audit --figure ...` -> `plate compare` -> `plate unify` (plan) ->
repeat `plate unify --apply` in isolated copy (before/after hashes) -> `plate receipt`.
Repeat: second `build_scene` geometry/view compare per scope.

## Evidence (all under output dir, NOT committed as repo logs)
`logs/` holds every command with exit/stdout/stderr (audit/compare/plan/
apply1/apply2/receipt/discover/verify per scope); `work/` holds drafts, plates,
isolated apply copies; `png/` R1 before-PNGs per scope; `raw_truth.json`,
`raw_png/`, `results_raw.json`, `results.json`.

## Corrected scoring
| sample | cond | recall | hint FP | bind FP | valid req | cap-rej | false-rej | unauth | repro |
|---|---|---|---|---|---|---|---|---|---|
| EV | R0 | 1/2 | 1/3 (set_title L59) | 0 | 0/2 | 2/2 | N/A | N/A/0 | 2/2 |
| EV | R1 | 0/2 (wrapper-AST limit) | 0/0 | 0 | 0/2 | 2/2 | N/A | N/A/0 | 1/1 + repeat-apply ✓ |
| ANN | R0 | 1/2 | 34/38 (34 ordinary annotations) | 0 | 0/2 | 2/2 | N/A | N/A/0 | 2/2 |
| ANN | R1 | 0/2 (wrapper-AST limit) | 0/0 | 0 | 0/2 | 2/2 | N/A | N/A/0 | 6/6 + repeat-apply ✓ |
axis.tick present in truth but unhinted (no tick call) — recall gap by
construction. axis.title absent: not a legal attempt.
