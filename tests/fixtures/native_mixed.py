"""原生混合夹具：左边一条 FTIR 曲线（带位窗口），右边一张显微图（比例尺 + 面板字母）。

**与绘图源码无关**：这张图是什么，全部写在下面对外声明的接缝里 ——
`SCOPES / FIGURE_ID / CONFIG_PATH / SCHEMA / load_config / list_params /
load_science / build_scene / build_figure_and_registry / layout_contract /
science_manifest / science_selfcheck`。别的 agent 不用读本文件其余部分，
就能拿到"有哪些对象、哪个 YAML 路径控制它、会产生什么效果、必须守住什么"。

科学内容（受保护，显示层不许改）：
- 曲线 a 的绘图数组逐字节等于 `fixture_data.ftir_curves()[0]`（严格递减的波数网格）；
- 带位窗口（cm⁻¹）= `fixture_data.ftir_band_limits()`：受保护的**显示窗口**；
- 显微图像素 = `fixture_data.micrograph("a")`，逐字节不变（不重采样、不归一化）；
- 裁切语义：`extent=(0, field_um, field_um*H/W, 0)`，视野宽 52 µm（260 px × 0.20 µm/px）；
- 面板宽高比锁定 1.3（260×200 px 视野）：`load_config` 拒绝任何
  `image_panel_w_mm != 1.3 × panel_h_mm` 的配置——**拉伸的显微图不是排版**；
- 比例尺 = `fixture_data.SCALE_BAR_UM`（10 µm）：`bar_frac = SCALE_BAR_UM / field_um`
  由**物理语义**反推，不是拍脑袋的长度；
- 面板字母 A/B 与轴标题是受保护文本；xlim/ylim 是受保护的显示窗口。

排版（真实物理毫米，不许 0.1 data-unit/mm 之类猜出来的换算）：
两个面板的矩形由四条外边距 + `panel_h_mm` + 两个面板宽度 + `panel_gap_mm` 精确算出；
字母只在轴分数锚点 (0,1) 上叠一个 `apply_display_shift(..., dx_mm, dy_mm)`；
曲线整体抬升同样是纯毫米显示位移。数据坐标一个字节都不动。

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
from matplotlib.lines import Line2D  # noqa: E402

from figpact import GidRegistry, apply_display_shift  # noqa: E402
from figpact import load_config as _engine_load_config  # noqa: E402
from figpact.config import ConfigError  # noqa: E402
from figpact.units import MM_PER_INCH  # noqa: E402
from tests.fixtures import _native, fixture_data  # noqa: E402

# ── 对外身份 ────────────────────────────────────────────────────────────────
#: 对象身份前缀，不是配置项：gid 是外部引用认的名字，做成旋钮只会让引用悄悄失效。
FIGURE_ID = "fig_mixed_native"
#: 「一次 build_scene 调用 = 一个作用域」。`bare` 没有面板字母，`main` 有。
SCOPES = ("main", "bare")
#: 显微图面板身份（受保护：视野宽度、裁切窗口、比例尺语义都挂在这个 id 上）。
IMAGE_ID = "a"
#: 曲线身份（`fixture_data.ftir_curves()` 的第 0 条）。
CURVE_ID = "a"
BAND_IDS = tuple(fixture_data.ftir_band_limits())
CONFIG_PATH = Path(__file__).with_name("native_mixed.yaml")

XLABEL = "Wavenumber (cm$^{-1}$)"
YLABEL = "Transmittance (a.u.)"
#: 面板字母：受保护文本（改字 = 改了这张图在说什么）。
LETTER_TEXT = {"curve": "A", "image": "B"}
PANEL_IDS = ("curve", "image")

FONT_RANGE = (3.0, 12.0)
#: 曲线纯显示位移上限（mm）：再多就被坐标框裁掉，那是 QA 阻断。
LIFT_LIMIT_MM = 4.0
#: 受保护曲线的采样点数（严格递减波数网格）。
CURVE_POINTS = int(fixture_data.FTIR_N)
#: 调用方/任务语料用的稳定句柄：曲线毫米位移键、面板净空键。
CURVE_LIFT_KEY = "curve_lift_mm"
PANEL_GAP_KEY = "panel_gap_mm"
#: 字母内缩上限（mm）：再多就压到曲线上了（TEXT_ON_DATA）。
INSET_LIMIT_MM = 5.0
#: 比例尺在图像面板里的轴分数位置（装饰性引导，不是测量结果）。
BAR_X_FRAC = 0.05
BAR_Y_FRAC = 0.08
#: `--strict` 每个 scope 必须产出的格式（共享契约：PNG/PDF/SVG/TIFF）。
OUTPUT_FORMATS = ("png", "pdf", "svg", "tiff")
#: 本夹具没有外部科学输入文件：载荷由 `fixture_data` 用固定种子在内存里现算。
#: 显式声明为空，别让输入修订号去猜".png/.json 到底算输入还是产物"。
SCIENCE_INPUTS: tuple[Path, ...] = ()


def science_inputs() -> tuple[Path, ...]:
    """声明的科学输入文件（绝对路径）。生成式夹具返回空元组——没有输入文件，
    来源是种子 + 生成函数；有外部输入的适配器必须在这里逐条列出真实文件。"""
    return SCIENCE_INPUTS

#: key → (类型, 下界, 上界)。数字型标量：所有长度都是**物理毫米**。
SCALARS = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 146.0, 220.0),
    "canvas_h_mm": (float, 64.0, 120.0),
    "render_dpi": (int, 96, 600),
    "margin_left_mm": (float, 5.0, 24.0),
    "margin_bottom_mm": (float, 5.0, 19.0),
    "margin_top_mm": (float, 3.0, 40.0),
    "margin_right_mm": (float, 3.0, 40.0),
    "panel_h_mm": (float, 10.0, 90.0),
    "curve_panel_w_mm": (float, 10.0, 62.0),
    "image_panel_w_mm": (float, 13.0, 117.0),
    "panel_gap_mm": (float, 0.0, 12.0),
    "axis_font_pt": (float, *FONT_RANGE),
    "tick_font_pt": (float, *FONT_RANGE),
    "letter_font_pt": (float, *FONT_RANGE),
    "line_width": (float, 0.2, 3.0),
    "scale_bar_lw_pt": (float, 0.2, 4.0),
    "letter_inset_x_mm": (float, 0.0, INSET_LIMIT_MM),
    "letter_inset_y_mm": (float, 0.0, INSET_LIMIT_MM),
    "curve_lift_mm": (float, -LIFT_LIMIT_MM, LIFT_LIMIT_MM),
    # 下面三个是受保护的科学宣称：改它 = 换了一张图在说什么。
    "image_field_width_um": (float, 1.0, 1000.0),
    "scale_bar_um": (float, 0.1, 100.0),
    "panel_aspect": (float, 0.1, 10.0),
}
SCHEMA = dict(SCALARS)

PARAM_GROUPS = {
    "元数据 (Meta)": ("schema_version",),
    "画布 (Canvas)": ("canvas_w_mm", "canvas_h_mm", "render_dpi"),
    "边距与面板 (Layout)": ("margin_left_mm", "margin_bottom_mm", "margin_top_mm",
                            "margin_right_mm", "panel_h_mm", "curve_panel_w_mm",
                            "image_panel_w_mm", "panel_gap_mm"),
    "字号与线宽 (Type)": ("axis_font_pt", "tick_font_pt", "letter_font_pt", "line_width",
                          "scale_bar_lw_pt"),
    "字母与曲线位移 (Display shifts)": ("letter_inset_x_mm", "letter_inset_y_mm",
                                       "curve_lift_mm"),
    "受保护语义 (Locked)": ("image_field_width_um", "scale_bar_um", "panel_aspect"),
}
PARAM_DESC = {
    "schema_version": ("配置契约版本", "—"),
    "canvas_w_mm": ("画布物理宽度", "mm"),
    "canvas_h_mm": ("画布物理高度", "mm"),
    "render_dpi": ("渲染分辨率", "dpi"),
    "margin_left_mm": ("面板带左边距（面板贴它排布）", "mm"),
    "margin_bottom_mm": ("面板带下边距（面板贴它排布）", "mm"),
    "margin_top_mm": ("顶部预留带（containment 用，不移动面板）", "mm"),
    "margin_right_mm": ("右侧预留带（containment 用，不移动面板）", "mm"),
    "panel_h_mm": ("两个面板共用的高度（受纵横比约束）", "mm"),
    "curve_panel_w_mm": ("曲线面板宽度", "mm"),
    "image_panel_w_mm": ("图像面板宽度 = panel_h_mm × panel_aspect", "mm"),
    "panel_gap_mm": ("两个面板之间的净空", "mm"),
    "axis_font_pt": ("轴标题字号", "pt"),
    "tick_font_pt": ("刻度字号", "pt"),
    "letter_font_pt": ("面板字母字号", "pt"),
    "line_width": ("谱线线宽", "pt"),
    "scale_bar_lw_pt": ("比例尺线宽", "pt"),
    "letter_inset_x_mm": ("字母距面板左边框", "mm"),
    "letter_inset_y_mm": ("字母距面板上边框（正数 = 向内）", "mm"),
    "curve_lift_mm": ("曲线整体抬升（纯显示位移）", "mm"),
    "image_field_width_um": ("显微图视野物理宽度（受保护）", "µm"),
    "scale_bar_um": ("比例尺代表的物理长度（受保护）", "µm"),
    "panel_aspect": ("视野宽高比（受保护，禁止拉伸）", "—"),
}

#: 任务语料引用这些名字，测试核对"每个断言的保护项都被夹具声明过"。
SCIENCE_INVARIANTS = {
    "mixed.curve_arrays": "曲线 a 的绘图数组逐字节等于受保护数组（严格递减波数网格）",
    "mixed.view_windows": "xlim/ylim 与带位窗口（cm⁻¹）显示窗口不变",
    "mixed.image_pixels": "显微图像素逐字节等于受保护数组（不重采样、不归一化）",
    "mixed.image_crop": "显微图 extent = (0, field_um, field_um*H/W, 0)，视野宽 52 µm",
    "mixed.scale_bar_meaning": "比例尺渲染长度 = SCALE_BAR_UM / field_um × 面板宽度",
    "mixed.panel_gap_order": "两个面板左曲线右图像、同一高度带、间隔 = panel_gap_mm",
}


# ── 配置 ────────────────────────────────────────────────────────────────────
def load_config(path: Path | str = CONFIG_PATH) -> dict:
    """引擎校验 + 视野/比例尺/纵横比只读校验 + 面板装得下的校验。"""
    cfg = _engine_load_config(path, SCHEMA)
    name = Path(path).name

    field_um = float(cfg["image_field_width_um"])
    expected_field = float(fixture_data.panel_field_width_um(IMAGE_ID))
    if not math.isclose(field_um, expected_field, rel_tol=0.0, abs_tol=1e-9):
        # 视野宽度就是裁切语义：改它 = 显微图在说另一个视场。
        raise ConfigError(f"{name}：image_field_width_um = {field_um} 与受保护视野宽度 "
                          f"{expected_field} µm 不一致")

    bar_um = float(cfg["scale_bar_um"])
    if not math.isclose(bar_um, float(fixture_data.SCALE_BAR_UM), rel_tol=0.0, abs_tol=1e-9):
        raise ConfigError(f"{name}：scale_bar_um = {bar_um} 与受保护比例尺 "
                          f"{fixture_data.SCALE_BAR_UM} µm 不一致")

    aspect = float(cfg["panel_aspect"])
    expected_aspect = (float(fixture_data.PANEL_SHAPE[1]) / float(fixture_data.PANEL_SHAPE[0]))
    if not math.isclose(aspect, expected_aspect, rel_tol=0.0, abs_tol=1e-9):
        raise ConfigError(f"{name}：panel_aspect = {aspect} 与视野像素 "
                          f"{fixture_data.PANEL_SHAPE[1]}×{fixture_data.PANEL_SHAPE[0]} 的纵横比 "
                          f"{expected_aspect} 不一致")

    panel_h = float(cfg["panel_h_mm"])
    panel_w = float(cfg["image_panel_w_mm"])
    if abs(panel_w - aspect * panel_h) > 1e-9:
        # 面板框的宽高比必须等于视野纵横比：否则 imshow 会把显微图拉伸。
        raise ConfigError(f"{name}：image_panel_w_mm = {panel_w} 与面板高 {panel_h} × "
                          f"视野纵横比 {aspect} = {aspect * panel_h} 不一致："
                          "显微图会被拉伸，拒绝构建")

    need_w = (float(cfg["margin_left_mm"]) + float(cfg["curve_panel_w_mm"])
              + float(cfg["panel_gap_mm"]) + panel_w + float(cfg["margin_right_mm"]))
    if need_w > float(cfg["canvas_w_mm"]) + 1e-9:
        raise ConfigError(f"{name}：面板带 + 两个预留带共 {need_w} mm，超出画布宽度 "
                          f"{cfg['canvas_w_mm']} mm；contain 关系不可能成立")
    need_h = float(cfg["margin_bottom_mm"]) + panel_h + float(cfg["margin_top_mm"])
    if need_h > float(cfg["canvas_h_mm"]) + 1e-9:
        raise ConfigError(f"{name}：面板带 + 两个预留带共 {need_h} mm，超出画布高度 "
                          f"{cfg['canvas_h_mm']} mm；contain 关系不可能成立")
    return cfg


def list_params(path: Path | str = CONFIG_PATH) -> None:
    """按可见对象分组的参数清单（当前值 / 单位 / 允许范围）。"""
    cfg = load_config(path)
    _native.print_param_table(cfg, SCALARS, PARAM_GROUPS, PARAM_DESC)


# ── 科学载荷 ────────────────────────────────────────────────────────────────
def load_science() -> dict:
    """受保护的数据与来源声明：不建 Figure，可以被反复调用（结果一致）。"""
    shape = tuple(int(v) for v in fixture_data.PANEL_SHAPE)
    field_um = float(fixture_data.panel_field_width_um(IMAGE_ID))
    return {
        "curve": fixture_data.ftir_curves()[0],
        "bands": fixture_data.ftir_band_limits(),
        "micrograph": fixture_data.micrograph(IMAGE_ID),
        "field_shape": shape,
        "field_width_um": field_um,
        "scale_bar_um": float(fixture_data.SCALE_BAR_UM),
        "panel_aspect": float(shape[1]) / float(shape[0]),
        "xlim": tuple(fixture_data.FTIR_XLIM),
        "ylim": tuple(fixture_data.FTIR_YLIM),
        "source": {
            "kind": "seeded_synthetic",
            "seed": fixture_data.SEED,
            "generator": "tests.fixtures.fixture_data.ftir_curves + micrograph",
            "note": "no instrument file, no private data",
        },
    }


def science_manifest(science: dict) -> dict:
    """来源/处理/受保护窗口/裁切/比例尺语义的 JSONable 声明（引擎另会指纹化真实内容）。"""
    shape = science["field_shape"]
    field_um = science["field_width_um"]
    field_h_um = field_um * shape[0] / shape[1]
    return {
        "science": {
            "source": science["source"],
            "processing": [
                "deterministic seeded payload, no smoothing",
                "no normalisation, no resampling of the plotted curve or the image pixels",
                "image drawn with interpolation='nearest' at the declared extent",
                "no unit conversion: the panel frame carries the field 1 µm ↔ "
                "image_panel_w_mm / field_width_um mm",
            ],
            "protected_windows": {
                "xlim_cm1": list(science["xlim"]),
                "ylim_au": list(science["ylim"]),
                "band_limits_cm1": {bid: list(pair) for bid, pair in science["bands"].items()},
            },
            "crop": {
                "panel": IMAGE_ID,
                "field_width_um": field_um,
                "field_height_um": field_h_um,
                "extent_um": [0.0, field_um, field_h_um, 0.0],
                "pixels": list(shape),
                "interpolation": "nearest",
                "resampling": "none",
            },
            "aspect": {
                "declared": science["panel_aspect"],
                "field_pixels": [shape[1], shape[0]],
                "no_stretch": True,
            },
            "scale_bars": [{
                "id": "scale_bar",
                "um": science["scale_bar_um"],
                "field_width_um": field_um,
                "bar_frac": science["scale_bar_um"] / field_um,
                "meaning": "bar length in field units, no invented mm/data-unit factor",
            }],
            "protected_text": {
                "letters": dict(LETTER_TEXT),
                "axis_titles": [XLABEL, YLABEL],
            },
            "arrays": [
                {"id": f"ftir.{CURVE_ID}", "kind": "curve", "n": int(science["curve"][0].size),
                 "units": {"x": "cm-1", "y": "a.u."}, "grid": "strictly descending"},
                {"id": f"micrograph.{IMAGE_ID}", "kind": "image", "shape": list(shape),
                 "dtype": str(science["micrograph"].dtype),
                 "units": {"x": "um", "y": "um"}},
            ],
        },
        "nodes": {g: {"science_policy": meta["science_policy"]}
                  for g, meta in _all_policy_nodes().items()},
    }


# ── 绘制 ────────────────────────────────────────────────────────────────────
def gid(scope: str, kind: str, name: str | None = None) -> str:
    """对象身份：`<figure>.<scope>.<kind>[.<name>]`。点号在 gid 里从不被拆开。"""
    return f"{FIGURE_ID}.{scope}.{kind}" + (f".{name}" if name else "")


def _panel_rects_mm(config: dict) -> dict[str, list[float]]:
    """两个面板的精确毫米矩形：[x0, y0, w, h]，坐标原点在画布左下。"""
    curve_w = float(config["curve_panel_w_mm"])
    x0 = float(config["margin_left_mm"])
    gap = float(config["panel_gap_mm"])
    y0 = float(config["margin_bottom_mm"])
    panel_h = float(config["panel_h_mm"])
    return {
        "curve": [x0, y0, curve_w, panel_h],
        "image": [x0 + curve_w + gap, y0, float(config["image_panel_w_mm"]), panel_h],
    }


def _panel_rects(config: dict) -> dict[str, list[float]]:
    """同一组矩形换成 figure 分数（matplotlib 要的是分数）。"""
    w_mm, h_mm = float(config["canvas_w_mm"]), float(config["canvas_h_mm"])
    return {panel: [x0 / w_mm, y0 / h_mm, bw / w_mm, bh / h_mm]
            for panel, (x0, y0, bw, bh) in _panel_rects_mm(config).items()}


def build_scene(science: dict, config: dict, scope: str):
    """确定性构建：基线布局完全由 config 决定；(Figure, GidRegistry)。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    cfg = config

    fig = plt.figure(figsize=(cfg["canvas_w_mm"] / MM_PER_INCH, cfg["canvas_h_mm"] / MM_PER_INCH),
                     dpi=float(cfg["render_dpi"]))
    rects = _panel_rects(cfg)
    ax_c = fig.add_axes(rects["curve"])
    ax_i = fig.add_axes(rects["image"])
    reg = GidRegistry()
    reg.register(fig.patch, gid(scope, "canvas"))
    reg.register(ax_c, gid(scope, "curve_panel"),
                 params=["canvas_w_mm", "canvas_h_mm", "margin_left_mm", "margin_bottom_mm",
                         "curve_panel_w_mm", "panel_h_mm"])
    reg.register(ax_i, gid(scope, "image_panel"),
                 params=["panel_gap_mm", "image_panel_w_mm", "panel_h_mm",
                         "margin_left_mm", "margin_bottom_mm"])

    # 带位窗口：受保护的显示窗口（先画，压在曲线下面）。
    for bid, (lo, hi) in science["bands"].items():
        span = ax_c.axvspan(lo, hi, color="0.45", alpha=0.16, lw=0.0, zorder=1)
        reg.register(span, gid(scope, "band", bid))

    # 曲线：绘图数组逐字节等于受保护数组；抬升是**纯毫米显示位移**。
    x, y = science["curve"]
    (line,) = ax_c.plot(x, y, lw=cfg["line_width"], color="C0", zorder=3)
    reg.register(line, gid(scope, "curve", CURVE_ID), params=["line_width", "curve_lift_mm"])
    apply_display_shift(line, dy_mm=cfg["curve_lift_mm"])

    ax_c.set_xlabel(XLABEL, fontsize=cfg["axis_font_pt"])
    reg.register(ax_c.xaxis.label, gid(scope, "xlabel"), params=["axis_font_pt"])
    ax_c.set_ylabel(YLABEL, fontsize=cfg["axis_font_pt"])
    reg.register(ax_c.yaxis.label, gid(scope, "ylabel"), params=["axis_font_pt"])
    ax_c.tick_params(labelsize=cfg["tick_font_pt"])
    ax_c.set_xlim(*science["xlim"])
    ax_c.set_ylim(*science["ylim"])

    # 显微图：extent 就是**裁切语义**；aspect="auto" + 锁死的面板框宽高比 = 不拉伸。
    height, width = science["field_shape"][0], science["field_shape"][1]
    field_um = science["field_width_um"]
    extent = (0.0, field_um, field_um * height / width, 0.0)
    image = ax_i.imshow(science["micrograph"], extent=extent, interpolation="nearest",
                        aspect="auto")
    reg.register(image, gid(scope, "image"), params=["image_field_width_um", "panel_aspect"])
    ax_i.set_axis_off()
    ax_i.set_xticks(())
    ax_i.set_yticks(())

    # 比例尺：轴分数坐标里的装饰性引导（science_policy = LAYOUT），长度由 µm 语义反推。
    bar_frac = science["scale_bar_um"] / field_um
    bar = Line2D([BAR_X_FRAC, BAR_X_FRAC + bar_frac], [BAR_Y_FRAC, BAR_Y_FRAC],
                 transform=ax_i.transAxes, lw=cfg["scale_bar_lw_pt"], color="k",
                 solid_capstyle="butt", zorder=5)
    ax_i.add_line(bar)
    reg.register(bar, gid(scope, "scale_bar"), params=["scale_bar_lw_pt", "scale_bar_um"])

    # 面板字母：轴分数锚点 (0,1) + 真实毫米内缩。只有 main 有字母。
    if scope == "main":
        for panel, ax in (("curve", ax_c), ("image", ax_i)):
            letter = ax.text(0.0, 1.0, LETTER_TEXT[panel], transform=ax.transAxes,
                             fontsize=cfg["letter_font_pt"], ha="left", va="top", zorder=6)
            reg.register(letter, gid(scope, "letter", panel),
                         params=["letter_font_pt", "letter_inset_x_mm", "letter_inset_y_mm"])
            apply_display_shift(letter, dx_mm=cfg["letter_inset_x_mm"],
                                dy_mm=-cfg["letter_inset_y_mm"])
    return fig, reg


