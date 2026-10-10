"""原生四联显微图夹具：2×2 固定种子显微图 + 真实毫米栅格 + 比例尺的物理语义。

**与绘图源码无关**：这张图是什么，全部写在下面对外声明的接缝里 ——
`SCOPES / FIGURE_ID / CONFIG_PATH / SCHEMA / load_config / list_params /
SCIENCE_INPUTS / science_inputs / load_science / build_scene / build_figure_and_registry /
layout_contract / science_manifest / science_selfcheck`。别的 agent 不用读本文件其余部分，
就能拿到"有哪些对象、哪个 YAML 路径控制它、会产生什么效果、必须守住什么"。

科学内容（受保护，显示层不许改）：
- 四张显微图来自 `fixture_data.micrograph(pid)`：载荷里拿到的就是那个**只读数组对象本身**
  （固定种子、uint8 RGB）。图元层里 matplotlib 会把它拷贝成 MaskedArray
  （`safe_masked_invalid(copy=True)`，显示层管线），所以自检在图上守住的是**逐字节相同**，
  在载荷上守住的是**同一个对象**：像素既不能被改写，也不能被归一化/重采样/重建；
- 每张图的裁切窗口（µm）是受保护的**显示窗口**：整幅视野 = 全像素，
  `extent=(0, 视野宽 µm, 视野高 µm, 0)`；xlim/ylim 就是这条窗口；
- 面板框的纵横比必须等于画幅比例 260:200 = 1.3，否则显微图被拉伸 —— 那是改了科学含义，
  `load_config` 里是硬闸；
- 比例尺代表的物理长度（µm）是受保护的语义：显示长度 = 比例尺 µm / 视野宽 µm × 面板显示宽 mm；
- 面板字母（A/B/C/D）是受保护的科学文本，`bare` 作用域**一个字母都不画**（作用域隔离必须看得见）。

排版（真实物理毫米，不许用"0.1 数据单位/mm"之类的猜出来的换算）：
四块面板落在精确的 2×2 毫米栅格上（列 0 = a/c，列 1 = b/d；行 0 = 底排 a/b）：
`x = margin_left + col × (panel_w + gap_x)`，`y = margin_bottom + row × (panel_h + gap_y)`。
面板字母只叠一个**真实毫米**的 `apply_display_shift(..., dx_mm=, dy_mm=)`；
比例尺画在**坐标轴分数**坐标里（长度由 µm 语义反推），数据坐标一个字节都不动。

导入本模块：不建 Figure、不渲染、不写文件、不打印。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:  # 直接以脚本方式运行（cwd 可能是任意目录）
    sys.path.insert(0, _ROOT)

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from figpact import GidRegistry, apply_display_shift  # noqa: E402
from figpact import load_config as _engine_load_config  # noqa: E402
from figpact.config import ConfigError  # noqa: E402
from figpact.units import MM_PER_INCH  # noqa: E402
from tests.fixtures import _native, fixture_data  # noqa: E402

# ── 对外身份 ────────────────────────────────────────────────────────────────
#: 对象身份前缀，不是配置项：gid 是外部引用认的名字，做成旋钮只会让引用悄悄失效。
FIGURE_ID = "fig_panels_native"
#: 「一次 build_scene 调用 = 一个作用域」。`main` 带面板字母，`bare` 不带。
SCOPES = ("main", "bare")
PANEL_IDS = fixture_data.PANEL_IDS
#: (高, 宽, 通道)：四张图**形状相同**，内容不同。
PANEL_SHAPE = fixture_data.PANEL_SHAPE
PANEL_UM_PER_PX = fixture_data.PANEL_UM_PER_PX
#: 比例尺代表的物理长度（µm）：受保护语义，配置里只许写成这一个值。
SCALE_BAR_UM = float(fixture_data.SCALE_BAR_UM)
#: 画幅比例 = 宽/高 = 260/200 = 1.3：面板框比例必须与它逐位一致，否则显微图被拉伸。
PANEL_ASPECT = float(PANEL_SHAPE[1]) / float(PANEL_SHAPE[0])
#: 面板 id → (列, 行)。行 0 = 底排。这是**声明**，不是从列表顺序猜出来的。
PANEL_GRID = {"a": (0, 0), "b": (1, 0), "c": (0, 1), "d": (1, 1)}
#: 面板字母：科学文本，排版可以挪位置、不可以改字。
LETTER_TEXT = {"a": "A", "b": "B", "c": "C", "d": "D"}
#: 比例尺引导线在**坐标轴分数**里的起点与高度：装饰几何（LAYOUT），语义在 science_manifest 里声明。
SCALE_BAR_X0 = 0.07
SCALE_BAR_Y = 0.09
CONFIG_PATH = Path(__file__).with_name("native_panels.yaml")
#: 本夹具没有外部科学输入文件：四张显微图由 `fixture_data` 用固定种子在内存里现算。
#: 「来源」= 种子 + 生成函数，不是磁盘上的某个 .png —— 但那不是可以含糊的地方：
#: 有外部输入的适配器必须逐条列出真实文件（精确路径，不 glob、不扫目录）。
SCIENCE_INPUTS: tuple[Path, ...] = ()

FONT_RANGE = (3.0, 12.0)
#: `--strict` 每个 scope 必须产出的格式（共享契约：PNG/PDF/SVG/TIFF）。
OUTPUT_FORMATS = ("png", "pdf", "svg", "tiff")

#: key → (类型, 下界, 上界)。`panel_field_um` 是字典型：**受保护的裁切窗口**。
#: 锁定项的下界 = 上界：这不是"范围"，是"只许是这一个值"。
SCALARS = {
    "schema_version": (int, 1, 1),
    "canvas_w_mm": (float, 40.0, 200.0),
    "canvas_h_mm": (float, 40.0, 200.0),
    "render_dpi": (int, 96, 600),
    "margin_left_mm": (float, 0.0, 40.0),
    "margin_bottom_mm": (float, 0.0, 40.0),
    "margin_right_mm": (float, 0.0, 40.0),
    "margin_top_mm": (float, 0.0, 40.0),
    "panel_w_mm": (float, 5.0, 60.0),
    "panel_h_mm": (float, 5.0, 60.0),
    "gap_x_mm": (float, 0.0, 20.0),
    "gap_y_mm": (float, 0.0, 20.0),
    "letter_font_pt": (float, *FONT_RANGE),
    "scale_bar_lw_pt": (float, 0.2, 3.0),
    "letter_inset_x_mm": (float, 0.0, 10.0),
    "letter_inset_y_mm": (float, 0.0, 10.0),
    "panel_aspect": (float, PANEL_ASPECT, PANEL_ASPECT),
    "panel_field_um": (dict,),
    "scale_bar_um": (float, SCALE_BAR_UM, SCALE_BAR_UM),
}
SCHEMA = dict(SCALARS)

PARAM_GROUPS = {
    "元数据 (Meta)": ("schema_version",),
    "画布 (Canvas)": ("canvas_w_mm", "canvas_h_mm", "render_dpi"),
    "毫米栅格 (Grid mm)": ("margin_left_mm", "margin_bottom_mm", "margin_right_mm", "margin_top_mm",
                           "panel_w_mm", "panel_h_mm", "gap_x_mm", "gap_y_mm"),
    "字号与线宽 (Type)": ("letter_font_pt", "scale_bar_lw_pt"),
    "面板字母 (Letters)": ("letter_inset_x_mm", "letter_inset_y_mm"),
    "受保护语义 (Locked)": ("panel_aspect", "scale_bar_um"),
}
PARAM_DESC = {
    "schema_version": ("配置契约版本", "—"),
    "canvas_w_mm": ("画布物理宽度", "mm"),
    "canvas_h_mm": ("画布物理高度", "mm"),
    "render_dpi": ("渲染分辨率", "dpi"),
    "margin_left_mm": ("栅格左外边距（a、c 列）", "mm"),
    "margin_bottom_mm": ("栅格下外边距（底排 a、b）", "mm"),
    "margin_right_mm": ("栅格右侧最小净空（只校验，不移动）", "mm"),
    "margin_top_mm": ("栅格上方最小净空（只校验，不移动）", "mm"),
    "panel_w_mm": ("面板显示宽度（左右列同步）", "mm"),
    "panel_h_mm": ("面板显示高度（上下排同步）", "mm"),
    "gap_x_mm": ("右列相对左列再加多少毫米", "mm"),
    "gap_y_mm": ("上排相对底排再加多少毫米", "mm"),
    "letter_font_pt": ("面板字母字号", "pt"),
    "scale_bar_lw_pt": ("比例尺线宽", "pt"),
    "letter_inset_x_mm": ("面板字母向右内缩", "mm"),
    "letter_inset_y_mm": ("面板字母向下内缩", "mm"),
    "panel_aspect": ("画幅比例（受保护，260:200）", "—"),
    "panel_field_um": ("面板裁切窗口宽度（受保护）", "µm"),
    "scale_bar_um": ("比例尺代表的物理长度（受保护）", "µm"),
}

#: 任务语料引用这些名字，测试核对"每个断言的保护项都被夹具声明过"。
SCIENCE_INVARIANTS = {
    "panels.pixels_unchanged": "四张显微图的像素数组逐字节（且同一对象）等于受保护数组",
    "panels.crop_window_unchanged": "每张图的裁切窗口与显示窗口（µm）不变",
    "panels.aspect_unchanged": "面板框纵横比仍等于画幅比例 1.3，显微图没有被拉伸",
    "panels.scale_bar_meaning": "比例尺代表的物理长度（µm）不变：显示长度 = µm/视野宽 × 面板宽",
    "panels.panel_order": "面板顺序不变：a 左下、b 右下、c 左上、d 右上",
}


# ── 物理量的小工具 ──────────────────────────────────────────────────────────
def field_um(panel_id: str) -> tuple[float, float]:
    """面板视野的物理尺寸 (宽, 高) µm：像素数 × 每像素物理尺寸，一行乘出来，不倒推。"""
    if panel_id not in PANEL_IDS:
        raise ValueError(f"未知面板 {panel_id!r}；可用：{list(PANEL_IDS)}")
    height_px, width_px = int(PANEL_SHAPE[0]), int(PANEL_SHAPE[1])
    um_per_px = float(PANEL_UM_PER_PX[panel_id])
    return (float(width_px) * um_per_px, float(height_px) * um_per_px)


def panel_extent_um(panel_id: str) -> tuple[float, float, float, float]:
    """面板的裁切窗口（受保护）：`(0, 视野宽, 视野高, 0)` —— y 轴朝下，行 0 在上。"""
    width_um, height_um = field_um(panel_id)
    return (0.0, width_um, height_um, 0.0)


def _panel_rect_mm(config: dict, panel_id: str) -> tuple[float, float, float, float]:
    """面板在画布毫米坐标里的精确矩形 (x, y, w, h)：列/行都从**左/下留白**起算。"""
    col, row = PANEL_GRID[panel_id]
    x_mm = config["margin_left_mm"] + col * (config["panel_w_mm"] + config["gap_x_mm"])
    y_mm = config["margin_bottom_mm"] + row * (config["panel_h_mm"] + config["gap_y_mm"])
    return (x_mm, y_mm, config["panel_w_mm"], config["panel_h_mm"])


def grid_clearance_mm(config: dict) -> tuple[float, float]:
    """栅格之外画布还剩多少毫米 (右, 上)：必须 >= margin_right_mm / margin_top_mm。"""
    right_mm = config["canvas_w_mm"] - (config["margin_left_mm"] + 2.0 * config["panel_w_mm"]
                                       + config["gap_x_mm"])
    top_mm = config["canvas_h_mm"] - (config["margin_bottom_mm"] + 2.0 * config["panel_h_mm"]
                                      + config["gap_y_mm"])
    return (right_mm, top_mm)


def _check_aspect(config: dict, name: str) -> None:
    """硬闸：面板框必须是画幅比例。差一点点就是"显微图被拉伸"，不是排版误差。"""
    stretched = config["panel_w_mm"] - PANEL_ASPECT * config["panel_h_mm"]
    if abs(stretched) > 1e-9:
        raise ConfigError(
            f"{name}：panel_w_mm={config['panel_w_mm']:g} 与画幅比例不符"
            f"（1.3 × panel_h_mm={config['panel_h_mm']:g} = {PANEL_ASPECT * config['panel_h_mm']!r}）；"
            f"面板框比例不等于 260:200，显微图会被拉伸 —— 那是改了科学含义，不是排版"
        )


# ── 配置 ────────────────────────────────────────────────────────────────────
def load_config(path: Path | str = CONFIG_PATH) -> dict:
    """引擎校验 + 裁切窗口/比例尺语义只读校验 + 画幅比例硬闸 + 栅格装得下画布。"""
    cfg = _engine_load_config(path, SCHEMA)
    name = Path(path).name

    declared = cfg["panel_field_um"]
    if not isinstance(declared, dict):
        raise ConfigError(f"{name}：panel_field_um 必须是 `面板id: 视野宽度µm` 映射")
    expected = {pid: fixture_data.panel_field_width_um(pid) for pid in PANEL_IDS}
    if set(declared) != set(expected):
        raise ConfigError(f"{name}：panel_field_um 必须完整列出 {list(expected)}；得到 {sorted(declared)}")
    for pid, value in declared.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ConfigError(f"{name}：panel_field_um.{pid} 必须是有限数字，得到 {value!r}")
        # 裁切窗口即受保护的科学窗口：改它 = 这张图看的是另一块样品，不是排版。
        if abs(float(value) - expected[pid]) > 1e-9:
            raise ConfigError(
                f"{name}：panel_field_um.{pid} = {value!r} 与受保护视野宽度 {expected[pid]} µm 不一致")

    if abs(cfg["scale_bar_um"] - SCALE_BAR_UM) > 1e-9:
        raise ConfigError(f"{name}：scale_bar_um = {cfg['scale_bar_um']!r} 与受保护语义 {SCALE_BAR_UM} µm 不一致")
    if abs(cfg["panel_aspect"] - PANEL_ASPECT) > 1e-9:
        raise ConfigError(f"{name}：panel_aspect = {cfg['panel_aspect']!r} 与画幅比例 {PANEL_ASPECT!r} 不一致")

    _check_aspect(cfg, name)

    right_mm, top_mm = grid_clearance_mm(cfg)
    if right_mm + 1e-9 < cfg["margin_right_mm"] or top_mm + 1e-9 < cfg["margin_top_mm"]:
        raise ConfigError(
            f"{name}：2×2 面板栅格装不进画布 —— 右侧只剩 {right_mm:.3f} mm"
            f"（要求 >= margin_right_mm = {cfg['margin_right_mm']:g}）、上方只剩 {top_mm:.3f} mm"
            f"（要求 >= margin_top_mm = {cfg['margin_top_mm']:g}）")
    return cfg


def list_params(path: Path | str = CONFIG_PATH) -> None:
    """按可见对象分组的参数清单（当前值 / 单位 / 允许范围）。"""
    cfg = load_config(path)
    _native.print_param_table(cfg, SCALARS, PARAM_GROUPS, PARAM_DESC)
    print("=== 受保护视野 (Locked crop, µm) ===")
    for pid in PANEL_IDS:
        width_um, height_um = field_um(pid)
        print(f"  panel_field_um.{pid} = {cfg['panel_field_um'][pid]:g} µm 宽 × {height_um:g} µm 高"
              f"（{PANEL_SHAPE[1]}×{PANEL_SHAPE[0]} px @ {PANEL_UM_PER_PX[pid]:g} µm/px）"
              f" → 比例尺 {SCALE_BAR_UM:g} µm 占宽度 {fixture_data.scale_bar_fraction(pid):.4f}")


# ── 科学载荷 ────────────────────────────────────────────────────────────────
def science_inputs() -> tuple[Path, ...]:
    """声明的科学输入文件（绝对路径）。

    生成式夹具返回空元组：没有输入文件，来源是种子 + 生成函数（`science["source"]` 里写明了）。
    有外部输入的适配器必须在这里逐条列出**真实**文件：不接受 glob、不接受扫目录、
    声明的路径不存在就是错误（不静默丢掉）。这里返回的永远是**输入**，
    绝不是 `layout_contract(scope)["outputs"]` 里的产物。
    """
    return SCIENCE_INPUTS


def load_science() -> dict:
    """受保护的数据与来源声明：不建 Figure，可以被反复调用（结果一致）。

    `micrograph()` 是 lru_cache 的：这里拿到的是**那个数组对象本身**（只读），
    不是副本 —— 图元层一旦就地改写它，"像素字节不变"立刻就能测出来。
    """
    if set(PANEL_GRID) != set(PANEL_IDS):  # 栅格声明必须先完整：少一个面板就是少一块证据
        raise ValueError(f"PANEL_GRID 必须完整声明 {list(PANEL_IDS)}；得到 {sorted(PANEL_GRID)}")
    panels = {pid: fixture_data.micrograph(pid) for pid in PANEL_IDS}
    widths = {pid: field_um(pid)[0] for pid in PANEL_IDS}
    heights = {pid: field_um(pid)[1] for pid in PANEL_IDS}
    return {
        "panels": panels,
        "fields_um": widths,
        "field_heights_um": heights,
        "extent": {pid: panel_extent_um(pid) for pid in PANEL_IDS},
        "shape": tuple(int(v) for v in PANEL_SHAPE),
        "um_per_px": {pid: float(PANEL_UM_PER_PX[pid]) for pid in PANEL_IDS},
        "aspect": PANEL_ASPECT,
        "scale_bar_um": SCALE_BAR_UM,
        "letters": dict(LETTER_TEXT),
        "grid": dict(PANEL_GRID),
        "source": {
            "kind": "seeded_synthetic",
            "seed": fixture_data.SEED,
            "generator": "tests.fixtures.fixture_data.micrograph",
            "note": "no instrument file, no private data, no pixel resampling",
        },
    }


def science_manifest(science: dict) -> dict:
    """来源/处理/裁切/比例尺语义的 JSONable 声明（引擎另会指纹化图的真实内容）。

    这里**只有与配置无关的数字**：视野宽度、比例尺 µm、像素形状。面板显示多宽（mm）
    是排版，进不了这份声明 —— 否则改一次排版就会伪造出一次"科学变化"。
    """
    return {
        "science": {
            "source": science["source"],
            "processing": [
                "fixed-seed synthetic micrographs, uint8 RGB, no instrument file",
                "no normalisation, no clipping, no resampling, no pixel array copy",
                "interpolation='nearest' is display-only (no pixel value interpolation)",
                "no unit conversion: field widths come from pixels × µm/px",
            ],
            "protected_windows": {
                "panel_extent_um": {pid: list(science["extent"][pid]) for pid in PANEL_IDS},
                "panel_xlim_um": {pid: [science["extent"][pid][0], science["extent"][pid][1]]
                                  for pid in PANEL_IDS},
                "panel_ylim_um": {pid: [science["extent"][pid][3], science["extent"][pid][2]]
                                  for pid in PANEL_IDS},
            },
            "crop": {
                pid: {
                    "full_frame": True,
                    "field_width_um": science["fields_um"][pid],
                    "field_height_um": science["field_heights_um"][pid],
                    "grid": f"pixel grid {int(science['shape'][1])}×{int(science['shape'][0])}"
                            f" @ {science['um_per_px'][pid]:g} µm/px",
                    "extent_um": list(science["extent"][pid]),
                }
                for pid in PANEL_IDS
            },
            "aspect": {
                "value": science["aspect"],
                "pixels": [int(science["shape"][1]), int(science["shape"][0])],
                "no_stretch": True,
            },
            "scale_bars": {
                pid: {
                    "um": science["scale_bar_um"],
                    "field_width_um": science["fields_um"][pid],
                    "fraction_of_panel_width": science["scale_bar_um"] / science["fields_um"][pid],
                }
                for pid in PANEL_IDS
            },
            "pixels": {
                pid: {"shape": list(science["panels"][pid].shape), "dtype": str(science["panels"][pid].dtype)}
                for pid in PANEL_IDS
            },
            "arrays": [
                {"id": f"panel.{pid}", "kind": "micrograph",
                 "shape": list(science["panels"][pid].shape), "units": {"x": "um", "y": "um"}}
                for pid in PANEL_IDS
            ],
            "protected_text": {
                "panel_letters": dict(science["letters"]),
                "titles": [],
                "label_text": [],
            },
        },
        "nodes": {gid_: {"science_policy": meta["science_policy"]}
                  for gid_, meta in _all_policy_nodes().items()},
    }


# ── 绘制 ────────────────────────────────────────────────────────────────────
def gid(scope: str, kind: str, name: str | None = None) -> str:
    """对象身份：`<figure>.<scope>.<kind>[.<name>]`。点号在 gid 里从不被拆开。"""
    return f"{FIGURE_ID}.{scope}.{kind}" + (f".{name}" if name else "")


def has_letters(scope: str) -> bool:
    """这个作用域画不画面板字母：`main` 画，`bare` 一个都不画（作用域隔离要看得见）。"""
    return scope == "main"


def _rect_fraction(config: dict, panel_id: str) -> list[float]:
    """面板矩形的 figure 分数坐标：毫米 -> 分数，一步除法，不经数据坐标。"""
    x_mm, y_mm, w_mm, h_mm = _panel_rect_mm(config, panel_id)
    return [x_mm / config["canvas_w_mm"], y_mm / config["canvas_h_mm"],
            w_mm / config["canvas_w_mm"], h_mm / config["canvas_h_mm"]]


def build_scene(science: dict, config: dict, scope: str):
    """确定性构建：四块面板的毫米栅格完全由 config 决定；(Figure, GidRegistry)。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    cfg = config
    _check_aspect(cfg, "配置")
    if cfg["panel_w_mm"] <= 0.0 or cfg["panel_h_mm"] <= 0.0:
        raise ValueError(f"面板尺寸必须为正：{cfg['panel_w_mm']}×{cfg['panel_h_mm']} mm")

    fig = plt.figure(figsize=(cfg["canvas_w_mm"] / MM_PER_INCH, cfg["canvas_h_mm"] / MM_PER_INCH),
                     dpi=float(cfg["render_dpi"]))
    reg = GidRegistry()
    reg.register(fig.patch, gid(scope, "canvas"))

    for pid in PANEL_IDS:
        ax = fig.add_axes(_rect_fraction(cfg, pid))
        reg.register(ax, gid(scope, "panel", pid),
                     params=["margin_left_mm", "margin_bottom_mm", "panel_w_mm", "panel_h_mm",
                             "gap_x_mm", "gap_y_mm"])

        # 显微图：绘图数组**就是**受保护数组（不拷贝、不归一化、不裁切）；
        # extent 是受保护的裁切窗口，interpolation 只影响显示采样方式。
        image = ax.imshow(science["panels"][pid], extent=science["extent"][pid],
                          interpolation="nearest", aspect="auto")
        reg.register(image, gid(scope, "image", pid), params=["panel_field_um"])
        ax.set_axis_off()

        # 比例尺：画在坐标轴分数里，长度由 µm 语义反推（10 µm / 视野宽 µm 占面板宽的比例）。
        # 它是**装饰几何**（LAYOUT）：含义在 science_manifest 里声明，不当作信号指纹化。
        bar_fraction = science["scale_bar_um"] / science["fields_um"][pid]
        (bar,) = ax.plot([SCALE_BAR_X0, SCALE_BAR_X0 + bar_fraction], [SCALE_BAR_Y, SCALE_BAR_Y],
                         transform=ax.transAxes, color="white", lw=cfg["scale_bar_lw_pt"],
                         solid_capstyle="butt", zorder=4)
        reg.register(bar, gid(scope, "scale_bar", pid),
                     params=["scale_bar_lw_pt", "panel_field_um", "scale_bar_um"])

        if has_letters(scope):
            # 面板字母锚在面板左上角，内缩是**真实毫米显示位移**（数据坐标不动）。
            letter = ax.text(0.0, 1.0, science["letters"][pid], transform=ax.transAxes,
                             ha="left", va="top", fontsize=cfg["letter_font_pt"],
                             color="black", zorder=5)
            reg.register(letter, gid(scope, "letter", pid),
                         params=["letter_font_pt", "letter_inset_x_mm", "letter_inset_y_mm"])
            apply_display_shift(letter, dx_mm=cfg["letter_inset_x_mm"], dy_mm=-cfg["letter_inset_y_mm"])
    return fig, reg


