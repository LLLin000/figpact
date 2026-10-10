"""原生 NMR 夹具：一条洛伦兹叠加谱 + 峰位引导线、积分窗口与归属标签。

**与绘图源码无关**：这张图是什么，全部写在下面对外声明的接缝里 ——
`SCOPES / FIGURE_ID / CONFIG_PATH / SCHEMA / load_config / list_params /
load_science / build_scene / build_figure_and_registry / layout_contract /
science_manifest / science_selfcheck`。别的 agent 不用读本文件其余部分，
就能拿到"有哪些对象、哪个 YAML 路径控制它、会产生什么效果、必须守住什么"。

科学内容（受保护，显示层不许改）：
- 谱线画在一条**严格递减**的化学位移网格上（8.0 → 0.5 ppm），绘图数组逐字节
  等于 `fixture_data` 的数组；
- 峰位（7.26 / 3.91 / 2.02 / 1.18 ppm）由竖直引导线标出，x 数据就是峰位本身；
- 每个峰有一段**受保护的积分窗口**（ppm）；窗口一变，"归属"这件事就不是同一件事；
- 归属文本、xlim/ylim 显示窗口同样受保护。
（峰高走 `fixture_data.interp_descending`：递减网格直接喂 `np.interp` 返回的是
没有意义的数——位移与标签都建在错的高度上。）

排版（真实物理毫米，不许用 0.1 data-unit/mm 之类的猜出来的换算）：
归属标签只在**数据锚点** (ppm, 峰高) 上再叠一个 `apply_display_shift(..., dy_mm=...)`；
每个峰的 `peak_shifts_mm` 是"完整受影响集合"（引导线 + 窗口 + 标签）的刚体
毫米位移，数据坐标一个字节都不动。

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
#: 对象身份前缀，不是配置项：gid 是外部引用认的名字，做成旋钮只会让引用悄悄失效。
FIGURE_ID = "fig_nmr_native"
#: 「一次 build_scene 调用 = 一个作用域」。改论文主图不许顺手改掉标注版。
SCOPES = ("main", "annotated")
#: 峰值身份 = 归属文本的键（`7.26` / `3.91` / `2.02` / `1.18`）：受保护的名字。
PEAK_KEYS = tuple(fixture_data.nmr_assignments())
CONFIG_PATH = Path(__file__).with_name("native_nmr.yaml")

XLABEL = "Chemical shift (ppm)"
YLABEL = "Intensity (a.u.)"

FONT_RANGE = (3.0, 12.0)
#: 单个峰的显示位移上限（mm）：超过这个数引导线会被坐标框裁掉，那是 QA 阻断。
SHIFT_LIMIT_MM = 6.0
#: `--strict` 每个 scope 必须产出的格式（共享契约：PNG/PDF/SVG/TIFF）。
OUTPUT_FORMATS = ("png", "pdf", "svg", "tiff")
#: 持"逐峰毫米显示位移"的那个字典键：任务语料与测试用它当稳定把手，不靠猜字段名。
SHIFT_KEY = "peak_shifts_mm"
#: 谱线点数（fixture_data.NMR_N）：用来把谱线（多点）与引导线（2 点）分开，不用猜 gid。
SPECTRUM_POINTS = int(fixture_data.NMR_N)
#: 本夹具没有外部科学输入文件：载荷由 fixture_data 用固定种子在内存里现算。
SCIENCE_INPUTS: tuple[Path, ...] = ()

#: key → (类型, 下界, 上界)。`peak_windows_ppm` 是字典型：**受保护的积分窗口**。
SCALARS = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 60.0, 160.0),
    "canvas_h_mm": (float, 50.0, 160.0),
    "render_dpi": (int, 96, 600),
    "axes_left_mm": (float, 5.0, 60.0),
    "axes_right_mm": (float, 5.0, 60.0),
    "axes_bottom_mm": (float, 5.0, 60.0),
    "axes_top_mm": (float, 5.0, 60.0),
    "axis_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "peak_font_pt": (float, *FONT_RANGE),
    "line_width": (float, 0.2, 3.0),
    "guide_lw_pt": (float, 0.2, 2.0),
    "peak_label_lift_mm": (float, 0.0, 6.0),
    "peak_windows_ppm": (dict,),
}
SCHEMA = dict(SCALARS)
SCHEMA[SHIFT_KEY] = (dict,)

PARAM_GROUPS = {
    "元数据 (Meta)": ("schema_version",),
    "画布 (Canvas)": ("canvas_w_mm", "canvas_h_mm", "render_dpi"),
    "坐标框 (Axes rect)": ("axes_left_mm", "axes_right_mm", "axes_bottom_mm", "axes_top_mm"),
    "字号与线宽 (Type)": ("axis_font_pt", "tick_font_pt", "peak_font_pt", "line_width", "guide_lw_pt"),
    "标签 (Labels)": ("peak_label_lift_mm",),
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
    "axis_font_pt": ("轴标题字号", "pt"),
    "tick_font_pt": ("刻度字号", "pt"),
    "peak_font_pt": ("归属标签字号", "pt"),
    "line_width": ("谱线线宽", "pt"),
    "guide_lw_pt": ("峰位引导线线宽", "pt"),
    "peak_label_lift_mm": ("归属标签上抬", "mm"),
    "peak_windows_ppm": ("积分窗口（受保护）", "ppm"),
}

#: 任务语料引用这些名字，测试核对"每个断言的保护项都被夹具声明过"。
SCIENCE_INVARIANTS = {
    "nmr.spectrum_arrays": "谱线绘图数组逐字节等于受保护数组（严格递减 ppm 网格，无平滑/重采样）",
    "nmr.peak_ppm_guides": "每根峰位引导线的 x 数据就是它的峰位 ppm（两端点相同）",
    "nmr.windows_unchanged": "每个峰的积分窗口（ppm）与受保护窗口一致",
    "nmr.assignments_unchanged": "归属文本一字不改",
    "nmr.view_windows": "xlim/ylim 显示的物理窗口不变",
}

#: 每个参数记录声明的"必须守住的东西"（= 上面全部不变量）。
_PRESERVE = list(SCIENCE_INVARIANTS)
#: 引导线基线：谱线的数据基线就是受保护的显示下界。
_BASELINE = float(fixture_data.NMR_YLIM[0])


# ── 配置 ────────────────────────────────────────────────────────────────────
def load_config(path: Path | str = CONFIG_PATH) -> dict:
    """引擎校验 + `peak_shifts_mm` 归一化 + 积分窗口只读校验。"""
    cfg = _engine_load_config(path, SCHEMA)
    name = Path(path).name

    declared = cfg["peak_windows_ppm"]
    if not isinstance(declared, dict):
        raise ConfigError(f"{name}：peak_windows_ppm 必须是 `峰位: [下界, 上界]` 映射")
    expected = {key: tuple(window) for key, window in zip(PEAK_KEYS, fixture_data.nmr_windows_ppm())}
    if set(declared) != set(expected):
        raise ConfigError(f"{name}：peak_windows_ppm 必须完整列出 {list(expected)}；得到 {sorted(declared)}")
    for key, value in declared.items():
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ConfigError(f"{name}：peak_windows_ppm.{key} 必须是 [下界, 上界]")
        pair = tuple(float(v) for v in value)
        if pair != expected[key]:
            # 积分窗口即受保护的科学窗口：改它 = 换了一张图在说什么，不是排版。
            raise ConfigError(
                f"{name}：peak_windows_ppm.{key} = {list(pair)} 与受保护窗口 {list(expected[key])} 不一致")
        if pair[0] >= pair[1] or not all(math.isfinite(v) for v in pair):
            raise ConfigError(f"{name}：peak_windows_ppm.{key} 不是有序有限区间")

    raw = cfg.get(SHIFT_KEY) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}：peak_shifts_mm 必须是字典映射")
    if unknown := sorted(set(raw) - set(SCOPES)):
        raise ConfigError(f"{name}：peak_shifts_mm 里有未知作用域 {unknown}；可用：{list(SCOPES)}")
    shifts: dict[str, dict[str, float]] = {scope: {key: 0.0 for key in PEAK_KEYS} for scope in SCOPES}
    for scope, per_peak in raw.items():
        if per_peak is None:
            continue
        if not isinstance(per_peak, dict):
            raise ConfigError(f"{name}：peak_shifts_mm.{scope} 必须是 `峰位: 毫米` 映射")
        if unknown := sorted(set(per_peak) - set(PEAK_KEYS)):
            raise ConfigError(f"{name}：peak_shifts_mm.{scope} 里有未知峰位 {unknown}；可用：{list(PEAK_KEYS)}")
        for key, value in per_peak.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{name}：peak_shifts_mm.{scope}.{key} 必须是数字")
            val = float(value)
            if not math.isfinite(val):
                raise ConfigError(f"{name}：peak_shifts_mm.{scope}.{key} 不能是 NaN 或 Inf")
            if abs(val) > SHIFT_LIMIT_MM:
                raise ConfigError(f"{name}：peak_shifts_mm.{scope}.{key} = {val} 超出 ±{SHIFT_LIMIT_MM} mm")
            shifts[scope][key] = val
    cfg[SHIFT_KEY] = shifts
    return cfg


def list_params(path: Path | str = CONFIG_PATH) -> None:
    """按可见对象分组的参数清单（当前值 / 单位 / 允许范围）。"""
    cfg = load_config(path)
    _native.print_param_table(cfg, SCALARS, PARAM_GROUPS, PARAM_DESC)
    print("=== 位移 (Peak shifts, mm) ===")
    for scope in SCOPES:
        print(f"  [{scope}] " + "、".join(f"{SHIFT_KEY}.{scope}.{key}={cfg[SHIFT_KEY][scope][key]:g}"
                                          for key in PEAK_KEYS))


# ── 科学载荷 ────────────────────────────────────────────────────────────────
def load_science() -> dict:
    """受保护的数据与来源声明：不建 Figure，可以被反复调用（结果一致）。"""
    x, y = fixture_data.nmr_spectrum()
    ppm = fixture_data.nmr_peak_ppm()
    heights = fixture_data.nmr_peak_heights()
    windows = fixture_data.nmr_windows_ppm()
    return {
        "spectrum": (x, y),
        "peak_ppm": {key: float(value) for key, value in zip(PEAK_KEYS, ppm)},
        "peak_heights": {key: float(value) for key, value in zip(PEAK_KEYS, heights)},
        "windows": {key: (float(lo), float(hi)) for key, (lo, hi) in zip(PEAK_KEYS, windows)},
        "assignments": dict(fixture_data.nmr_assignments()),
        "xlim": tuple(fixture_data.NMR_XLIM),
        "ylim": tuple(fixture_data.NMR_YLIM),
        "source": {
            "kind": "seeded_synthetic",
            "seed": fixture_data.SEED,
            "generator": "tests.fixtures.fixture_data.nmr_spectrum",
            "note": "no instrument file, no private data",
        },
    }


def science_manifest(science: dict) -> dict:
    """来源/处理/受保护窗口/文本的 JSONable 声明（引擎另会指纹化图的真实内容）。"""
    n_points = int(science["spectrum"][0].size)
    return {
        "science": {
            "source": science["source"],
            "processing": [
                "deterministic seeded noise, no smoothing",
                "no normalisation, no resampling, no interpolation of the plotted arrays",
                "ppm axis strictly descending as generated (8.0 -> 0.5); peak heights via interp_descending",
                "assignments are the generated strings; no relabelling",
            ],
            "protected_windows": {
                "xlim_ppm": [float(v) for v in science["xlim"]],
                "ylim_au": [float(v) for v in science["ylim"]],
                "integration_windows_ppm": {key: [float(lo), float(hi)]
                                           for key, (lo, hi) in science["windows"].items()},
            },
            "protected_text": {
                "assignments": dict(science["assignments"]),
                "axis_labels": [XLABEL, YLABEL],
            },
            "arrays": [
                {"id": "spectrum", "kind": "line", "n": n_points, "units": {"x": "ppm", "y": "a.u."},
                 "grid": "strictly descending"},
            ],
            "scale_bars": [],
            # 显式声明"没有裁切、没有拉伸"：谱线整段画在受保护 ppm 窗口里，
            # 两条轴各自线性映射到声明的毫米矩形，没有任何隐式缩放或重采样。
            "crop": {
                "spectrum": "uncropped",
                "note": "no data-unit cropping, no pixel crop, no thumbnail",
                "ppm_window": "full protected window",
            },
            "aspect": {
                "mode": "fixed_axes_rect_mm",
                "equal_data_aspect": False,
                "distorted": False,
                "note": "both axes scale 1:1 from data units to the declared mm rect; "
                        "no shared-aspect rescaling, no shear, no implicit stretch of the arrays",
            },
        },
        "nodes": {g: {"science_policy": meta["science_policy"]}
                  for g, meta in _all_policy_nodes().items()},
    }


def _span_ppm_limits(span) -> tuple[float, float]:
    """积分窗口的 x 数据范围（ppm）。

    `axvspan` 在 matplotlib 里既可能是 Polygon 也可能是 Rectangle：Polygon 的
    路径顶点已是数据坐标，Rectangle 的路径是单位矩形、靠 patch transform 定位。
    先过一遍 patch transform，两种都拿到数据坐标，也不受版本影响。
    """
    verts = np.asarray(span.get_path().vertices, float)
    data = np.asarray(span.get_patch_transform().transform(verts), float)
    return float(data[:, 0].min()), float(data[:, 0].max())


# ── 绘制 ────────────────────────────────────────────────────────────────────
def gid(scope: str, kind: str, name: str | None = None) -> str:
    """对象身份：`<figure>.<scope>.<kind>[.<name>]`。点号在 gid 里从不被拆开。"""
    return f"{FIGURE_ID}.{scope}.{kind}" + (f".{name}" if name else "")


def _axes_rect(config: dict) -> list[float]:
    """坐标框的精确位置：canvas 毫米 - 四条外边距，直接换成 figure 分数。"""
    width_mm, height_mm = config["canvas_w_mm"], config["canvas_h_mm"]
    left, right = config["axes_left_mm"], config["axes_right_mm"]
    bottom, top = config["axes_bottom_mm"], config["axes_top_mm"]
    box_w = width_mm - left - right
    box_h = height_mm - bottom - top
    if box_w <= 5.0 or box_h <= 5.0:
        raise ValueError(f"坐标框只剩 {box_w:.1f}×{box_h:.1f} mm（画布 {width_mm}×{height_mm} mm）")
    return [left / width_mm, bottom / height_mm, box_w / width_mm, box_h / height_mm]


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
    reg.register(ax, gid(scope, "axes"))

    # 积分窗口：受保护的显示窗口（先画，压在谱线下面）。
    for key in PEAK_KEYS:
        lo, hi = science["windows"][key]
        span = ax.axvspan(lo, hi, color="0.45", alpha=0.16, lw=0.0, zorder=1)
        reg.register(span, gid(scope, "peak_window", key),
                     params=["peak_windows_ppm", SHIFT_KEY])

    # 谱线：绘图数组逐字节等于受保护数组，数据坐标一个字节都不动。
    x, y = science["spectrum"]
    (line,) = ax.plot(x, y, lw=cfg["line_width"], color="C0", zorder=3)
    reg.register(line, gid(scope, "spectrum"), params=["line_width"])

    # 峰位引导线：从数据基线拉到**反序插值**算出的峰高（递减网格不做 np.interp）。
    for key in PEAK_KEYS:
        ppm = science["peak_ppm"][key]
        height = science["peak_heights"][key]
        (guide,) = ax.plot([ppm, ppm], [_BASELINE, height],
                           lw=cfg["guide_lw_pt"], color="0.35", zorder=2)
        reg.register(guide, gid(scope, "peak_guide", key), params=["guide_lw_pt", SHIFT_KEY])

    # 归属标签：数据锚点 (ppm, 峰高) + 真实毫米上抬（不许 0.1 data-unit/mm 之类的猜想）。
    for key in PEAK_KEYS:
        text = ax.text(science["peak_ppm"][key], science["peak_heights"][key],
                       science["assignments"][key], fontsize=cfg["peak_font_pt"],
                       ha="center", va="bottom", zorder=4)
        reg.register(text, gid(scope, "peak_label", key),
                     params=["peak_font_pt", "peak_label_lift_mm", SHIFT_KEY])

    # 逐峰毫米位移作用在**完整受影响集合**上：引导线 + 窗口 + 标签一起走。
    for key in PEAK_KEYS:
        shift = cfg[SHIFT_KEY][scope][key]
        apply_display_shift(reg.get(gid(scope, "peak_guide", key)), dy_mm=shift)
        apply_display_shift(reg.get(gid(scope, "peak_window", key)), dy_mm=shift)
        apply_display_shift(reg.get(gid(scope, "peak_label", key)),
                            dy_mm=shift + cfg["peak_label_lift_mm"])

    ax.set_xlabel(XLABEL, fontsize=cfg["axis_font_pt"])
    reg.register(ax.xaxis.label, gid(scope, "xlabel"), params=["axis_font_pt"])
    ax.set_ylabel(YLABEL, fontsize=cfg["axis_font_pt"])
    reg.register(ax.yaxis.label, gid(scope, "ylabel"), params=["axis_font_pt"])
    ax.tick_params(labelsize=cfg["tick_font_pt"])
    ax.set_xlim(*science["xlim"])
    ax.set_ylim(*science["ylim"])
    return fig, reg


def build_figure_and_registry(scope: str, *, config: dict | None = None):
    """旧接缝保持不变：等价于 build_scene(load_science(), config, scope)。"""
    return build_scene(load_science(), config if config is not None else load_config(), scope)


# ── 布局契约 ────────────────────────────────────────────────────────────────
def _nodes(scope: str) -> dict:
    """节点元数据：type / parent / editable / science_policy。未声明的默认锁死。"""
    root = gid(scope, "root")
    # 图元挂在实际拥有它们的坐标框下：谱线/峰位引导线/积分窗口/归属标签都是这个 Axes 的子对象。
    # 挂到 root 或语义分组上会把坐标框的父子关系抹平（Panel→后代的依赖闭包就断了）；
    # 语义分组（curves/guides/aspects/text）仍然在契约里声明为**集合**。
    own_panel = gid(scope, "axes")
    nodes: dict[str, dict] = {
        gid(scope, "canvas"): _native.node(gid(scope, "canvas"), type_name="Figure", parent=None,
                                           editable=False, science_policy="LOCKED_SCIENCE",
                                           label="画布"),
        gid(scope, "axes"): _native.node(gid(scope, "axes"), type_name="Axes", parent=root,
                                         editable=False, science_policy="LOCKED_SCIENCE",
                                         label="坐标框"),
        gid(scope, "spectrum"): _native.node(gid(scope, "spectrum"), type_name="Line2D",
                                             parent=own_panel, editable=False,
                                             science_policy="LOCKED_SCIENCE", label="谱线"),
        gid(scope, "xlabel"): _native.node(gid(scope, "xlabel"), type_name="Text",
                                            parent=own_panel,
                                            editable=False, science_policy="LOCKED_SCIENCE",
                                            label=XLABEL),
        gid(scope, "ylabel"): _native.node(gid(scope, "ylabel"), type_name="Text",
                                            parent=own_panel,
                                            editable=False, science_policy="LOCKED_SCIENCE",
                                            label=YLABEL),
    }
    for key in PEAK_KEYS:
        nodes[gid(scope, "peak_guide", key)] = _native.node(
            gid(scope, "peak_guide", key), type_name="Line2D", parent=own_panel,
            editable=False, science_policy="LOCKED_SCIENCE", label=f"峰位引导线 {key} ppm")
        nodes[gid(scope, "peak_window", key)] = _native.node(
            gid(scope, "peak_window", key), type_name="Rectangle", parent=own_panel,
            editable=False, science_policy="LOCKED_SCIENCE", label=f"积分窗口 {key} ppm")
        nodes[gid(scope, "peak_label", key)] = _native.node(
            gid(scope, "peak_label", key), type_name="Text", parent=own_panel, editable=False,
            science_policy="LOCKED_SCIENCE", label=fixture_data.nmr_assignments()[key])
    return nodes


def _all_policy_nodes() -> dict:
    """全部 scope 的 science_policy 表（science_manifest 与契约共用一份）。"""
    out: dict[str, dict] = {}
    for scope in SCOPES:
        out.update(_nodes(scope))
    return out


def layout_contract(scope: str) -> dict:
    """这张图的可控点：参数 / 节点 / 组 / 关系 / 产物。路径永远是精确段数组。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    canvas_node = gid(scope, "canvas")
    axes_node = gid(scope, "axes")
    root = gid(scope, "root")
    spectrum = gid(scope, "spectrum")
    guides = [gid(scope, "peak_guide", key) for key in PEAK_KEYS]
    windows = [gid(scope, "peak_window", key) for key in PEAK_KEYS]
    labels = [gid(scope, "peak_label", key) for key in PEAK_KEYS]
    text_nodes = labels + [gid(scope, "xlabel"), gid(scope, "ylabel")]
    keep = list(_PRESERVE)

    parameters = [
        _native.param("canvas_w_mm", ["canvas_w_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas_node], operation="rebuild", axis="x",
                      minimum=SCALARS["canvas_w_mm"][1], maximum=SCALARS["canvas_w_mm"][2],
                      expected=_native.expect("resize", objects=[canvas_node], axis="x", preserve=keep)),
        _native.param("canvas_h_mm", ["canvas_h_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas_node], operation="rebuild", axis="y",
                      minimum=SCALARS["canvas_h_mm"][1], maximum=SCALARS["canvas_h_mm"][2],
                      expected=_native.expect("resize", objects=[canvas_node], axis="y", preserve=keep)),
        _native.param("render_dpi", ["render_dpi"], unit="dpi", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas_node, axes_node], operation="rebuild",
                      axis=None, minimum=SCALARS["render_dpi"][1], maximum=SCALARS["render_dpi"][2],
                      expected=_native.expect("style", objects=[canvas_node], preserve=keep)),
    ]
    for key, axis in (("axes_left_mm", "x"), ("axes_right_mm", "x"),
                      ("axes_bottom_mm", "y"), ("axes_top_mm", "y")):
        parameters.append(_native.param(
            key, [key], unit="mm", mutability="EDITABLE", scopes=list(SCOPES),
            objects=[axes_node], operation="rebuild", axis=axis,
            minimum=SCALARS[key][1], maximum=SCALARS[key][2],
            expected=_native.expect("resize", objects=[axes_node], axis=axis, preserve=keep)))
    for key in ("axis_font_pt", "tick_font_pt", "peak_font_pt", "line_width", "guide_lw_pt"):
        if key == "axis_font_pt":
            target: list[str] = [gid(scope, "xlabel"), gid(scope, "ylabel")]
        elif key == "peak_font_pt":
            target = labels
        elif key == "line_width":
            target = [spectrum]
        elif key == "guide_lw_pt":
            target = guides
        else:
            target = []
        parameters.append(_native.param(
            key, [key], unit="pt", mutability="FIXED_STYLE", scopes=list(SCOPES),
            objects=target, operation="rebuild", axis=None,
            minimum=SCALARS[key][1], maximum=SCALARS[key][2],
            expected=_native.expect("style", objects=target, preserve=keep)))
    parameters.append(_native.param(
        "peak_label_lift_mm", ["peak_label_lift_mm"], unit="mm", mutability="EDITABLE",
        scopes=list(SCOPES), objects=labels, operation="translate", axis="y", scale=1.0,
        minimum=SCALARS["peak_label_lift_mm"][1], maximum=SCALARS["peak_label_lift_mm"][2],
        expected=_native.expect("translate", objects=labels, axis="y", preserve=keep)))
    parameters.append(_native.param(
        "peak_windows_ppm", ["peak_windows_ppm"], unit="ppm", mutability="LOCKED_SCIENCE",
        scopes=list(SCOPES), objects=windows + labels, operation="rebuild", axis=None,
        expected=_native.expect("style", objects=windows + labels,
                                preserve=["nmr.windows_unchanged", "nmr.view_windows"])))
    for key in PEAK_KEYS:
        parameters.append(_native.param(
            f"{SHIFT_KEY}.{scope}.{key}", [SHIFT_KEY, scope, key], unit="mm",
            mutability="EDITABLE", scopes=[scope],
            objects=[gid(scope, "peak_guide", key), gid(scope, "peak_window", key),
                     gid(scope, "peak_label", key)],
            operation="translate", axis="y", scale=1.0,
            minimum=-SHIFT_LIMIT_MM, maximum=SHIFT_LIMIT_MM,
            expected=_native.expect("translate",
                                    objects=[gid(scope, "peak_guide", key), gid(scope, "peak_window", key),
                                             gid(scope, "peak_label", key)],
                                    axis="y", preserve=keep)))

    relations = [
        _native.relation("nmr.contain_x", "contain", [canvas_node, axes_node], axis="x",
                         controlled_by=[["canvas_w_mm"], ["axes_left_mm"], ["axes_right_mm"]]),
        _native.relation("nmr.contain_y", "contain", [canvas_node, axes_node], axis="y",
                         controlled_by=[["canvas_h_mm"], ["axes_bottom_mm"], ["axes_top_mm"]]),
        # 外边距是**容器内缩**（坐标框在画布里），不是邻居对象的净空：
        # 嵌套包络上的 gap 只会读出重叠量（负值），锚点展幅才是真实同侧边偏移。
        _native.relation("nmr.margin_left", "align", [canvas_node, axes_node], axis="x",
                         anchor="left", controlled_by=[["axes_left_mm"]], move=[axes_node]),
        _native.relation("nmr.margin_right", "align", [canvas_node, axes_node], axis="x",
                         anchor="right", controlled_by=[["axes_right_mm"]], move=[axes_node]),
        _native.relation("nmr.margin_bottom", "align", [canvas_node, axes_node], axis="y",
                         anchor="bottom", controlled_by=[["axes_bottom_mm"]], move=[axes_node]),
        _native.relation("nmr.margin_top", "align", [canvas_node, axes_node], axis="y",
                         anchor="top", controlled_by=[["axes_top_mm"]], move=[axes_node]),
    ]
    for key in PEAK_KEYS:
        relations.append(_native.relation(
            f"nmr.peak_label_center.{key}", "align",
            [gid(scope, "peak_label", key), gid(scope, "peak_window", key)], axis="x",
            anchor="center_x", controlled_by=[["peak_windows_ppm"]]))
    for lower, upper in zip(PEAK_KEYS, PEAK_KEYS[1:]):
        relations.append(_native.relation(
            f"nmr.peak_spacing.{lower}_{upper}", "gap",
            [gid(scope, "peak_guide", lower), gid(scope, "peak_guide", upper)], axis="x",
            controlled_by=[["peak_windows_ppm"]]))

    return _native.contract_record(
        sys.modules[__name__], scope, parameters=parameters, nodes=_nodes(scope),
        groups=[
            _native.group(root, parent=None, members=[canvas_node, axes_node]),
            _native.group(gid(scope, "curves"), parent=root, members=[spectrum]),
            _native.group(gid(scope, "guides"), parent=root, members=guides),
            _native.group(gid(scope, "aspects"), parent=root, members=windows),
            _native.group(gid(scope, "text"), parent=root, members=text_nodes),
        ],
        relations=relations,
        outputs=[f"{FIGURE_ID}_{scope}.{ext}" for ext in OUTPUT_FORMATS])


# ── 科学自检（strict 会用它拒绝发布） ───────────────────────────────────────
def science_selfcheck(science: dict, fig=None) -> list[str]:
    """受保护内容的自检：谱线数组、峰位引导线、窗口、文本。返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    ref_x, ref_y = fixture_data.nmr_spectrum()
    if not np.all(np.diff(ref_x) < 0):
        problems.append("SCIENCE_PAYLOAD: ppm 网格不再严格递减")

    x, y = science["spectrum"]
    if x.shape != ref_x.shape or y.shape != x.shape:
        problems.append(f"SCIENCE_PAYLOAD: 谱线形状 {x.shape}/{y.shape} 与受保护网格 {ref_x.shape} 不符")
    else:
        if not np.array_equal(x, ref_x):
            problems.append("SCIENCE_PAYLOAD: 谱线的 ppm 网格与受保护数组不一致")
        if not np.array_equal(y, ref_y):
            problems.append("SCIENCE_PAYLOAD: 谱线的强度数组与受保护数组不一致")
    if not np.all(np.isfinite(y)):
        problems.append("SCIENCE_PAYLOAD: 谱线含 NaN/Inf")

    for key, (lo, hi) in zip(PEAK_KEYS, fixture_data.nmr_windows_ppm()):
        ppm = science["peak_ppm"][key]
        if not math.isclose(ppm, fixture_data.nmr_peak_ppm()[PEAK_KEYS.index(key)], rel_tol=0.0, abs_tol=1e-12):
            problems.append(f"SCIENCE_PAYLOAD: 峰 {key} 的 ppm 锚点变成了 {ppm}")
        want = fixture_data.interp_descending(ref_x, ref_y, ppm)
        if not math.isclose(science["peak_heights"][key], want, rel_tol=0.0, abs_tol=1e-12):
            problems.append(f"SCIENCE_PAYLOAD: 峰 {key} 的高度 {science['peak_heights'][key]} != 反序插值 {want}")
        if tuple(science["windows"][key]) != (lo, hi):
            problems.append(f"SCIENCE_WINDOW: 峰 {key} 的积分窗口变成了 {science['windows'][key]}")
        if science["assignments"][key] != fixture_data.nmr_assignments()[key]:
            problems.append(f"SCIENCE_TEXT: 峰 {key} 的归属文本被改成了 {science['assignments'][key]!r}")

    if fig is None:
        return problems

    by_gid = _native.artists_by_gid(fig)
    # 只看**这张图里真的存在**的 scope：单 scope 构建时另一个 scope 的对象本来就不在，
    # 报"少了对象"是假警报；但本 scope 内缺对象是真变化，必须报。
    scopes_here = [scope for scope in SCOPES
                   if any(name.startswith(f"{FIGURE_ID}.{scope}.") for name in by_gid)]
    for scope in scopes_here:
        line = by_gid.get(gid(scope, "spectrum"))
        if line is None:
            problems.append(f"SCIENCE_PAYLOAD: {scope} 少了谱线对象")
        elif not (np.array_equal(np.asarray(line.get_xdata(), float), x)
                  and np.array_equal(np.asarray(line.get_ydata(), float), y)):
            problems.append(f"SCIENCE_PAYLOAD: {scope} 谱线的绘图数组 != 受保护数组")
        for key in PEAK_KEYS:
            ppm = science["peak_ppm"][key]
            height = science["peak_heights"][key]
            guide = by_gid.get(gid(scope, "peak_guide", key))
            if guide is None:
                problems.append(f"SCIENCE_PAYLOAD: {scope} 少了峰位引导线 {key}")
            else:
                gx = np.asarray(guide.get_xdata(), float)
                gy = np.asarray(guide.get_ydata(), float)
                if gx.size != 2 or not np.allclose(gx, ppm, rtol=0.0, atol=1e-12):
                    problems.append(f"SCIENCE_PAYLOAD: {scope} 峰 {key} 的引导线 x 数据变成了 {tuple(float(v) for v in gx)}")
                if gy.size != 2 or not np.allclose(gy, (_BASELINE, height), rtol=0.0, atol=1e-12):
                    problems.append(f"SCIENCE_PAYLOAD: {scope} 峰 {key} 的引导线 y 数据变成了 {tuple(float(v) for v in gy)}")
            span = by_gid.get(gid(scope, "peak_window", key))
            if span is None:
                problems.append(f"SCIENCE_WINDOW: {scope} 少了积分窗口 {key}")
            else:
                got = _span_ppm_limits(span)
                if not np.allclose(got, science["windows"][key], rtol=0.0, atol=1e-12):
                    problems.append(f"SCIENCE_WINDOW: {scope} 峰 {key} 的积分窗口变成了 {got}")
            label = by_gid.get(gid(scope, "peak_label", key))
            if label is None:
                problems.append(f"SCIENCE_TEXT: {scope} 少了归属标签 {key}")
            elif label.get_text() != science["assignments"][key]:
                problems.append(f"SCIENCE_TEXT: {scope} 峰 {key} 的文本被改成了 {label.get_text()!r}")
        ax = by_gid.get(gid(scope, "axes"))
        if ax is not None:
            if not np.allclose(ax.get_xlim(), science["xlim"], rtol=0.0, atol=1e-12):
                problems.append(f"SCIENCE_WINDOW: {scope} xlim 变成了 {tuple(ax.get_xlim())}")
            if not np.allclose(ax.get_ylim(), science["ylim"], rtol=0.0, atol=1e-12):
                problems.append(f"SCIENCE_WINDOW: {scope} ylim 变成了 {tuple(ax.get_ylim())}")
            if any(image.get_visible() for image in ax.images):
                problems.append(f"SCIENCE_PIXELS: {scope} 出现了未声明的图像（本图声明不裁切/无像素载荷）")
    return problems


if __name__ == "__main__":
    raise SystemExit(_native.run(sys.modules[__name__]))
