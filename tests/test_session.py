"""FigureSession / FigureWorker 行为回归。

夹具是**真原生脚本**（load_science / build_scene / layout_contract / science_manifest），
写在临时目录里，带真实的 mm 级别的 display 位移、包络、导引线与一条声明里的坏绑定。
全部断言都打在可观测的事实上：真实 YAML 重建、实测 mm、revision、导入次数、协议帧。

关键判据：声明与实测**不符**（错标尺 / 没接线 / 牵连未声明对象）必须明确拒绝
（EFFECT_MISMATCH / NO_EFFECT），不许退回渲染验证后拿 QA 当成功；只有「同渲染器解析
容差证明不了」的非刚体改动才合法走 RENDER_CHECKED，且那条路上仍要观测声明的落实。
"""
from __future__ import annotations

import base64
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import matplotlib
matplotlib.use('Agg', force=True)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from figpact.session import (  # noqa: E402
    ContractError, EDITABLE, FIXED_STYLE, FigureSession, SessionError, StaleRevision, STATUS_AMBIGUOUS,
    STATUS_CONTRADICTORY, STATUS_EFFECT_MISMATCH, STATUS_GEOMETRY_REJECTED,
    STATUS_INVALID_VALUE, STATUS_LOCKED, STATUS_NO_EFFECT, STATUS_NOT_IN_SCOPE, STATUS_OK,
    STATUS_OUT_OF_RANGE, STATUS_STALE, STATUS_UNKNOWN_RELATION,
    STATUS_UNSUPPORTED_PATH, STATUS_UNSUPPORTED_PROOF, STATUS_UNSUPPORTED_RELATION,
    TOL_SAME_RENDERER_MM,
    VERIFICATION_GEOMETRY, VERIFICATION_RENDER, drawn_shapes, loader_counters,
    module_revision, source_revision,
)
from figpact.runtime import FigureWorker, FigureWorkerError, WorkerTimeout  # noqa: E402

NATIVE_SCRIPT = '''\
"""原生探针夹具：真 load_science/build_scene/layout_contract/science_manifest 接缝。

几何按 mm 设计：曲线的显示位移沿 y、导引线在曲线之上、标签在中间靠上、
徽标在左下；因此「平移」「包含性越界」「与曲线相交」都是可算的确定性事实。
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from figpact import GidRegistry, apply_display_shift
from figpact.config import load_config as _engine_load_config

FIGURE_ID = "probe"
SCOPES = ("main", "other")
CONFIG_PATH = Path(__file__).with_name("probe.yaml")

CANVAS = {"canvas_w_mm": (float, 40.0, 120.0), "canvas_h_mm": (float, 30.0, 120.0)}
SHIFT = (float, -6.0, 6.0)
SCHEMA = {
    "schema_version": (int, 1, 1),
    **CANVAS,
    "curve_shift_mm": SHIFT,
    "guide_shift_mm": SHIFT,
    "label_x_mm": SHIFT,
    "label_font_pt": (float, 5.0, 12.0),
    "font_knob": (float, 5.0, 12.0),
    "ghost_shift_mm": SHIFT,
    "unused_knob": (float, 0.0, 10.0),
    "locked_knob": (float, 0.0, 10.0),
}


def load_config(path=CONFIG_PATH):
    return _engine_load_config(path, SCHEMA)


def load_science():
    x = np.linspace(0.0, 10.0, 121)
    y = np.sin(x)
    return {"x": x, "y": y, "peak_x": float(x[int(np.argmax(y))]), "loaded": True}


def science_manifest(science):
    return {"arrays": 2, "peak_x": science["peak_x"], "scale_bar_mm": None}


def build_scene(science, config, scope):
    if scope not in SCOPES:
        raise ValueError("未知 scope: " + scope)
    print("[probe] build " + scope)   # 故意打印：协议纯净性素材
    fig, ax = plt.subplots(figsize=(config["canvas_w_mm"] / 25.4,
                                    config["canvas_h_mm"] / 25.4))
    fig.subplots_adjust(left=0.22, right=0.95, top=0.9, bottom=0.2)
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(-1.2, 1.3)
    reg = GidRegistry()
    prefix = FIGURE_ID + "." + scope

    curve, = ax.plot(science["x"], science["y"], lw=0.8)
    reg.register(curve, prefix + ".curve", params=["curve_shift_mm"])
    apply_display_shift(curve, dy_mm=config["curve_shift_mm"])

    guide, = ax.plot([0.0, 10.0], [1.25, 1.25], lw=0.6, ls="--")
    reg.register(guide, prefix + ".guide", params=["guide_shift_mm"])
    apply_display_shift(guide, dy_mm=config["guide_shift_mm"])

    label = ax.text(5.0, 0.6, "peak", fontsize=config["label_font_pt"])
    reg.register(label, prefix + ".label", params=["label_font_pt", "label_x_mm"])
    apply_display_shift(label, dx_mm=config["label_x_mm"])

    badge = ax.text(1.0, -0.9, "badge", fontsize=config["font_knob"])
    reg.register(badge, prefix + ".badge", params=["font_knob"])

    ax.set_xlabel("t (s)", fontsize=8.0)
    reg.register(ax.xaxis.label, prefix + ".xlabel", params=[])
    ax.set_ylabel("signal (a.u.)", fontsize=8.0)
    reg.register(ax.yaxis.label, prefix + ".ylabel", params=[])
    return fig, reg


def layout_contract(scope):
    if scope not in SCOPES:
        raise ValueError("未知 scope: " + scope)
    prefix = FIGURE_ID + "." + scope
    curve, guide, label, badge = (prefix + ".curve", prefix + ".guide",
                                  prefix + ".label", prefix + ".badge")
    return {
        "parameters": [
            {"key": "curve_shift", "path": ["curve_shift_mm"], "unit": "mm",
             "mutability": "EDITABLE", "operation": "translate", "axis": "y", "scale": 1.0,
             "min": -6.0, "max": 6.0, "scopes": list(SCOPES), "objects": [curve],
             "expected": {"kind": "translate", "objects": [curve], "axis": "y"}},
            {"key": "guide_shift", "path": ["guide_shift_mm"], "unit": "mm",
             "mutability": "EDITABLE", "operation": "translate", "axis": "y", "scale": 1.0,
             "min": -6.0, "max": 6.0, "scopes": list(SCOPES), "objects": [guide],
             "expected": {"kind": "translate", "objects": [guide], "axis": "y"}},
            {"key": "label_x", "path": ["label_x_mm"], "unit": "mm",
             "mutability": "EDITABLE", "operation": "translate", "axis": "x", "scale": 1.0,
             "min": -6.0, "max": 6.0, "scopes": list(SCOPES), "objects": [label],
             "expected": {"kind": "translate", "objects": [label], "axis": "x"}},
            {"key": "label_font", "path": ["label_font_pt"], "unit": "pt",
             "mutability": "EDITABLE", "operation": "rebuild",
             "min": 5.0, "max": 12.0, "scopes": list(SCOPES), "objects": [label],
             "expected": {"kind": "style", "objects": [label]}},
            {"key": "font_knob_wrong_binding", "path": ["font_knob"], "unit": "pt",
             "mutability": "EDITABLE", "operation": "rebuild",
             "min": 5.0, "max": 12.0, "scopes": list(SCOPES), "objects": [curve],
             "expected": {"kind": "style", "objects": [curve]}},
            {"key": "ghost_shift", "path": ["ghost_shift_mm"], "unit": "mm",
             "mutability": "EDITABLE", "operation": "translate", "axis": "y", "scale": 1.0,
             "min": -6.0, "max": 6.0, "scopes": list(SCOPES), "objects": [curve],
             "expected": {"kind": "translate", "objects": [curve], "axis": "y"}},
            {"key": "unused_style", "path": ["unused_knob"], "unit": "pt",
             "mutability": "EDITABLE", "operation": "rebuild",
             "min": 0.0, "max": 10.0, "scopes": list(SCOPES), "objects": [label],
             "expected": {"kind": "style", "objects": [label]}},
            {"key": "locked", "path": ["locked_knob"], "unit": "a.u.",
             "mutability": "LOCKED_SCIENCE", "operation": "rebuild",
             "min": 0.0, "max": 10.0, "scopes": list(SCOPES), "objects": [curve]},
            {"key": "other_scope_only", "path": ["canvas_w_mm"], "unit": "mm",
             "mutability": "LOCKED_SCIENCE", "operation": "resize",
             "min": 40.0, "max": 120.0, "scopes": ["other"], "objects": [curve]},
        ],
        "nodes": {curve: {"type": "Line2D", "parent": prefix, "editable": True,
                          "science_policy": "LAYOUT"},
                  guide: {"type": "Line2D", "parent": prefix, "editable": True,
                          "science_policy": "LAYOUT"}},
        "groups": [{"id": prefix, "parent": FIGURE_ID, "members": [curve, guide, label, badge]}],
        "relations": [
            {"id": "guide_above_curve", "kind": "gap", "objects": [curve, guide], "axis": "y",
             "controlled_by": [["guide_shift_mm"]], "move": [guide]},
            {"id": "no_mapping", "kind": "gap", "objects": [curve, guide], "axis": "y"},
            {"id": "two_mappings", "kind": "gap", "objects": [curve, guide], "axis": "y",
             "controlled_by": [["guide_shift_mm"], ["curve_shift_mm"]], "move": [guide]},
            {"id": "moves_both_ends", "kind": "gap", "objects": [curve, guide], "axis": "y",
             "controlled_by": [["curve_shift_mm"]], "move": [curve, guide]},
        ],
        "outputs": ["probe.png"],
    }
'''