def build_figure_and_registry(scope: str, *, config: dict | None = None):
    """旧接缝保持不变：等价于 build_scene(load_science(), config, scope)。"""
    return build_scene(load_science(), config if config is not None else load_config(), scope)


# ── 布局契约 ────────────────────────────────────────────────────────────────
def _image_set(scope: str) -> list[str]:
    """图像面板的**完整受影响集合**：面板框 + 图像 + 比例尺（main 还有字母）。

    `panel_gap_mm` 声明成纯位移，必须作用在这个完整集合上——少一个对象，
    "移动右面板是一次刚体显示位移"这句话就不成立了。
    """
    members = [gid(scope, "image_panel"), gid(scope, "image"), gid(scope, "scale_bar")]
    if scope == "main":
        members.append(gid(scope, "letter", "image"))
    return members


def _nodes(scope: str) -> dict:
    """节点元数据：type / parent / editable / science_policy。未声明的默认锁死。"""
    root = gid(scope, "root")
    # 图元挂在**真正拥有它们的面板**下：图像/比例尺/字母属于图像面板，
    # 曲线/带位/轴标题/字母属于曲线面板。挂到 root 会把 Panel→后代的依赖闭包抹平。
    cur_panel = gid(scope, "curve_panel")
    img_panel = gid(scope, "image_panel")
    nodes: dict[str, dict] = {
        gid(scope, "canvas"): _native.node(gid(scope, "canvas"), type_name="Figure", parent=None,
                                           editable=True, science_policy="LOCKED_SCIENCE",
                                           label="画布"),
        gid(scope, "curve_panel"): _native.node(
            gid(scope, "curve_panel"), type_name="Axes", parent=root, editable=True,
            science_policy="LOCKED_SCIENCE", label="曲线面板（FTIR）"),
        gid(scope, "image_panel"): _native.node(
            gid(scope, "image_panel"), type_name="Axes", parent=root, editable=True,
            science_policy="LOCKED_SCIENCE", label="显微图面板"),
        gid(scope, "image"): _native.node(
            gid(scope, "image"), type_name="AxesImage", parent=img_panel, editable=False,
            science_policy="LOCKED_SCIENCE", label=f"显微图像素 {IMAGE_ID}"),
        gid(scope, "scale_bar"): _native.node(
            gid(scope, "scale_bar"), type_name="Line2D", parent=img_panel, editable=False,
            science_policy="LAYOUT", label=f"比例尺 {fixture_data.SCALE_BAR_UM:g} µm"),
        gid(scope, "curve", CURVE_ID): _native.node(
            gid(scope, "curve", CURVE_ID), type_name="Line2D", parent=cur_panel, editable=True,
            science_policy="LOCKED_SCIENCE", label=f"曲线 {CURVE_ID}"),
        gid(scope, "xlabel"): _native.node(gid(scope, "xlabel"), type_name="Text",
                                            parent=cur_panel,
                                            editable=False, science_policy="LOCKED_SCIENCE",
                                            label=XLABEL),
        gid(scope, "ylabel"): _native.node(gid(scope, "ylabel"), type_name="Text",
                                            parent=cur_panel,
                                            editable=False, science_policy="LOCKED_SCIENCE",
                                            label=YLABEL),
    }
    for bid in BAND_IDS:
        nodes[gid(scope, "band", bid)] = _native.node(
            gid(scope, "band", bid), type_name="Rectangle", parent=cur_panel, editable=False,
            science_policy="LOCKED_SCIENCE", label=f"带位窗口 {bid}")
    if scope == "main":
        for panel, host in (("curve", cur_panel), ("image", img_panel)):
            nodes[gid(scope, "letter", panel)] = _native.node(
                gid(scope, "letter", panel), type_name="Text", parent=host, editable=True,
                science_policy="LOCKED_SCIENCE", label=f"面板字母 {LETTER_TEXT[panel]}")
    return nodes


