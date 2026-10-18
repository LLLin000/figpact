"""G15 stratum C final results builder (corrected scoring, no engine re-run).

Reads archive results_raw.json + tracked logs/drafts; writes results.json
(tracked + archive copies must match). Scoring follows parent corrections:
- truth from tools/g15/inputs.json: each C file roles=[axis.tick, curve.linewidth],
  d=2 per file (union across figures; scopes do not multiply the denominator).
  Legal visual intents d=2 per file: ticks 8pt + curve 0.8pt. Absent axis.title
  is NOT a legal edit attempt.
- Role-hint FP: per-location audit of R0 draft unresolved. set_title->axis.title
  (EV L59) and annotate->panel.label (ANN 34x) ARE hint FPs (engine-proposed role
  strings at wrong semantics). Binding-precision FP stays separate (0 candidates).
- R1 runpy wrappers are protocol-allowed declarations; AST hiding is a
  declaration-form/discovery limitation, not scientific distortion. Old single-scope
  cross-registry experiment is harness-invalid and excluded from the main table.
- Pipeline: independent audit CLI, repeat apply with before/after hashes; all 6
  annotation figures enumerated/rechecked in R1 (per-scope full-text rerun).
"""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
C = REPO / "tools" / "g15" / "C"
ARCH = REPO.parent / "figpact-archive" / "g15-frozen" / "C"
RAW = json.loads((ARCH / "results_raw.json").read_text(encoding="utf-8"))
INPUTS = json.loads((REPO / "tools" / "g15" / "inputs.json").read_text(encoding="utf-8"))
BY_PATH = {s["path"]: s for s in INPUTS["samples"]}

TRUTH = {
    "eventcollection": {
        "file": "eventcollection_demo.py",
        "present_roles": ["axis.tick", "curve.linewidth"],
        "role_evidence": {
            "axis.tick": ["default Axes ticks present (get_xticklabels 0.0..1.0, fs 10.0); "
                          "no tick_fontsize call in source"],
            "curve.linewidth": ["L36 ax.plot(xdata1, ydata1, color='tab:blue')",
                                "L37 ax.plot(xdata2, ydata2, color='tab:orange')"],
        },
        "non_role": ["4x EventCollection collection marks", "Axes title L59 (not axis.title role)",
                     "no xlabel/ylabel/legend/panel letters"],
    },
    "annotation": {
        "file": "annotation_demo.py",
        "present_roles": ["axis.tick", "curve.linewidth"],
        "role_evidence": {
            "axis.tick": ["default Axes ticks on all 7 axes; no tick_fontsize call"],
            "curve.linewidth": ["L62 ax.plot(t, s)", "L116 polar ax.plot(theta, r)",
                                "L120 marker-only plot", "L164 ax.plot(t, s, lw=3)"],
        },
        "non_role": ["34x ordinary Annotation (NOT panel.label truth, incl. polar/transform demos)",
                     "Ellipse patches", "no xlabel/ylabel/title/legend anywhere"],
    },
}


def hint_fp_audit(key):
    """Per-location audit of R0 draft unresolved -> hint FP count.

    EV: axis.title@L59 (set_title Axes title) = 1 hint FP; 2x linewidth hints correct.
    ANN: 34x panel.label hints on ordinary annotations = 34 hint FPs;
         4x linewidth hints correct (L62/116/120/164).
    """
    if key == "eventcollection":
        return {"n": 1, "d": 3, "detail": "axis.title hint@L59 is FP (Axes title, not xlabel/ylabel role); 2x curve.linewidth hints correct."}
    return {"n": 34, "d": 38, "detail": "34x panel.label hints on ordinary annotations are FP (no panel letters in source); 4x curve.linewidth hints correct."}