NATIVE_YAML = """\
schema_version: 1
canvas_w_mm: 60.0
canvas_h_mm: 45.0
curve_shift_mm: 0.0
guide_shift_mm: 0.0
label_x_mm: 0.0
label_font_pt: 6.0
font_knob: 6.0
ghost_shift_mm: 0.0
unused_knob: 5.0
locked_knob: 5.0
"""


def write_native_probe(root: Path):
    """把原生探针脚本 + 配置写进目录；返回 (script, config)。"""
    script = root / 'probe_plot.py'
    config = root / 'probe.yaml'
    script.write_text(NATIVE_SCRIPT, encoding='utf8')
    config.write_text(NATIVE_YAML, encoding='utf8')
    return script, config


def loaders() -> dict:
    """进程内**真实**的装载计数与缓存规模（模块/科学对象），不用夹具日志当证据。"""
    return loader_counters()


PANEL_SCRIPT = '''\
"""原生面板夹具：两块真坐标轴面板，一块整体平移，另一块是**无关兄弟**。

面板 A 里的像素图与文字由作者用 nodes.parent 声明归属（控制对象 → 后代闭包），
`gap_x_mm` 是面板 A 的整体刚体平移（作用集合 = A 及其后代，单位 mm）；
`stray_x_mm` 声称移动的是面板 A，绑定却移动面板 B —— 这是错绑定，必须报出来。
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from figpact import GidRegistry
from figpact.config import load_config as _engine_load_config

FIGURE_ID = "panels"
SCOPES = ("main",)
CONFIG_PATH = Path(__file__).with_name("panels.yaml")
MM_PER_INCH = 25.4
SCHEMA = {"canvas_w_mm": (float, 30.0, 120.0), "canvas_h_mm": (float, 30.0, 90.0),
          "gap_x_mm": (float, -5.0, 5.0), "stray_x_mm": (float, -5.0, 5.0)}


def load_config(path=CONFIG_PATH):
    return _engine_load_config(path, SCHEMA)


def load_science():
    return {"image": np.arange(16, dtype=float).reshape(4, 4), "loaded": True}


def science_manifest(science):
    return {"arrays": 1, "shape": list(science["image"].shape)}


def _rect_mm(x_mm, y_mm, w_mm, h_mm, config):
    return [x_mm / config["canvas_w_mm"], y_mm / config["canvas_h_mm"],
            w_mm / config["canvas_w_mm"], h_mm / config["canvas_h_mm"]]


def build_scene(science, config, scope):
    if scope not in SCOPES:
        raise ValueError("未知 scope: " + scope)
    print("[panels] build " + scope)
    fig = plt.figure(figsize=(config["canvas_w_mm"] / MM_PER_INCH,
                              config["canvas_h_mm"] / MM_PER_INCH))
    reg = GidRegistry()
    prefix = FIGURE_ID + "." + scope
    # 面板 A：x 位置由 gap_x_mm 决定 —— 整体平移，里面的图元跟着走。
    ax_a = fig.add_axes(_rect_mm(10.0 + config["gap_x_mm"], 25.0, 20.0, 15.0, config))
    ax_a.set_xlim(0.0, 1.0)
    ax_a.set_ylim(0.0, 1.0)
    reg.register(ax_a, prefix + ".panel.a", params=["gap_x_mm"])
    image = ax_a.imshow(science["image"], extent=[0.0, 1.0, 0.0, 1.0])
    reg.register(image, prefix + ".image.a", params=["gap_x_mm"])
    label_a = ax_a.text(0.5, 0.5, "A", ha="center", va="center", fontsize=8.0)
    reg.register(label_a, prefix + ".label.a", params=["gap_x_mm"])
    # 面板 B：无关兄弟，位置固定；错绑定参数会把**它**推开。
    ax_b = fig.add_axes(_rect_mm(40.0 + config["stray_x_mm"], 25.0, 20.0, 15.0, config))
    ax_b.set_xlim(0.0, 1.0)
    ax_b.set_ylim(0.0, 1.0)
    reg.register(ax_b, prefix + ".panel.b", params=["stray_x_mm"])
    label_b = ax_b.text(0.5, 0.5, "B", ha="center", va="center", fontsize=8.0)
    reg.register(label_b, prefix + ".label.b", params=[])
    return fig, reg


def layout_contract(scope):
    if scope not in SCOPES:
        raise ValueError("未知 scope: " + scope)
    prefix = FIGURE_ID + "." + scope
    panel_a, panel_b = prefix + ".panel.a", prefix + ".panel.b"
    image_a, label_a = prefix + ".image.a", prefix + ".label.a"
    return {
        "parameters": [
            {"key": "gap_x", "path": ["gap_x_mm"], "unit": "mm", "mutability": "EDITABLE",
             "operation": "translate", "axis": "x", "scale": 1.0, "min": -5.0, "max": 5.0,
             "scopes": list(SCOPES), "objects": [panel_a],
             "expected": {"kind": "translate", "objects": [panel_a], "axis": "x"}},
            {"key": "stray_x", "path": ["stray_x_mm"], "unit": "mm", "mutability": "EDITABLE",
             "operation": "translate", "axis": "x", "scale": 1.0, "min": -5.0, "max": 5.0,
             "scopes": list(SCOPES), "objects": [panel_a],
             "expected": {"kind": "translate", "objects": [panel_a], "axis": "x"}},
        ],
        "nodes": {
            panel_a: {"type": "Axes", "parent": prefix, "editable": False,
                      "science_policy": "LOCKED_SCIENCE"},
            panel_b: {"type": "Axes", "parent": prefix, "editable": False,
                      "science_policy": "LOCKED_SCIENCE"},
            image_a: {"type": "AxesImage", "parent": panel_a, "editable": False,
                      "science_policy": "LOCKED_SCIENCE"},
            label_a: {"type": "Text", "parent": panel_a, "editable": False,
                      "science_policy": "LOCKED_SCIENCE"},
        },
        "groups": [{"id": prefix, "parent": None, "members": [panel_a, panel_b]}],
        "relations": [
            {"id": "panels.gap", "kind": "gap", "objects": [panel_b, panel_a], "axis": "x",
             "controlled_by": [["gap_x_mm"]], "move": [panel_a]},
        ],
        "outputs": ["panels.png"],
    }
'''

