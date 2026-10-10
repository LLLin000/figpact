"""
示例项目 — 统一绘图样式模块（唯一来源 / single source of truth）
=================================================================
配套文档：同目录 `DESIGN.md`（画图前必读）

用法（每个绘图脚本头部固定三行）：
    import sys
    from pathlib import Path
    sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents
                                 if (p / "figure_style.py").is_file())))
    import figure_style as fs

    fs.apply()                      # 应用全局样式
    fig, ax = plt.subplots(figsize=fs.canvas("SQ"))   # 标准正方形画布
    ...
    fs.export(fig, "输出名")         # 一键导出 svg/pdf/png/tiff
    print(fs.find_text_overlaps(fig))  # 出图前 QA：检查文字重叠
"""

from __future__ import annotations

import sys
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

MM = 1.0 / 25.4  # mm → inch

# ══════════════════════════════════════════════════════════════════════════════
# 1. 画布尺寸（只有这几个，禁止自定义）
# ══════════════════════════════════════════════════════════════════════════════
# 基准格 = 90 × 90 mm（= Advanced Science 双栏 180 mm 的一半）
# Q4 = 一行四张的单元格（180 mm 版心 ÷ 4 栏，扣 2–3 mm 栏间距）
CANVAS_MM = {
    "Q4": (43.0, 34.0),        # ★ 一行四张的单元格：180 mm 版心 ÷ 4
    "Q2W": (88.0, 34.0),       # ★ 一行四格中跨两格（叠谱类：FTIR/XRD/NMR）
    "Q3": (57.0, 42.0),        # 一行三张
    "SQ": (90.0, 90.0),        # 单格正方形
    "SQ2": (90.0, 180.0),      # 上下两格
    "WIDE": (180.0, 90.0),     # 左右两格
    "GRID2x2": (180.0, 180.0), # 2 × 2 方图矩阵
}


def canvas(token: str = "SQ") -> tuple[float, float]:
    """返回 matplotlib figsize（英寸）；token ∈ {SQ, SQ2, WIDE, GRID2x2}。"""
    if token not in CANVAS_MM:
        raise KeyError(f"未知画布 '{token}'，只允许 {list(CANVAS_MM)}")
    w, h = CANVAS_MM[token]
    return (w * MM, h * MM)


def canvas_mm(width_mm: float, height_mm: float) -> tuple[float, float]:
    """按最终版式里的实际占位尺寸出图（见 DESIGN.md §2.1）。

    例：面板在拼版中占 2 栏 × 60 mm 高 → fs.canvas_mm(88, 60)。
    **不要**先按 90 mm 画再缩放：字号会等比缩小，跌破 5 pt 下限。
    """
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("宽高必须为正")
    return (width_mm * MM, height_mm * MM)


# 常见栏宽（mm）——Advanced Science 双栏版心 180 mm，Nature 单栏 89 mm
COLUMN_MM = {1: 43.0, 2: 88.0, 3: 58.0, 4: 43.0, "full": 180.0}


# ══════════════════════════════════════════════════════════════════════════════
# 2. 调色板（全项目唯一色表；脚本内禁止新增十六进制色值）
# ══════════════════════════════════════════════════════════════════════════════

# ── 2.1 材料体系：全项目共用（Fig 2 表征 / Fig 3 体外 / Fig 4 动物 一律照此）──
MATERIAL = {
    "HA":                    "#536878",  # 雾岩灰蓝 — 未改性透明质酸（基线对照）
    "ZnO":                   "#7B963F",  # 橄榄绿 — 纳米 / 介孔氧化锌
    "MOD_HA":                "#3E739E",  # 钢蓝 — 改性透明质酸 ★全项目主色（见命名约定）
    "COMPOSITE_MICROSPHERE": "#377A73",  # 深青绿 — Cu²⁺/ZnO 载药复合微球
    "COMPOSITE_GEL":         "#856B8F",  # 灰紫 — 凝胶 + 复合微球终态体系
}

# ── 2.2 小分子合成链：仅 NMR 使用 ──
# 直接复用材料调色板中的 4 色（小分子在这些图里不与其他实体同框出现）。
# 理由（ΔE 实测）：最小两两色差 17.4（与旧淡冷阶相同），但**最淡层对白底对比度
# 从 18.2 提升到 56.2（×3）**——淡色在印刷/投影上几乎看不见，故弃用淡色阶。
SYNTHESIS = {
    "CPD2_VANCHO":  "#536878",  # 同 MATERIAL["HA"] 雾岩灰蓝 — 起点（香兰素醛酯）
    "CPD3_VANOH":   "#377A73",  # 同 COMPOSITE_MICROSPHERE 深青 — 还原苄醇
    "CPD4_VANNH2":  "#856B8F",  # 同 COMPOSITE_GEL 灰紫 — 胺解单体
    # 合成终产物（改性透明质酸）直接用 MATERIAL["MOD_HA"] = #3E739E
}

