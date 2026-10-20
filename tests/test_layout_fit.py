"""Layout-aware fitting: minimal authorized edits, real-preview contract."""
from __future__ import annotations

import json
from figpact.layout_fit import fit, read_target


class FakeSession:
    def __init__(self, controls, accept_min):
        self.controls = controls
        self.accept_min = accept_min
        self.previews = []
        self.revision = 7

    def snapshot(self):
        return {"frame_revision": f"rev{self.revision}",
                "native": {"controls": self.controls, "pending": None}}

    def preview(self, body):
        self.revision += 1
        self.previews.append(body)
        values = {edit["control_id"]: edit["value"] for edit in body["edits"]}
        current = {c["control_id"]: c["current"] for c in self.controls}
        current.update(values)
        fonts = [c["control_id"] for c in self.controls if "font" in c["label"]]
        minimum = min(current[cid] for cid in fonts) if fonts else 0
        ok = minimum + 1e-9 >= self.accept_min
        trial = {"status": "OK" if ok else "REJECTED",
                 "verification": "RENDER_CHECKED",
                 "new_qa": [] if ok else [{"id": "overlap"}],
                 "message": "ok" if ok else "overlap"}
        return {"status": "OK" if ok else "REJECTED", "receipt": trial}, 200 if ok else 400


def _controls(label=4.7, legend=4.7, axis=8.5):
    return [
        {"control_id": json.dumps(["label_font_pt"]), "label": "label_font_pt",
         "current": label, "min": 3.0, "max": 12.0},
        {"control_id": json.dumps(["legend_font_pt"]), "label": "legend_font_pt",
         "current": legend, "min": 3.0, "max": 12.0},
        {"control_id": json.dumps(["axis_font_pt"]), "label": "axis_font_pt",
         "current": axis, "min": 3.0, "max": 12.0},
        {"control_id": json.dumps(["legend_cols"]), "label": "legend_cols",
         "current": 2, "min": 1, "max": 3},
        {"control_id": json.dumps(["legend_anchor_x"]), "label": "legend_anchor_x",
         "current": 0.98, "min": 0.0, "max": 1.0},
    ]


def test_fit_raises_only_fonts_below_floor_and_does_not_save():
    session = FakeSession(_controls(), accept_min=5.0)
    result = fit(session, target_w_mm=48.0, min_font_pt=5.0)
    assert result["status"] == "FEASIBLE"
    assert result["selected"]["min_font_pt"] == 5.0
    assert {e["control_id"] for e in result["selected"]["edits"]} == {
        json.dumps(["label_font_pt"]), json.dumps(["legend_font_pt"])}
    assert "未保存" in result["note"]


def test_fit_escalates_to_next_smaller_feasible_bump():
    session = FakeSession(_controls(), accept_min=5.5)
    result = fit(session, target_w_mm=48.0, min_font_pt=5.0)
    assert result["status"] == "FEASIBLE"
    assert result["selected"]["min_font_pt"] == 5.5


def test_infeasible_reports_estimate_without_claiming_a_fix():
    session = FakeSession(_controls(), accept_min=9.5)
    result = fit(session, target_w_mm=48.0, min_font_pt=8.0)
    assert result["status"] == "INFEASIBLE"
    assert result["estimate_width_for_floor_mm"] > 48.0
    assert "1:1" in result["estimate_note"]


def test_already_above_floor_produces_no_changes():
    session = FakeSession(_controls(label=6.0, legend=6.0, axis=8.5), accept_min=5.0)
    result = fit(session, target_w_mm=48.0, min_font_pt=5.0)
    assert result["status"] == "ALREADY_OK"
    assert result["candidates"] == []
    assert session.previews == []


def test_read_target_requires_one_unique_panel(tmp_path):
    layout = tmp_path / "layout.json"
    layout.write_text(json.dumps({"schema": 3, "canvases": [{
        "id": "c1", "name": "Figure 2", "objects": [
            {"id": "p1", "type": "panel", "fileId": "09 FTIR\\Fig.pdf", "w": 48.0, "h": 47.5},
            {"id": "p2", "type": "panel", "fileId": "08 NMR\\Fig.pdf", "w": 48.0, "h": 48.0},
        ]}]}), encoding="utf-8")
    width, height, panel = read_target(layout, panel="08 NMR/Fig.pdf", canvas="Figure 2")
    assert (width, height) == (48.0, 48.0)
    assert panel is not None and panel["id"] == "p2"
