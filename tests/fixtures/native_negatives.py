"""原生"负例"夹具：**故意带缺陷**的 NMR 风格谱图，专门用来证明门禁真的会拦人。

**这个夹具永远不可发布**：缺陷是写进来的、逐条记录的，不是不小心漏的。
`DEFECTS` 里每条都带规则 id；`--strict` 必然失败，退出码 1，一个产物都不发布。

故意缺陷（每条都在 `DEFECTS` 里写明规则 id 与作用域）：
1. UNUSED_KNOB（rule_id = NO_EFFECT）：YAML/SCHEMA 里有 `unused_knob`，契约把它声明成
   EDITABLE translate axis=y mm、objects=[note]，但 `build_scene` **从不读它** ——
   扰动它不会移动注释文本，效果校验必须报"没有效果"，而不是默默通过。
2. WRONG_BINDING（rule_id = NO_EFFECT + EFFECT_MISMATCH）：YAML/SCHEMA 里同时有
   `xlabel_font_pt` 与 `axis_font_pt`；契约声明 `xlabel_font_pt` 管 xlabel、
   `axis_font_pt` **只管 ylabel**，但构建器用 `axis_font_pt` 同时设 xlabel/ylabel 字号。
   于是扰动 `xlabel_font_pt` 什么都不会发生（NO_EFFECT），扰动 `axis_font_pt` 又会
   碰一个**没有被声明**的对象（xlabel），实际受影响集合 ≠ 声明集合（EFFECT_MISMATCH）。
3. HIDDEN_SCIENCE_CHANGE（rule_id = SCIENCE_PAYLOAD，**只有 scope "main"**）：
   画出来的谱线不是受保护数组，而是受保护数组 × 1.0005（0.05% 改写）。
   xlim/ylim、文本、对象数量都不变，所以 QA 完全干净、校验"看得见的东西"全部通过，
   只有科学自检/科学指纹能拒绝它。scope "annotated" 画的是受保护数组。
4. TEXT_COLLISION（rule_id = TEXT_OVERLAP，**只有 scope "annotated"**）：
   两对标签被放在同一个数据锚点上（`7p26`/`3p91` 同一锚点、`2p02`/`1p18` 同一锚点），
   `qa.check_text_overlap` 会给出 **2 条真实阻断项**。scope "main" 的标签各在自己的峰位上，
   一个 QA 阻断项都没有 —— 它的缺陷在科学层，不在几何层。

另外两条**关系记录层面的边界材料**（不是画错了，是故意让门禁必须表态）：
5. 只测量、不接受编辑（rule_id = UNSUPPORTED_RELATION）：关系 `negatives.label_spacing`
   的 `controlled_by` 是空列表 —— 两个标签之间的净空由数据里的峰位决定，YAML 里没有任何
   旋钮管它；对它下编辑请求必须回 UNSUPPORTED_RELATION，不许替调用方猜一个参数。
6. 两个映射都成立（rule_id = AMBIGUOUS）：关系 `negatives.label_headroom` 同时被
   `label_lift_mm` 与 `axes_top_mm` 控制（两条路径都在本契约里声明过），编辑请求必须回
   AMBIGUOUS，`options` 里正好带这两条映射，不许替调用方挑一个。
（与之相对，`window_ppm` 是**真被守住**的受保护量：构建器真的读它、`load_config` 真的
拒绝不一致的配置，所以 `set_parameter` 打在这条路径上必须回 LOCKED。）

因此 `--strict` 的预期结果（`EXPECTED_STRICT_FINDINGS` 逐条对齐）：
- scope "main"：QA 无阻断项（preview 干净），但科学自检给出 1 条 `SCIENCE_PAYLOAD`，
  发布必须被拒；
- scope "annotated"：科学自检干净，但 QA 给出 2 条 `TEXT_OVERLAP`；
- 合起来阻断项 3 条 → `--strict --probe <dir>` 拒绝发布：退出码 1，**什么都不写**。
刻意**不**把两个缺陷放在同一个 scope：隐藏科学改动只存在于 main，碰撞只存在于
annotated —— 否则"QA 干净但科学不干净"与"科学干净但 QA 不干净"这两件事就分不开了。

科学内容（受保护）：谱线 = `fixture_data.nmr_spectrum()`（严格递减 ppm 网格）；
峰位/峰高/标签文本/xlim/ylim 都是受保护载荷。

排版：标签只在数据锚点 (ppm, 峰高) 上叠一个真实毫米位移，数据坐标一个字节都不动。

导入本模块：不建 Figure、不渲染、不写文件、不打印。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:  # 直接以脚本方式运行（cwd 可能是任意目录）
    sys.path.insert(0, _ROOT)

import math  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from figpact import GidRegistry, apply_display_shift  # noqa: E402
from figpact import load_config as _engine_load_config  # noqa: E402
from figpact.config import ConfigError  # noqa: E402
from figpact.units import MM_PER_INCH  # noqa: E402
from tests.fixtures import _native, fixture_data  # noqa: E402

# ── 对外身份 ────────────────────────────────────────────────────────────────
#: 对象身份前缀，不是配置项。
FIGURE_ID = "fig_negatives_native"
#: main = 几何干净但科学不干净；annotated = 科学干净但几何不干净（见模块 docstring）。
SCOPES = ("main", "annotated")
#: 峰位身份 = 标签文本（点号换成 `p`，因为 gid 里的点从不被拆开）。
PEAK_IDS = ("7p26", "3p91", "2p02", "1p18")
CONFIG_PATH = Path(__file__).with_name("native_negatives.yaml")

XLABEL = "Chemical shift (ppm)"
YLABEL = "Intensity (a.u.)"
#: 注释文本：受保护的科学文本（说清了溶剂）。
NOTE_TEXT = "CDCl3"
#: 注释的数据锚点（谱线下方一段空白区）。
NOTE_XY = (5.0, 0.30)

FONT_RANGE = (3.0, 12.0)
#: 标签位移下界 = 2 mm：锚点是**插值**出的峰高，最靠近峰顶的采样点可能比它高出 ~0.05 a.u.
#: （0.05 a.u. ≈ 1.3 mm），抬得太少标签就压在谱线上（那是 QA 阻断）。
#: 上界 = 6 mm：再高标签就顶到 ylim 上边了。
LIFT_LIMIT_MM = 6.0
LIFT_MIN_MM = 2.0
#: `--strict` 每个 scope 必须产出的格式（共享契约：PNG/PDF/SVG/TIFF）。
OUTPUT_FORMATS = ("png", "pdf", "svg", "tiff")
#: 本夹具没有外部科学输入文件：载荷由 `fixture_data` 用固定种子在内存里现算。
SCIENCE_INPUTS: tuple[Path, ...] = ()

#: 缺陷 3 的倍数：`main` 画的是受保护数组 × 这个数（0.05% 改写，肉眼不可见）。
HIDDEN_SCALE = 1.0005
#: 缺陷 4 的锚点：key = 锚点所在的峰 id，value = 压在这个锚点上的标签 id。
COLLIDED_ANCHORS = {"7p26": ("7p26", "3p91"), "2p02": ("2p02", "1p18")}

#: 稳定句柄（测试与任务语料按名字取用，别去猜字符串）。
UNUSED_KEY = "unused_knob"
DECLARED_XLABEL_PARAM = "xlabel_font_pt"
REAL_FONT_PARAM = "axis_font_pt"


def gid(scope: str, kind: str, name: str | None = None) -> str:
    """对象身份：`<figure>.<scope>.<kind>[.<name>]`。点号在 gid 里从不被拆开。"""
    return f"{FIGURE_ID}.{scope}.{kind}" + (f".{name}" if name else "")


def XLABEL_GID(scope: str) -> str:
    """xlabel 的 gid（缺陷 2 的受害对象之一：它没被声明，却真的会变）。"""
    return gid(scope, "xlabel")


def science_inputs() -> tuple[Path, ...]:
    """声明的科学输入文件（绝对路径）。生成式夹具返回空元组——没有输入文件，
    来源是种子 + 生成函数；有外部输入的适配器必须在这里逐条列出真实文件。"""
    return SCIENCE_INPUTS


#: 故意缺陷登记表：每条都写清规则 id 与作用域，strict/效果校验的预期就靠它对齐。
DEFECTS: dict[str, dict] = {
    UNUSED_KEY: {
        "kind": "UNUSED_KNOB",
        "rule_id": "NO_EFFECT",
        "scope": "both",
        "detail": (f"{UNUSED_KEY} 在 YAML/SCHEMA 里存在，契约声明它 EDITABLE translate "
                   "axis=y mm、objects=[note]，但 build_scene 从不读它：扰动它不会移动注释。"),
    },
    DECLARED_XLABEL_PARAM: {
        "kind": "WRONG_BINDING",
        "rule_id": "NO_EFFECT",
        "scope": "both",
        "detail": (f"契约声明 {DECLARED_XLABEL_PARAM} 管 xlabel，但构建器用 {REAL_FONT_PARAM} "
                   "设 xlabel/ylabel 字号：扰动它什么都发生不了。"),
    },
    REAL_FONT_PARAM: {
        "kind": "WRONG_BINDING",
        "rule_id": "EFFECT_MISMATCH",
        "scope": "both",
        "detail": (f"契约声明 {REAL_FONT_PARAM} 只管 ylabel，构建器却同时用它设 xlabel："
                   "实际受影响集合比声明的多一个未声明对象（xlabel）。"),
    },
    "main_hidden_scale": {
        "kind": "HIDDEN_SCIENCE_CHANGE",
        "rule_id": "SCIENCE_PAYLOAD",
        "scope": "main",
        "detail": (f"main 画的是受保护数组 × {HIDDEN_SCALE}：窗口/文本/对象都不变，QA 干净，"
                   "只有科学自检与科学指纹能拒绝。annotated 画的是受保护数组。"),
    },
    "annotated_label_anchors": {
        "kind": "TEXT_COLLISION",
        "rule_id": "TEXT_OVERLAP",
        "scope": "annotated",
        "detail": ("两对标签压在同一数据锚点上（7p26/3p91、2p02/1p18）："
                   "qa.check_text_overlap 给出 2 条真实阻断项。main 的标签各在自己的峰位。"),
    },
    # 下面两条不是"画错了"，是**关系记录层面故意留的边界材料**：
    "rel_label_spacing": {
        "kind": "MEASUREMENT_ONLY_RELATION",
        "rule_id": "UNSUPPORTED_RELATION",
        "scope": "both",
        "detail": ("关系 negatives.label_spacing 的 controlled_by 是空列表：它只测量两个标签之间"
                   "的净空（那由数据里的峰位决定），YAML 里没有任何旋钮管它。"
                   "编辑请求必须回 UNSUPPORTED_RELATION，不许替调用方猜一个参数。"),
    },
    "rel_label_headroom": {
        "kind": "AMBIGUOUS_CONTROL",
        "rule_id": "AMBIGUOUS",
        "scope": "both",
        "detail": ("关系 negatives.label_headroom 有两个 controlled_by 映射"
                   "（label_lift_mm 与 axes_top_mm，两条路径都在本契约里声明过）："
                   "编辑请求必须回 AMBIGUOUS，options 里正好带这两条映射，"
                   "不许替调用方挑一个。"),
    },
}

#: `--strict` 的预期结果（逐条可与 DEFECTS 对齐）。
EXPECTED_STRICT_FINDINGS = (
    "main: QA 无阻断项；science_selfcheck 给出 1 条 SCIENCE_PAYLOAD（绘图数组 = 受保护数组 × "
    f"{HIDDEN_SCALE}）",
    "annotated: science_selfcheck 干净（画的就是受保护数组）；QA 给出 2 条 TEXT_OVERLAP",
    "合计 3 条阻断项 → strict 退出码 1，不发布任何产物（staging 一并清掉）",
    "会话层：set_parameter(window_ppm) → LOCKED；relation negatives.label_spacing → "
    "UNSUPPORTED_RELATION；relation negatives.label_headroom → AMBIGUOUS（options 正好两条映射）",
)

#: key → (类型, 下界, 上界)。
SCALARS = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 70.0, 160.0),
    "canvas_h_mm": (float, 56.0, 160.0),
    "render_dpi": (int, 96, 600),
    "axes_left_mm": (float, 5.0, 50.0),
    "axes_right_mm": (float, 5.0, 50.0),
    "axes_bottom_mm": (float, 5.0, 40.0),
    "axes_top_mm": (float, 5.0, 24.0),
    "axis_font_pt": (float, *FONT_RANGE),
    "xlabel_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "label_font_pt": (float, *FONT_RANGE),
    "line_width": (float, 0.2, 3.0),
    "label_lift_mm": (float, LIFT_MIN_MM, LIFT_LIMIT_MM),
    "unused_knob": (float, -5.0, 5.0),
    # 受保护的积分窗口半宽（ppm）：改它 = "归属"这件事换了一个意思。
    "window_ppm": (float, 0.0, 1.0),
}
SCHEMA = dict(SCALARS)

PARAM_GROUPS = {
    "元数据 (Meta)": ("schema_version",),
    "画布 (Canvas)": ("canvas_w_mm", "canvas_h_mm", "render_dpi"),
    "坐标框 (Axes rect)": ("axes_left_mm", "axes_right_mm", "axes_bottom_mm", "axes_top_mm"),
    "字号与线宽 (Type)": ("axis_font_pt", "xlabel_font_pt", "tick_font_pt", "label_font_pt",
                          "line_width"),
    "标签 (Labels)": ("label_lift_mm",),
    "未使用旋钮 (Unused)": ("unused_knob",),
    "受保护窗口 (Locked)": ("window_ppm",),
}
PARAM_DESC = {
    "schema_version": ("配置契约版本", "—"),
    "canvas_w_mm": ("画布物理宽度", "mm"),
    "canvas_h_mm": ("画布物理高度", "mm"),
    "render_dpi": ("渲染分辨率", "dpi"),
    "axes_left_mm": ("坐标框左外边距", "mm"),
    "axes_right_mm": ("坐标框右外边距", "mm"),
    "axes_bottom_mm": ("坐标框下外边距", "mm"),
    "axes_top_mm": ("坐标框上外边距", "mm"),
    "axis_font_pt": ("轴标题字号（缺陷 2：实际同时作用在 xlabel 上）", "pt"),
    "xlabel_font_pt": ("xlabel 字号（缺陷 2：被静默忽略）", "pt"),
    "tick_font_pt": ("刻度字号", "pt"),
    "label_font_pt": ("峰位标签字号", "pt"),
    "line_width": ("谱线线宽", "pt"),
    "label_lift_mm": ("峰位标签上抬", "mm"),
    "unused_knob": ("未使用旋钮（缺陷 1：声明了却从不被读）", "mm"),
    "window_ppm": ("积分窗口半宽（受保护：与 fixture_data 必须逐值一致）", "ppm"),
}

#: 任务语料引用这些名字，测试核对"每个断言的保护项都被夹具声明过"。
SCIENCE_INVARIANTS = {
    "negatives.science_payload": ("annotated 的谱线绘图数组逐字节等于受保护数组；"
                                  "main 故意不等于（× %s）" % HIDDEN_SCALE),
    "negatives.view_windows": "xlim/ylim 显示窗口不变",
    "negatives.protected_text": "峰位标签与注释文本不变",
}


# ── 配置 ────────────────────────────────────────────────────────────────────
def load_config(path: Path | str = CONFIG_PATH) -> dict:
    """引擎校验 + 积分窗口只读校验。

    夹具自己的"效果约束"故意是缺的（见 DEFECTS），但**受保护窗口是真的守住的**：
    `window_ppm` 与 `fixture_data.NMR_WINDOW_PPM` 不一致就直接拒绝构建
    —— 所以 `set_parameter` 打在这条路径上必须回 LOCKED，而不是照单全收。
    """
    cfg = _engine_load_config(path, SCHEMA)
    name = Path(path).name
    window = float(cfg["window_ppm"])
    expected = float(fixture_data.NMR_WINDOW_PPM)
    if not math.isclose(window, expected, rel_tol=0.0, abs_tol=1e-9):
        raise ConfigError(f"{name}：window_ppm = {window} 与受保护积分窗口半宽 {expected} ppm 不一致")
    return cfg


def list_params(path: Path | str = CONFIG_PATH) -> None:
    """按可见对象分组的参数清单（当前值 / 单位 / 允许范围）。"""
    cfg = load_config(path)
    _native.print_param_table(cfg, SCALARS, PARAM_GROUPS, PARAM_DESC)


# ── 科学载荷 ────────────────────────────────────────────────────────────────
def load_science() -> dict:
    """受保护的数据与来源声明：不建 Figure，可以被反复调用（结果一致）。"""
    x, y = fixture_data.nmr_spectrum()
    ppm = fixture_data.nmr_peak_ppm()
    heights = fixture_data.nmr_peak_heights()
    if len(ppm) != len(PEAK_IDS):
        raise ValueError(f"峰位数量 {len(ppm)} 与本夹具声明的标签 {list(PEAK_IDS)} 不符")
    return {
        "spectrum": (x, y),
        "peak_ppm": {pid: float(p) for pid, p in zip(PEAK_IDS, ppm)},
        "peak_heights": {pid: float(h) for pid, h in zip(PEAK_IDS, heights)},
        "labels": {pid: pid for pid in PEAK_IDS},
        "window_ppm": float(fixture_data.NMR_WINDOW_PPM),
        "windows": {pid: (float(p) - float(fixture_data.NMR_WINDOW_PPM),
                          float(p) + float(fixture_data.NMR_WINDOW_PPM))
                    for pid, p in zip(PEAK_IDS, ppm)},
        "note": NOTE_TEXT,
        "xlim": tuple(fixture_data.NMR_XLIM),
        "ylim": tuple(fixture_data.NMR_YLIM),
        "source": {
            "kind": "seeded_synthetic",
            "seed": fixture_data.SEED + 1,
            "generator": "tests.fixtures.fixture_data.nmr_spectrum",
            "note": "no instrument file, no private data",
        },
    }


def science_manifest(science: dict) -> dict:
    """来源/处理/受保护窗口/文本的 JSONable 声明 + 故意缺陷登记（绝不自称干净）。"""
    return {
        "science": {
            "source": science["source"],
            "processing": [
                "deterministic seeded Lorentzian sum, no smoothing",
                "no normalisation, no resampling of the plotted arrays",
                "annotated plots the protected arrays verbatim",
            ],
            "protected_windows": {
                "xlim_ppm": list(science["xlim"]),
                "ylim_au": list(science["ylim"]),
                # 积分窗口：受保护的显示窗口，"归属"这件事的一半。
                "window_half_width_ppm": science["window_ppm"],
                "integration_windows_ppm": {pid: list(pair)
                                            for pid, pair in science["windows"].items()},
            },
            "crop": [],
            "scale_bars": [],
            "protected_text": {
                "peak_labels": dict(science["labels"]),
                "note": science["note"],
                "axis_titles": [XLABEL, YLABEL],
            },
            "arrays": [{
                "id": "nmr.spectrum", "kind": "curve", "n": int(science["spectrum"][0].size),
                "units": {"x": "ppm", "y": "a.u."}, "grid": "strictly descending",
            }],
            "defects": {key: {"kind": item["kind"], "rule_id": item["rule_id"],
                              "scope": item["scope"], "detail": item["detail"]}
                        for key, item in DEFECTS.items()},
        },
        "nodes": {g: {"science_policy": meta["science_policy"]}
                  for g, meta in _all_policy_nodes().items()},
    }


# ── 绘制 ────────────────────────────────────────────────────────────────────
def _axes_rect(config: dict) -> list[float]:
    """坐标框的精确位置：canvas 毫米 - 四条外边距，直接换成 figure 分数。"""
    width_mm, height_mm = config["canvas_w_mm"], config["canvas_h_mm"]
    box_w = width_mm - config["axes_left_mm"] - config["axes_right_mm"]
    box_h = height_mm - config["axes_bottom_mm"] - config["axes_top_mm"]
    if box_w <= 5.0 or box_h <= 5.0:
        raise ValueError(f"坐标框只剩 {box_w:.1f}×{box_h:.1f} mm"
                         f"（画布 {width_mm}×{height_mm} mm）")
    return [config["axes_left_mm"] / width_mm, config["axes_bottom_mm"] / height_mm,
            box_w / width_mm, box_h / height_mm]


def _label_plan(science: dict, scope: str) -> list[tuple[str, float, float]]:
    """(标签 id, 数据锚点 x=ppm, 数据锚点 y=峰高)。

    `main`：每个标签在自己的峰位上；`annotated`：**故意**把两对标签压在同两个锚点上
    （缺陷 4 —— 这是几何层缺陷，由 QA 拦，不由科学自检拦）。
    """
    if scope == "main":
        return [(pid, science["peak_ppm"][pid], science["peak_heights"][pid])
                for pid in PEAK_IDS]
    plan: list[tuple[str, float, float]] = []
    for anchor_id, ids in COLLIDED_ANCHORS.items():
        for pid in ids:
            plan.append((pid, science["peak_ppm"][anchor_id],
                         science["peak_heights"][anchor_id]))
    return plan


def build_scene(science: dict, config: dict, scope: str):
    """确定性构建：基线布局完全由 config 决定；(Figure, GidRegistry)。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    cfg = config

    fig = plt.figure(figsize=(cfg["canvas_w_mm"] / MM_PER_INCH, cfg["canvas_h_mm"] / MM_PER_INCH),
                     dpi=float(cfg["render_dpi"]))
    ax = fig.add_axes(_axes_rect(cfg))
    reg = GidRegistry()
    reg.register(fig.patch, gid(scope, "canvas"))
    reg.register(ax, gid(scope, "axes"), params=["canvas_w_mm", "canvas_h_mm", "axes_left_mm",
                                                 "axes_right_mm", "axes_bottom_mm",
                                                 "axes_top_mm"])

    # 积分窗口：**受保护**的显示窗口（先画，压在谱线下面）。
    # 半宽由 `window_ppm` 给，而 load_config 已经把那个值钉在受保护窗口上。
    for pid in PEAK_IDS:
        center = science["peak_ppm"][pid]
        span = ax.axvspan(center - cfg["window_ppm"], center + cfg["window_ppm"],
                          color="0.45", alpha=0.16, lw=0.0, zorder=1)
        reg.register(span, gid(scope, "peak_window", pid), params=["window_ppm"])

    # 缺陷 3：main 的 y 被乘了 HIDDEN_SCALE（受保护数组 ≠ 绘图数组）。
    # annotated 逐字节画受保护数组。x 网格两边都是受保护的。
    x, y = science["spectrum"]
    plotted = y * HIDDEN_SCALE if scope == "main" else y
    (line,) = ax.plot(x, plotted, lw=cfg["line_width"], color="C0", zorder=3)
    reg.register(line, gid(scope, "spectrum"), params=["line_width"])

    # 峰位标签：数据锚点 + 真实毫米上抬。
    for pid, anchor_x, anchor_y in _label_plan(science, scope):
        text = ax.text(anchor_x, anchor_y, science["labels"][pid],
                       fontsize=cfg["label_font_pt"], ha="center", va="bottom", zorder=4)
        reg.register(text, gid(scope, "peak_label", pid),
                     params=["label_font_pt", "label_lift_mm"])
        apply_display_shift(text, dy_mm=cfg["label_lift_mm"])

    # 溶剂注释：缺陷 1 的受害对象 —— 契约说 `unused_knob` 会移动它，构建器从不读那个键。
    note = ax.text(NOTE_XY[0], NOTE_XY[1], science["note"], fontsize=cfg["label_font_pt"],
                   ha="center", va="bottom", zorder=4)
    reg.register(note, gid(scope, "note"), params=["label_font_pt", UNUSED_KEY])

    # 缺陷 2：xlabel 的字号来自 REAL_FONT_PARAM，而不是契约声明的 DECLARED_XLABEL_PARAM。
    ax.set_xlabel(XLABEL, fontsize=cfg[REAL_FONT_PARAM])
    reg.register(ax.xaxis.label, gid(scope, "xlabel"), params=[DECLARED_XLABEL_PARAM])
    ax.set_ylabel(YLABEL, fontsize=cfg[REAL_FONT_PARAM])
    reg.register(ax.yaxis.label, gid(scope, "ylabel"), params=[REAL_FONT_PARAM])
    ax.tick_params(labelsize=cfg["tick_font_pt"])
    ax.set_xlim(*science["xlim"])
    ax.set_ylim(*science["ylim"])
    return fig, reg


