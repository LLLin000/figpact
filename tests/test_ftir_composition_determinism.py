"""P0b：FTIR 构图是 (science, config, scope) 的纯函数——同进程连建不携带上次的中间结果。

本文件把 G6b 的 **D-5 失败样例**固化成永久回归。当年的样例是 `g6b-v2/harness/measure.py`
在同一进程里连建两次（两份**字节相同**的配置），报出：

    fig2_ftir.annotated.band.oh    center_delta_mm = [ 0.0,                +0.3586896259029402]
    fig2_ftir.annotated.band.zn_o  center_delta_mm = [-0.06614583333333002,  +0.3586896259029402]

两个根因都修在 `examples/ftir/plot_ftir.py` 里：

  ① `_apply_config()` 装进 `_CFG` 的现在是配置的**深拷工作副本**。以前是 `_CFG = cfg`
     （直接绑上调用方的字典），`draw_panel()` 又把实测视口与实测净距写回 `_CFG` →
     「构图」顺手改掉了调用方的 config，同进程第二次构图读到的还是上一次的中间结果。
  ② 样式（字体 / `figure.dpi` / 线宽）在**每次构图**时重新 apply。它以前只在模块导入时
     apply 一次，而 native runtime 装载脚本时会把 rcParams 恢复成导入前的值 → 同一进程
     里的第二次构图会掉回 matplotlib 默认样式（100 dpi、DejaVu），整张图的几何随之改变。
     上面那 0.36 mm「位移」全部来自这里（跨进程重建逐位确定）。

验收矩阵（矩阵 → 测试）：

| 矩阵 | 测试 |
|---|---|
| A→A 两次 Scene/GID/关键几何一致 | `test_repeat_composition_is_identical_and_read_only` |
| A→B→A 的最后 A 与独立新进程 A 一致 | `test_a_b_a_matches_a_fresh_process` |
| 跨 scope 连续构图不互相污染 | `test_cross_scope_composition_does_not_cross_pollute` |
| 输入配置构图前后深度比较一致 | `test_input_config_is_not_modified_*`（两条） |
| 旧版出版图科学指纹/布局/QA 不变 | `test_published_science_fingerprint_and_qa_are_unchanged` |
| D-5 复现（同进程双建无伪位移） | `test_same_process_double_build_reports_no_displacement` |
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import pytest
import yaml

import figpact.scene as scene
from figpact.intents import IntentSession
from figpact.science import capture_science
from figpact.session import load_module

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "examples" / "ftir" / "plot_ftir.py"
CONFIG = REPO_ROOT / "examples" / "ftir" / "ftir.yaml"
SCOPES = ("main", "annotated", "compare_raw", "compare_processed")

#: 判定「动了」的阈值（mm）：与 `figpact try` 的对象位移口径一致。
MOVE_MM = 0.05
#: D-5 当年实测到的伪位移（annotated 的归属标签中心，mm），留作回归的对照值。
D5_FALSE_DELTA_MM = (-0.06614583333333002, 0.3586896259029402)
#: 既有出版图的科学指纹（P0b 修复**前**实测）。修复后必须逐位相同——变了就是未经解释的
#: 科学变化。视口声明验证通过时 `capture_science` 只哈希**声明**的冻结视口，所以这几个
#: 值不含字体/布局自由度，只反映受保护的科研载荷。
DIGEST_BY_SCOPE = {
    "main": "45b340b8bb5a6f194e6883529f016e8c3127d360bbbbf2e0f491f33ce1aaf5b8",
    "annotated": "da8829a8eea60880747234faaba173e71503ad915262e9269f66273affd57ef9",
    "compare_raw": "24ae5639fac410c98a979c792f101caf1e7c53c7488ab4b956a6d0674a50228f",
    "compare_processed": "24ae5639fac410c98a979c792f101caf1e7c53c7488ab4b956a6d0674a50228f",
}


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────
def _config(module) -> dict:
    """与 native runtime 同一条装载路径：YAML → `prepare_config`（缺 shifts_mm 补 0）。"""
    return module.prepare_config(yaml.safe_load(CONFIG.read_text(encoding="utf-8")))


def _fingerprint(node: dict) -> dict:
    """一个 gid 对外可观察到的身份与几何（毫米）：类型、包围盒、折线、文字、所属 panel。"""
    return {key: node.get(key) for key in ("type", "bounds_mm", "runs_mm", "text", "parent")}


def _snapshot(module, science: dict, config: dict, scope: str) -> dict:
    fig, registry = module.build_scene(science, config, scope)
    try:
        frame = scene.snapshot(fig, registry, scope=scope)
    finally:
        plt.close(fig)
    return {node["id"]: _fingerprint(node) for node in frame["nodes"]}


def _compose(module, science: dict, config: dict) -> dict:
    """用**同一个配置字典**按 SCOPES 顺序连续构图 → `{scope: {gid: 指纹}}`。"""
    return {scope: _snapshot(module, science, config, scope) for scope in SCOPES}


def _displacements(before: dict, after: dict, tolerance: float = MOVE_MM) -> list:
    """两份快照之间**实测的物理位移**（mm）；口径同 `figpact try` 的对象位移。"""
    moved = []
    for gid, node in after.items():
        box0 = (before.get(gid) or {}).get("bounds_mm")
        box1 = node.get("bounds_mm")
        if not box0 or not box1:
            continue
        delta = [((box1[i] + box1[i + 2]) - (box0[i] + box0[i + 2])) / 2.0 for i in range(2)]
        if (delta[0] ** 2 + delta[1] ** 2) ** 0.5 > tolerance:
            moved.append((gid, delta))
    return sorted(moved)


def _session_snapshot(scope: str, dpi: int = 120) -> dict:
    """`IntentSession` 走一遍（baseline 再当前帧），返回当前帧的 `{gid: 节点}`。

    D-5 发生在**这条路径**上：会话在 `matplotlib.rc_context()` 里装载脚本、恢复
    rcParams，模块导入只 apply 一次样式。两次会话 = 两次构图 = 两次快照。
    """
    with IntentSession(script=SCRIPT, config=CONFIG, scope=scope, dpi=dpi) as session:
        snapshot = session.snapshot()
    frame = json.loads(snapshot["scene_json"]) if "scene_json" in snapshot else snapshot
    return {node["id"]: node for node in frame["nodes"]}


def _child_main(argv) -> None:
    """子进程入口（一进程一 scope）：把一个 scope 的几何指纹写到 stdout。

    由 `_fresh_scope()` 以 `python -c "…; _child_main(sys.argv[1:])"` 调用。独立进程既是
    D-5 的判分口径（「每个配置各起一次进程」），也是「同进程有没有串味」的对照。
    """
    script, config, scope = argv
    module = load_module(Path(script), Path(config))
    loaded = module.prepare_config(yaml.safe_load(Path(config).read_text(encoding="utf-8")))
    fig, registry = module.build_scene(module.load_science(), loaded, scope)
    try:
        frame = scene.snapshot(fig, registry, scope=scope)
    finally:
        plt.close(fig)
    print(json.dumps({node["id"]: _fingerprint(node) for node in frame["nodes"]},
                     ensure_ascii=False, sort_keys=True))


def _fresh_scope(home: Path, scope: str) -> dict:
    """在**独立进程**里建这一个 scope（一进程一配置，互不共享进程状态）。"""
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join([str(REPO_ROOT), str(Path(__file__).parent)]),
           "PYTHONDONTWRITEBYTECODE": "1",
           "MPLCONFIGDIR": str(home / "mpl"),
           "TEMP": str(home), "TMP": str(home), "TMPDIR": str(home)}
    code = ("import sys; import test_ftir_composition_determinism as t; "
            "t._child_main(sys.argv[1:])")
    done = subprocess.run([sys.executable, "-B", "-c", code,
                           str(SCRIPT), str(CONFIG), scope],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=600)
    assert done.returncode == 0, f"独立进程建图失败：{done.stderr[-2000:]}"
    return json.loads(done.stdout.strip().splitlines()[-1])


# ──────────────────────────────────────────────────────────────────────────────
# fixtures
# ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def plot():
    return load_module(SCRIPT, CONFIG)


@pytest.fixture(scope="module")
def science(plot):
    return plot.load_science()


@pytest.fixture(scope="module")
def base_config(plot):
    return _config(plot)


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    """每个 scope 各起一次进程 → `{scope: {gid: 指纹}}`（独立基准）。"""
    home = tmp_path_factory.mktemp("fresh-process")
    return {scope: _fresh_scope(home, scope) for scope in SCOPES}


# ──────────────────────────────────────────────────────────────────────────────
# 矩阵：输入配置 / A→A / 跨 scope
# ──────────────────────────────────────────────────────────────────────────────
def test_repeat_composition_is_identical_and_read_only(plot, science, base_config):
    """A→A：四个 scope 连续构图两轮 → gid 集合与几何逐位一致，输入配置逐位不变。"""
    before = copy.deepcopy(base_config)
    first = _compose(plot, science, base_config)
    assert base_config == before, "构图改写了输入配置（P0b 根因①）"
    second = _compose(plot, science, base_config)
    assert base_config == before, "第二次构图改写了输入配置（P0b 根因①）"
    for scope in SCOPES:
        assert set(first[scope]) == set(second[scope]), f"{scope}: gid 集合变了"
        assert first[scope] == second[scope], f"{scope}: 两次构图几何不一致"
        assert _displacements(first[scope], second[scope]) == [], f"{scope}: 出现伪位移"


def test_input_config_is_not_modified_when_the_viewport_is_measured(plot, science,
                                                                   base_config):
    """配置没写冻结视口时也一样：实测视口与实测净距是**派生量**，不许写回输入。

    这一条是 P0b 根因①的直接回归：`layout_reference.*.units_per_mm is None` 时
    `draw_panel()` 会走实测分支——旧代码把实测值原地写回 `_CFG`（= 调用方的字典）。
    """
    config = copy.deepcopy(base_config)
    for scope in SCOPES:
        config["layout_reference"][scope].update(axis_bottom_data=None, units_per_mm=None)
    before = copy.deepcopy(config)
    first = _compose(plot, science, config)
    assert config == before, "实测视口/净距被写回了输入配置（P0b 根因①）"
    second = _compose(plot, science, config)
    assert config == before, "第二次构图把实测值写回了输入配置（P0b 根因①）"
    for scope in SCOPES:
        assert first[scope] == second[scope], f"{scope}: 没有冻结视口时两次构图不一致"


def test_cross_scope_composition_does_not_cross_pollute(plot, science, base_config, fresh):
    """四个 scope 连续构图（共享一个输入字典）：每个 scope 都等于它独占一个进程的结果，
    且只带自己的作用域前缀（对照图天生带 raw/processed 两个 panel）。"""
    before = copy.deepcopy(base_config)
    composed = _compose(plot, science, base_config)
    assert base_config == before
    for scope in SCOPES:
        assert composed[scope] == fresh[scope], f"{scope} 被别的 scope 污染了"
        expected = ({"compare_raw", "compare_processed"} if scope.startswith("compare")
                    else {scope})
        prefix = f"{plot.FIGURE_ID}."
        owners = {gid.split(".")[1] for gid in composed[scope] if gid.startswith(prefix)}
        assert owners == expected, f"{scope}: 图里混进了别的作用域的 gid {sorted(owners)}"


def test_a_b_a_matches_a_fresh_process(plot, science, base_config, fresh):
    """A→B→A：最后一个 A（以及同进程的第一个 A）都与**独立新进程**建的 A 逐位一致。"""
    other = copy.deepcopy(base_config)
    other["curve_gap_mm"] = base_config["curve_gap_mm"] + 1.5
    other["group_y_mm"]["annotated"] = 0.6

    first_a = _compose(plot, science, base_config)
    _compose(plot, science, other)
    last_a = _compose(plot, science, base_config)
    for scope in SCOPES:
        assert first_a[scope] == fresh[scope], f"{scope}: 同进程第一次 A 与新进程 A 不一致"
        assert last_a[scope] == fresh[scope], f"{scope}: A→B→A 后的 A 与新进程 A 不一致"


# ──────────────────────────────────────────────────────────────────────────────
# 矩阵：D-5 复现（同进程双建不得产生伪位移）
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("scope", SCOPES)
def test_same_process_double_build_reports_no_displacement(scope):
    """同一进程里连建两次同一份配置：**零位移**。

    当年 `harness/measure.py` 正是这条路径（baseline 与 candidate 在同一进程内），
    FTIR annotated 报出 18 个非零项；这里把「两次快照之间的实测物理位移」重新算一遍。
    """
    first = _session_snapshot(scope)
    second = _session_snapshot(scope)
    assert set(first) == set(second), "两次快照的 gid 集合不同"
    moved = _displacements(first, second)
    assert moved == [], (
        f"{scope}: 同进程双建出现伪位移（D-5 复现）；当年 annotated 报的是 "
        f"{D5_FALSE_DELTA_MM} mm。实测：{moved[:4]}")


# ──────────────────────────────────────────────────────────────────────────────
# 矩阵：旧版出版图（科学指纹 / 既有布局 / QA）不因修复变化
# ──────────────────────────────────────────────────────────────────────────────
def test_published_science_fingerprint_and_qa_are_unchanged(plot, science, base_config):
    """既有出版图：科学指纹逐位相同、声明的冻结视口仍然成立、QA 判据不变。

    指纹常量取自**修复前**的实测（见模块 docstring）；`viewports` 全为 True 才说明真实
    窗口仍是 `ftir.yaml` 里那份只读几何记录——真被重新测过，指纹也会跟着变。
    """
    declarations = plot.science_manifest(science)
    for scope in SCOPES:
        fig, registry = plot.build_scene(science, copy.deepcopy(base_config), scope)
        try:
            scene.snapshot(fig, registry, scope=scope)
            scientific = capture_science(fig, registry, declarations=declarations)
            problems = plot.preview_qa(fig, scope)
        finally:
            plt.close(fig)
        viewports = {key: value.get("viewport", {}).get("verified")
                     for key, value in scientific["objects"].items() if key.endswith(":view")}
        assert viewports and all(viewports.values()), \
            f"{scope}: 真实窗口不再是声明的冻结视口：{viewports}"
        assert scientific["digest"] == DIGEST_BY_SCOPE[scope], \
            f"{scope}: 受保护的科学载荷变了（应有逐项解释）"
        assert problems == [], f"{scope}: 出现阻断项 {problems}"


# ──────────────────────────────────────────────────────────────────────────────
# 派生量的唯一消费者：`--migrate-config`
# ──────────────────────────────────────────────────────────────────────────────
#: schema 1（迁移入口）认的键：v2 才有的 `clearance_mm` / `group_y_mm` / `layout_reference`
#: 一律不出现，布局记录由迁移当场实测产出。
_LEGACY_KEYS = ("canvas_w_mm", "canvas_h_mm", "label_font_pt", "legend_font_pt",
                "label_edge_margin_mm", "label_gap_top_mm", "curve_gap_mm", "axis_font_pt",
                "tick_font_pt", "note_font_pt", "line_width", "legend_cols",
                "legend_anchor_x", "shifts_mm")


def test_migration_still_freezes_the_measured_viewport(tmp_path):
    """`--migrate-config` 仍然把**实测**视口与实测净距固化进产出的 YAML。

    构图本身不再写配置（P0b 根因①：派生量只进 `_DERIVED`），所以迁移必须显式取走它
    （`_adopt_measured_layout`）。这条守着那个入口：产出里的 `axis_bottom_data` /
    `units_per_mm` 不许变成 None，且要与既有 `ftir.yaml` 的记录一致。
    """
    current = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    legacy = {key: current[key] for key in _LEGACY_KEYS}
    legacy.update(schema_version=1, stack_gap=45.0, stack_gap_annotated=55.0,
                  stack_lift_annotated_mm=0.5)
    legacy_path = tmp_path / "legacy_v1.yaml"
    legacy_path.write_text(yaml.safe_dump(legacy, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")
    output = tmp_path / "migrated.yaml"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "MPLCONFIGDIR": str(tmp_path / "mpl"),
           "TEMP": str(tmp_path), "TMP": str(tmp_path), "TMPDIR": str(tmp_path)}
    done = subprocess.run([sys.executable, "-B", str(SCRIPT), "--config", str(legacy_path),
                           "--migrate-config", str(output)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=600)
    assert done.returncode == 0, f"迁移失败：{done.stderr[-2000:]}"

    migrated = yaml.safe_load(output.read_text(encoding="utf-8"))
    for scope in SCOPES:
        reference = migrated["layout_reference"][scope]
        assert reference["axis_bottom_data"] is not None, f"{scope}: 迁移丢了实测视口原点"
        assert reference["units_per_mm"] > 0, f"{scope}: 迁移丢了显示标尺"
        assert reference == current["layout_reference"][scope], \
            f"{scope}: 迁移产出的只读几何记录与既有 ftir.yaml 不一致"
        assert migrated["clearance_mm"][scope] == current["clearance_mm"][scope], \
            f"{scope}: 迁移产出的相邻净距与既有 ftir.yaml 不一致"