# ── 2.3 基底材料：仅黏附图使用（语义 = 人工植入物 vs 生物组织）──
SUBSTRATE = {
    "TI64":   "#2B5C8F",  # 钛青蓝 — Ti-6Al-4V (TC4)
    "SS316L": "#4A7BB0",  # 钢青蓝 — 316L 不锈钢
    "PEEK":   "#7895B2",  # 雾灰蓝 — PEEK
    "BONE":   "#D96B43",  # 陶土橙 — 骨组织（生物）
    "SKIN":   "#E8997A",  # 暖珊瑚 — 猪皮组织（生物）
}

# ── 2.4 中性色与功能性颜色 ──
NEUTRAL = {
    "AXIS":          "#1A1A1A",  # 坐标轴、刻度线
    "TEXT":          "#262626",  # 刻度和图例文字
    "ANNOT":         "#303030",  # 峰位/基团标注文字
    "GUIDE":         "#9A9A9A",  # 竖直指引虚线（仅在需要时使用）
    "BAND":          "#BFBFBF",  # 特征带阴影（FTIR 归属窗口，alpha 见下）
    "BAND_ALPHA":    "#000000",  # 占位（不使用；alpha 见 BAND_ALPHA_VALUE）
    "SOLVENT":       "#CCCCCC",  # 溶剂峰截顶标记
    "ERRORBAR":      "#1A1A1A",  # 误差棒
    "HIGHLIGHT":     "#C0392B",  # 需要强调的单一对照（慎用，全图最多 1 处）
    "CTRL":          "#9E9E9E",  # 未处理/介质对照柱（柱状图、曲线的 baseline 组）
}
BAND_ALPHA_VALUE = 0.32  # 特征带阴影透明度

PALETTE = {**MATERIAL, **SYNTHESIS, **SUBSTRATE, **NEUTRAL}


def c(token: str) -> str:
    """按 token 取色。c('MOD_HA') → '#3E739E'。"""
    if token not in PALETTE:
        raise KeyError(f"未知颜色 token '{token}'；可用：{sorted(PALETTE)}")
    return PALETTE[token]


# ══════════════════════════════════════════════════════════════════════════════
# 3. 字号层级（pt）
# ══════════════════════════════════════════════════════════════════════════════
# 【硬约束】Nature QA：导出 PDF 中每一个字形（含 mathtext 上下标）都必须 ≥ 5.0 pt。
# matplotlib 把上下标硬编码缩到母体的 0.7×（SHRINK_FACTOR），
# 因此任何含 `^` 或 `_` 的文字，母体必须 ≥ 5.0 / 0.7 = 7.15 pt。
# Arial 不含 Unicode 下标(₂ U+2082)与上标正负号(⁺ U+207A / ⁻ U+207B)，
# 只能用 mathtext，故本条不可绕过。
MIN_GLYPH_PT = 5.0
SCRIPT_SHRINK = 0.7
MIN_PARENT_FOR_SCRIPT = MIN_GLYPH_PT / SCRIPT_SHRINK   # ≈ 7.143

FONT = {
    "panel":  9.5,                 # 分图字母 a / b （Bold；脚本不加，拼版时用）
    "axis":   8.5,                 # 坐标轴标题（Bold）
    "tick":   8.0,                 # 刻度数字（无上下标）
    "legend": 7.5,                 # 图例
    "annot":  7.2,                 # 峰位 / 基团标注（含 COO$^{-}$、H$_2$ 等）
    "note":   6.5,                 # 图内小注：★禁止出现任何 mathtext 上下标★
}


def script_safe(size_key: str = "annot") -> float:
    """返回满足 5 pt 字形下限、可用于含上下标文字的字号。"""
    return max(FONT[size_key], MIN_PARENT_FOR_SCRIPT)


