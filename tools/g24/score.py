"""G24 blind scorer: frozen gold stays independent of the planner; score first outputs only.

Parent session instantiation (run_blind.py owns it; this file only reads evidence):
- sessions.<name> = {script, config|null, scope, routes}. Resolve ${NMR_ROOT} /
  ${FTIR_ROOT} against --nmr-root / --ftir-root (defaults examples/nmr,
  examples/ftir); repo-relative paths resolve under the repo root.
- Per case open the listed routes only (native -> AgentSession(script, config,
  scope); overlay -> StyleSession(script, config, scope, fresh overlay file)),
  combine_contexts() the genuine discoveries, and send request_packet() carrying
  {request, context} but never gold. The model is stateless and sees no answers.
- Trial exactly the first <case-id>.json response via check_plan + trial_plan on
  fresh sessions (prepared context revision must still match). trials.json holds
  {cases_sha256, planner_sha256, model_transport, trials: [{id, attempt: 1,
  request, raw_response?, plan?, resolved_edits?, validation?, error?,
  trial_seconds, saved: false, publication_verified: false}]}.
- Score here: load_cases() refuses on frozen_sha256 mismatch (gold is immutable
  after freeze; no edits post-outputs). Denominators are derived from the frozen
  cases, never hand-filled. candidate_accepted (first-output trial accepted by
  the existing engine) is reported separately from publication_verified (whole
  QA / saved state, always false in blind trials): trial acceptance is NOT
  publication. Usage:
  python tools/g24/score.py --trials <trials.json> [--cases <blind_cases.json>]
      [--output <report.json>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD_VERSION = "g24-blind-v1"
VALUE_REL_TOL = 1e-9
VALUE_ABS_TOL = 1e-12


def canonical_cases_sha(cases) -> str:
    return hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def load_cases(path) -> dict:
    """Read + validate the frozen manifest; refuse on any sha/format mismatch."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("format") != GOLD_VERSION:
        raise ValueError(f"unknown gold format {manifest.get('format')!r}")
    sessions, cases = manifest.get("sessions"), manifest.get("cases")
    if not isinstance(sessions, dict) or not sessions:
        raise ValueError("manifest sessions must be a nonempty mapping")
    for name, descriptor in sessions.items():
        if not isinstance(descriptor, dict):
            raise ValueError(f"session {name!r} must be a mapping")
        if set(descriptor) != {"script", "config", "scope", "routes"}:
            raise ValueError(f"session {name!r} must declare exactly "
                             "script/config/scope/routes")
        if not isinstance(descriptor["script"], str) or not descriptor["script"]:
            raise ValueError(f"session {name!r} script must be a nonempty path")
        if descriptor["config"] is not None and not isinstance(descriptor["config"], str):
            raise ValueError(f"session {name!r} config must be a path or null")
        if not isinstance(descriptor["scope"], str) or not descriptor["scope"]:
            raise ValueError(f"session {name!r} scope must be nonempty")
        if not isinstance(descriptor["routes"], list) or not descriptor["routes"] \
                or any(r not in ("native", "overlay") for r in descriptor["routes"]):
            raise ValueError(f"session {name!r} routes must list native/overlay")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest cases must be a nonempty list")
    seen = set()
    for case in cases:
        for key in ("id", "session", "lang", "category", "request", "expected"):
            if key not in case:
                raise ValueError(f"case missing {key}: {case.get('id')!r}")
        if case["id"] in seen:
            raise ValueError(f"duplicate case id {case['id']!r}")
        seen.add(case["id"])
        if case["session"] not in sessions:
            raise ValueError(f"case {case['id']!r} names unknown session")
        if case["lang"] not in ("zh", "en"):
            raise ValueError(f"case {case['id']!r} lang must be zh|en")
        expected = case["expected"]
        if set(expected) != {"route", "status", "reject_category", "edits",
                             "preserve", "note"}:
            raise ValueError(f"case {case['id']!r} expected fields mismatch")
        if expected["route"] not in sessions[case["session"]]["routes"]:
            raise ValueError(f"case {case['id']!r} route not in session routes")
        if expected["status"] not in ("READY", "CLARIFY", "REFUSE"):
            raise ValueError(f"case {case['id']!r} bad status")
        if not isinstance(expected["preserve"], list) \
                or not {"science", "view"} <= set(expected["preserve"]):
            raise ValueError(f"case {case['id']!r} must preserve science+view")
        if expected["status"] == "READY" and not expected["edits"]:
            raise ValueError(f"case {case['id']!r} READY requires edits")
        if expected["status"] != "READY" and expected["edits"]:
            raise ValueError(f"case {case['id']!r} non-ready must have no edits")
    if manifest.get("frozen_sha256") != canonical_cases_sha(cases):
        raise ValueError("frozen_sha256 mismatch: gold was edited after freezing")
    return manifest