def build_figure_and_registry(scope: str, *, config: dict | None = None):
    """旧接缝保持不变：等价于 build_scene(load_science(), config, scope)。"""
    return build_scene(load_science(), config if config is not None else load_config(), scope)


# ── 布局契约 ────────────────────────────────────────────────────────────────
def _nodes(scope: str) -> dict:
    """节点元数据。这个夹具把**所有**节点都声明成 LOCKED_SCIENCE（含注释文本），
    好让缺陷停在"声明过的对象/路径"层面：不是悬空引用，是声明与实现不一致。"""
    root = gid(scope, "root")
    nodes: dict[str, dict] = {
        gid(scope, "canvas"): _native.node(gid(scope, "canvas"), type_name="Figure", parent=None,
                                           editable=False, science_policy="LOCKED_SCIENCE",
                                           label="画布"),
        gid(scope, "axes"): _native.node(gid(scope, "axes"), type_name="Axes", parent=root,
                                         editable=False, science_policy="LOCKED_SCIENCE",
                                         label="坐标框"),
        gid(scope, "spectrum"): _native.node(
            gid(scope, "spectrum"), type_name="Line2D", parent=root, editable=False,
            science_policy="LOCKED_SCIENCE", label="NMR 谱线"),
        gid(scope, "xlabel"): _native.node(XLABEL_GID(scope), type_name="Text", parent=root,
                                           editable=False, science_policy="LOCKED_SCIENCE",
                                           label=XLABEL),
        gid(scope, "ylabel"): _native.node(gid(scope, "ylabel"), type_name="Text", parent=root,
                                           editable=False, science_policy="LOCKED_SCIENCE",
                                           label=YLABEL),
        gid(scope, "note"): _native.node(gid(scope, "note"), type_name="Text", parent=root,
                                         editable=False, science_policy="LOCKED_SCIENCE",
                                         label=NOTE_TEXT),
    }
    for pid in PEAK_IDS:
        nodes[gid(scope, "peak_window", pid)] = _native.node(
            gid(scope, "peak_window", pid), type_name="Rectangle", parent=root, editable=False,
            science_policy="LOCKED_SCIENCE", label=f"积分窗口 {pid}")
        nodes[gid(scope, "peak_label", pid)] = _native.node(
            gid(scope, "peak_label", pid), type_name="Text", parent=root, editable=False,
            science_policy="LOCKED_SCIENCE", label=pid)
    return nodes