# ══════════════════════════════════════════════════════════════════════════════
# 4. 全局样式
# ══════════════════════════════════════════════════════════════════════════════
def apply() -> None:
    """一键应用项目全局绘图样式（每个脚本在 plt.subplots 之前调用一次）。"""
    mpl.rcParams.update({
        # 字体
        "font.family": "Arial",
        "font.sans-serif": ["Arial"],
        "font.size": FONT["tick"],
        "mathtext.fontset": "custom",
        "mathtext.rm": "Arial",
        "mathtext.it": "Arial:italic",
        "mathtext.bf": "Arial:bold",
        "mathtext.sf": "Arial",
        # 矢量可编辑（必须项）
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        # 坐标轴：**四边框 + 内向刻度**（对齐参考论文版式）
        "axes.spines.top": True,
        "axes.spines.right": True,
        "axes.linewidth": 0.8,
        "axes.edgecolor": NEUTRAL["AXIS"],
        "axes.labelcolor": NEUTRAL["AXIS"],
        "axes.labelweight": "bold",
        "axes.labelsize": FONT["axis"],
        "axes.titlesize": FONT["axis"],
        "axes.titleweight": "bold",
        # 刻度：四边内向
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "xtick.color": NEUTRAL["AXIS"],
        "ytick.color": NEUTRAL["AXIS"],
        "xtick.labelsize": FONT["tick"],
        "ytick.labelsize": FONT["tick"],
        # 图例：无边框
        "legend.frameon": False,
        "legend.fontsize": FONT["legend"],
        "legend.handlelength": 1.3,
        "legend.handletextpad": 0.45,
        "legend.labelspacing": 0.24,
        "legend.borderpad": 0.0,
        "legend.borderaxespad": 0.0,
        # 线条
        "lines.linewidth": 0.85,
        "lines.solid_capstyle": "round",
        "lines.antialiased": True,
        # 画布
        "figure.facecolor": "#FFFFFF",
        "axes.facecolor": "#FFFFFF",
        "figure.dpi": 120,
        "savefig.facecolor": "#FFFFFF",
        "grid.alpha": 0.0,
    })


# ══════════════════════════════════════════════════════════════════════════════
# 5. 常用装饰
# ══════════════════════════════════════════════════════════════════════════════
def panel_letter(ax, letter: str) -> None:
    """在图外侧左上角放分图字母（a / b / c ...）。"""
    ax.text(-0.16, 1.06, letter, transform=ax.transAxes,
            fontsize=FONT["panel"], fontweight="bold",
            color=NEUTRAL["AXIS"], ha="left", va="bottom")


def align_edge_ticks(ax) -> None:
    """把 x 轴首/末刻度数字向内对齐，避免溢出坐标框压住轴标题。"""
    labels = ax.get_xticklabels()
    if labels:
        labels[0].set_horizontalalignment("left")
        labels[-1].set_horizontalalignment("right")


def strip_yticks(ax) -> None:
    """隐藏 y 轴刻度**数字**但保留刻度线——四边框样式下这样才完整。"""
    ax.tick_params(labelleft=False, labelright=False)
    if not ax.get_yticks().size:
        ax.set_yticks(np.linspace(*ax.get_ylim(), 5)[1:-1])


def assign_label_tiers(positions, min_gap: float) -> list[int]:
    """贪心分层：同层内任意两点的水平间距 ≥ min_gap；返回每点的层号（0 起）。

    用于标签自动错排，避免"标注乱飞"（DESIGN.md §5.1）。层号即纵向偏移倍数。
    """
    tiers: list[list[float]] = []
    out: list[int] = []
    for p in positions:
        for i, tier in enumerate(tiers):
            if all(abs(p - q) >= min_gap for q in tier):
                tier.append(p)
                out.append(i)
                break
        else:
            tiers.append([p])
            out.append(len(tiers) - 1)
    return out


PT_TO_MM = 25.4 / 72.0   # 1 pt = 0.3528 mm


def estimate_text_width_mm(text: str, size_pt: float, char_factor: float = 0.52) -> float:
    """粗估 Arial 文字渲染宽度（mm）。仅供无渲染上下文时使用；优先用 measure_text_widths_mm。"""
    plain = text.replace("\n", " ")
    return len(plain) * char_factor * size_pt * PT_TO_MM


def measure_text_widths_mm(ax, texts, size_pt: float) -> list[float]:
    """用 matplotlib 渲染器实测一批文字的宽度（mm）。比字符数估算精确，无逐条重绘开销。

    做法：把全部文字以不可见临时对象加入坐标系 → 一次 draw → 逐条取 window_extent → 删除。
    """
    return measure_text_boxes_mm(ax, texts, size_pt)[0]