PANEL_YAML = """\
canvas_w_mm: 60.0
canvas_h_mm: 45.0
gap_x_mm: 0.0
stray_x_mm: 0.0
"""


def write_panel_fixture(root: Path):
    """把面板夹具脚本 + 配置写进目录；返回 (script, config)。"""
    script = root / 'panel_plot.py'
    config = root / 'panels.yaml'
    script.write_text(PANEL_SCRIPT, encoding='utf8')
    config.write_text(PANEL_YAML, encoding='utf8')
    return script, config


def measured_frames(session, config, gids):
    """真实重建给定配置，按 gid 取**实测** mm 包围盒（公开 build_candidate + drawn_shapes）。

    面板的位置由渲染器决定（`imshow` 会把坐标框按等比例数据收缩），所以任何期望值都
    必须从这里的实测结果推出来，而不是照抄 `add_axes` 的名义矩形。
    """
    import matplotlib.pyplot as plt
    fig, reg = session.build_candidate(config)
    try:
        shapes = drawn_shapes(fig, reg, include_frames=True)
    finally:
        plt.close(fig)
    return {gid: shapes[f'gid:{gid}']['bbox_mm'] for gid in gids}


PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def png_bytes(payload):
    """预览产物必须解得出真 PNG 字节：非空字符串本身不是证据。"""
    return base64.b64decode(payload or '', validate=True)


def scene_relation(session, relation_id):
    """公开场景快照里的一条关系读数（gap 的符号/语义由父模块测量定义给出）。"""
    return next(r for r in session.snapshot()['relations'] if r['id'] == relation_id)


class _ProbeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='figpact-session-test-')
        self.root = Path(self._tmp.name)
        self.script, self.config = write_native_probe(self.root)

    def tearDown(self):
        import matplotlib.pyplot as plt
        plt.close('all')
        self._tmp.cleanup()

    def session(self, **kwargs):
        return FigureSession(self.script, self.config, kwargs.pop('scope', 'main'), **kwargs)