def build_figure_and_registry(scope: str, *, config: dict | None = None):
    """旧接缝保持不变：等价于 build_scene(load_science(), config, scope)。"""
    return build_scene(load_science(), config if config is not None else load_config(), scope)


# ── 布局契约 ────────────────────────────────────────────────────────────────
def _nodes(scope: str) -> dict:
    """节点元数据：type / parent / editable / science_policy。未声明的默认锁死。"""
    root = gid(scope, "root")
    nodes: dict[str, dict] = {
        gid(scope, "canvas"): _native.node(gid(scope, "canvas"), type_name="Figure", parent=None,
                                           editable=False, science_policy="LOCKED_SCIENCE",
                                           label="画布"),
    }
    for pid in PANEL_IDS:
        # 图像/比例尺/字母是**那块面板**的子对象：挂到 root 会让 Panel→后代的依赖闭包断掉。
        panel = gid(scope, "panel", pid)
        nodes[panel] = _native.node(
            panel, type_name="Axes", parent=root, editable=False,
            science_policy="LOCKED_SCIENCE", label=f"面板 {pid}(列{PANEL_GRID[pid][0]},行{PANEL_GRID[pid][1]})")
        nodes[gid(scope, "image", pid)] = _native.node(
            gid(scope, "image", pid), type_name="AxesImage", parent=panel, editable=False,
            science_policy="LOCKED_SCIENCE", label=f"显微图 {pid}（{field_um(pid)[0]:g} µm 视野）")
        nodes[gid(scope, "scale_bar", pid)] = _native.node(
            gid(scope, "scale_bar", pid), type_name="Line2D", parent=panel, editable=False,
            science_policy="LAYOUT", label=f"比例尺 {pid}（{SCALE_BAR_UM:g} µm）")
        if has_letters(scope):
            nodes[gid(scope, "letter", pid)] = _native.node(
                gid(scope, "letter", pid), type_name="Text", parent=panel, editable=False,
                science_policy="LOCKED_SCIENCE", label=LETTER_TEXT[pid])
    return nodes