def measure_text_boxes_mm(ax, texts, size_pt: float):
    """实测一批文字的 (宽度列表, 最大高度)（mm）。高度含 ascent/descent，大于名义字号。"""
    fig = ax.figure
    probes = []
    for s in texts:
        t = ax.text(0.5, 0.5, s, fontsize=size_pt, transform=ax.transAxes)
        t.set_alpha(0.0)          # 用 alpha=0 而非 visible=False：
        probes.append(t)          # 不可见 artist 的 window_extent 会退化成 0×0
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_px = 25.4 / fig.dpi
    widths, h_max = [], 0.0
    for t in probes:
        try:
            bb = t.get_window_extent(renderer)
            if bb.width > 0 and bb.height > 0:
                widths.append(bb.width * mm_per_px)
                h_max = max(h_max, bb.height * mm_per_px)
            else:
                raise ValueError("degenerate bbox")
        except Exception:
            widths.append(estimate_text_width_mm(t.get_text(), size_pt))
            h_max = max(h_max, size_pt * PT_TO_MM * 1.2)
        t.remove()
    return widths, h_max


def place_trace_labels(ax, items, *, base_y, text_h, tier_step, mm_per_unit,
                       floor_of, ceil_of, color, fontsize, leader_color=None,
                       obstacles=None):
    """把一组峰位标签放进"本层峰顶 ↔ 上一条谱线"之间的空闲带。

    items      : [(x, text, peak_y), ...]，peak_y 为相对本层基线的峰高
    floor_of   : callable(x, half_width) -> 该横跨范围内本层曲线的最高点（绝对 y）
    ceil_of    : callable(x, half_width) -> 该横跨范围内上一条谱线的最低点（绝对 y），无则 inf
    obstacles  : [(x0, x1, y0, y1), ...] 事先占位的固定文字框（如溶剂名、面板标题），
                 单位与坐标轴数据一致；标签不得压到它们
    返回 (已放置数, 弃用列表)。保证：不压线、不压其他标签、不压固定文字。
    """
    if leader_color is None:
        leader_color = NEUTRAL["GUIDE"]
    # 实测宽度（精确）→ 层间距与碰撞检测都用它
    widths = measure_text_widths_mm(ax, [t for _, t, _ in items], fontsize)
    min_gap = (max(widths) + 2.0) / mm_per_unit if items else 1.0
    tiers = assign_label_tiers([x for x, _, _ in items], min_gap)

    placed_boxes: list[tuple[float, float, float, float]] = list(obstacles or [])
    dropped: list[str] = []

    # 画框四边（数据坐标）。NMR 的 x 轴反向，故用 sorted 取区间端点。
    d_lo, d_hi = sorted(ax.get_xlim())
    y_lo, y_hi = sorted(ax.get_ylim())
    inset = 1.2 / mm_per_unit if mm_per_unit > 0 else 0.0    # 标签距画框的最小净空（mm）

    for (x, text, peak_y), tier, w_mm in zip(items, tiers, widths):
        half_w = w_mm / 2.0 / mm_per_unit
        # 标签横向必须落在画框内：越界则向内吸附；比画框还宽则弃用
        if d_hi - d_lo < 2.0 * (half_w + inset):
            dropped.append(f"{text} @ {x:.2f} (标签宽于画框)")
            continue
        x = min(max(x, d_lo + half_w + inset), d_hi - half_w - inset)
        floor = floor_of(x, half_w)
        ceil = ceil_of(x, half_w)

        def box_free(ty: float) -> bool:
            if ty < floor - 1e-9 or ty + text_h > ceil + 1e-6:
                return False
            # 纵向也不得越出画框（否则会被裁切或压住上边框）
            if ty < y_lo - 1e-9 or ty + text_h > y_hi - inset + 1e-9:
                return False
            for bx0, bx1, by0, by1 in placed_boxes:
                if x - half_w < bx1 and x + half_w > bx0 and ty < by1 and ty + text_h > by0:
                    return False
            return True

        # 已占用区间（与本次横跨范围有交叠的）
        occupied = sorted((by0, by1) for bx0, bx1, by0, by1 in placed_boxes
                          if x - half_w < bx1 and x + half_w > bx0)
        y_cursor = floor
        for by0, by1 in occupied:
            if y_cursor + text_h <= by0 + 1e-9:
                break
            y_cursor = max(y_cursor, by1 + 0.8)

        candidates = [base_y + t * tier_step for t in [tier, 0, 1, 2, 3]]
        candidates += [y_cursor, ceil - text_h, floor]
        ty = next((c for c in candidates if box_free(c)), None)
        if ty is None:
            dropped.append(f"{text} @ {x:.2f}")
            continue

        placed_boxes.append((x - half_w, x + half_w, ty, ty + text_h))
        if peak_y is not None:
            ax.plot([x, x], [peak_y, ty - 0.6], color=leader_color, lw=0.55, zorder=3)
        ax.text(x, ty, text, fontsize=fontsize, ha="center", va="bottom",
                color=color, zorder=4)
    return len(placed_boxes), dropped