def _candidate_accepted(validation) -> bool:
    """Only explicit existing-engine acceptance counts; absent evidence fails."""
    if not isinstance(validation, dict) or validation.get("status") != "OK":
        return False
    if validation.get("route") == "overlay":
        return validation.get("accepted") is True
    trial = validation.get("trial")
    return (validation.get("route") == "native" and isinstance(trial, dict)
            and trial.get("status") == "OK" and isinstance(validation.get("preview"), dict))


def _axis_of(control: dict):
    if not isinstance(control, dict):
        return None
    for container in (control, control.get("selector"), control.get("display")):
        if isinstance(container, dict) and container.get("axis") in ("x", "y"):
            return container["axis"]
    return None


def _match_binding(resolved: dict, want: dict) -> tuple[bool, str]:
    """Match one resolved control (+value) against one gold edit descriptor."""
    if not isinstance(resolved, dict):
        return False, "resolved edit is not a mapping"
    value = resolved.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        return False, "resolved value is not a finite number"
    if not math.isclose(float(value), float(want["value"]),
                        rel_tol=VALUE_REL_TOL, abs_tol=VALUE_ABS_TOL):
        return False, (f"value {value!r} != gold {want['value']!r}")
    if want["kind"] == "native-path":
        if list(resolved.get("path", None) or []) == list(want["path"]):
            return True, "native path + value match"
        return False, f"native path {resolved.get('path')!r} != gold {want['path']!r}"
    role, prop, scope = (resolved.get("role"), resolved.get("property"),
                         resolved.get("scope"))
    if (role, prop, scope) != (want["role"], want["property"], want["scope"]):
        return False, (f"overlay {(role, prop, scope)!r} != "
                       f"gold {(want['role'], want['property'], want['scope'])!r}")
    axis = _axis_of(resolved)
    if axis is not None and axis != want.get("axis"):
        return False, f"overlay axis {axis!r} != gold {want.get('axis')!r}"
    if axis is None and want.get("axis"):
        return False, "axis identity missing; target cannot be credited"
    gid = want.get("selector_gid")
    if gid and gid not in (resolved.get("id") or "") \
            and gid not in json.dumps(resolved.get("selector", ""), sort_keys=True):
        return False, f"overlay target missing gold gid {gid!r}"
    return True, "role/property/scope/value match"


def score_record(record: dict, case: dict) -> dict:
    """Score one first-output trial record against its frozen gold case."""
    expected = case["expected"]
    verdict: dict = {"id": case["id"], "expected_status": expected["status"],
                     "expected_route": expected["route"],
                     "predicted": None, "route": None, "route_ok": False,
                     "binding_ok": False, "candidate_accepted": False,
                     "publication_verified": bool(record.get("publication_verified")),
                     "pass": False, "details": []}
    if record.get("attempt") != 1:
        verdict["details"].append("only first outputs score (attempt must be 1)")
        return verdict
    if record.get("error"):
        verdict["predicted"] = "ERROR"
        verdict["details"].append(f"first output unusable: {record['error']}")
        return verdict
    plan = record.get("plan") or {}
    verdict["predicted"] = plan.get("status")
    verdict["route"] = plan.get("route")
    verdict["route_ok"] = plan.get("route") == expected["route"]
    if plan.get("status") != expected["status"]:
        verdict["details"].append(
            f"status {plan.get('status')!r} != gold {expected['status']!r}")
        return verdict
    if expected["status"] != "READY":
        verdict["binding_ok"] = True  # non-ready plans carry no edits by construction
        verdict["candidate_accepted"] = False
        if verdict["route_ok"]:
            verdict["pass"] = True
            verdict["details"].append(f"correct {expected['status']} on gold route")
        else:
            verdict["details"].append(f"correct status but route {plan.get('route')!r} "
                                      f"!= gold {expected['route']!r}")
        return verdict
    # READY: route, edit count, per-edit binding+value, engine trial acceptance.
    if not verdict["route_ok"]:
        verdict["details"].append(f"route {plan.get('route')!r} != gold {expected['route']!r}")
        return verdict
    resolved = record.get("resolved_edits") or []
    want = list(expected["edits"])
    if len(plan.get("edits") or []) != len(want) or len(resolved) != len(want):
        verdict["details"].append(f"edit count {len(resolved)} != gold {len(want)} "
                                  "(partial multi-edit plans fail)")
        return verdict
    unmatched = list(resolved)
    for gold_edit in want:
        hit = next((r for r in unmatched
                    if _match_binding(r, gold_edit)[0]), None)
        if hit is None:
            reasons = "; ".join(_match_binding(r, gold_edit)[1] for r in resolved)
            verdict["details"].append(f"gold edit {gold_edit!r} unmatched: {reasons}")
            return verdict
        unmatched.remove(hit)
    verdict["binding_ok"] = True
    if not _candidate_accepted(record.get("validation")):
        verdict["details"].append("engine trial refused the candidate; not accepted")
        return verdict
    verdict["candidate_accepted"] = True
    if verdict["publication_verified"]:
        verdict["details"].append("anomaly: blind trials never publish")
        return verdict
    verdict["pass"] = True
    verdict["details"].append("first-output READY accepted at candidate level "
                              "(publication_verified=false: not whole QA)")
    return verdict