class WarmSessionTest(_ProbeCase):
    def test_declared_translation_is_geometry_checked_without_png(self):
        with self.session() as session:
            baseline = session.revision
            before = loaders()
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['curve_shift_mm'], 'value': 2.0}])
            self.assertEqual(result['status'], STATUS_OK, result)
            self.assertEqual(result['verification'], VERIFICATION_GEOMETRY, result)
            self.assertIsNone(result['png'], '几何快车道不出 PNG')
            self.assertNotEqual(result['revision'], baseline)
            after = loaders()
            self.assertEqual(after['module_loads'], before['module_loads'],
                             '热试算不许再冷导入模块')
            self.assertEqual(after['science_loads'], before['science_loads'],
                             '热试算不许重装科学对象')
            self.assertEqual(session.candidate_patch, {'curve_shift_mm': 2.0})
            proof = next(c for c in result['checks'] if c['check'] == 'translation_proof')
            self.assertEqual(proof['parameter'], 'curve_shift')
            self.assertEqual(proof['descendants'], [], '曲线声明的对象没有后代')
            self.assertEqual(next(c for c in result['checks']
                                  if c['check'] == 'containment')['status'], 'OK')
            # 科学等值：核心模块必须在场，且必须是实测 True
            self.assertIs(result['science_unchanged'], True, result)

    def test_measured_collision_rejects_without_state_change(self):
        """导引线压进曲线：新相交必须是测出来的拒绝，不是渲染后放过。"""
        with self.session() as session:
            baseline = session.revision
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['guide_shift_mm'], 'value': -6.0}])
            self.assertEqual(result['status'], STATUS_GEOMETRY_REJECTED, result)
            self.assertEqual(result['verification'], VERIFICATION_GEOMETRY)
            self.assertIsNone(result['png'])
            collision = next(c for c in result['checks'] if c['check'] == 'collision')
            self.assertEqual(collision['status'], 'FAIL')
            pair = next(p for p in collision['pairs']
                        if sorted(p['pair']) == ['probe.main.curve', 'probe.main.guide'])
            self.assertLessEqual(pair['gap_mm'], 0.0, pair)
            self.assertGreater(pair['baseline_gap_mm'], 0.0,
                               '基线同一对并未相交 → 这是新碰撞，不是既有布局')
            self.assertEqual(collision['pre_existing'], [])
            self.assertEqual(session.revision, baseline, '失败不许留下目标')
            self.assertEqual(session.candidate_patch, {})

    def test_complex_change_rebuilds_warm_and_caches_preview(self):
        with self.session() as session:
            before = loaders()
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['label_font_pt'], 'value': 9.0}])
            self.assertEqual(result['verification'], VERIFICATION_RENDER, result)
            self.assertEqual(result['status'], STATUS_OK, result)
            self.assertEqual(result['new_qa'], [], '候选不得新增 QA 阻断项')
            effect = next(c for c in result['checks']
                          if c['check'] == 'declared_effect' and c['status'] == 'OK')
            self.assertEqual(effect['parameter'], 'label_font',
                             '渲染验证也要观测到声明的作用对象确实响应了')
            first = session.render_preview()
            self.assertTrue(first['cached'], 'try_layout 已warm重建过同 revision，预览应命中缓存')
            self.assertEqual(png_bytes(first['png'])[:8], PNG_SIGNATURE)
            second = session.render_preview()
            self.assertTrue(second['cached'])
            self.assertEqual(second['png'], first['png'])
            # 位移路径不渲染 → 它的预览是冷渲染（缓存里没有）
            session.try_layout([{'operation': 'reset'}])
            third = session.render_preview()
            self.assertFalse(third['cached'], '基线预览还没被渲染过')
            self.assertEqual(png_bytes(third['png'])[:8], PNG_SIGNATURE)
            session.try_layout([{'operation': 'set_parameter',
                                 'path': ['curve_shift_mm'], 'value': 1.0}])
            fourth = session.render_preview()
            self.assertFalse(fourth['cached'], '几何快车道不渲染，预览必须真渲染一次')
            self.assertEqual(png_bytes(fourth['png'])[:8], PNG_SIGNATURE)
            after = loaders()
            self.assertEqual(after['module_loads'], before['module_loads'],
                             '渲染也在同一个热进程里，不许重导模块')
            self.assertEqual(after['science_loads'], before['science_loads'])

    def test_repeated_absolute_goals_and_reset_do_not_drift(self):
        with self.session() as session:
            baseline = session.revision
            before = loaders()
            first = session.try_layout([{'operation': 'set_parameter',
                                         'path': ['curve_shift_mm'], 'value': 2.0}])
            second = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['curve_shift_mm'], 'value': -2.0}])
            again = session.try_layout([{'operation': 'set_parameter',
                                         'path': ['curve_shift_mm'], 'value': 2.0}])
            self.assertEqual(first['revision'], again['revision'], '绝对值目标不许漂移')
            self.assertNotEqual(first['revision'], second['revision'])
            reset = session.try_layout([{'operation': 'reset'}])
            self.assertEqual(reset['revision'], baseline)
            self.assertEqual(session.candidate_patch, {})
            after = loaders()
            self.assertEqual(after['module_loads'], before['module_loads'],
                             '反复试算/复位都不许重导模块')

    def test_wrong_scale_declaration_rejects_requested_goal(self):
        """声明错标尺的平移参数：契约按 10× 声明，夹具其实 1:1，必须拒绝而不是渲染后放行。"""
        needle = ('"key": "curve_shift", "path": ["curve_shift_mm"], "unit": "mm",\n'
                  '             "mutability": "EDITABLE", "operation": "translate", '
                  '"axis": "y", "scale": 1.0,')
        replacement = ('"key": "curve_shift", "path": ["curve_shift_mm"], "unit": "mm",\n'
                       '             "mutability": "EDITABLE", "operation": "translate", '
                       '"axis": "y", "scale": 10.0,')
        wrong = NATIVE_SCRIPT.replace(needle, replacement)
        self.assertNotEqual(wrong, NATIVE_SCRIPT, '夹具文本替换必须命中')
        script = self.root / 'probe_wrong_scale.py'
        script.write_text(wrong, encoding='utf8')
        with FigureSession(script, self.config, 'main') as session:
            baseline = session.revision
            rec = next(p for p in session.contract['parameters'] if p['key'] == 'curve_shift')
            self.assertEqual(rec['scale'], 10.0, '契约声明的是 10× 标尺')
            # 独立实测夹具的物理事实：参数加 1，曲线只走 1 mm（声明说 10 mm）→ 声明与绑定不符。
            before = measured_frames(session, session.candidate_config, ('probe.main.curve',))
            after = measured_frames(session, dict(session.candidate_config, curve_shift_mm=1.0),
                                    ('probe.main.curve',))
            self.assertAlmostEqual(after['probe.main.curve'][1] - before['probe.main.curve'][1],
                                   1.0, delta=0.02, msg='夹具的绑定是 1 mm/单位')
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['curve_shift_mm'], 'value': 2.0}])
            self.assertEqual(result['status'], STATUS_EFFECT_MISMATCH, result)
            self.assertIsNone(result['verification'], '错标尺声明不许进几何快车道，也不许靠渲染放行')
            self.assertIsNone(result['png'])
            self.assertEqual(session.state()['proofs'],
                             {'curve_shift': STATUS_EFFECT_MISMATCH})
            self.assertEqual(session.revision, baseline, '拒绝必须是无状态的')
            self.assertEqual(session.candidate_patch, {})

    def test_wrong_binding_moving_text_one_tenth_rejects_two_mm(self):
        """声明 scale 1.0 但绑定只移动 0.1×：请求 2 mm 必须被拒（不是 OK）。"""
        needle = 'apply_display_shift(label, dx_mm=config["label_x_mm"])'
        replacement = 'apply_display_shift(label, dx_mm=config["label_x_mm"] * 0.1)'
        wrong = NATIVE_SCRIPT.replace(needle, replacement)
        self.assertNotEqual(wrong, NATIVE_SCRIPT, '夹具文本替换必须命中')
        script = self.root / 'probe_wrong_binding.py'
        script.write_text(wrong, encoding='utf8')
        with FigureSession(script, self.config, 'main') as session:
            rec = next(p for p in session.contract['parameters'] if p['key'] == 'label_x')
            self.assertEqual(rec['scale'], 1.0, '契约声明的是 1:1 位移')
            # 独立实测：参数加 1 只走 0.1 mm，声明却是 1 mm → 绑定只有声明的 1/10。
            before = measured_frames(session, session.candidate_config, ('probe.main.label',))
            after = measured_frames(session, dict(session.candidate_config, label_x_mm=1.0),
                                    ('probe.main.label',))
            self.assertAlmostEqual(after['probe.main.label'][0] - before['probe.main.label'][0],
                                   0.1, delta=0.02, msg='夹具的绑定只有 0.1 mm/单位')
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['label_x_mm'], 'value': 2.0}])
            self.assertNotEqual(result['status'], STATUS_OK, result)
            self.assertEqual(result['status'], STATUS_EFFECT_MISMATCH, result)
            self.assertIsNone(result['verification'], result)
            self.assertIsNone(result['png'])
            self.assertEqual(session.candidate_patch, {})

    def test_unconnected_translate_parameter_is_refused_as_no_effect(self):
        """声明了 translate 但绘图代码根本不读这个键 → NO_EFFECT，不是「渲染后 OK」。"""
        with self.session() as session:
            baseline = session.revision
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['ghost_shift_mm'], 'value': -1.0}])
            self.assertEqual(result['status'], STATUS_NO_EFFECT, result)
            self.assertIsNone(result['verification'], result)
            self.assertIsNone(result['png'])
            self.assertEqual(session.state()['proofs'], {'ghost_shift': STATUS_NO_EFFECT})
            self.assertEqual(session.revision, baseline)
            self.assertEqual(session.candidate_patch, {})

    def test_unconnected_rebuild_parameter_is_refused_as_no_effect(self):
        """rebuild 声明也可能没接线：真实重建后声明对象毫无变化 → NO_EFFECT。"""
        with self.session() as session:
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['unused_knob'], 'value': 7.0}])
            self.assertEqual(result['status'], STATUS_NO_EFFECT, result)
            self.assertIsNone(result['verification'], result)

    def test_small_scale_translation_falls_back_to_render_and_still_observes_mm(self):
        """扰动量小于可测下限 → 合法退回渲染验证，但那条路上仍要观测到声明的毫米位移。"""
        needle = ('"key": "label_x", "path": ["label_x_mm"], "unit": "mm",\n'
                  '             "mutability": "EDITABLE", "operation": "translate", '
                  '"axis": "x", "scale": 1.0,')
        replacement = needle.replace('"scale": 1.0', '"scale": 0.05')
        scaled = NATIVE_SCRIPT.replace(
            needle, replacement).replace(
            'apply_display_shift(label, dx_mm=config["label_x_mm"])',
            'apply_display_shift(label, dx_mm=config["label_x_mm"] * 0.05)')
        self.assertNotEqual(scaled, NATIVE_SCRIPT, '夹具文本替换必须命中')
        script = self.root / 'probe_small_scale.py'
        script.write_text(scaled, encoding='utf8')
        with FigureSession(script, self.config, 'main') as session:
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['label_x_mm'], 'value': 6.0}])
            self.assertEqual(result['status'], STATUS_OK, result)
            self.assertEqual(result['verification'], VERIFICATION_RENDER, result)
            observed = next(c for c in result['checks'] if c['check'] == 'declared_translation')
            self.assertAlmostEqual(observed['expected_mm'], 0.3, delta=1e-6)
            self.assertEqual(observed['objects'], ['probe.main.label'])
            self.assertEqual(observed['axis'], 'x')
            # 0.3 mm 落在快车道能给出的有界扰动之下：证明不了就如实标 UNSUPPORTED_PROOF，
            # 改走真实重建继续核对毫米位移，而不是把「量不了」当成通过。
            self.assertEqual(session.state()['proofs'], {'label_x': STATUS_UNSUPPORTED_PROOF})

    def test_relation_target_is_observed_on_the_real_rebuild(self):
        """关系目标不许只靠预测几何：真实重建出来的候选上也要在解析容差内量到它。"""
        with self.session() as session:
            before = scene_relation(session, 'guide_above_curve')
            self.assertEqual(before['status'], 'OK', before)
            result = session.try_layout([{'operation': 'set_relation',
                                          'relation_id': 'guide_above_curve',
                                          'target_mm': 2.0}])
            self.assertEqual(result['status'], STATUS_OK, result)
            after = scene_relation(session, 'guide_above_curve')
            self.assertEqual(after['status'], 'OK', after)
            self.assertAlmostEqual(after['value_mm'], 2.0, delta=TOL_SAME_RENDERER_MM)
            self.assertNotAlmostEqual(before['value_mm'], after['value_mm'],
                                      delta=TOL_SAME_RENDERER_MM,
                                      msg='候选必须真的被重建并改变了间隙')

    def test_relation_solves_against_candidate_not_baseline(self):
        target = 2.0
        with self.session() as plain:
            alone = plain.try_layout([{'operation': 'set_relation',
                                       'relation_id': 'guide_above_curve', 'target_mm': target}])
            self.assertEqual(alone['status'], STATUS_OK, alone)
            solved_alone = plain.candidate_patch['guide_shift_mm']
            self.assertAlmostEqual(alone['relations'][0]['measured_mm'], target, delta=0.05)
        with self.session() as shifted:
            first = shifted.try_layout([{'operation': 'set_parameter',
                                         'path': ['curve_shift_mm'], 'value': 1.0}])
            self.assertEqual(first['status'], STATUS_OK, first)
            result = shifted.try_layout([{'operation': 'set_relation',
                                          'relation_id': 'guide_above_curve',
                                          'target_mm': target}])
            self.assertEqual(result['status'], STATUS_OK, result)
            solved_shifted = shifted.candidate_patch['guide_shift_mm']
            self.assertAlmostEqual(result['relations'][0]['measured_mm'], target, delta=0.05)
            # 独立位移把净空压掉 1 mm → 导引线目标要少降 1 mm（补偿 +1.0）
            self.assertAlmostEqual(solved_shifted - solved_alone, 1.0, delta=0.05)
            self.assertNotAlmostEqual(solved_shifted, target, delta=0.5,
                                      msg='关系目标不许被照抄成参数值')

    def test_stale_revision_is_refused(self):
        with self.session() as session:
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['curve_shift_mm'], 'value': 1.0}],
                                        revision='deadbeef')
            self.assertEqual(result['status'], STATUS_STALE)
            self.assertEqual(result['revision'], session.revision)
            with self.assertRaises(StaleRevision):
                session.render_preview(revision='deadbeef')

    def test_unsafe_and_ambiguous_mappings_are_rejected_explicitly(self):
        cases = [
            ([{'operation': 'set_parameter', 'path': ['locked_knob'], 'value': 6.0}], STATUS_LOCKED),
            ([{'operation': 'set_parameter', 'path': ['canvas_w_mm'], 'value': 61.0}],
             STATUS_NOT_IN_SCOPE),
            ([{'operation': 'set_parameter', 'path': ['no_such_key'], 'value': 1.0}],
             STATUS_UNSUPPORTED_PATH),
            ([{'operation': 'set_parameter', 'path': ['curve_shift_mm'], 'value': 99.0}],
             STATUS_OUT_OF_RANGE),
            ([{'operation': 'set_parameter', 'path': ['curve_shift_mm'], 'value': float('nan')}],
             STATUS_INVALID_VALUE),
            ([{'operation': 'set_parameter', 'path': ['curve_shift_mm'], 'value': 1.0},
              {'operation': 'set_parameter', 'path': ['curve_shift_mm'], 'value': 2.0}],
             STATUS_CONTRADICTORY),
            ([{'operation': 'set_relation', 'relation_id': 'nope', 'target_mm': 1.0}],
             STATUS_UNKNOWN_RELATION),
            ([{'operation': 'set_relation', 'relation_id': 'no_mapping', 'target_mm': 1.0}],
             STATUS_UNSUPPORTED_RELATION),
            ([{'operation': 'set_relation', 'relation_id': 'two_mappings', 'target_mm': 1.0}],
             STATUS_AMBIGUOUS),
            ([{'operation': 'set_relation', 'relation_id': 'moves_both_ends', 'target_mm': 1.0}],
             STATUS_UNSUPPORTED_RELATION),
            ([{'operation': 'set_relation', 'relation_id': 'guide_above_curve', 'target_mm': 1.0},
              {'operation': 'set_relation', 'relation_id': 'guide_above_curve', 'target_mm': 2.0}],
             STATUS_CONTRADICTORY),
        ]
        with self.session() as session:
            baseline = session.revision
            for operations, expected in cases:
                with self.subTest(expected=expected):
                    result = session.try_layout(operations)
                    self.assertEqual(result['status'], expected, result)
                    self.assertIsNone(result['verification'], result)
                    self.assertEqual(session.revision, baseline, '拒绝必须是无状态的')
                    self.assertEqual(session.candidate_patch, {})
            ambiguous = session.try_layout([{'operation': 'set_relation',
                                             'relation_id': 'two_mappings', 'target_mm': 1.0}])
            self.assertEqual(len(ambiguous['options']), 2)

    def test_config_change_invalidates_cache_and_baseline(self):
        """YAML 变更只重基线：作废证明/候选，但不重导模块、不重装科学对象。"""
        with self.session() as session:
            before_rev = session.base_config_revision
            before_state = session.state()
            before_loads = loaders()
            first = session.try_layout([{'operation': 'set_parameter',
                                         'path': ['curve_shift_mm'], 'value': 2.0}])
            self.assertEqual(first['status'], STATUS_OK)
            self.assertEqual(session.state()['proofs'], {'curve_shift': STATUS_OK},
                             '位移快车道要为这个声明留下证明')
            self.assertIs(session.state()['has_candidate'], True)
            self.config.write_text(NATIVE_YAML.replace('canvas_w_mm: 60.0', 'canvas_w_mm: 70.0'),
                                   encoding='utf8')
            self.assertEqual(session.state()['base_config_revision'], before_rev,
                             'state 不偷偷跟随磁盘（提交方要看到陈旧）')
            preview = session.render_preview()   # 触发重基线
            self.assertEqual(png_bytes(preview['png'])[:8], PNG_SIGNATURE)
            after_state = session.state()
            after_loads = loaders()
            self.assertNotEqual(after_state['source_revision'], before_state['source_revision'],
                                '总修订必须跟着配置变')
            self.assertEqual(after_state['module_revision'], before_state['module_revision'],
                             '模块/资产指纹不含配置：YAML 变更不动它')
            self.assertNotEqual(after_state['base_config_revision'], before_rev)
            self.assertEqual(after_loads['module_loads'], before_loads['module_loads'],
                             '配置变了不必重导脚本模块（源码没动）')
            self.assertEqual(after_loads['science_loads'], before_loads['science_loads'],
                             '配置变了不必重装科学对象（科学输入没动）')
            self.assertEqual(after_state['science_manifest'], before_state['science_manifest'],
                             '复用的必须是同一份已装载的科学清单')
            self.assertEqual(after_state['proofs'], {}, '配置变了，证明缓存必须作废')
            self.assertFalse(after_state['has_candidate'], '重载后目标回到基线')
            self.assertEqual(session.candidate_patch, {})
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['curve_shift_mm'], 'value': 1.0}])
            self.assertEqual(result['status'], STATUS_OK, result)

    def test_source_edit_invalidates_module_cache(self):
        """脚本源码变了必须**真的**重新导入（进程内模块指纹也变）。"""
        with self.session() as session:
            before_loads = loaders()
            before_module = session.state()['module_revision']
            self.script.write_text(NATIVE_SCRIPT + '\n# 源码改了一行\n', encoding='utf8')
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['curve_shift_mm'], 'value': 1.0}])
            self.assertEqual(result['status'], STATUS_OK, result)
            after_loads = loaders()
            self.assertEqual(after_loads['module_loads'], before_loads['module_loads'] + 1,
                             '脚本源码变了必须重新导入一次')
            self.assertNotEqual(session.state()['module_revision'], before_module,
                                '模块指纹必须跟着源码变')

    def test_unknown_scope_is_rejected_by_construction(self):
        with self.assertRaises(SessionError):
            FigureSession(self.script, self.config, 'nope')

    def test_source_revision_tracks_source_and_config(self):
        """总修订跟配置和源码都变；模块指纹只跟源码变（两者不是一回事）。"""
        first = source_revision(self.script, self.config)
        first_module = module_revision(self.script, self.config)
        self.config.write_text(NATIVE_YAML + '\n', encoding='utf8')
        self.assertNotEqual(first, source_revision(self.script, self.config))
        self.assertEqual(first_module, module_revision(self.script, self.config),
                         '配置字节不进模块指纹')
        self.script.write_text(NATIVE_SCRIPT + '\n# touch\n', encoding='utf8')
        self.assertNotEqual(first, source_revision(self.script, self.config))
        self.assertNotEqual(first_module, module_revision(self.script, self.config),
                            '源码变了模块指纹必须变')

    @unittest.skipUnless((ROOT / 'figpact' / 'scene.py').is_file(), 'figpact.scene 尚未落地')
    def test_snapshot_delegates_to_scene(self):
        with self.session() as session:
            shot = session.snapshot()
            self.assertEqual(shot['scope'], 'main')
            self.assertEqual(shot['unit'], 'mm')
            self.assertEqual(shot['revision'], session.revision)
            ids = {node['id'] for node in shot['nodes']}
            for gid in ('probe.main.curve', 'probe.main.guide', 'probe.main.label',
                        'probe.main.badge'):
                self.assertIn(gid, ids, '场景快照必须覆盖注册过的图元')
            # 场景的节点类型是**语义**类型（'curve'），不是 matplotlib 类名。
            found = session.inspect(type='curve')
            matched = [node['id'] for node in found['nodes']]
            self.assertIn('probe.main.curve', matched)
            self.assertNotIn('probe.main.badge', matched, '语义类型过滤必须排除文字节点')