def top_space_for_tiers(n_tiers: int, text_h_mm: float, axes_h_mm: float,
                        y_span_wo_top: float, margin_units: float = 8.0):
    """闭式解：为 n 层文字预留的顶部空间（数据单位）。

    设 A=axes 高(mm)、t=一行字高(mm)、R=不含顶部预留的 y 跨度(数据单位)，
    需要满足  n·t ≤ A·(top/(R+top))  →  top = (n·t·R/A + m) / (1 − n·t/A)
    返回 None 表示该画布物理上放不下这么多层（应放大画布或减少标签）。
    """
    A = max(axes_h_mm, 1e-6)
    frac = n_tiers * text_h_mm / A
    if frac >= 0.92:
        return None
    return (frac * y_span_wo_top + margin_units) / (1.0 - frac)


def place_labels(ax, xs, ys, texts, *, x_lines=None, y_lines=None,
                 direction: str = "north", fontsize: str | float | None = None,
                 color: str | None = None, draw_lines: bool = False,
                 margin: float = 0.02, min_distance: float = 0.03,
                 nbr_candidates: int = 80):
    """★ 统一标注入口：用 textalloc 自动放置标签，避开**曲线 / 图框 / 其他标签**。

    xs, ys   : 每个标签的锚点（数据坐标）
    x_lines,
    y_lines  : 需要避让的曲线（list of arrays）；NaN 会被自动过滤
    direction: north / south / east / west / northeast / ...（只朝该方向摆）
    margin / min_distance : 距图框 / 标签之间的最小间距（轴尺寸的比例）
                            0.02 / 0.03 为本项目实测可用的最紧凑值
    draw_lines: 是否画引线（锚点 → 文字）

    失败（库缺失或数据异常）时打印警告并原地退化为 ax.text，不中断出图。
    """
    fontsize = FONT["annot"] if fontsize is None else fontsize
    color = NEUTRAL["ANNOT"] if color is None else color
    try:
        import textalloc as ta
    except ImportError:
        print("[figure_style] 未安装 textalloc，退化为直接放文字（可能有重叠）")
        for x, y, t in zip(xs, ys, texts):
            ax.text(x, y, t, ha="center", va="bottom", fontsize=fontsize,
                    color=color, zorder=5)
        return False

    def _finite(arr):
        import numpy as _np
        out = []
        for a in (arr or []):
            a = _np.asarray(a, dtype=float)
            out.append(a[_np.isfinite(a)])
        return out

    xl, yl = _finite(x_lines), _finite(y_lines)
    try:
        ta.allocate(ax, list(xs), list(ys), list(texts),
                    x_lines=xl or None, y_lines=yl or None,
                    textsize=fontsize, textcolor=color,
                    direction=direction, draw_lines=draw_lines,
                    margin=margin, min_distance=min_distance,
                    nbr_candidates=nbr_candidates)
        return True
    except Exception as exc:
        print(f"[figure_style] textalloc 放置失败（{type(exc).__name__}: {exc}）；退化为直接放文字")
        for x, y, t in zip(xs, ys, texts):
            ax.text(x, y, t, ha="center", va="bottom", fontsize=fontsize,
                    color=color, zorder=5)
        return False