def _all_policy_nodes() -> dict:
    """全部 scope 的 science_policy 表（science_manifest 与契约共用一份）。"""
    out: dict[str, dict] = {}
    for scope in SCOPES:
        out.update(_nodes(scope))
    return out


def _parameters(scope: str) -> list[dict]:
    """参数记录。**故意**在声明层留了两个洞（`unused_knob`、`xlabel_font_pt`），
    并让 `axis_font_pt` 的声明对象与实际受影响集合不一致 —— 见 DEFECTS。"""
    canvas = gid(scope, "canvas")
    axes_node = gid(scope, "axes")
    labels = [gid(scope, "peak_label", pid) for pid in PEAK_IDS]
    note = gid(scope, "note")
    xlabel, ylabel = XLABEL_GID(scope), gid(scope, "ylabel")
    spectrum = gid(scope, "spectrum")
    keep = ["negatives.science_payload", "negatives.view_windows"]

    parameters = [
        _native.param("canvas_w_mm", ["canvas_w_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis="x",
                      minimum=SCALARS["canvas_w_mm"][1], maximum=SCALARS["canvas_w_mm"][2],
                      expected=_native.expect("resize", objects=[canvas], axis="x",
                                              preserve=keep)),
        _native.param("canvas_h_mm", ["canvas_h_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis="y",
                      minimum=SCALARS["canvas_h_mm"][1], maximum=SCALARS["canvas_h_mm"][2],
                      expected=_native.expect("resize", objects=[canvas], axis="y",
                                              preserve=keep)),
        _native.param("render_dpi", ["render_dpi"], unit="dpi", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis=None,
                      minimum=SCALARS["render_dpi"][1], maximum=SCALARS["render_dpi"][2],
                      expected=_native.expect("style", objects=[canvas], preserve=keep)),
    ]
    for key, axis in (("axes_left_mm", "x"), ("axes_right_mm", "x"),
                      ("axes_bottom_mm", "y"), ("axes_top_mm", "y")):
        parameters.append(_native.param(
            key, [key], unit="mm", mutability="EDITABLE", scopes=list(SCOPES),
            objects=[axes_node], operation="rebuild", axis=axis,
            minimum=SCALARS[key][1], maximum=SCALARS[key][2],
            expected=_native.expect("resize", objects=[axes_node], axis=axis, preserve=keep)))
    # 缺陷 2：xlabel 的字号旋钮声明成 EDITABLE，但构建器读的是 axis_font_pt。
    parameters.append(_native.param(
        DECLARED_XLABEL_PARAM, [DECLARED_XLABEL_PARAM], unit="pt", mutability="EDITABLE",
        scopes=list(SCOPES), objects=[xlabel], operation="rebuild", axis=None,
        minimum=SCALARS[DECLARED_XLABEL_PARAM][1],
        maximum=SCALARS[DECLARED_XLABEL_PARAM][2],
        expected=_native.expect("style", objects=[xlabel], preserve=keep)))
    # 缺陷 2 的另一半：只声明 ylabel，实际连 xlabel 一起改。
    parameters.append(_native.param(
        REAL_FONT_PARAM, [REAL_FONT_PARAM], unit="pt", mutability="EDITABLE",
        scopes=list(SCOPES), objects=[ylabel], operation="rebuild", axis=None,
        minimum=SCALARS[REAL_FONT_PARAM][1], maximum=SCALARS[REAL_FONT_PARAM][2],
        expected=_native.expect("style", objects=[ylabel], preserve=keep)))
    for key, target in (("tick_font_pt", []), ("label_font_pt", labels + [note]),
                        ("line_width", [spectrum])):
        parameters.append(_native.param(
            key, [key], unit="pt", mutability="FIXED_STYLE", scopes=list(SCOPES),
            objects=target, operation="rebuild", axis=None,
            minimum=SCALARS[key][1], maximum=SCALARS[key][2],
            expected=_native.expect("style", objects=target, preserve=keep)))
    parameters.append(_native.param(
        "label_lift_mm", ["label_lift_mm"], unit="mm", mutability="EDITABLE",
        scopes=list(SCOPES), objects=labels, operation="translate", axis="y", scale=1.0,
        minimum=SCALARS["label_lift_mm"][1], maximum=SCALARS["label_lift_mm"][2],
        expected=_native.expect("translate", objects=labels, axis="y", preserve=keep)))
    # 缺陷 1：声明成移动注释的纯位移，构建器从不读它 → 效果校验必须报 NO_EFFECT。
    parameters.append(_native.param(
        UNUSED_KEY, [UNUSED_KEY], unit="mm", mutability="EDITABLE", scopes=list(SCOPES),
        objects=[note], operation="translate", axis="y", scale=1.0,
        minimum=SCALARS[UNUSED_KEY][1], maximum=SCALARS[UNUSED_KEY][2],
        expected=_native.expect("translate", objects=[note], axis="y", preserve=keep)))
    # 受保护的积分窗口半宽：真被构建器读、真被 load_config 守住 →
    # 打在这条路径上的 set_parameter 必须回 LOCKED（不是"照单全收"，也不是静默 no-op）。
    parameters.append(_native.param(
        "window_ppm", ["window_ppm"], unit="ppm", mutability="LOCKED_SCIENCE",
        scopes=list(SCOPES), objects=[gid(scope, "peak_window", pid) for pid in PEAK_IDS],
        operation="rebuild", axis=None, minimum=SCALARS["window_ppm"][1],
        maximum=SCALARS["window_ppm"][2],
        expected=_native.expect("style", objects=[gid(scope, "peak_window", pid)
                                                 for pid in PEAK_IDS],
                                preserve=["negatives.view_windows"])))
    return parameters


def _relations(scope: str) -> list[dict]:
    canvas = gid(scope, "canvas")
    axes_node = gid(scope, "axes")
    return [
        _native.relation("negatives.contain_x", "contain", [canvas, axes_node], axis="x",
                         controlled_by=[["canvas_w_mm"], ["axes_left_mm"], ["axes_right_mm"]]),
        _native.relation("negatives.contain_y", "contain", [canvas, axes_node], axis="y",
                         controlled_by=[["canvas_h_mm"], ["axes_bottom_mm"], ["axes_top_mm"]]),
        _native.relation("negatives.margin_left", "gap", [canvas, axes_node], axis="x",
                         anchor="left", controlled_by=[["axes_left_mm"]], move=[axes_node]),
        _native.relation("negatives.margin_right", "gap", [canvas, axes_node], axis="x",
                         anchor="right", controlled_by=[["axes_right_mm"]], move=[axes_node]),
        _native.relation("negatives.margin_bottom", "gap", [canvas, axes_node], axis="y",
                         anchor="bottom", controlled_by=[["axes_bottom_mm"]], move=[axes_node]),
        _native.relation("negatives.margin_top", "gap", [canvas, axes_node], axis="y",
                         anchor="top", controlled_by=[["axes_top_mm"]], move=[axes_node]),
        # 只测量、不接受编辑：两个标签之间的净空由数据里的峰位决定，
        # YAML 里没有任何旋钮管它 → 编辑请求必须回 UNSUPPORTED_RELATION，不许猜一个参数。
        _native.relation("negatives.label_spacing", "gap",
                         [gid(scope, "peak_label", PEAK_IDS[0]),
                          gid(scope, "peak_label", PEAK_IDS[1])], axis="x", controlled_by=[]),
        # 两个映射都真的管这段关系（抬标签 / 动上边距），而且两条路径都在本契约里声明过
        # → 编辑请求必须回 AMBIGUOUS，`options` 里正好带这两条映射，不许替调用方挑一个。
        _native.relation("negatives.label_headroom", "gap",
                         [gid(scope, "peak_label", PEAK_IDS[0]), axes_node], axis="y",
                         anchor="top", controlled_by=[["label_lift_mm"], ["axes_top_mm"]],
                         move=[gid(scope, "peak_label", PEAK_IDS[0])]),
    ]


def layout_contract(scope: str) -> dict:
    """这张图的可控点：参数 / 节点 / 组 / 关系 / 产物。路径永远是精确段数组。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    root = gid(scope, "root")
    canvas = gid(scope, "canvas")
    axes_node = gid(scope, "axes")
    labels = [gid(scope, "peak_label", pid) for pid in PEAK_IDS]
    windows = [gid(scope, "peak_window", pid) for pid in PEAK_IDS]
    text = [XLABEL_GID(scope), gid(scope, "ylabel"), gid(scope, "note"), *labels]
    return _native.contract_record(
        sys.modules[__name__], scope,
        parameters=_parameters(scope),
        nodes=_nodes(scope),
        groups=[
            _native.group(root, parent=None,
                          members=[canvas, axes_node, gid(scope, "spectrum"), *windows, *text]),
            _native.group(gid(scope, "peak_windows"), parent=root, members=windows),
            _native.group(gid(scope, "peak_labels"), parent=root, members=labels),
            _native.group(gid(scope, "text"), parent=root, members=text),
        ],
        relations=_relations(scope),
        outputs=[f"{FIGURE_ID}_{scope}.{ext}" for ext in OUTPUT_FORMATS],
        source={
            "publishable": False,
            "hidden_scale": HIDDEN_SCALE,
            "unused_key": UNUSED_KEY,
            "declared_xlabel_param": DECLARED_XLABEL_PARAM,
            "real_font_param": REAL_FONT_PARAM,
            "xlabel_gid": XLABEL_GID(scope),
            "defects": {key: item["rule_id"] for key, item in DEFECTS.items()},
            "expected_strict_findings": list(EXPECTED_STRICT_FINDINGS),
            "science_invariants": dict(SCIENCE_INVARIANTS),
            "science_inputs": [str(p) for p in science_inputs()],
        },
    )


# ── 科学自检（strict 会用它拒绝发布） ───────────────────────────────────────
def science_selfcheck(science: dict, fig=None) -> list[str]:
    """受保护内容的自检。**必须**抓住 main 那份 0.05% 改写（rule_id SCIENCE_PAYLOAD），
    并且对 annotated 保持干净（那边的缺陷是几何碰撞，由 QA 拦）。"""
    problems: list[str] = []
    x, y = science["spectrum"]
    if not (x.ndim == y.ndim == 1 and x.shape == y.shape and x.size >= 2):
        problems.append(f"SCIENCE_PAYLOAD: 谱线数组形状非法（{x.shape}/{y.shape}）")
    elif not np.all(np.diff(x) < 0):
        problems.append("SCIENCE_GRID: 化学位移网格不再严格递减")
    elif not np.all(np.isfinite(y)):
        problems.append("SCIENCE_PAYLOAD: 谱线含 NaN/Inf")
    for pid, label in science["labels"].items():
        if label != pid:
            problems.append(f"SCIENCE_TEXT: 标签 {pid} 的文本被改成了 {label!r}")
    if science["note"] != NOTE_TEXT:
        problems.append(f"SCIENCE_TEXT: 注释文本被改成了 {science['note']!r}")

    if fig is None:
        return problems

    by_gid = _native.artists_by_gid(fig)
    for scope in SCOPES:
        line = by_gid.get(gid(scope, "spectrum"))
        if line is not None:
            want_x, want_y = science["spectrum"]
            got_x = np.asarray(line.get_xdata(), float)
            got_y = np.asarray(line.get_ydata(), float)
            if not np.array_equal(got_x, want_x):
                problems.append(f"SCIENCE_PAYLOAD: {scope} 谱线的化学位移网格 != 受保护网格")
            elif got_y.shape != want_y.shape:
                problems.append(f"SCIENCE_PAYLOAD: {scope} 谱线 y 形状 {got_y.shape} "
                                f"!= 受保护形状 {want_y.shape}")
            elif not np.array_equal(got_y, want_y):
                # 逐点比：连 0.05% 的改写也要报出来（这就是"隐藏科学改动"的探针）。
                scale = np.abs(got_y) / np.where(want_y == 0.0, 1.0, np.abs(want_y))
                deviation = float(np.max(np.abs(got_y - want_y))) if want_y.size else 0.0
                ratio = float(np.max(scale)) - 1.0 if want_y.size else 0.0
                problems.append(f"SCIENCE_PAYLOAD: {scope} 谱线绘图数组 != 受保护数组"
                                f"（y 最大绝对偏差 {deviation:.6g}，最大相对偏差 "
                                f"{ratio:.6g}）")
        ax = by_gid.get(gid(scope, "axes"))
        if ax is not None:
            if not np.allclose(ax.get_xlim(), science["xlim"], atol=1e-9):
                problems.append(f"SCIENCE_WINDOW: {scope} xlim 变成了 {tuple(ax.get_xlim())}")
            if not np.allclose(ax.get_ylim(), science["ylim"], atol=1e-9):
                problems.append(f"SCIENCE_WINDOW: {scope} ylim 变成了 {tuple(ax.get_ylim())}")
        for pid, (lo, hi) in science["windows"].items():
            span = by_gid.get(gid(scope, "peak_window", pid))
            if span is None:
                continue
            # axvspan 是 Rectangle：get_x()/get_width() 给数据坐标（get_verts() 给显示像素）。
            got = (float(span.get_x()), float(span.get_x() + span.get_width()))
            if not np.allclose(got, (lo, hi), atol=1e-9):
                problems.append(f"SCIENCE_WINDOW: {scope} 积分窗口 {pid} 变成了 {got}")
        for pid, want in science["labels"].items():
            art = by_gid.get(gid(scope, "peak_label", pid))
            if art is not None and art.get_text() != want:
                problems.append(f"SCIENCE_TEXT: {scope} 标签 {pid} 被改成了 "
                                f"{art.get_text()!r}")
        note = by_gid.get(gid(scope, "note"))
        if note is not None and note.get_text() != science["note"]:
            problems.append(f"SCIENCE_TEXT: {scope} 注释被改成了 {note.get_text()!r}")
        for key, want in (("xlabel", XLABEL), ("ylabel", YLABEL)):
            art = by_gid.get(gid(scope, key))
            if art is not None and art.get_text() != want:
                problems.append(f"SCIENCE_TEXT: {scope} {key} 文本被改成了 {art.get_text()!r}")
    return problems


if __name__ == "__main__":
    raise SystemExit(_native.run(sys.modules[__name__]))