class PanelClosureTest(unittest.TestCase):
    """面板整体平移：后代跟着走、无关兄弟必须原地不动、错绑定必须报出来。"""

    PANEL_GIDS = ('panels.main.panel.a', 'panels.main.panel.b',
                  'panels.main.image.a', 'panels.main.label.a')

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='figpact-panel-test-')
        self.root = Path(self._tmp.name)
        self.script, self.config = write_panel_fixture(self.root)

    def tearDown(self):
        import matplotlib.pyplot as plt
        plt.close('all')
        self._tmp.cleanup()

    def _frames(self, session, config, gids=PANEL_GIDS):
        """真实重建给定配置，返回面板/像素图/文字的**实测** mm 包围盒。"""
        return measured_frames(session, config, gids)

    def _gap_mm(self, session):
        """关系当前值的公开读数：场景快照里两面板的边到边间隙。"""
        relation = scene_relation(session, 'panels.gap')
        self.assertEqual(relation['status'], 'OK', relation)
        return relation['value_mm']

    def test_panel_translation_follows_children_and_keeps_siblings_still(self):
        with FigureSession(self.script, self.config, 'main') as session:
            baseline = self._frames(session, session.candidate_config)
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['gap_x_mm'], 'value': 2.0}])
            self.assertEqual(result['status'], STATUS_OK, result)
            self.assertEqual(result['verification'], VERIFICATION_GEOMETRY, result)
            proof = next(c for c in result['checks'] if c['check'] == 'translation_proof')
            self.assertEqual(proof['descendants'],
                             ['panels.main.image.a', 'panels.main.label.a'],
                             '后代闭包来自作者声明的 parent 归属')
            after = self._frames(session, session.candidate_config)
            self.assertAlmostEqual(after['panels.main.panel.a'][0] - baseline['panels.main.panel.a'][0],
                                   2.0, delta=0.01, msg='声明的作用对象按 mm 平移')
            for gid in ('panels.main.image.a', 'panels.main.label.a'):
                self.assertAlmostEqual(after[gid][0] - baseline[gid][0], 2.0, delta=0.01,
                                       msg=f'{gid} 必须跟着面板一起动')
            self.assertAlmostEqual(after['panels.main.panel.b'][0] - baseline['panels.main.panel.b'][0],
                                   0.0, delta=0.01, msg='无关兄弟必须原地不动')

    def test_binder_moving_an_unowned_sibling_is_reported_as_mismatch(self):
        """声明移动面板 A，绑定却移动面板 B：闭包外的对象动了 → EFFECT_MISMATCH。"""
        with FigureSession(self.script, self.config, 'main') as session:
            baseline = self._frames(session, session.candidate_config)
            # 先把「错绑定到底动了谁」独立测出来：按 stray=2 直接重建，B 真的走 2 mm、A 不动。
            strayed = self._frames(session, dict(session.candidate_config, stray_x_mm=2.0))
            self.assertAlmostEqual(strayed['panels.main.panel.b'][0]
                                   - baseline['panels.main.panel.b'][0], 2.0, delta=0.01,
                                   msg='错绑定移动的是无关兄弟 B')
            self.assertAlmostEqual(strayed['panels.main.panel.a'][0]
                                   - baseline['panels.main.panel.a'][0], 0.0, delta=0.01,
                                   msg='声明的面板 A 反而没动')
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['stray_x_mm'], 'value': 2.0}])
            self.assertEqual(result['status'], STATUS_EFFECT_MISMATCH, result)
            self.assertIsNone(result['verification'], result)
            self.assertEqual(session.candidate_patch, {}, '拒绝必须是无状态的')
            after = self._frames(session, session.candidate_config)
            self.assertEqual(after['panels.main.panel.b'], baseline['panels.main.panel.b'],
                             '被拒的候选不许落盘成状态')

    def test_relation_target_is_derived_from_measured_scene_gap(self):
        """关系目标必须从场景实测的间隙反解，不许把名义矩形当成实测几何。

        面板 A 画了 `imshow`，matplotlib 会按等比例数据把它的坐标框收缩（aspect='equal'），
        所以实际边到边间隙不等于 `add_axes` 的名义值。期望值一律取「实测间隙 ± 增量」。
        """
        with FigureSession(self.script, self.config, 'main') as session:
            baseline = self._frames(session, session.candidate_config)
            gap = self._gap_mm(session)
            # 两个独立渠道必须报同一个数：场景快照 vs 实际渲染坐标框的边到边间隙。
            self.assertAlmostEqual(baseline['panels.main.panel.b'][0]
                                   - baseline['panels.main.panel.a'][2], gap,
                                   delta=TOL_SAME_RENDERER_MM)
            target = gap + 2.0
            result = session.try_layout([{'operation': 'set_relation',
                                          'relation_id': 'panels.gap', 'target_mm': target}])
            self.assertEqual(result['status'], STATUS_OK, result)
            self.assertEqual(result['verification'], VERIFICATION_GEOMETRY, result)
            # 间隙 +2 mm 靠面板 A 沿 -x 位移 2 mm；参数值是位移，不是目标 mm 的照抄。
            self.assertAlmostEqual(session.candidate_patch['gap_x_mm'], -2.0,
                                   delta=TOL_SAME_RENDERER_MM)
            self.assertNotAlmostEqual(session.candidate_patch['gap_x_mm'], target, delta=1.0,
                                      msg='关系目标不许被照抄成参数值')
            self.assertAlmostEqual(self._gap_mm(session), target, delta=TOL_SAME_RENDERER_MM)
            self.assertAlmostEqual(result['relations'][0]['measured_mm'], target,
                                   delta=TOL_SAME_RENDERER_MM)
            # 实测重建：声明对象被移动，闭包里的后代跟着走，无关兄弟原地不动。
            after = self._frames(session, session.candidate_config)
            for gid in ('panels.main.panel.a', 'panels.main.image.a', 'panels.main.label.a'):
                self.assertAlmostEqual(after[gid][0] - baseline[gid][0], -2.0, delta=0.01,
                                       msg=f'{gid} 在声明对象/后代的闭包里，必须跟着走 2 mm')
            self.assertAlmostEqual(after['panels.main.panel.b'][0]
                                   - baseline['panels.main.panel.b'][0], 0.0, delta=0.01,
                                   msg='无关兄弟必须原地不动')