def place_band_labels(ax, centers, y_top, texts, *, x_lines=None, y_lines=None,
                      fontsize=None, color=None, mm_margin: float = 1.2,
                      top_limit: float | None = None):
    """★ 归属窗口标签的最优放置（实测结论）：

    ① **优先按层对齐**——同类标签排在同一水平层，整齐（参考论文就是这么做的）；
    ② 顶部空间放不下所需层数时，**退回 textalloc 自由放置**——不整齐但保证零重叠。

    实测：纯 textalloc 虽然能消重叠，但排版呈"阶梯状散落"，观感反而不如分层。
    返回 'tiered' / 'textalloc' / 'fallback'。
    """
    fontsize = FONT["annot"] if fontsize is None else fontsize
    color = NEUTRAL["ANNOT"] if color is None else color

    fig = ax.figure
    fig.canvas.draw()
    bb = ax.get_window_extent()
    mm_per_px = 25.4 / fig.dpi
    w_mm, h_mm = abs(bb.width) * mm_per_px, abs(bb.height) * mm_per_px
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    mm_per_unit_x = w_mm / max(abs(x0 - x1), 1e-6)
    mm_per_unit_y = h_mm / max(abs(y1 - y0), 1e-6)

    widths, text_h = measure_text_boxes_mm(ax, list(texts), fontsize)
    tiers = assign_label_tiers(list(centers), (max(widths) + 1.0) / mm_per_unit_x)
    n_tiers = max(tiers) + 1
    step = (text_h * 1.10) / mm_per_unit_y
    text_h_u = text_h / mm_per_unit_y
    margin_y = mm_margin / mm_per_unit_y
    need_units = (n_tiers - 1) * step + text_h_u
    avail_units = max(0.0, y1 - y_top - margin_y)            # 锚点之上、上边框之下
    lo_edge, hi_edge = min(x0, x1), max(x0, x1)
    margin_x = mm_margin / mm_per_unit_x

    if need_units <= avail_units:
        # 分层放置：**自顶向下锚定**，保证顶层文字不贴上边框；
        # 横向按实测宽度逐个钳制进框内（越框的只平移，不整组降级）。
        if top_limit is None:
            top_limit = y1 - margin_y
        else:
            top_limit = min(top_limit, y1 - margin_y)
        for c, t, tier, w in zip(centers, texts, tiers, widths):
            half = (w / 2) / mm_per_unit_x
            xs = min(max(c, lo_edge + half + margin_x), hi_edge - half - margin_x)
            ty = max(top_limit - text_h_u - (n_tiers - 1 - tier) * step, y_top)
            ax.text(xs, ty, t, ha="center", va="bottom",
                    fontsize=fontsize, color=color, zorder=5)
        return "tiered"

    # 兜底：交给 textalloc（不整齐但绝不重叠/压线）
    ok = place_labels(ax, list(centers), [y_top] * len(centers), list(texts),
                      x_lines=x_lines, y_lines=y_lines, direction="north",
                      fontsize=fontsize, color=color)
    return "textalloc" if ok else "fallback"


def shade_band(ax, lo: float, hi: float, alpha: float = BAND_ALPHA_VALUE,
               ymin: float = 0.0, ymax: float = 1.0) -> None:
    """FTIR 特征归属窗口：浅灰阴影带（替代虚线，避免线穿文字）。

    ymin/ymax 为轴坐标比例；底部预留图例带时可设 ymin>0，让阴影带**不侵入图例区**，
    否则图例文字会压在灰带上显得脏。
    """
    ax.axvspan(lo, hi, ymin=ymin, ymax=ymax,
               color=NEUTRAL["BAND"], alpha=alpha, lw=0.0, zorder=0)


def export(fig, base_path, dpi: int = 600, audit: bool = True) -> None:
    """一键导出 4 种格式：svg / pdf / png / tiff，并自动审计 PDF 字形下限。"""
    base = Path(base_path)
    if base.suffix:
        base = base.with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)
    # 画布尺寸 = 版面里的最终占位尺寸，**不裁 tight**：
    # tight 会把画布按内容缩小（90 mm 的画布存成 80.8–88.5 mm 不等），
    # 既对不上拼版栅格，又把 subplots_adjust 留出的边距一起吃掉——
    # 在 Tavotto 里就变成「四周没有余量、刻度/轴标题拖不动」。
    fig.savefig(base.with_suffix(".svg"), facecolor="white")
    pdf_path = base.with_suffix(".pdf")
    fig.savefig(pdf_path, facecolor="white")
    png = base.with_suffix(".png")
    fig.savefig(png, dpi=dpi, facecolor="white")
    try:
        from PIL import Image
        with Image.open(png) as im:
            im.save(base.with_suffix(".tiff"), compression="tiff_lzw", dpi=(dpi, dpi))
    except Exception as exc:  # PIL 缺失时至少保证前三种格式
        print(f"[figure_style] TIFF 写出失败（{exc}），已保留 svg/pdf/png")

    if not pdf_path.exists():
        # 宿主接管 savefig 时（Tavotto 的「试运行探测」在 safe 档只捕获图形对象、
        # 不落盘）这里没有 PDF 可审计。直接跳过——不能把 FileNotFoundError 当成
        # 脚本执行失败，那会把整次试运行判死。
        print(f"[figure_style] {base.name}: savefig 未落盘（被宿主接管），跳过字形审计")
        return
    print(f"[figure_style] 导出完成: {base.name}.[svg|pdf|png|tiff]")

    if audit:
        ok, bad = audit_pdf(pdf_path)
        if ok:
            print(f"[字形审计] {base.name}.pdf: 全部字形 ≥ {MIN_GLYPH_PT} pt ✓")
        else:
            print(f"[字形审计] {base.name}.pdf: {len(bad)} 处跌破 {MIN_GLYPH_PT} pt ✗")
            for size, txt in bad[:8]:
                print(f"           {size} pt  «{txt}»")