def _all_policy_nodes() -> dict:
    """全部 scope 的 science_policy 表（science_manifest 与契约共用一份）。"""
    out: dict[str, dict] = {}
    for scope in SCOPES:
        out.update(_nodes(scope))
    return out


def _panel_gids(scope: str) -> list[str]:
    return [gid(scope, "panel", pid) for pid in PANEL_IDS]


def _gids_where(scope: str, *, col: int | None = None, row: int | None = None) -> list[str]:
    """按**声明的栅格**取面板 gid：关系记录跟着 `PANEL_GRID` 走，不按下标猜。"""
    return [gid(scope, "panel", pid) for pid in PANEL_IDS
            if (col is None or PANEL_GRID[pid][0] == col) and (row is None or PANEL_GRID[pid][1] == row)]


def _letter_gids(scope: str) -> list[str]:
    return [gid(scope, "letter", pid) for pid in PANEL_IDS]


def layout_contract(scope: str) -> dict:
    """这张图的可控点：参数 / 节点 / 组 / 关系 / 产物。路径永远是精确段数组。"""
    if scope not in SCOPES:
        raise ValueError(f"未知 scope：{scope}；可用：{list(SCOPES)}")
    canvas = gid(scope, "canvas")
    root = gid(scope, "root")
    panels = _panel_gids(scope)
    images = [gid(scope, "image", pid) for pid in PANEL_IDS]
    bars = [gid(scope, "scale_bar", pid) for pid in PANEL_IDS]
    letters = _letter_gids(scope) if has_letters(scope) else []
    keep = list(SCIENCE_INVARIANTS)
    row_bottom = _gids_where(scope, row=0)
    row_top = _gids_where(scope, row=1)
    col_left = _gids_where(scope, col=0)
    col_right = _gids_where(scope, col=1)
    # 缝宽一变，动的就是「右列」「上排」这些面板本身 —— 完整受影响集写在这一行里。
    b_panel = _gids_where(scope, col=1, row=0)
    d_panel = _gids_where(scope, col=1, row=1)
    c_panel = _gids_where(scope, col=0, row=1)

    parameters = [
        _native.param("canvas_w_mm", ["canvas_w_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis="x",
                      minimum=SCALARS["canvas_w_mm"][1], maximum=SCALARS["canvas_w_mm"][2],
                      expected=_native.expect("resize", objects=[canvas], axis="x", preserve=keep)),
        _native.param("canvas_h_mm", ["canvas_h_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis="y",
                      minimum=SCALARS["canvas_h_mm"][1], maximum=SCALARS["canvas_h_mm"][2],
                      expected=_native.expect("resize", objects=[canvas], axis="y", preserve=keep)),
        _native.param("render_dpi", ["render_dpi"], unit="dpi", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=[canvas] + panels, operation="rebuild", axis=None,
                      minimum=SCALARS["render_dpi"][1], maximum=SCALARS["render_dpi"][2],
                      expected=_native.expect("style", objects=[canvas], preserve=keep)),
        # 左/下留白是栅格的**锚点**：改它整块栅格平移，四块面板一起动（完整受影响集）。
        _native.param("margin_left_mm", ["margin_left_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=panels, operation="rebuild", axis="x",
                      minimum=SCALARS["margin_left_mm"][1], maximum=SCALARS["margin_left_mm"][2],
                      expected=_native.expect("resize", objects=panels, axis="x", preserve=keep)),
        _native.param("margin_bottom_mm", ["margin_bottom_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=panels, operation="rebuild", axis="y",
                      minimum=SCALARS["margin_bottom_mm"][1], maximum=SCALARS["margin_bottom_mm"][2],
                      expected=_native.expect("resize", objects=panels, axis="y", preserve=keep)),
        # 右/上留白是**派生量**：画布比栅格多出来的净空，只做校验、不移动任何图元。
        # 声明成 EDITABLE 会撒谎（改它什么都不动），所以是 DERIVED。
        _native.param("margin_right_mm", ["margin_right_mm"], unit="mm", mutability="DERIVED",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis="x",
                      expected=_native.expect("resize", objects=[canvas], axis="x", preserve=keep)),
        _native.param("margin_top_mm", ["margin_top_mm"], unit="mm", mutability="DERIVED",
                      scopes=list(SCOPES), objects=[canvas], operation="rebuild", axis="y",
                      expected=_native.expect("resize", objects=[canvas], axis="y", preserve=keep)),
        _native.param("panel_w_mm", ["panel_w_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=panels, operation="resize", axis="x",
                      minimum=SCALARS["panel_w_mm"][1], maximum=SCALARS["panel_w_mm"][2],
                      expected=_native.expect("resize", objects=panels, axis="x", preserve=keep)),
        _native.param("panel_h_mm", ["panel_h_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=panels, operation="resize", axis="y",
                      minimum=SCALARS["panel_h_mm"][1], maximum=SCALARS["panel_h_mm"][2],
                      expected=_native.expect("resize", objects=panels, axis="y", preserve=keep)),
        # 缝宽是**真实毫米显示位移**：右列/上排整体平移，受影响集就是那一列/那一排。
        _native.param("gap_x_mm", ["gap_x_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=col_right, operation="translate", axis="x", scale=1.0,
                      minimum=SCALARS["gap_x_mm"][1], maximum=SCALARS["gap_x_mm"][2],
                      expected=_native.expect("translate", objects=col_right, axis="x", preserve=keep)),
        _native.param("gap_y_mm", ["gap_y_mm"], unit="mm", mutability="EDITABLE",
                      scopes=list(SCOPES), objects=row_top, operation="translate", axis="y", scale=1.0,
                      minimum=SCALARS["gap_y_mm"][1], maximum=SCALARS["gap_y_mm"][2],
                      expected=_native.expect("translate", objects=row_top, axis="y", preserve=keep)),
        _native.param("scale_bar_lw_pt", ["scale_bar_lw_pt"], unit="pt", mutability="FIXED_STYLE",
                      scopes=list(SCOPES), objects=bars, operation="rebuild", axis=None,
                      minimum=SCALARS["scale_bar_lw_pt"][1], maximum=SCALARS["scale_bar_lw_pt"][2],
                      expected=_native.expect("style", objects=bars, preserve=keep)),
        _native.param("scale_bar_um", ["scale_bar_um"], unit="um", mutability="LOCKED_SCIENCE",
                      scopes=list(SCOPES), objects=bars, operation="rebuild", axis=None,
                      expected=_native.expect("style", objects=bars, preserve=keep)),
        _native.param("panel_aspect", ["panel_aspect"], unit="—", mutability="LOCKED_SCIENCE",
                      scopes=list(SCOPES), objects=panels, operation="rebuild", axis=None,
                      expected=_native.expect("style", objects=panels, preserve=keep)),
        _native.param("panel_field_um", ["panel_field_um"], unit="um", mutability="LOCKED_SCIENCE",
                      scopes=list(SCOPES), objects=images + bars, operation="rebuild", axis=None,
                      expected=_native.expect("style", objects=images + bars, preserve=keep)),
    ]
    if has_letters(scope):
        # 字母只在 main 存在：bare 的契约里连参数、节点、关系都不出现（契约是**按作用域**的）。
        parameters.append(_native.param(
            "letter_font_pt", ["letter_font_pt"], unit="pt", mutability="FIXED_STYLE",
            scopes=[scope], objects=letters, operation="rebuild", axis=None,
            minimum=SCALARS["letter_font_pt"][1], maximum=SCALARS["letter_font_pt"][2],
            expected=_native.expect("style", objects=letters, preserve=keep)))
        parameters.append(_native.param(
            "letter_inset_x_mm", ["letter_inset_x_mm"], unit="mm", mutability="EDITABLE",
            scopes=[scope], objects=letters, operation="translate", axis="x", scale=1.0,
            minimum=SCALARS["letter_inset_x_mm"][1], maximum=SCALARS["letter_inset_x_mm"][2],
            expected=_native.expect("translate", objects=letters, axis="x", preserve=keep)))
        parameters.append(_native.param(
            # 内缩是从面板上边框往下量：旋钮 +1 mm，字母在画面上**往下**走 1 mm，
            # 所以 scale = -1（方向写进声明，别让调用方靠猜）。
            "letter_inset_y_mm", ["letter_inset_y_mm"], unit="mm", mutability="EDITABLE",
            scopes=[scope], objects=letters, operation="translate", axis="y", scale=-1.0,
            minimum=SCALARS["letter_inset_y_mm"][1], maximum=SCALARS["letter_inset_y_mm"][2],
            expected=_native.expect("translate", objects=letters, axis="y", preserve=keep)))

    relations = [
        _native.relation("panels.contain_x", "contain", [canvas] + panels, axis="x",
                         controlled_by=[["canvas_w_mm"], ["margin_left_mm"], ["margin_right_mm"],
                                        ["panel_w_mm"], ["gap_x_mm"]]),
        _native.relation("panels.contain_y", "contain", [canvas] + panels, axis="y",
                         controlled_by=[["canvas_h_mm"], ["margin_bottom_mm"], ["margin_top_mm"],
                                        ["panel_h_mm"], ["gap_y_mm"]]),
        _native.relation("panels.equal_width", "equal_size", panels, axis="x",
                         controlled_by=[["panel_w_mm"]]),
        _native.relation("panels.equal_height", "equal_size", panels, axis="y",
                         controlled_by=[["panel_h_mm"]]),
        _native.relation("panels.gap_x_bottom", "gap", row_bottom, axis="x", anchor="right",
                         controlled_by=[["gap_x_mm"]], move=b_panel),
        _native.relation("panels.gap_x_top", "gap", row_top, axis="x", anchor="right",
                         controlled_by=[["gap_x_mm"]], move=d_panel),
        _native.relation("panels.gap_y_left", "gap", col_left, axis="y", anchor="bottom",
                         controlled_by=[["gap_y_mm"]], move=c_panel),
        _native.relation("panels.gap_y_right", "gap", col_right, axis="y", anchor="bottom",
                         controlled_by=[["gap_y_mm"]], move=d_panel),
        _native.relation("panels.align_row_bottom", "align", row_bottom, axis="y", anchor="bottom",
                         controlled_by=[["margin_bottom_mm"]]),
        _native.relation("panels.align_col_left", "align", col_left, axis="x", anchor="left",
                         controlled_by=[["margin_left_mm"]]),
    ]
    if has_letters(scope):
        for pid in PANEL_IDS:
            # 字母顶边距面板顶边就是 letter_inset_y_mm：字母在面板**里面**，
            # 包络间隙只会读出"重叠了多少毫米"（负值）；同侧锚点展幅才是真实的内缩量。
            relations.append(_native.relation(
                f"panels.letter_gap.{pid}", "align",
                [gid(scope, "panel", pid), gid(scope, "letter", pid)], axis="y", anchor="top",
                controlled_by=[["letter_inset_y_mm"]], move=[gid(scope, "letter", pid)]))

    groups = [
        _native.group(root, parent=None, members=[canvas] + panels),
        _native.group(gid(scope, "panels"), parent=root, members=panels),
    ]
    if has_letters(scope):
        groups.append(_native.group(gid(scope, "letters"), parent=root, members=letters))

    return _native.contract_record(
        sys.modules[__name__], scope, parameters=parameters, nodes=_nodes(scope), groups=groups,
        relations=relations, outputs=[f"{FIGURE_ID}_{scope}.{ext}" for ext in OUTPUT_FORMATS])


# ── 科学自检（strict 会用它拒绝发布） ───────────────────────────────────────
def _panel_rect_mm_measured(fig, ax) -> tuple[float, float, float, float]:
    """从**画出来的图**量面板矩形（mm）：figure 分数 × 画布毫米。"""
    pos = ax.get_position()
    width_mm = fig.get_figwidth() * MM_PER_INCH
    height_mm = fig.get_figheight() * MM_PER_INCH
    return (pos.x0 * width_mm, pos.y0 * height_mm, pos.width * width_mm, pos.height * height_mm)


def science_selfcheck(science: dict, fig=None) -> list[str]:
    """受保护内容的自检：像素、裁切窗口、比例尺语义、面板顺序。返回问题列表（空 = 通过）。

    有 `fig` 时按 gid 找**真实图元**再量一遍：像素数组逐字节比对、extent/xlim/ylim 比对、
    面板框纵横比（mm 实测）比对、比例尺长度（显示坐标 -> mm）比对、字母文本比对。
    """
    problems: list[str] = []

    if set(science["panels"]) != set(PANEL_IDS):
        problems.append(f"SCIENCE_PAYLOAD: 载荷面板集合 {sorted(science['panels'])} 与 {list(PANEL_IDS)} 不符")
    if set(PANEL_GRID) != set(PANEL_IDS):
        problems.append(f"SCIENCE_PAYLOAD: PANEL_GRID 未完整声明 {list(PANEL_IDS)}")

    for pid in PANEL_IDS:
        protected = fixture_data.micrograph(pid)
        payload = science["panels"].get(pid)
        if payload is not protected:  # 载荷必须是**同一个对象**：副本就不再是受保护数组
            problems.append(f"SCIENCE_PAYLOAD: 面板 {pid} 的载荷不是受保护数组对象本身（被复制/重建）")
            continue
        if protected.flags.writeable:
            problems.append(f"SCIENCE_PIXELS: 面板 {pid} 的受保护数组变成可写了")
        width_um, height_um = field_um(pid)
        if abs(width_um - fixture_data.panel_field_width_um(pid)) > 1e-9:
            problems.append(f"SCIENCE_WINDOW: 面板 {pid} 视野宽度 {width_um} µm 与受保护值不符")
        if abs(width_um / height_um - PANEL_ASPECT) > 1e-12:
            problems.append(f"SCIENCE_WINDOW: 面板 {pid} 视野 {width_um}×{height_um} µm 不是画幅比例")
        if abs(science["scale_bar_um"] / width_um - fixture_data.scale_bar_fraction(pid)) > 1e-12:
            problems.append(f"SCIENCE_PAYLOAD: 面板 {pid} 比例尺占比与受保护语义不符")

    if fig is None:
        return problems

    by_gid = _native.artists_by_gid(fig)
    for scope in SCOPES:
        present = [pid for pid in PANEL_IDS if by_gid.get(gid(scope, "panel", pid)) is not None]
        if not present:
            continue
        if sorted(present) != sorted(PANEL_IDS):
            problems.append(f"SCIENCE_PAYLOAD: {scope} 只画出了面板 {sorted(present)}，不是四块")

        rects: dict[str, tuple[float, float, float, float]] = {}
        for pid in present:
            rects[pid] = _panel_rect_mm_measured(fig, by_gid[gid(scope, "panel", pid)])

            # 1) 像素：绘图数组的字节必须与受保护数组逐字节相同（形状/类型也相同）。
            #    注意 matplotlib 的 `_normalize_image_array` 会自己 copy 成 MaskedArray
            #    （`cbook.safe_masked_invalid(A, copy=True)`），那是显示层管线，不是我们拷的：
            #    "载荷是同一个对象"在 load_science/下面那条检查里守住，这里守住字节。
            image = by_gid.get(gid(scope, "image", pid))
            if image is None:
                problems.append(f"SCIENCE_PIXELS: {scope} 面板 {pid} 缺少显微图图元")
            else:
                protected = fixture_data.micrograph(pid)
                drawn = np.asarray(image.get_array())
                if drawn.shape != protected.shape or drawn.dtype != protected.dtype:
                    problems.append(f"SCIENCE_PIXELS: {scope} 面板 {pid} 像素形状/类型 "
                                    f"{drawn.shape}/{drawn.dtype} != {protected.shape}/{protected.dtype}")
                elif not np.array_equal(drawn, protected):
                    problems.append(f"SCIENCE_PIXELS: {scope} 面板 {pid} 的像素字节与受保护数组不一致"
                                    f"（被改写、归一化或重采样）")
                extent = tuple(float(v) for v in image.get_extent())
                want_extent = science["extent"][pid]
                if len(extent) != 4 or any(abs(a - b) > 1e-9 for a, b in zip(extent, want_extent)):
                    problems.append(f"SCIENCE_WINDOW: {scope} 面板 {pid} 的裁切窗口变成了 {extent}"
                                    f"（受保护 {want_extent}）")

            # 2) 显示窗口：xlim/ylim 必须还是这条 µm 裁切窗口（y 轴朝下：上边界是 0）。
            view = by_gid.get(gid(scope, "panel", pid))
            want_extent = science["extent"][pid]
            if view is not None:
                if not (np.allclose(view.get_xlim(), (want_extent[0], want_extent[1]), atol=1e-9)
                        and np.allclose(view.get_ylim(), (want_extent[2], want_extent[3]), atol=1e-9)):
                    problems.append(f"SCIENCE_WINDOW: {scope} 面板 {pid} 的显示窗口变成了 "
                                    f"x{tuple(view.get_xlim())} y{tuple(view.get_ylim())}")

            # 3) 比例尺：实测长度（显示坐标 -> mm）必须等于 µm 语义推出的毫米长度。
            #    量法：线的数据点（坐标轴分数）过自身变换得到显示像素，(像素差) × 25.4/dpi = mm。
            bar = by_gid.get(gid(scope, "scale_bar", pid))
            if bar is None:
                problems.append(f"SCIENCE_PAYLOAD: {scope} 面板 {pid} 缺少比例尺图元")
            else:
                points = bar.get_transform().transform(np.asarray(bar.get_xydata(), float))
                length_mm = float(np.hypot(*(points[1] - points[0]))) * MM_PER_INCH / float(fig.dpi)
                # 面板显示宽度（mm）是**实测**的：不读配置，避免"配置说对了、图上没对"。
                want_mm = science["scale_bar_um"] / science["fields_um"][pid] * rects[pid][2]
                if abs(length_mm - want_mm) > 1e-6:
                    problems.append(f"SCIENCE_PAYLOAD: {scope} 面板 {pid} 比例尺实测 {length_mm:.4f} mm"
                                    f" != 语义长度 {want_mm:.4f} mm（{science['scale_bar_um']:g} µm"
                                    f"/{science['fields_um'][pid]:g} µm × {rects[pid][2]:.4f} mm）")

            # 4) 纵横比：面板框比例必须等于画幅比例，否则显微图被拉伸。
            if rects[pid][3] > 0.0:
                drawn_aspect = rects[pid][2] / rects[pid][3]
                if abs(drawn_aspect - science["aspect"]) > 1e-6:
                    problems.append(f"SCIENCE_WINDOW: {scope} 面板 {pid} 框比例 {drawn_aspect:.9f}"
                                    f" != 画幅比例 {science['aspect']}（显微图被拉伸）")

        # 5) 面板顺序：等宽等高、两列两行，且每块仍在声明的 (列, 行) 上。
        widths = {round(r[2], 9) for r in rects.values()}
        heights = {round(r[3], 9) for r in rects.values()}
        if len(widths) != 1 or len(heights) != 1:
            problems.append(f"SCIENCE_PAYLOAD: {scope} 四块面板尺寸不再相等 "
                            f"(宽 {sorted(widths)} / 高 {sorted(heights)})")
        xs = sorted({round(r[0], 9) for r in rects.values()})
        ys = sorted({round(r[1], 9) for r in rects.values()})
        if len(xs) != 2 or len(ys) != 2:
            problems.append(f"SCIENCE_PAYLOAD: {scope} 面板不再是 2×2 毫米栅格（列 {xs} / 行 {ys}）")
        else:
            for pid in present:
                col, row = PANEL_GRID[pid]
                if (xs.index(round(rects[pid][0], 9)), ys.index(round(rects[pid][1], 9))) != (col, row):
                    problems.append(f"SCIENCE_PAYLOAD: {scope} 面板 {pid} 不在声明的"
                                    f"(列{col},行{row})位置（面板顺序变了）")

        # 6) 面板字母：main 必须有且文本不变；bare 一个都不许有（作用域隔离）。
        found_letters = [g for g in by_gid if f".{scope}.letter." in g]
        if has_letters(scope):
            for pid in PANEL_IDS:
                letter = by_gid.get(gid(scope, "letter", pid))
                if letter is None:
                    problems.append(f"SCIENCE_TEXT: {scope} 缺少面板字母 {science['letters'][pid]}")
                elif letter.get_text() != science["letters"][pid]:
                    problems.append(f"SCIENCE_TEXT: {scope} 面板 {pid} 的字母被改成了 {letter.get_text()!r}")
        elif found_letters:
            problems.append(f"SCIENCE_TEXT: {scope} 不该有面板字母，却找到 {sorted(found_letters)}")
    return problems


if __name__ == "__main__":
    raise SystemExit(_native.run(sys.modules[__name__]))