def _all_policy_nodes() -> dict:
    """全部 scope 的 science_policy 表（science_manifest 与契约共用一份）。"""
    out: dict[str, dict] = {}
    for scope in SCOPES:
        out.update(_nodes(scope))
    return out


def _parameters(scope: str) -> list[dict]:
    """参数记录。EDITABLE 的都是**真有效果**的：改一个 mark，动的是它自己声明的对象。"""
    cur_panel = gid(scope, "curve_panel")
    img_panel = gid(scope, "image_panel")
    canvas = gid(scope, "canvas")
    curve = gid(scope, "curve", CURVE_ID)
    scale_bar = gid(scope, "scale_bar")
    image = gid(scope, "image")
    xlabel, ylabel = gid(scope, "xlabel"), gid(scope, "ylabel")
    panels = [cur_panel, img_panel]
    image_set = _image_set(scope)
    letters = [gid(scope, "letter", panel) for panel in PANEL_IDS] if scope == "main" else []
    keep = ["mixed.curve_arrays", "mixed.view_windows", "mixed.image_pixels",
            "mixed.image_crop", "mixed.scale_bar_meaning"]

    parameters = [
        # 画布尺寸的**完整受影响集合 = 只有画布**：两个面板的 mm 矩形是画布毫米里的
        # 绝对量（margin_left + 面板宽 + gap…），画布变大只是多出空白，面板不动。
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
        # 保持本图原有只读渲染条件；测量记录真实 DPI，不新增编辑旋钮。
        _native.param("render_dpi", ["render_dpi"], unit="dpi", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis=None,
                      minimum=SCALARS["render_dpi"][1], maximum=SCALARS["render_dpi"][2],
                      expected=_native.expect("style", objects=[canvas], preserve=keep)),
        # 左/下边距是面板带的**锚点**：改它两个面板整体平移（dx/dy = ±Δ、尺寸不变），
        # 方向就是旋钮方向 → 纯显示位移 scale = +1；面板后代跟着走属于闭包。
        _native.param("margin_left_mm", ["margin_left_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=panels, operation="translate", axis="x", scale=1.0,
                      minimum=SCALARS["margin_left_mm"][1], maximum=SCALARS["margin_left_mm"][2],
                      expected=_native.expect("translate", objects=panels, axis="x", preserve=keep)),
        _native.param("margin_bottom_mm", ["margin_bottom_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=panels, operation="translate", axis="y", scale=1.0,
                      minimum=SCALARS["margin_bottom_mm"][1],
                      maximum=SCALARS["margin_bottom_mm"][2],
                      expected=_native.expect("translate", objects=panels, axis="y",
                                              preserve=keep)),
        # 上/右两条预留带是**只读校验闸**：面板贴左边距/下边距排布，改它们不会移动任何
        # 面板，只参与"面板带 + 预留带装不装得下画布"的校验 —— 用 FIXED_STYLE 表示
        # "只读、不动几何"，不是几何旋钮、也不是派生量。
        _native.param("margin_top_mm", ["margin_top_mm"], unit="mm", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=[canvas], operation="resize", axis="y",
                      minimum=SCALARS["margin_top_mm"][1], maximum=SCALARS["margin_top_mm"][2],
                      expected=_native.expect("resize", objects=[canvas], axis="y",
                                              preserve=keep)),
        _native.param("margin_right_mm", ["margin_right_mm"], unit="mm", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=[canvas], operation="resize", axis="x",
                      minimum=SCALARS["margin_right_mm"][1],
                      maximum=SCALARS["margin_right_mm"][2],
                      expected=_native.expect("resize", objects=[canvas], axis="x",
                                              preserve=keep)),
        # 面板高度与两个面板的宽度都是**受纵横比约束的派生量**：单独改一个就会被
        # load_config 拒绝（显微图不许被拉伸），所以它们不是可编辑旋钮。
        _native.param("panel_h_mm", ["panel_h_mm"], unit="mm", mutability="DERIVED",
                      scopes=list(SCOPES), objects=panels, operation="resize", axis="y",
                      minimum=SCALARS["panel_h_mm"][1], maximum=SCALARS["panel_h_mm"][2],
                      expected=_native.expect("resize", objects=panels, axis="y",
                                              preserve=keep + ["mixed.panel_gap_order"])),
        # 曲线面板宽度：受影响的完整集合是**两个面板**（两个面板是相邻的：曲线面板变宽
        # Δ，图像面板整体右移 Δ，它自己的宽度不变），但**主目标是曲线面板**——
        # 量级核对只落在主目标上（图像面板是被推着走的邻居，不是尺寸变化的被控对象）。
        _native.param("curve_panel_w_mm", ["curve_panel_w_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=panels, operation="rebuild", axis="x",
                      minimum=SCALARS["curve_panel_w_mm"][1],
                      maximum=SCALARS["curve_panel_w_mm"][2],
                      expected=_native.expect("resize", objects=[cur_panel], axis="x",
                                              preserve=keep)),
        _native.param("image_panel_w_mm", ["image_panel_w_mm"], unit="mm", mutability="DERIVED",
                      scopes=list(SCOPES), objects=[img_panel, image, scale_bar],
                      operation="resize", axis="x", minimum=SCALARS["image_panel_w_mm"][1],
                      maximum=SCALARS["image_panel_w_mm"][2],
                      expected=_native.expect("resize", objects=[img_panel], axis="x",
                                              preserve=keep + ["mixed.image_crop"])),
        _native.param("panel_gap_mm", ["panel_gap_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=image_set, operation="translate", axis="x",
                      scale=1.0, minimum=SCALARS["panel_gap_mm"][1],
                      maximum=SCALARS["panel_gap_mm"][2],
                      expected=_native.expect("translate", objects=image_set, axis="x",
                                              preserve=keep + ["mixed.panel_gap_order"])),
        _native.param("curve_lift_mm", ["curve_lift_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[curve], operation="translate", axis="y",
                      scale=1.0, minimum=SCALARS["curve_lift_mm"][1],
                      maximum=SCALARS["curve_lift_mm"][2],
                      expected=_native.expect("translate", objects=[curve], axis="y",
                                              preserve=keep)),
        _native.param("axis_font_pt", ["axis_font_pt"], unit="pt", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=[xlabel, ylabel], operation="rebuild",
                      axis=None, minimum=SCALARS["axis_font_pt"][1],
                      maximum=SCALARS["axis_font_pt"][2],
                      expected=_native.expect("style", objects=[xlabel, ylabel], preserve=keep)),
        _native.param("tick_font_pt", ["tick_font_pt"], unit="pt", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=[], operation="rebuild", axis=None,
                      minimum=SCALARS["tick_font_pt"][1], maximum=SCALARS["tick_font_pt"][2],
                      expected=_native.expect("style", objects=[], preserve=keep)),
        _native.param("letter_font_pt", ["letter_font_pt"], unit="pt", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=letters, operation="rebuild", axis=None,
                      minimum=SCALARS["letter_font_pt"][1],
                      maximum=SCALARS["letter_font_pt"][2],
                      expected=_native.expect("style", objects=letters, preserve=keep)),
        _native.param("line_width", ["line_width"], unit="pt", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=[curve], operation="rebuild", axis=None,
                      minimum=SCALARS["line_width"][1], maximum=SCALARS["line_width"][2],
                      expected=_native.expect("style", objects=[curve], preserve=keep)),
        _native.param("scale_bar_lw_pt", ["scale_bar_lw_pt"], unit="pt", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=[scale_bar], operation="rebuild", axis=None,
                      minimum=SCALARS["scale_bar_lw_pt"][1],
                      maximum=SCALARS["scale_bar_lw_pt"][2],
                      expected=_native.expect("style", objects=[scale_bar], preserve=keep)),
        _native.param("image_field_width_um", ["image_field_width_um"], unit="µm",
                      mutability="LOCKED_SCIENCE", scopes=list(SCOPES),
                      objects=[image, img_panel], operation="rebuild", axis=None,
                      minimum=SCALARS["image_field_width_um"][1],
                      maximum=SCALARS["image_field_width_um"][2],
                      expected=_native.expect("style", objects=[image, img_panel],
                                              preserve=["mixed.image_crop",
                                                        "mixed.scale_bar_meaning"])),
        _native.param("scale_bar_um", ["scale_bar_um"], unit="µm", mutability="LOCKED_SCIENCE",
                      scopes=list(SCOPES), objects=[scale_bar], operation="rebuild", axis=None,
                      minimum=SCALARS["scale_bar_um"][1], maximum=SCALARS["scale_bar_um"][2],
                      expected=_native.expect("style", objects=[scale_bar],
                                              preserve=["mixed.scale_bar_meaning"])),
        _native.param("panel_aspect", ["panel_aspect"], unit="—", mutability="LOCKED_SCIENCE",
                      scopes=list(SCOPES), objects=[img_panel, image], operation="rebuild",
                      axis=None, minimum=SCALARS["panel_aspect"][1],
                      maximum=SCALARS["panel_aspect"][2],
                      expected=_native.expect("style", objects=[img_panel, image],
                                              preserve=["mixed.image_crop"])),
    ]
    if scope == "main":
        parameters.append(_native.param(
            "letter_inset_x_mm", ["letter_inset_x_mm"], unit="mm", mutability="EDITABLE",
            scopes=["main"], objects=letters, operation="translate", axis="x", scale=1.0,
            minimum=SCALARS["letter_inset_x_mm"][1],
            maximum=SCALARS["letter_inset_x_mm"][2],
            expected=_native.expect("translate", objects=letters, axis="x", preserve=keep)))
        parameters.append(_native.param(
            # 内缩是"从面板上边框往下量"：旋钮加 1 mm，字母在画面上往下走 1 mm，
            # 所以 scale = -1（声明里写清楚方向，别让调用方去猜）。
            "letter_inset_y_mm", ["letter_inset_y_mm"], unit="mm", mutability="EDITABLE",
            scopes=["main"], objects=letters, operation="translate", axis="y", scale=-1.0,
            minimum=SCALARS["letter_inset_y_mm"][1],
            maximum=SCALARS["letter_inset_y_mm"][2],
            expected=_native.expect("translate", objects=letters, axis="y", preserve=keep)))
    return parameters


def _relations(scope: str) -> list[dict]:
    canvas = gid(scope, "canvas")
    cur_panel = gid(scope, "curve_panel")
    img_panel = gid(scope, "image_panel")
    panels = [cur_panel, img_panel]
    image_set = _image_set(scope)
    relations = [
        _native.relation("mixed.contain_x", "contain", [canvas, *panels], axis="x",
                         controlled_by=[["canvas_w_mm"], ["margin_left_mm"], ["margin_right_mm"],
                                        ["curve_panel_w_mm"], ["image_panel_w_mm"],
                                        ["panel_gap_mm"]]),
        _native.relation("mixed.contain_y", "contain", [canvas, *panels], axis="y",
                         controlled_by=[["canvas_h_mm"], ["margin_bottom_mm"], ["margin_top_mm"],
                                        ["panel_h_mm"]]),
        _native.relation("mixed.panel_gap", "gap", panels, axis="x",
                         controlled_by=[["panel_gap_mm"]], move=image_set),
        _native.relation("mixed.panels_align_y", "align", panels, axis="y", anchor="center_y",
                         controlled_by=[["panel_h_mm"]]),
    ]
    if scope == "main":
        for panel, host in (("curve", cur_panel), ("image", img_panel)):
            letter = gid(scope, "letter", panel)
            # 字母在面板**里面**：x 向左内缩量要用同侧锚点展幅量，不是包络间隙
            # （嵌套包络的 gap 只会读出重叠量，负值）。
            relations.append(_native.relation(
                f"mixed.letter_gap.{panel}", "align", [letter, host], axis="x", anchor="left",
                controlled_by=[["letter_inset_x_mm"]], move=[letter]))
            relations.append(_native.relation(
                f"mixed.letter_align.{panel}", "align", [letter, host], axis="y", anchor="top",
                controlled_by=[["letter_inset_y_mm"]], move=[letter]))
    return relations


def layout_contract(scope: str) -> dict:
    """这张图的可控点：参数 / 节点 / 组 / 关系 / 产物。路径永远是精确段数组。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    root = gid(scope, "root")
    canvas = gid(scope, "canvas")
    cur_panel = gid(scope, "curve_panel")
    img_panel = gid(scope, "image_panel")
    bands = [gid(scope, "band", bid) for bid in BAND_IDS]
    letters = [gid(scope, "letter", panel) for panel in PANEL_IDS] if scope == "main" else []
    text = [gid(scope, "xlabel"), gid(scope, "ylabel"), *letters]
    return _native.contract_record(
        sys.modules[__name__], scope,
        parameters=_parameters(scope),
        nodes=_nodes(scope),
        groups=[
            _native.group(root, parent=None,
                          members=[canvas, cur_panel, img_panel, gid(scope, "curve", CURVE_ID),
                                   gid(scope, "image"), gid(scope, "scale_bar"), *bands, *text]),
            _native.group(gid(scope, "bands"), parent=root, members=bands),
            _native.group(gid(scope, "image_set"), parent=root, members=_image_set(scope)),
            _native.group(gid(scope, "text"), parent=root, members=text),
        ],
        relations=_relations(scope),
        outputs=[f"{FIGURE_ID}_{scope}.{ext}" for ext in OUTPUT_FORMATS],
        source={
            "letters": scope == "main",
            "panel_order": list(PANEL_IDS),
            "curve_points": CURVE_POINTS,
            "curve_lift_key": CURVE_LIFT_KEY,
            "panel_gap_key": PANEL_GAP_KEY,
            "science_invariants": dict(SCIENCE_INVARIANTS),
            "science_inputs": [str(p) for p in science_inputs()],
        },
    )


# ── 科学自检（strict 会用它拒绝发布） ───────────────────────────────────────
def science_selfcheck(science: dict, fig=None) -> list[str]:
    """受保护内容的自检：数据、显示窗口、像素、裁切、纵横比、比例尺长度、文本。"""
    problems: list[str] = []
    x, y = science["curve"]
    grid = fixture_data.ftir_x()
    if x.shape != grid.shape or not np.array_equal(x, grid):
        problems.append("SCIENCE_PAYLOAD: 曲线 a 的波数网格与受保护网格不一致")
    if y.shape != x.shape or not np.all(np.isfinite(y)):
        problems.append(f"SCIENCE_PAYLOAD: 曲线 a 的 y 数组形状/有限性不符（{y.shape}）")
    if science["bands"] != fixture_data.ftir_band_limits():
        problems.append("SCIENCE_WINDOW: 带位窗口与受保护的显示窗口不一致")
    image = science["micrograph"]
    if tuple(image.shape) != tuple(fixture_data.PANEL_SHAPE) or image.dtype != np.uint8:
        problems.append(f"SCIENCE_PIXELS: 显微图像素形状/类型不符（{image.shape}/{image.dtype}）")
    if not math.isclose(science["field_width_um"], fixture_data.panel_field_width_um(IMAGE_ID),
                        rel_tol=0.0, abs_tol=1e-9):
        problems.append("SCIENCE_CROP: 视野宽度与受保护的裁切语义不一致")
    if not math.isclose(science["scale_bar_um"], fixture_data.SCALE_BAR_UM,
                        rel_tol=0.0, abs_tol=1e-9):
        problems.append("SCIENCE_SCALE_BAR: 比例尺代表的物理长度被改")
    if not math.isclose(science["panel_aspect"],
                        fixture_data.PANEL_SHAPE[1] / fixture_data.PANEL_SHAPE[0],
                        rel_tol=0.0, abs_tol=1e-9):
        problems.append("SCIENCE_ASPECT: 面板纵横比与视野像素不符")

    if fig is None:
        return problems

    by_gid = _native.artists_by_gid(fig)
    canvas_w_mm = float(fig.get_size_inches()[0]) * MM_PER_INCH
    canvas_h_mm = float(fig.get_size_inches()[1]) * MM_PER_INCH
    mm_per_px = MM_PER_INCH / float(fig.dpi)
    height, width = science["field_shape"][0], science["field_shape"][1]
    field_um = science["field_width_um"]
    want_extent = (0.0, field_um, field_um * height / width, 0.0)

    for scope in SCOPES:
        line = by_gid.get(gid(scope, "curve", CURVE_ID))
        if line is not None:
            got_x = np.asarray(line.get_xdata(), float)
            got_y = np.asarray(line.get_ydata(), float)
            if not (np.array_equal(got_x, x) and np.array_equal(got_y, y)):
                problems.append(f"SCIENCE_PAYLOAD: {scope} 曲线 a 的绘图数组 != 受保护数组")

        ax_c = by_gid.get(gid(scope, "curve_panel"))
        if ax_c is not None:
            if not np.allclose(ax_c.get_xlim(), science["xlim"], atol=1e-9):
                problems.append(f"SCIENCE_WINDOW: {scope} xlim 变成了 {tuple(ax_c.get_xlim())}")
            if not np.allclose(ax_c.get_ylim(), science["ylim"], atol=1e-9):
                problems.append(f"SCIENCE_WINDOW: {scope} ylim 变成了 {tuple(ax_c.get_ylim())}")

        for bid, (lo, hi) in science["bands"].items():
            span = by_gid.get(gid(scope, "band", bid))
            if span is None:
                continue
            # axvspan 返回 Rectangle：跨度用 get_x()/get_width()（数据坐标）。
            # 注意 get_verts() 在 mpl 3.10 上给的是显示像素，不能拿来比数据窗口。
            got = (float(span.get_x()), float(span.get_x() + span.get_width()))
            if not np.allclose(got, (lo, hi), atol=1e-9):
                problems.append(f"SCIENCE_WINDOW: {scope} 带位 {bid} 的显示窗口变成了 {got}")

        ax_i = by_gid.get(gid(scope, "image_panel"))
        art = by_gid.get(gid(scope, "image"))
        box_w_mm = box_h_mm = 0.0
        if ax_i is not None:
            pos = ax_i.get_position()
            box_w_mm = pos.width * canvas_w_mm
            box_h_mm = pos.height * canvas_h_mm
        if art is not None:
            if not np.array_equal(np.asarray(art.get_array()), image):
                problems.append(f"SCIENCE_PIXELS: {scope} 显微图像素 != 受保护像素")
            got_extent = tuple(float(v) for v in art.get_extent())
            if not np.allclose(got_extent, want_extent, atol=1e-9):
                problems.append(f"SCIENCE_CROP: {scope} 显微图 extent 变成了 {got_extent}")
            if box_h_mm > 0 and abs(box_w_mm / box_h_mm - science["panel_aspect"]) > 1e-6:
                problems.append(f"SCIENCE_ASPECT: {scope} 图像面板宽高比 "
                                f"{box_w_mm / box_h_mm:.6f} != 视野纵横比 "
                                f"{science['panel_aspect']:.6f}")
            x_um = abs(got_extent[1] - got_extent[0])
            y_um = abs(got_extent[3] - got_extent[2])
            if x_um > 0 and y_um > 0 and abs(box_w_mm / x_um - box_h_mm / y_um) > 1e-9:
                problems.append(f"SCIENCE_ASPECT: {scope} 显微图被拉伸（x "
                                f"{box_w_mm / x_um:.6f} mm/µm vs y {box_h_mm / y_um:.6f} mm/µm）")

        bar = by_gid.get(gid(scope, "scale_bar"))
        if bar is not None and box_w_mm > 0:
            data = np.column_stack([np.asarray(bar.get_xdata(), float),
                                    np.asarray(bar.get_ydata(), float)])
            disp = np.asarray(bar.get_transform().transform(data), float)
            got_mm = abs(float(disp[1, 0]) - float(disp[0, 0])) * mm_per_px
            want_mm = science["scale_bar_um"] / field_um * box_w_mm
            if abs(got_mm - want_mm) > 1e-6:
                problems.append(f"SCIENCE_SCALE_BAR: {scope} 比例尺渲染长度 {got_mm:.6f} mm "
                                f"!= 声明的 {want_mm:.6f} mm")

        for key, want in (("xlabel", XLABEL), ("ylabel", YLABEL)):
            art_text = by_gid.get(gid(scope, key))
            if art_text is not None and art_text.get_text() != want:
                problems.append(f"SCIENCE_TEXT: {scope} {key} 文本被改成了 "
                                f"{art_text.get_text()!r}")
        if scope == "main":
            for panel, want in LETTER_TEXT.items():
                art_text = by_gid.get(gid(scope, "letter", panel))
                if art_text is not None and art_text.get_text() != want:
                    problems.append(f"SCIENCE_TEXT: {scope} 面板字母 {panel} 被改成了 "
                                    f"{art_text.get_text()!r}")
    return problems


if __name__ == "__main__":
    raise SystemExit(_native.run(sys.modules[__name__]))