# ══════════════════════════════════════════════════════════════════════════════
# 6. 出图前 QA：文字重叠自检
# ══════════════════════════════════════════════════════════════════════════════
def find_text_overlaps(fig, min_area_px: float = 4.0) -> list[str]:
    """
    渲染后检查所有文字对象（轴标题、刻度、图例、标注、分图字母）的包围盒，
    返回互相重叠的文本对列表。空列表 = 通过。

    只报告“真实重叠”（交叠面积 > min_area_px），忽略刻度数字之间的正常邻接。
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    items: list[tuple[str, object, bool]] = []
    for ax in fig.axes:
        tick_ids = set()
        for t in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            tick_ids.add(id(t))
            items.append((t.get_text(), t, True))
        cands = [ax.title, ax.xaxis.label, ax.yaxis.label]
        cands += list(ax.texts)
        leg = ax.get_legend()
        if leg is not None:
            cands += list(leg.get_texts())
        for t in cands:
            if t is not None:
                items.append((t.get_text(), t, id(t) in tick_ids))
    for t in fig.texts:
        items.append((t.get_text(), t, False))

    boxes = []
    for label, t, is_tick in items:
        if not str(label).strip():
            continue
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        boxes.append((label, bb, is_tick))

    problems = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            la, ba, ta = boxes[i]
            lb, bb_, tb = boxes[j]
            if ta and tb:          # 两个刻度数字之间不判
                continue
            if la == lb and ba.bounds == bb_.bounds:
                continue
            dx = min(ba.x1, bb_.x1) - max(ba.x0, bb_.x0)
            dy = min(ba.y1, bb_.y1) - max(ba.y0, bb_.y0)
            if dx > 0 and dy > 0 and dx * dy > min_area_px:
                problems.append(
                    f"重叠 {dx * dy:6.1f}px²  «{la}»  ×  «{lb}»"
                )
    return problems


def find_text_over_data(fig, pad_px: float = 0.0) -> list[str]:
    """检测「文字压在数据曲线上」。返回冲突列表；空列表 = 通过。

    对每条真实谱线（顶点数 > 2 的 Line2D）取所有采样点，变换到显示坐标后
    与每个文字的包围盒求交。装饰性线段（基线、引线，顶点数 ≤ 2）自动跳过。

    取的是 `Line2D` **自己的** transform，不是 `ax.transData`：脚本给曲线挂了
    `ScaledTranslation`（纯显示位移）时，用 ax.transData 算出来的位置是**没位移**
    的那一份，压线检查会对着一个不存在的几何下结论。
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    problems: list[str] = []

    for ax in fig.axes:
        texts: list[tuple[str, object]] = []
        for t in ax.texts:
            if t.get_text().strip():
                texts.append((t.get_text(), t))
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                if t.get_text().strip():
                    texts.append((t.get_text(), t))
        if not texts:
            continue

        boxes = []
        for label, t in texts:
            try:
                bb = t.get_window_extent(renderer)
            except Exception:
                continue
            if bb.width <= 0 or bb.height <= 0:
                continue
            boxes.append((label, bb))

        for ln in ax.lines:
            xy = ln.get_xydata()
            if len(xy) <= 2:            # 基线 / 引线等装饰线段
                continue
            disp = ln.get_transform().transform(xy)
            for label, bb in boxes:
                hit = ((disp[:, 0] >= bb.x0 - pad_px) & (disp[:, 0] <= bb.x1 + pad_px) &
                       (disp[:, 1] >= bb.y0 - pad_px) & (disp[:, 1] <= bb.y1 + pad_px))
                n = int(hit.sum())
                if n:
                    problems.append(f"压线 {n:5d} 点  «{label[:30]}»")
    return problems