def build():
    out = {"group": "C", "freeze_sha": RAW["freeze_sha"],
           "upstream_sha": RAW["upstream_sha"], "upstream_urls": RAW["upstream_urls"],
           "license": "tools/g15/LICENSE.matplotlib.txt + NOTICE.txt (parent-saved, shared)",
           "truth_source": "tools/g15/inputs.json (parent-unified): per-file roles d=2; "
                           "legal intents d=2 (ticks 8pt, curve 0.8pt); axis.title absent "
                           "is not a legal attempt; scopes do not multiply the denominator.",
           "method_validity": {
               "r1_form": "per-scope build_scene (SCOPES fig0..fig5 + main), each rerunning the "
                          "FULL raw text in order then selecting its figure; registry and "
                          "contract nodes derive from the RETURNED figure's real artists only. "
                          "Protocol-allowed declarations, not harness distortion.",
               "r1_ast_limit": "wrapper AST hides original plotting statements from Discover; "
                               "recorded as declaration-form/discovery limitation (main-table "
                               "0/2 with limitation note), not as all-wrapper-forms-fail.",
               "old_experiment": "previous single-scope cross-registry ANN run retained as "
                                 "harness-invalid, excluded from the main table.",
               "scoring": "recall per-raw-file role kinds (d=2); hint FP per unresolved "
                          "location; binding FP separate (0 candidates); "
                          "unauthorized N/A on 0 acceptances.",
           },
           "samples": []}
    for smp in RAW["samples"]:
        key = smp["id"]
        T = TRUTH[key]
        entry = {"id": key, "source": smp["source"], "truth": T,
                 "present_roles": T["present_roles"], "role_denom": 2,
                 "legal_intents": [
                     {"role": "axis.tick", "param": "tick_font_pt", "target": "8pt"},
                     {"role": "curve.linewidth", "param": "line_width", "target": "0.8pt"}],
                 "conditions": {}}
        # ---------- R0 ----------
        c0 = smp["conditions"]["R0"]
        fp = hint_fp_audit(key)
        tag0 = ("r0_" + key)
        entry["conditions"]["R0"] = {
            "config": "external empty YAML (no binding)",
            "source_sha_before": c0.get("source_sha_before"),
            "source_sha_after": c0.get("source_sha_after"),
            "source_unchanged": c0.get("source_unchanged"),
            "log_paths": {st: f"{ARCH.as_posix()}/logs/{st}_{tag0}.log"
                          for st in ("discover", "verify", "audit", "compare", "plan",
                                     "apply1", "apply2", "receipt")},
            "stages": {"discover_exit": c0.get("discover_exit"),
                       "verify_exit": c0.get("verify_exit"),
                       "audit_exit": c0.get("audit_exit"),
                       "compare_exit": c0.get("compare_exit"),
                       "plan_exit": c0.get("plan_exit"),
                       "apply_exit": c0.get("apply_exit"),
                       "receipt_exit": c0.get("receipt_exit"),
                       "verified": c0.get("verified", []), "failed": c0.get("failed", [])},
            "plate_note": "blocked: raw exposes no build entry. The corrected audit, "
                          "compare, plan, apply and receipt CLI attempts exit 1 with RuntimeError; "
                          "the earlier audit argument-shape error is excluded from final scores.",
            "role_recall": {"n": 1, "d": 2,
                            "note": "curve.linewidth hinted with exact AST lines; axis.tick "
                                    "present in truth but unhinted (no tick call in source)."},
            "role_hint_fp": fp,
            "binding_precision": {"n": 0, "d": "N/A",
                                  "note": "0 candidates; precision N/A, not 100%."},
            "binding_fp": {"n": 0, "checked": "0 candidates: nothing to misbind."},
            "valid_requests": {"n": 0, "d": 2,
                               "note": "ticks 8pt + curve 0.8pt preregistered; no bindings, "
                                       "0 successes. axis.title absent: not an attempt."},
            "capability_rejections": {"n": 2, "d": 2,
                                      "note": "both intents lack bindings; capability gap, "
                                              "not engine false rejection."},
            "false_rejections": {"n": 0, "d": "N/A",
                                 "note": "nothing safely expressible was refused."},
            "unauthorized_accepted": {"n": "N/A", "d": 0,
                                      "note": "0 accepted edits; unobserved, not proven 0."},
            "reproducibility": {"n": 2, "d": 2,
                                "blocked": "plate stages N/A (no build entry)",
                                "note": "Discover+Verify repeat-consistent; source bytes unchanged."},
        }
        # ---------- R1 ----------
        c1 = smp["conditions"]["R1"]
        scopes = c1.get("scopes", [])
        # per-scope outcomes
        scope_rows = {}
        for sc, d in c1.get("scope_data", {}).items():
            tag = f"r1_{key}_{sc}"
            scope_rows[sc] = {"discover_exit": d.get("discover_exit"),
                              "verify_exit": d.get("verify_exit"),
                              "n_gids": d.get("n_gids"), "gids": d.get("gids"),
                              "repeat": d.get("repeat"),
                              "log_paths": {st: f"{ARCH.as_posix()}/logs/{st}_{tag}.log"
                                            for st in ("discover", "verify", "audit", "compare",
                                                       "plan", "apply1", "apply2", "receipt")}}
        plate_rows = {}
        for sc, p in c1.get("plate", {}).items():
            plate_rows[sc] = {"audit_exit": p.get("audit_exit"),
                              "compare_exit": p.get("compare_exit"),
                              "plan_exit": p.get("plan_exit"),
                              "apply_exit": p.get("apply_exit"),
                              "receipt_exit": p.get("receipt_exit"),
                              "apply1_unchanged": p.get("apply_hashes", {}).get("apply1", {}).get("source_unchanged"),
                              "apply2_unchanged": p.get("apply_hashes", {}).get("apply2", {}).get("source_unchanged"),
                              "apply_status": (p.get("apply") or {}).get("status")}
        # recall: wrapper AST hides originals -> 0/2 with limitation note (not distortion claim)
        entry["conditions"]["R1"] = {
            "declaration": c1.get("declaration"),
            "decl_sha256": c1.get("decl_sha256"),
            "scopes": scopes,
            "scope_outcomes": scope_rows,
            "plate_outcomes": plate_rows,
            "source_sha_before": c1.get("source_sha_before"),
            "source_sha_after": c1.get("source_sha_after"),
            "source_unchanged": c1.get("source_unchanged"),
            "all_figures_enumerated": (len(scopes) == (6 if key == "annotation" else 1) and
                                       all(v.get("n_gids", 0) > 0 for v in scope_rows.values())),
            "role_recall": {"n": 0, "d": 2,
                            "note": "wrapper AST hides original plotting statements from Discover "
                                    "(0 hints by construction); declaration-form/discovery "
                                    "limitation, not scientific distortion; denominator unchanged."},
            "role_hint_fp": {"n": 0, "d": 0, "checked": "0 hints proposed; nothing to misattribute."},
            "binding_precision": {"n": 0, "d": "N/A",
                                  "note": "identity-only registry, 0 EDITABLE params; N/A."},
            "binding_fp": {"n": 0, "checked": "0 candidates; nothing to misbind."},
            "valid_requests": {"n": 0, "d": 2, "note": "same 2 intents, 0 successes (no bindings)."},
            "capability_rejections": {"n": 2, "d": 2,
                                      "note": "declaration form frozen; no tuning to manufacture params."},
            "false_rejections": {"n": 0, "d": "N/A", "note": "nothing safely expressible refused."},
            "unauthorized_accepted": {"n": "N/A", "d": 0,
                                      "note": "0 accepted edits across repeat applies (NOT_WRITTEN, "
                                              "before/after hashes equal); unobserved."},
            "reproducibility": {
                "n": sum(1 for v in scope_rows.values()
                         if v.get("repeat", {}).get("view_equal") and v.get("repeat", {}).get("lines_equal")),
                "d": len(scope_rows),
                "repeat_apply": all(v.get("apply1_unchanged") and v.get("apply2_unchanged")
                                    for v in plate_rows.values()),
                "note": "per-scope rebuild geometry/view equal; repeat --apply identical refusal "
                        "with unchanged file hashes."},
        }
        out["samples"].append(entry)
    out["observed_bugs"] = [
        "No engine fix attempted; no source/engine edits made. R1 uses per-scope declarations "
        "(fig0..fig5 + main), each rerunning the full raw text in order (no per-cell split, no "
        "new seed); only the protocol-allowed single-declaration form changed, for validity. "
        "Notes: (1) plate audit CLI takes --figure flags; R0 audit/compare/plan/apply/receipt "
        "are blocked at entry (no build hooks in raw) — expected. (2) axis.tick is present in "
        "truth but undiscoverable by construction (no tick call) — recall gap, not a miss. "
        "(3) annotation science-capture gap: text/arrow repositioning has no binding and arrow "
        "geometry is display_derived — documented gap, nothing passed off as proof."
    ]
    (C / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (ARCH / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"wrote": [str(C / "results.json"), str(ARCH / "results.json")],
                      "samples": len(out["samples"])}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    build()