class WorkerProtocolTest(_ProbeCase):
    def test_warm_worker_imports_once_and_reuses_one_process(self):
        with FigureWorker(self.script, self.config, 'main') as worker:
            opened = worker.open()
            self.assertEqual(opened['scope'], 'main')
            pid = worker.pid
            for value in (1.0, 2.0, -1.0):
                result = worker.try_layout([{'operation': 'set_parameter',
                                             'path': ['curve_shift_mm'], 'value': value}])
                self.assertEqual(result['status'], STATUS_OK, result)
                self.assertEqual(result['verification'], VERIFICATION_GEOMETRY)
            state = worker.state()
            self.assertEqual(state['worker_pid'], pid, '热试算不许换进程')
            self.assertEqual(worker.pid, pid)
            self.assertEqual(state['loaders']['module_loads'], 1, '工作者只冷导入一次')
            self.assertEqual(state['loaders']['science_loads'], 1, '科学对象只装一次')
            self.assertEqual(state['candidate_patch'], {'curve_shift_mm': -1.0})
            self.assertIs(state['has_candidate'], True)
            self.assertEqual(state['revision'], worker.revision)
            self.assertEqual(state['revision'], result['revision'])
            self.assertEqual(state['science_manifest']['arrays'], 2)
            self.assertEqual(state['proofs'], {'curve_shift': STATUS_OK})
            self.assertEqual(worker.contract['source'], 'validated',
                             '契约必须经过父模块校验，不许原样放行')
            self.assertEqual([p['key'] for p in worker.contract['parameters']],
                             ['curve_shift', 'guide_shift', 'label_x', 'label_font',
                              'font_knob_wrong_binding', 'ghost_shift', 'unused_style',
                              'locked'],
                             '不在本作用域声明的参数必须离开参数表')
            self.assertEqual(worker.contract['out_of_scope'],
                             [{'key': 'other_scope_only', 'path': ['canvas_w_mm'],
                               'scopes': ['other']}])
            self.assertEqual(worker.ping()['pong'], True)
            self.assertIs(worker.alive, True)
            self.assertIsInstance(worker.pid, int)

    def test_timeout_raises_and_restart_is_counted(self):
        worker = FigureWorker(self.script, self.config, 'main', timeout=120.0)
        try:
            worker.open()
            first_pid = worker.pid
            first_loads = worker.state()['loaders']['module_loads']
            worker.timeout = 0.05   # check_effects 要重建十几张图，必然超时
            with self.assertRaises(WorkerTimeout):
                worker.check_effects()
            self.assertFalse(worker.alive, '超时必须杀进程，不许静默成功')
            worker.timeout = 120.0
            result = worker.try_layout([{'operation': 'set_parameter',
                                         'path': ['curve_shift_mm'], 'value': 1.0}])
            self.assertEqual(result['status'], STATUS_OK, result)
            self.assertGreaterEqual(worker.restarts, 1)
            state = worker.state()
            self.assertNotEqual(state['worker_pid'], first_pid, '重启必须换进程')
            self.assertEqual(state['loaders']['module_loads'], first_loads,
                             '新进程重新冷导入：计数从头开始，正是「真的重来了」的证据')
        finally:
            worker.close()

    def test_dead_worker_never_returns_stale_state(self):
        worker = FigureWorker(self.script, self.config, 'main')
        try:
            worker.open()
            worker.close()
            with self.assertRaises(FigureWorkerError):
                worker.state()
            with self.assertRaises(FigureWorkerError):
                worker.candidate_patch
        finally:
            worker.close()

    def test_worker_reports_config_change_and_rejects_bad_scope(self):
        """YAML 变更只让工作者里的会话重基线：不换进程、不冷导入、会话仍然开着。"""
        with FigureWorker(self.script, self.config, 'main') as worker:
            worker.open()
            before = worker.base_config_revision
            before_state = worker.state()
            pid = worker.pid
            self.config.write_text(NATIVE_YAML.replace('curve_shift_mm: 0.0',
                                                       'curve_shift_mm: 0.5'), encoding='utf8')
            result = worker.try_layout([{'operation': 'set_parameter',
                                         'path': ['curve_shift_mm'], 'value': 1.0}])
            self.assertEqual(result['status'], STATUS_OK, result)
            self.assertNotEqual(worker.base_config_revision, before)
            after_state = worker.state()
            self.assertEqual(after_state['worker_pid'], pid, 'YAML 变更不许换进程')
            self.assertEqual(after_state['loaders']['module_loads'],
                             before_state['loaders']['module_loads'],
                             'YAML 变更不许重导模块')
            self.assertEqual(after_state['loaders']['science_loads'],
                             before_state['loaders']['science_loads'],
                             'YAML 变更不许重装科学对象')
            self.assertEqual(after_state['module_revision'], before_state['module_revision'])
        bad = FigureWorker(self.script, self.config, 'nope')
        try:
            with self.assertRaises(SessionError):
                bad.open()
        finally:
            bad.close()