def check_edge_clearance(fig, min_mm: float = 1.0) -> list[str]:
    """检查文字/图例与坐标框边缘的净空是否足够（默认要求 ≥1.5 mm）。

    过窄（如 0.9 mm）时视觉上会"贴住边框"，看起来像压线——本函数专门抓这一类。
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_px = 25.4 / fig.dpi
    out: list[str] = []
    for ax in fig.axes:
        axbb = ax.get_window_extent()
        items: list[tuple[str, object]] = [(t.get_text(), t) for t in ax.texts
                                           if t.get_text().strip()]
        leg = ax.get_legend()
        if leg is not None:
            items.append(("<legend>", leg))
            items += [(t.get_text(), t) for t in leg.get_texts()]
        for label, obj in items:
            try:
                bb = obj.get_window_extent(renderer)
            except Exception:
                continue
            if bb.width <= 0:
                continue
            gaps = {"上": (axbb.y1 - bb.y1), "下": (bb.y0 - axbb.y0),
                    "左": (bb.x0 - axbb.x0), "右": (axbb.x1 - bb.x1)}
            for side, gap_px in gaps.items():
                # 只报"贴边且仍在框内"的情况（在框外的由 find_text_over_data 等负责）
                if -0.5 < gap_px * mm_per_px < min_mm:
                    out.append(f"贴{side}边框 {gap_px * mm_per_px:.2f} mm  «{label[:26]}»")
    return out


def qa_report(fig, name: str = "figure") -> bool:
    """出图前 QA：① 上下标字号下限 ② 文字互相重叠 ③ 文字压在曲线上。"""
    ok = True

    # ① 含 mathtext 上下标的文字，母体字号必须 ≥ MIN_PARENT_FOR_SCRIPT
    offenders = _script_size_violations(fig)
    if offenders:
        ok = False
        print(f"[QA] {name}: {len(offenders)} 处上下标字号跌破字形下限 ✗")
        for s in offenders:
            print(f"       {s}")
    else:
        print(f"[QA] {name}: 上下标字号达标 ✓")

    # ② 文字互相重叠
    problems = find_text_overlaps(fig)
    if problems:
        ok = False
        print(f"[QA] {name}: 发现 {len(problems)} 处文字重叠 ✗")
        for p in problems:
            print("      ", p)
    else:
        print(f"[QA] {name}: 文字无重叠 ✓")

    # ③ 文字压在数据曲线上
    on_data = find_text_over_data(fig)
    if on_data:
        ok = False
        print(f"[QA] {name}: 发现 {len(on_data)} 处文字压线 ✗")
        for p in on_data:
            print("      ", p)
    else:
        print(f"[QA] {name}: 文字未压线 ✓")

    # ④ 元素距边框的净空（过窄 → 视觉上像贴边/压线）
    tight = check_edge_clearance(fig)
    if tight:
        ok = False
        print(f"[QA] {name}: 发现 {len(tight)} 处贴边（净空 < 1.0 mm）✗")
        for p in tight:
            print("      ", p)
    else:
        print(f"[QA] {name}: 边缘净空充足 ✓")
    return ok


def _script_size_violations(fig) -> list[str]:
    """扫描所有文字对象：含 $...^...$ / $..._...$ 的，母体字号须 ≥ 7.15 pt。"""
    import re
    script_re = re.compile(r"\$[^$]*[\\^_][^$]*\$")
    out = []
    for ax in fig.axes:
        texts = list(ax.texts) + [ax.title, ax.xaxis.label, ax.yaxis.label]
        texts += list(ax.get_xticklabels()) + list(ax.get_yticklabels())
        leg = ax.get_legend()
        if leg is not None:
            texts += list(leg.get_texts())
        texts += list(fig.texts)
        for t in texts:
            if t is None:
                continue
            s = t.get_text()
            if not script_re.search(s):
                continue
            size = float(t.get_fontsize())
            if size * SCRIPT_SHRINK < MIN_GLYPH_PT - 1e-9:
                out.append(f"{size:.1f} pt → 字形 {size * SCRIPT_SHRINK:.2f} pt  «{s[:34]}»")
    return out


def audit_pdf(path, min_pt: float = MIN_GLYPH_PT) -> tuple[bool, list[tuple[float, str]]]:
    """
    导出后终极校验：直接读 PDF 里每个字形的真实渲染尺寸（含上下标）。
    返回 (是否通过, [(字号, 文本片段), ...])。需要 pymupdf。
    """
    try:
        import collections

        import pymupdf
    except ImportError:
        print("[audit_pdf] 未安装 pymupdf，跳过 PDF 字形审计（pip install pymupdf）")
        return True, []

    doc = pymupdf.open(str(path))
    bad: list[tuple[float, str]] = []
    for page in doc:
        d = page.get_text("dict")
        for block in d["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if txt and round(span["size"], 2) < min_pt:
                        bad.append((round(span["size"], 2), txt[:34]))
    doc.close()
    unique = collections.OrderedDict((b, None) for b in bad)
    return (not bad), list(unique)

