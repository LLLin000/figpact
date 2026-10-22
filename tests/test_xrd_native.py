"""XRD Native 提供者：科学与来源回归（需真实外部 .txt 数据时才跑）。

外部夹具：与 plot_xrd.py 同目录的临时 config 把 `data_dir` 指向真实
Rigaku .txt 目录（含 1.txt..5.txt）。夹具缺席（目录/文件不存在）时整模块
skip——绝不伪造数据冒充通过。按指令 mid-flight 不执行，本文件只声明不断言。
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import pytest
import yaml
REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "xrd" / "plot_xrd.py"
CONFIG = REPO / "examples" / "xrd" / "xrd.yaml"

REAL_DATA_CANDIDATES = [
    Path(r"D:\L\OB\Literature-hub\Project\20260804之江有机硅\实验数据\拼图"
         r"\fig2\10 XRD\2084_1788433571941_26083186806\26083186806"),
    Path.home() / "figpact-xrd-fixture",
]

EXPECTED_HKL = ["(100)", "(101)", "(102)", "(110)", "(103)"]
EXPECTED_POS = [31.77, 36.25, 47.54, 56.60, 62.86]
EXPECTED_TAGS = ["100", "101", "102", "110", "103"]
#: 源行为（41.0 x 46.13444575910199 mm 原始画布实测）：求解器只放得下
#: (100)/(102)/(103)，(101)/(110) 静默不画。提供者必须逐字复现这一分裂，
#: 不得假装五个都画上了。
EXPECTED_DRAWN_TAGS = ["100", "102", "103"]
EXPECTED_NOT_DRAWN_TAGS = ["101", "110"]
EXPECTED_DRAWN_HKL = ["(100)", "(102)", "(103)"]
EXPECTED_DRAWN_GIDS = [f"fig2_xrd.main.hkl.{t}" for t in EXPECTED_DRAWN_TAGS]


def _real_data_dir() -> Path | None:
    for candidate in REAL_DATA_CANDIDATES:
        if candidate.is_dir() and all((candidate / f"{n}.txt").is_file()
                                      for n in range(1, 6)):
            return candidate
    return None


def _load_module():
    from figpact.session import load_module
    return load_module(SCRIPT, CONFIG)


requires_real_data = pytest.mark.skipif(
    _real_data_dir() is None, reason="真实 Rigaku .txt 外部夹具缺席：不伪造数据")


@requires_real_data
def test_science_matches_source_processing_and_drawn_split(tmp_path):
    """科学与来源：真实管线 + 处理常数/窗口锁定 + 源行为的 hkl 绘制分裂。

    源在原始画布上只画出 (100)/(102)/(103)，(101)/(110) 静默不画；
    提供者必须复现同一分裂（绘制文字、gid、manifest 缺一不可），
    同时五个晶面的科学锚点一个不少。
    """
    from figpact.science import capture_science
    plot = _load_module()
    data_dir = _real_data_dir()
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["data_dir"] = str(data_dir)
    cfg = plot.prepare_config(raw)
    plot._apply_config(cfg)
    science = plot.load_science()
    try:
        # 常数锁定：与源逐字一致。
        assert plot.DISPLAY_X_MIN == 10.0 and plot.DISPLAY_X_MAX == 80.0
        assert plot.BASELINE_LAMBDA == 2.0e7 and plot.BASELINE_ASYMMETRY == 0.01
        assert plot.BASELINE_ITERATIONS == 15
        assert plot.SMOOTHING_WINDOW == 7 and plot.SMOOTHING_POLYORDER == 2
        assert plot.WAVELENGTH_A == 1.540593
        assert plot.OFFSET_STEP == 2.40
        assert plot.ZNO_HKL == EXPECTED_POS and plot.ZNO_HKL_LABELS == EXPECTED_HKL
        # 输入依赖：五个外部 .txt 全部声明且在场；science_inputs 即引擎指纹的 extra。
        inputs = plot.science_inputs()
        assert len(inputs) == 5 and all(Path(p).is_file() for p in inputs)
        assert inputs == sorted({s["resolved"] for s in science["scans"]})
        # 渲染：五曲线 + x 窗口；hkl 按源行为只画出 (100)/(102)/(103)。
        fig, reg = plot.build_scene(science, cfg, "main")
        try:
            gids = set(reg.all())
            for gid in EXPECTED_DRAWN_GIDS:
                assert gid in gids, f"缺 hkl 身份 {gid}"
            for tag in EXPECTED_NOT_DRAWN_TAGS:
                assert f"fig2_xrd.main.hkl.{tag}" not in gids, \
                    f"源不画的 hkl 不应出现 {tag}"
            for n in range(1, 6):
                assert f"fig2_xrd.main.curve.{n}" in gids
            ax = fig.axes[0]
            assert list(ax.get_xlim()) == [10.0, 80.0]
            texts = {t.get_text() for t in ax.texts}
            for hkl in EXPECTED_DRAWN_HKL:
                assert hkl in texts, f"缺标注文字 {hkl}"
            for hkl in set(EXPECTED_HKL) - set(EXPECTED_DRAWN_HKL):
                assert hkl not in texts, f"源不画的标注不应出现 {hkl}"
            # 绘制位置：与源锚点（窗内极大实测 2θ）逐字一致。
            drawn_pos = {t.get_text(): t.get_position()[0] for t in ax.texts}
            for anchor_x, hkl, tag, _anchor_y in plot._detect_hkl_anchors(
                    science["display"],
                    [i * plot.OFFSET_STEP for i in range(len(science["display"]))]):
                if tag in EXPECTED_DRAWN_TAGS:
                    assert abs(drawn_pos[hkl] - anchor_x) < 1e-9, f"{hkl} 锚点漂移"
            # 来源声明：文件/窗口/锚点齐全，锚点 2θ 与源峰位偏差 ≤0.7° 窗。
            manifest = plot.science_manifest(science)
            protected = manifest["science"]["protected"]
            assert protected["hkl_labels"] == EXPECTED_HKL
            assert protected["hkl_positions_deg"] == EXPECTED_POS
            assert protected["hkl_labels_drawn"] == EXPECTED_DRAWN_TAGS
            assert protected["hkl_labels_not_drawn"] == EXPECTED_NOT_DRAWN_TAGS
            for tag, nominal in zip(EXPECTED_TAGS, EXPECTED_POS):
                anchor = protected["hkl_anchors"][tag]
                assert abs(anchor["two_theta_deg"] - nominal) <= 0.7
            assert manifest["science"]["source"]["files"] == [f"{n}.txt" for n in range(1, 6)]
            assert manifest["input_files"] == manifest["science"]["source"]["input_files"]
            assert [e["file"] for e in manifest["input_files"]] == [
                f"{n}.txt" for n in range(1, 6)]
            assert [e["path"] for e in manifest["input_files"]] == inputs
            assert all(len(e["sha256"]) == 64 for e in manifest["input_files"])
            # 科学指纹可捕获：画出的三个 hkl 文字在指纹里；
            # 没画出的两个只活在 manifest 锚点/分裂声明里（源同样不画它们）。
            fp = capture_science(fig, reg, declarations=manifest)
            assert fp.get("digest")
            blob = str(fp["objects"])
            for hkl in EXPECTED_DRAWN_HKL:
                assert hkl in blob
            for hkl in set(EXPECTED_HKL) - set(EXPECTED_DRAWN_HKL):
                assert hkl not in blob
        finally:
            plt.close(fig)
    finally:
        plot._SCIENCE = None
        plot._SCIENCE_KEY = None


@requires_real_data
def test_controls_only_safe_typography_and_offsets(tmp_path):
    """控制面：只有安全排版旋钮可 EDITABLE；科学量无一可改。"""
    plot = _load_module()
    data_dir = _real_data_dir()
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["data_dir"] = str(data_dir)
    cfg = plot.prepare_config(raw)
    plot._apply_config(cfg)
    science = plot.load_science()
    try:
        contract = plot.layout_contract("main")
        editable_paths = {tuple(p["path"]) for p in contract["parameters"]
                          if p["mutability"] == "EDITABLE"}
        flat = {"".join(map(str, p)) for p in editable_paths}
        for forbidden in ("DISPLAY", "BASELINE", "SMOOTH", "ZNO_HKL", "OFFSET_STEP",
                           "data_dir", "layout_reference", "schema_version"):
            assert not any(forbidden in f for f in flat), f"科学量可编辑：{forbidden}"
        assert ("canvas_w_mm",) in editable_paths
        assert ("axis_font_pt",) in editable_paths
        assert ("tick_font_pt",) in editable_paths
        # 位移是纯显示：扰动 offsets_mm 不改科学指纹。
        from figpact.science import capture_science
        fig0, reg0 = plot.build_scene(science, cfg, "main")
        try:
            base = capture_science(fig0, reg0,
                                   declarations=plot.science_manifest(science))["digest"]
        finally:
            plt.close(fig0)
        cfg2 = {**cfg, "offsets_mm": {**cfg["offsets_mm"],
                                      "main": {**cfg["offsets_mm"]["main"], "2": 1.0}}}
        fig1, reg1 = plot.build_scene(science, cfg2, "main")
        try:
            moved = capture_science(fig1, reg1,
                                    declarations=plot.science_manifest(science))["digest"]
        finally:
            plt.close(fig1)
        assert moved == base
    finally:
        plot._SCIENCE = None
        plot._SCIENCE_KEY = None


def test_portable_default_fails_clearly_without_data_dir():
    """便携默认（data_dir 为空）load_science 必须明确报错，不猜路径。"""
    plot = _load_module()
    plot._apply_config(plot.prepare_config(
        yaml.safe_load(CONFIG.read_text(encoding="utf-8"))))
    try:
        with pytest.raises(Exception, match="data_dir"):
            plot.load_science()
    finally:
        plot._SCIENCE = None
        plot._SCIENCE_KEY = None


def test_hkl_constants_never_drift():
    """模块级常量回归：五峰位置/标签/tag 无需数据即可断言，防删峰改位。"""
    plot = _load_module()
    assert plot.ZNO_HKL == EXPECTED_POS
    assert plot.ZNO_HKL_LABELS == EXPECTED_HKL
    assert plot.HKL_TAGS == EXPECTED_TAGS
    assert [plot._hkl_gid(t) for t in EXPECTED_TAGS] == \
        [f"fig2_xrd.main.hkl.{t}" for t in EXPECTED_TAGS]