class LegacyScriptSessionTest(unittest.TestCase):
    """旧脚本（build_figure_and_registry，无 layout_contract）必须继续能用。"""

    SCRIPT = ROOT / 'tests' / 'fixtures' / 'synth_plot.py'
    CONFIG = ROOT / 'tests' / 'fixtures' / 'synth.yaml'

    def tearDown(self):
        import matplotlib.pyplot as plt
        plt.close('all')

    @unittest.skipUnless((ROOT / 'tests' / 'fixtures' / 'synth_plot.py').is_file(),
                         '旧夹具不在')
    def test_legacy_script_renders_and_refuses_undeclared_edits(self):
        with FigureSession(self.SCRIPT, self.CONFIG, 'main') as session:
            self.assertEqual(session.contract['source'], 'absent')
            result = session.try_layout([{'operation': 'set_parameter',
                                          'path': ['line_width'], 'value': 1.2}])
            self.assertEqual(result['status'], STATUS_UNSUPPORTED_PATH, result)
            self.assertEqual(session.candidate_patch, {})
            preview = session.render_preview()
            self.assertEqual(png_bytes(preview['png'])[:8], PNG_SIGNATURE)
            self.assertEqual(preview['qa_kind'], 'blocking_problems')


class ContractValidationTest(_ProbeCase):
    """布局契约必须在构造时通过父模块校验：缺失可变性 / 悬空对象都不许放行。"""

    @staticmethod
    def _contract(**overrides):
        record = {'key': 'knob', 'path': ['curve_shift_mm'], 'unit': 'mm',
                  'mutability': 'EDITABLE', 'operation': 'translate', 'axis': 'y',
                  'min': -6.0, 'max': 6.0, 'objects': ['probe.main.curve'],
                  'expected': {'kind': 'translate', 'objects': ['probe.main.curve'],
                               'axis': 'y'}}
        record.update(overrides)
        return {'parameters': [record], 'nodes': {}, 'groups': [], 'relations': [],
                'outputs': []}

    def test_parameter_without_mutability_is_refused_at_construction(self):
        contract = self._contract()
        del contract['parameters'][0]['mutability']
        with self.assertRaises(ContractError):
            FigureSession(self.script, self.config, 'main', contract=contract)

    def test_parameter_with_dangling_object_is_refused_at_construction(self):
        contract = self._contract(objects=['probe.main.nope'])
        with self.assertRaises(ContractError):
            FigureSession(self.script, self.config, 'main', contract=contract)

    def test_reconstruction_fields_can_be_inspected_but_never_edited(self):
        contract = self._contract()
        contract['parameters'].append({
            'key': 'schema', 'path': ['schema_version'], 'unit': 'int',
            'mutability': FIXED_STYLE, 'scopes': ['main'], 'objects': [],
        })
        original = self.config.read_bytes()
        with FigureSession(self.script, self.config, 'main', contract=contract) as session:
            before = session.revision
            result = session.try_layout([{
                'operation': 'set_parameter', 'path': ['schema_version'], 'value': 2,
            }])
            self.assertEqual(result['status'], FIXED_STYLE, result)
            self.assertEqual(session.revision, before)
            self.assertEqual(self.config.read_bytes(), original)
        contract['parameters'][-1].update(
            mutability=EDITABLE, operation='rebuild', objects=['probe.main.curve'])
        with self.assertRaises(ContractError):
            FigureSession(self.script, self.config, 'main', contract=contract)


