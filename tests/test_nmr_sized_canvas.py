"""Focused regression: NMR contract/baseline consistency at a non-default canvas.

Real RenderSession open on examples/nmr/08 NMR.py with the page's stored
native size 41.0 x 46.13444575910199 mm must succeed with a validated contract
and verified science; the 48x48 default path must keep working. Proves that:
- every gid declared in the contract (parameters/relations/groups node keys)
  has a real artist in the session frame;
- the science manifest states, per template peak, whether its annotation was
  DRAWN or NOT_PLACED (no gid is declared for an unplaced peak).
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import matplotlib
import yaml

matplotlib.use("Agg", force=True)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "nmr" / "08 NMR.py"
BASE_YAML = ROOT / "examples" / "nmr" / "nmr.yaml"

SIZED_W, SIZED_H = 41.0, 46.13444575910199

from figpact.render_api import RenderSession  # noqa: E402


def _copy_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "nmr.yaml"
    shutil.copyfile(BASE_YAML, path)
    return path


def _sized_yaml(tmp_path: Path) -> Path:
    path = _copy_yaml(tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    data["canvas_w_mm"] = SIZED_W
    data["canvas_h_mm"] = SIZED_H
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _open_frame(cfg: Path) -> dict:
    session = RenderSession(SCRIPT, cfg, "main")
    try:
        return session.open()
    finally:
        session.close()


def _declared_gids(contract: dict) -> set[str]:
    out: set[str] = set()
    for param in contract.get("parameters") or []:
        if isinstance(param, dict):
            for gid in param.get("objects") or []:
                if isinstance(gid, str):
                    out.add(gid)
    for rel in contract.get("relations") or []:
        if isinstance(rel, dict):
            for gid in (rel.get("objects") or []) + (rel.get("move") or []):
                if isinstance(gid, str):
                    out.add(gid)
    for group in contract.get("groups") or []:
        if isinstance(group, dict):
            for gid in group.get("members") or []:
                if isinstance(gid, str):
                    out.add(gid)
    for gid in (contract.get("nodes") or {}):
        if isinstance(gid, str):
            out.add(gid)
    return out


def _worker_snapshot(cfg: Path) -> dict:
    session = RenderSession(SCRIPT, cfg, "main")
    try:
        return session._native._agent._call(session._native._agent._worker.state)
    finally:
        session.close()


def test_sized_canvas_open_validates_and_every_declared_gid_has_artist(tmp_path):
    cfg = _sized_yaml(tmp_path)
    opened = _open_frame(cfg)
    frame = opened["frame"]
    assert frame["schema"] == "figpact.inspector/1"
    assert frame["science"]["verified"] is True
    # open itself raises ContractError on dangling objects, so reaching here
    # is the primary assertion; the rest pins down the exact declared sets.
    worker = _worker_snapshot(cfg)
    contract = worker.get("contract") or {}
    assert contract.get("source") == "validated", contract.get("source")
    scene_nodes = {node.get("id") for node in json.loads(frame["scene_json"])["nodes"]}
    declared = _declared_gids(contract)
    assert declared, "contract declares no gids at all"
    assert declared <= scene_nodes, (
        "declared gids without a real artist: "
        f"{sorted(declared - scene_nodes)}"
    )
    manifest = worker.get("science_manifest") or {}
    manifest_nodes = set(manifest.get("nodes") or {})
    assert manifest_nodes <= scene_nodes, (
        f"manifest nodes without a real artist: {sorted(manifest_nodes - scene_nodes)}"
    )


def test_manifest_states_drawn_vs_not_placed_at_both_canvas_sizes(tmp_path):
    def anchors_for(cfg: Path) -> dict:
        worker = _worker_snapshot(cfg)
        manifest = worker.get("science_manifest") or {}
        assert manifest, "session carries no science_manifest"
        anchors = ((manifest.get("science") or {}).get("protected") or {}).get("peak_anchors")
        assert isinstance(anchors, dict) and len(anchors) == 7, anchors
        return anchors

    default_anchors = anchors_for(_copy_yaml(tmp_path))
    sized_anchors = anchors_for(_sized_yaml(tmp_path))

    assert {a.get("placement") for a in default_anchors.values()} == {"DRAWN"}
    assert all(a.get("drawn") is True for a in default_anchors.values())

    expected_missing = {"fig2_nmr.main.peak.vancho.3p68", "fig2_nmr.main.peak.hama.2p02"}
    assert {gid for gid, a in sized_anchors.items()
            if a.get("placement") == "NOT_PLACED"} == expected_missing
    assert {gid for gid, a in sized_anchors.items()
            if a.get("drawn") is False} == expected_missing
    assert {gid for gid, a in sized_anchors.items()
            if a.get("placement") == "DRAWN"} == set(sized_anchors) - expected_missing
    # Scientific identity survives even when unplaced: assignment + measured
    # ppm stay declared; only the gid declaration (artist) is absent.
    for gid in expected_missing:
        record = sized_anchors[gid]
        assert isinstance(record.get("assignment"), str) and record["assignment"]
        assert isinstance(record.get("exact_ppm"), float)
        assert isinstance(record.get("guide_anchor_data"), list)
        assert isinstance(record.get("guide_gid"), str) and record["guide_gid"]


def test_default_canvas_still_opens(tmp_path):
    opened = _open_frame(_copy_yaml(tmp_path))
    assert opened["frame"]["science"]["verified"] is True