def derive_denominators(manifest: dict) -> dict:
    cases = manifest["cases"]
    ready = [c for c in cases if c["expected"]["status"] == "READY"]
    edits = [e for c in ready for e in c["expected"]["edits"]]
    by_route: dict[str, int] = {}
    for edit in edits:
        route = "native" if edit["kind"] == "native-path" else "overlay"
        by_route[route] = by_route.get(route, 0) + 1
    refuse: dict[str, int] = {}
    for case in cases:
        if case["expected"]["status"] == "REFUSE":
            key = case["expected"]["reject_category"] or "UNKNOWN"
            refuse[key] = refuse.get(key, 0) + 1
    return {"cases": len(cases),
            "ready_cases": len(ready),
            "ready_binding_attempts": len(edits),
            "ready_edits_by_route": by_route,
            "refuse_cases": sum(1 for c in cases if c["expected"]["status"] == "REFUSE"),
            "refuse_by_category": refuse,
            "clarify_cases": sum(1 for c in cases if c["expected"]["status"] == "CLARIFY"),
            "unauthorized_attempts": sum(1 for c in cases if c["category"] == "unauthorized")}


def score_all(manifest: dict, records: list[dict]) -> dict:
    if len({r.get("id") for r in records}) != len(records):
        raise ValueError("duplicate attempts cannot replace first responses")
    by_id = {r.get("id"): r for r in records if isinstance(r, dict)}
    verdicts = [score_record(by_id.get(case["id"], {"id": case["id"]}), case)
                for case in manifest["cases"]]
    denominators = derive_denominators(manifest)
    passed = sum(1 for v in verdicts if v["pass"])
    candidate_rate = (sum(1 for v in verdicts if v["candidate_accepted"])
                      / denominators["ready_cases"] if denominators["ready_cases"] else 0.0)
    ready = [c for c in manifest["cases"] if c["expected"]["status"] == "READY"]
    negatives = [c for c in manifest["cases"] if c["expected"]["status"] != "READY"]
    binding_hits = 0
    target_hits = 0
    for case in ready:
        record = by_id.get(case["id"], {})
        plan = record.get("plan") or {}
        if plan.get("route") != case["expected"]["route"]:
            continue
        remaining = list(record.get("resolved_edits") or [])
        for want in case["expected"]["edits"]:
            target = next((r for r in remaining
                           if _match_binding({**r, "value": want["value"]}, want)[0]), None)
            if target is not None:
                target_hits += 1
                binding_hits += int(_match_binding(target, want)[0])
                remaining.remove(target)
    unsafe = sum(_candidate_accepted(by_id.get(c["id"], {}).get("validation"))
                 for c in negatives)
    metrics = {
        "target_location": {"correct": target_hits, "total": denominators["ready_binding_attempts"]},
        "binding_and_value": {"correct": binding_hits, "total": denominators["ready_binding_attempts"]},
        "ready_plan": {"correct": sum(v["binding_ok"] and v["route_ok"] for v in verdicts
                                     if v["expected_status"] == "READY"), "total": len(ready)},
        "first_candidate": {"accepted": sum(v["candidate_accepted"] for v in verdicts),
                            "total": len(ready)},
        "negative_decision": {"correct": sum(v["pass"] for v in verdicts
                                            if v["expected_status"] != "READY"),
                              "total": len(negatives)},
        "unauthorized_acceptance": {"accepted": unsafe, "negative_requests": len(negatives),
                                   "missing_trials": sum(c["id"] not in by_id for c in negatives)},
    }
    return {"gold": {"format": manifest["format"],
                     "frozen_sha256": manifest["frozen_sha256"],
                     "denominators": denominators},
            "metrics": metrics,
            "verdicts": verdicts,
            "summary": {"passed": passed, "failed": len(verdicts) - passed,
                        "total": len(verdicts),
                        "candidate_accept_rate_on_ready": candidate_rate,
                        "publications": sum(1 for v in verdicts if v["publication_verified"]),
                        "note": "first outputs only; candidate acceptance is not "
                                "publication or saved state"}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "tools/g24/blind_cases.json")
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    manifest = load_cases(args.cases)
    payload = json.loads(args.trials.read_text(encoding="utf-8"))
    records = payload.get("trials") if isinstance(payload, dict) and "trials" in payload \
        else payload
    report = score_all(manifest, records)
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    summary = report["summary"]
    print(f"{summary['passed']}/{summary['total']} passed; "
          f"candidate accept rate on READY {summary['candidate_accept_rate_on_ready']:.2f}; "
          f"publications {summary['publications']}; "
          f"gold {report['gold']['frozen_sha256'][:12]}")
    for verdict in report["verdicts"]:
        if not verdict["pass"]:
            print(f"FAIL {verdict['id']}: " + "; ".join(verdict["details"]))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