NATIVE_DIR = ROOT / 'tests' / 'fixtures'
POSITIVE_FIXTURES = ('native_ftir.py', 'native_nmr.py', 'native_panels.py', 'native_mixed.py')
NEGATIVE_FIXTURE = 'native_negatives.py'


def _fixture(name):
    path = NATIVE_DIR / name
    return path if path.is_file() else None


def _import_fixture(path):
    """导入原生夹具模块拿 CONFIG_PATH/SCOPES（不渲染、不打印）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(f'fixture_{path.stem}', path)
    module = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = [str(path)]
    try:
        with redirect_stdout(io.StringIO()):
            spec.loader.exec_module(module)
    finally:
        sys.argv = argv
    return module


@unittest.skipUnless(any(_fixture(name) for name in POSITIVE_FIXTURES),
                     'C 切片的原生夹具尚未落地')
class RealNativeFixtureTest(unittest.TestCase):
    def tearDown(self):
        import matplotlib.pyplot as plt
        plt.close('all')

    def _effects_for(self, path):
        module = _import_fixture(path)
        config = Path(module.CONFIG_PATH)
        return [FigureSession(path, config, scope).check_effects()
                for scope in tuple(module.SCOPES)]

    def test_image_size_requires_aspect_preserving_atomic_batch(self):
        path = _fixture('native_panels.py')
        if path is None:
            self.skipTest('四面板夹具尚未落地')
        module = _import_fixture(path)
        with FigureSession(path, Path(module.CONFIG_PATH), 'main') as session:
            baseline = session.snapshot()
            baseline_revision = session.revision
            width = session._base_config['panel_w_mm'] * 0.8
            height = session._base_config['panel_h_mm'] * 0.8
            rejected = session.try_layout([
                {'operation': 'set_parameter', 'path': ['panel_w_mm'], 'value': width},
            ])
            self.assertNotEqual(rejected['status'], STATUS_OK, rejected)
            self.assertEqual(session.revision, baseline_revision)
            self.assertEqual(session.snapshot()['nodes'], baseline['nodes'])
            accepted = session.try_layout([
                {'operation': 'set_parameter', 'path': ['panel_w_mm'], 'value': width},
                {'operation': 'set_parameter', 'path': ['panel_h_mm'], 'value': height},
            ])
            self.assertEqual(accepted['status'], STATUS_OK, accepted)
            self.assertIs(accepted['science_unchanged'], True, accepted)
            panels = [node for node in session.snapshot()['nodes'] if node['type'] == 'panel']
            self.assertEqual(len(panels), 4)
            for panel in panels:
                x0, y0, x1, y1 = panel['bounds_mm']
                self.assertAlmostEqual(x1 - x0, width, places=6)
                self.assertAlmostEqual(y1 - y0, height, places=6)

    def test_negative_fixture_defects_are_detected(self):
        from figpact import effects
        path = _fixture(NEGATIVE_FIXTURE)
        if path is None:
            self.skipTest('负向夹具尚未落地')
        seen = set()
        for report in self._effects_for(path):
            for entry in report['results']:
                seen.add(entry['status'])
        self.assertIn(effects.NO_EFFECT, seen, '必须抓到「声明了却不生效」')
        self.assertIn(effects.EFFECT_MISMATCH, seen, '必须抓到错绑定')
        self.assertNotIn(effects.SCIENCE_VIOLATION, seen, '科学内容不该被布局参数碰到')


if __name__ == '__main__':
    unittest.main()
