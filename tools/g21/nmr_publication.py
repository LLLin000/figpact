#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G21 NMR publication proof (public, generic runner): existing native
transaction + audit on a private copy, then strict reload + render.

Owns NOTHING except running: script/config/output-dir come from env/flags
(private archive paths, never the repo). No product changes, no FTIR files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv=None) -> int:
    import matplotlib
    matplotlib.use("Agg")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--script", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--output-dir", required=True,
                    help="fresh private dir; evidence lands here, never the repo")
    ap.add_argument("--save", action="store_true",
                    help="also install strict artifacts + config (publication step)")
    args = ap.parse_args(argv)
    script = Path(args.script).resolve()
    config = Path(args.config).resolve()
    outdir = Path(args.output_dir)
    if outdir.exists():
        ap.error("output dir must be fresh (never overwrite evidence)")
    outdir.mkdir(parents=True)

    from figpact import runtime
    from figpact import qa as qa_mod

    worker = runtime.FigureWorker(script, config, "main")
    try:
        state0 = worker.state()
        base_cfg = dict(state0.get("candidate_config") or {})
        evidence: dict = {
            "script": str(script), "config": str(config),
            "script_sha256": _sha(script), "config_sha256": _sha(config),
            "science_inputs": state0.get("science_inputs"),
            "contract_source": (state0.get("contract") or {}).get("source"),
            "n_contract_params": len((state0.get("contract") or {}).get("parameters", [])),
        }
        # Baseline: real objects/values/thresholds/roles via actual measure.
        import importlib.util
        spec = importlib.util.spec_from_file_location("nmr_g21_base", str(script))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fig0, _ = mod.build_figure_and_registry("main")
        try:
            measured = qa_mod.measure(fig0)
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig0)
        glyph = [r for r in measured["records"] if r["rule"] == "GLYPH_FLOOR"]
        evidence["baseline"] = {
            "n_records": len(measured["records"]),
            "glyph_floor": [{"key": r["key"], "value": r["value"],
                             "unit": r["unit"], "threshold": r["threshold"],
                             "severity": r["severity"], "text": r["text"]}
                            for r in glyph],
            "problems": list(measured["problems"]),
            "env": measured.get("env"),
        }
        # Controlled repair via EXISTING native transaction: width-only canvas
        # expansion (height stays 48 so raw ylim is bit-identical) + fonts 7.2.
        ops = [
            {"operation": "set_parameter", "path": ["peak_font_pt"], "value": 7.2},
            {"operation": "set_parameter", "path": ["legend_font_pt"], "value": 7.2},
            {"operation": "set_parameter", "path": ["canvas_w_mm"], "value": 68.0},
        ]
        tried = worker.try_layout(ops)
        evidence["try_layout"] = {
            "status": tried.get("status"),
            "verification": tried.get("verification"),
            "message": tried.get("message"),
            "changes": tried.get("changes"),
            "checks": tried.get("checks"),
            "diagnostics": tried.get("diagnostics"),
            "science_unchanged": tried.get("science_unchanged"),
            "science_notes": tried.get("science_notes"),
            "qa_kind": tried.get("qa_kind"),
            "qa": tried.get("qa"),
            "new_qa": tried.get("new_qa"),
            "affected_objects": tried.get("affected_objects"),
            "relations": tried.get("relations"),
        }
        if tried.get("status") != "OK":
            (outdir / "nmr_evidence.json").write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps({"status": tried.get("status"),
                              "message": tried.get("message")}, indent=2, ensure_ascii=False))
            return 2
        # Independent audit (fresh rebuilds, existing capture API): compare the
        # BASE build against the CANDIDATE build — never the candidate vs itself.
        cand_cfg = dict(worker.state().get("candidate_config") or {})
        evidence["candidate_config_delta"] = {
            k: {"base": base_cfg.get(k), "candidate": cand_cfg.get(k)}
            for k in ("peak_font_pt", "legend_font_pt", "canvas_w_mm", "canvas_h_mm")
        }
        from figpact import science as _sci
        import copy as _copy
        _base_cfg_snapshot = dict(base_cfg)
        import matplotlib.pyplot as _plt
        _fig_b, _reg_b = mod._build(mod.load_science(), "main")
        try:
            _ax_b = _fig_b.axes[0]
            _cap_b = _sci.capture_science(
                _fig_b, _reg_b,
                declarations=mod.science_manifest(mod.load_science()))
            _meas_b = qa_mod.measure(_fig_b)
        finally:
            _plt.close(_fig_b)
        mod._apply_config(_copy.deepcopy(cand_cfg))
        _fig_c, _reg_c = mod._build(mod.load_science(), "main")
        try:
            _ax_c = _fig_c.axes[0]
            _cap_c = _sci.capture_science(
                _fig_c, _reg_c,
                declarations=mod.science_manifest(mod.load_science()))
            _meas_c = qa_mod.measure(_fig_c)
            import matplotlib.text as _mt
            _fig_c.canvas.draw()
            _rc = _fig_c.canvas.get_renderer()
            _fb = [float(v) for v in _fig_c.bbox.bounds]
            _worst = {"over_px": 0.0, "text": None, "fontsize": None}
            for _a in _fig_c.findobj():
                if not isinstance(_a, _mt.Text) or not _a.get_visible():
                    continue
                if not str(_a.get_text() or "").strip():
                    continue
                try:
                    _bb = _a.get_window_extent(_rc)
                except Exception:
                    continue
                _over = max(_fb[0] - _bb.x0, _fb[1] - _bb.y0,
                            _bb.x1 - (_fb[0] + _fb[2]), _bb.y1 - (_fb[1] + _fb[3]))
                if _worst["text"] is None or _over > _worst["over_px"]:
                    _worst = {"over_px": round(float(_over), 4),
                              "text": str(_a.get_text())[:32],
                              "fontsize": round(float(_a.get_fontsize()), 2)}
            _ov_c = {"fig_bbox_px": [round(v, 2) for v in _fb], **_worst}
        finally:
            _plt.close(_fig_c)
        mod._apply_config(_base_cfg_snapshot)
        _o_b, _o_c = _cap_b["objects"], _cap_c["objects"]
        _curves_b = {g: (_reg_b.get(g).get_xdata().tobytes(),
                         _reg_b.get(g).get_ydata().tobytes())
                     for g in _reg_b.all() if ".curve." in g}
        _curves_c = {g: (_reg_c.get(g).get_xdata().tobytes(),
                         _reg_c.get(g).get_ydata().tobytes())
                     for g in _reg_c.all() if ".curve." in g}
        _texts_b = sorted(
            (g, _reg_b.get(g).get_text()) for g in _reg_b.all()
            if hasattr(_reg_b.get(g), "get_text")
            and (_reg_b.get(g).get_text() or "").strip()
            and (".peak." in g or ".legend.text." in g))
        _texts_c = sorted(
            (g, _reg_c.get(g).get_text()) for g in _reg_c.all()
            if hasattr(_reg_c.get(g), "get_text")
            and (_reg_c.get(g).get_text() or "").strip()
            and (".peak." in g or ".legend.text." in g))
        evidence["independent_audit"] = {
            "baseline": {
                "xlim": [float(v) for v in _ax_b.get_xlim()],
                "ylim": [float(v) for v in _ax_b.get_ylim()],
                "xscale": str(_ax_b.get_xscale()), "yscale": str(_ax_b.get_yscale()),
                "science_digest": _cap_b.get("digest"),
                "n_qa_records": len(_meas_b["records"]),
                "edge_clearance": [{"text": s.split("«")[1].split("»")[0] if "«" in s else s,
                                    "raw": s} for s in qa_mod.check_edge_clearance(_fig_b)],
                "n_peaks": len([g for g in _reg_b.all() if ".peak." in g]),
            },
            "candidate": {
                "xlim": [float(v) for v in _ax_c.get_xlim()],
                "ylim": [float(v) for v in _ax_c.get_ylim()],
                "xscale": str(_ax_c.get_xscale()), "yscale": str(_ax_c.get_yscale()),
                "science_digest": _cap_c.get("digest"),
                "qa_records": [{"rule": r["rule"], "key": r["key"],
                                "value": r.get("value")} for r in _meas_c["records"]],
                "edge_clearance": [{"text": s.split("«")[1].split("»")[0] if "«" in s else s,
                                    "raw": s} for s in qa_mod.check_edge_clearance(_fig_c)],
                "n_peaks": len([g for g in _reg_c.all() if ".peak." in g]),
                "text_overflow_px": _ov_c,
            },
            "qa_coverage_gap": ("qa.measure/QA gates do not check plain-text "
                                "(tick) canvas clipping; text_overflow_px is the "
                                "runner-owned real-renderer proof, not a product QA change"),
            "xlim_identical": (tuple(map(float, _ax_c.get_xlim()))
                               == tuple(map(float, _ax_b.get_xlim()))),
            "ylim_identical": (tuple(map(float, _ax_c.get_ylim()))
                               == tuple(map(float, _ax_b.get_ylim()))),
            "scales_identical": (str(_ax_c.get_xscale()) == str(_ax_b.get_xscale())
                                 and str(_ax_c.get_yscale()) == str(_ax_b.get_yscale())),
            "curve_arrays_identical": (
                set(_curves_b) == set(_curves_c)
                and all(_curves_b[g] == _curves_c[g] for g in _curves_b)),
            "n_curves": len(_curves_c),
            "peak_texts_identical": _texts_c == _texts_b,
            "n_peak_texts": len(_texts_c),
            "science_digest_identical": _cap_c.get("digest") == _cap_b.get("digest"),
            "science_object_diffs": sorted(
                k for k in set(_o_b) | set(_o_c) if _o_b.get(k) != _o_c.get(k)),
            "candidate_qa_empty": list(_meas_c["records"]) == [],
            "text_inside_figure": _ov_c["over_px"] <= 0.0,
        }
        if not (evidence["independent_audit"]["xlim_identical"]
                and evidence["independent_audit"]["ylim_identical"]
                and evidence["independent_audit"]["scales_identical"]
                and evidence["independent_audit"]["curve_arrays_identical"]
                and evidence["independent_audit"]["peak_texts_identical"]
                and evidence["independent_audit"]["science_digest_identical"]
                and evidence["independent_audit"]["candidate_qa_empty"]
                and evidence["independent_audit"]["text_inside_figure"]):
            (outdir / "nmr_evidence.json").write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps({"status": "AUDIT_MISMATCH",
                              "independent_audit": evidence["independent_audit"]},
                             indent=2, ensure_ascii=False))
            return 7
        (outdir / "candidate.yaml").write_text(
            __import__("yaml").safe_dump(cand_cfg, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        (outdir / "nmr_evidence.json").write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"status": "OK", "verification": tried.get("verification"),
                          "science_unchanged": tried.get("science_unchanged"),
                          "qa": tried.get("qa")}, indent=2, ensure_ascii=False))
    finally:
        worker.close()
    # Strict proof: real `--strict --probe` render of the candidate config.
    # Gate: returncode 0 AND the exact 4 declared artifacts, each nonempty.
    strict_dir = outdir / "strict_probe"
    strict_dir.mkdir()
    cmd = [sys.executable, "-X", "utf8", str(script), "--config", str(outdir / "candidate.yaml"),
           "--strict", "--probe", str(strict_dir)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    (outdir / "strict_stdout.txt").write_text(res.stdout or "", encoding="utf-8")
    (outdir / "strict_stderr.txt").write_text(res.stderr or "", encoding="utf-8")
    (outdir / "strict_returncode.txt").write_text(str(res.returncode), encoding="utf-8")
    expected = {f"Fig2_NMR_pure_stacked.{ext}" for ext in ("pdf", "png", "svg", "tiff")}
    produced = sorted(p.name for p in strict_dir.iterdir() if p.is_file())
    nonempty = sorted(p.name for p in strict_dir.iterdir()
                      if p.is_file() and p.stat().st_size > 0)
    print(json.dumps({"strict_returncode": res.returncode, "artifacts": produced,
                      "nonempty": nonempty}, indent=2, ensure_ascii=False))
    if res.returncode != 0 or set(nonempty) != expected:
        return 3
    # Glyph + PDF audit of the first strict artifact set (real files, not stdout).
    _pdf_sizes: list[float] = []
    try:
        import fitz as _fitz
        _doc = _fitz.open(strict_dir / "Fig2_NMR_pure_stacked.pdf")
        for _page in _doc:
            for _b in _page.get_text("dict")["blocks"]:
                for _l in _b.get("lines", []):
                    for _s in _l.get("spans", []):
                        _pdf_sizes.append(round(float(_s["size"]), 2))
    except Exception as _e:
        (outdir / "pdf_audit_error.txt").write_text(str(_e), encoding="utf-8")
    _pdf_min = min(_pdf_sizes) if _pdf_sizes else None
    _qa_lines = [line for line in (res.stdout or "").splitlines() if "[QA]" in line]
    (outdir / "pdf_audit.json").write_text(
        json.dumps({"pdf_font_sizes_pt": sorted(set(_pdf_sizes)),
                    "pdf_min_pt": _pdf_min,
                    "pdf_min_ge_5pt": _pdf_min is not None and _pdf_min >= 5.0 - 1e-9,
                    "qa_lines": _qa_lines, "artifacts_nonempty": nonempty},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"pdf_min_pt": _pdf_min,
                      "pdf_min_ge_5pt": _pdf_min is not None and _pdf_min >= 5.0 - 1e-9},
                     indent=2))
    if _pdf_min is None or _pdf_min < 5.0 - 1e-9:
        return 8
    if args.save:
        from figpact import agent_api
        inst = outdir / "installed"
        inst.mkdir(parents=True, exist_ok=True)
        sess = agent_api.AgentSession(script, outdir / "candidate.yaml", "main",
                                      output_dir=inst)
        try:
            sess.try_layout([
                {"operation": "set_parameter", "path": ["peak_font_pt"], "value": 7.2},
                {"operation": "set_parameter", "path": ["legend_font_pt"], "value": 7.2},
                {"operation": "set_parameter", "path": ["canvas_w_mm"], "value": 68.0},
            ])
            out = sess.commit("publication",
                              revision=sess._call(lambda: sess._worker.revision),
                              output_dir=inst, confirm=True)
        finally:
            sess.close()
        (outdir / "publication.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps({"publication": out.get("status"),
                          "verification": out.get("verification"),
                          "artifacts": out.get("artifacts")}, indent=2))
        if out.get("status") != "committed" or out.get("verification") != "STRICT_VERIFIED":
            return 4
        # Restart: fresh session on the saved candidate config (the session's
        # own config path; installed dir holds only the strict artifacts).
        inst_cfg = outdir / "candidate.yaml"
        assert inst_cfg.is_file(), "candidate config missing after publication"
        sess2 = agent_api.AgentSession(script, inst_cfg, "main", output_dir=inst)
        try:
            st2 = sess2._call(sess2._worker.state)
            cc2 = dict((st2.get("candidate_config") or st2.get("candidate_patch")) or {})
            reopen = {k: cc2.get(k) for k in ("peak_font_pt", "legend_font_pt",
                                              "canvas_w_mm", "canvas_h_mm",
                                              "note_font_pt")}
            # Second edit as a real commit: note_font_pt 5.5 -> 6.0 (plain '//'
            # text, floor-safe, no label loss), then strict-verify + install.
            cont = sess2.try_layout(
                [{"operation": "set_parameter", "path": ["note_font_pt"], "value": 6.0}])
            cont_rev = sess2._call(lambda: sess2._worker.revision)
            out2 = sess2.commit("publication", revision=cont_rev,
                                output_dir=inst, confirm=True)
        finally:
            sess2.close()
        # Final audit: persisted YAML on the reopened session path must carry the
        # second edit; installed dir must hold the exact 4 second-commit
        # artifacts, each nonempty; second-commit PDF glyph floor re-checked.
        import yaml as _yaml
        _final_cfg = _yaml.safe_load(inst_cfg.read_text(encoding="utf-8"))
        _final_note = _final_cfg.get("note_font_pt")
        _exp2 = {f"Fig2_NMR_pure_stacked.{e}" for e in ("pdf", "png", "svg", "tiff")}
        _nonempty2 = sorted(p.name for p in inst.iterdir()
                            if p.is_file() and p.stat().st_size > 0)
        _sizes2: list[float] = []
        try:
            import fitz as _fitz2
            _d2 = _fitz2.open(inst / "Fig2_NMR_pure_stacked.pdf")
            for _pg in _d2:
                for _b in _pg.get_text("dict")["blocks"]:
                    for _ln in _b.get("lines", []):
                        for _sp in _ln.get("spans", []):
                            _sizes2.append(round(float(_sp["size"]), 2))
        except Exception as _e2:
            (outdir / "pdf_audit2_error.txt").write_text(str(_e2), encoding="utf-8")
        _min2 = min(_sizes2) if _sizes2 else None
        (outdir / "restart_continued.json").write_text(
            json.dumps({"reopened_values": reopen, "continued_edit": {
                "status": cont.get("status"), "verification": cont.get("verification"),
                "message": cont.get("message"),
                "science_unchanged": cont.get("science_unchanged"),
                "qa": cont.get("qa"), "new_qa": cont.get("new_qa")},
                "second_publication": {
                    "status": out2.get("status"), "verification": out2.get("verification"),
                    "artifacts": out2.get("artifacts"), "qa": out2.get("qa")},
                "final_yaml_note_font_pt": _final_note,
                "final_yaml_match": _final_note == 6.0,
                "origin_compare": {"peak_font_pt": [base_cfg.get("peak_font_pt"),
                                                   cc2.get("peak_font_pt")],
                                   "canvas_w_mm": [base_cfg.get("canvas_w_mm"),
                                                   cc2.get("canvas_w_mm")],
                                   "note_font_pt": [base_cfg.get("note_font_pt"),
                                                    _final_note]},
                "installed_nonempty": _nonempty2,
                "installed_pdf_sizes_pt": sorted(set(_sizes2)),
                "installed_pdf_min_pt": _min2,
                "installed_pdf_min_ge_5pt": _min2 is not None and _min2 >= 5.0 - 1e-9},
                indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps({"reopened": reopen, "continued": cont.get("status"),
                          "continued_verification": cont.get("verification"),
                          "continued_science": cont.get("science_unchanged"),
                          "second_publication": out2.get("status"),
                          "second_verification": out2.get("verification"),
                          "final_note": _final_note,
                          "installed_pdf_min_pt": _min2}, indent=2))
        if cont.get("status") != "OK" or not cont.get("science_unchanged"):
            return 5
        if out2.get("status") != "committed" or out2.get("verification") != "STRICT_VERIFIED":
            return 6
        if _final_note != 6.0 or set(_nonempty2) != _exp2:
            return 9
        if _min2 is None or _min2 < 5.0 - 1e-9:
            return 10
        # Overlay Strict PASS on the persisted final config: an actually
        # supported change (axis.title 8.5 -> 9.5), strict load (NOT workspace)
        # must return a Figure with figure_verification_state PASS, then strict
        # render writes the PDF whose glyph floor is re-checked from the file.
        from figpact import style_overlay as _ov
        from figpact.inspector_style import StyleSession as _SS
        _ovdir = outdir / "strict_overlay"
        _ovdir.mkdir(exist_ok=True)
        _ovp = _ovdir / "nmr.overlay.json"
        _s3 = _SS(script=script, config=inst_cfg, scope="main", overlay=_ovp)
        try:
            _fr3 = _s3.snapshot()
            _tid3 = next(t["target_id"] for t in _fr3["style"]["targets"]
                         if t.get("label") == "xlabel")
            _prev3, _code3 = _s3.preview(
                {"frame_revision": _fr3["frame_revision"],
                 "target_id": _tid3, "value": 9.5})
            assert _code3 == 200, f"overlay preview refused: {_prev3}"
            _pend3 = _prev3["style"]["pending"]
            _out3, _cc3 = _s3.commit(
                {"candidate_id": _pend3["candidate_id"],
                 "frame_revision": _pend3["base_frame_revision"],
                 "expected_sha256": _pend3["expected_sha256"]})
            assert _cc3 == 200 and _out3.get("status") == "COMMITTED", _out3
        finally:
            _s3._drop_pending()
        _fig4, _reg4, _rc4 = _ov.load(str(_ovp))
        assert _fig4 is not None, f"strict load refused: {_rc4}"
        _load_pass = (_rc4.get("local_edit_state") == "PASS"
                      and _rc4.get("figure_verification_state") == "PASS"
                      and bool((_rc4.get("figure_qa") or {}).get("pass")))
        import matplotlib.pyplot as _plt4
        _plt4.close(_fig4)
        _rout = _ov.render(str(_ovp), str(_ovdir / "Fig2_NMR_overlay_strict.pdf"))
        assert _rout.get("figure_verification_state") == "PASS", _rout
        _sizes4: list[float] = []
        import fitz as _fitz4
        _d4 = _fitz4.open(_ovdir / "Fig2_NMR_overlay_strict.pdf")
        for _pg4 in _d4:
            for _b4 in _pg4.get_text("dict")["blocks"]:
                for _ln4 in _b4.get("lines", []):
                    for _sp4 in _ln4.get("spans", []):
                        _sizes4.append(round(float(_sp4["size"]), 2))
        _min4 = min(_sizes4) if _sizes4 else None
        (outdir / "strict_overlay_proof.json").write_text(
            json.dumps({"preview_http": _code3, "commit": _out3.get("status"),
                        "strict_load_fig_open": _fig4 is not None,
                        "strict_load_pass": _load_pass,
                        "strict_load_qa": _rc4.get("figure_qa"),
                        "render_verification": _rout.get("figure_verification_state"),
                        "rendered": _rout.get("rendered"),
                        "overlay_pdf_sizes_pt": sorted(set(_sizes4)),
                        "overlay_pdf_min_pt": _min4,
                        "overlay_pdf_min_ge_5pt": (
                            _min4 is not None and _min4 >= 5.0 - 1e-9)},
                       indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps({"overlay_strict_load_pass": _load_pass,
                          "overlay_pdf_min_pt": _min4}, indent=2))
        if not _load_pass or _min4 is None or _min4 < 5.0 - 1e-9:
            return 11
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
