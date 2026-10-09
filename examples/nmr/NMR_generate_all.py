#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成标准学术出版级核磁系列图件：
1. 四张独立子图（结构式 + 独立溶剂核磁谱图 + 红字编号对应）：
   - Fig_S1_Compound2_NMR.png / pdf
   - Fig_S2_Compound3_NMR.png / pdf
   - Fig_S3_Compound4_NMR.png / pdf
   - Fig_S4_HAMBDA_NMR.png / pdf
2. 一张 2x2 大组合总图（Figure 2: 分子合成与多重接枝表征总图）：
   - Fig2_NMR_Combined_2x2.png / pdf / svg
"""

import pathlib

import sys
from pathlib import Path as _P
sys.path.insert(0, str(next(p for p in _P(__file__).resolve().parents
                             if (p / "figure_style.py").is_file())))
import figure_style as fs

import nmrglue as ng
import matplotlib.pyplot as plt
import matplotlib as mpl
from PIL import Image
import numpy as np

# ===== 1. 全局配置 =====
ROOT = pathlib.Path(__file__).parent
DATA_ROOT = ROOT / "核磁原始数据"
STRUCT_ROOT = pathlib.Path("tmp/pdfs/hama/structures")

mpl.rcParams["font.family"] = "Arial"
mpl.rcParams["axes.linewidth"] = 0.8
mpl.rcParams["mathtext.fontset"] = "stixsans"
DPI = 600

# 通用谱图读取与预处理函数
def load_and_process_spec(rel_path, solv_ppm=None, solv_w=0.06, norm_val=22):
    p = DATA_ROOT / pathlib.Path(rel_path) / "pdata" / "1"
    dic, data = ng.bruker.read_pdata(str(p))
    udic = ng.bruker.guess_udic(dic, data)
    uc = ng.fileiobase.uc_from_udic(udic)
    ppm = uc.ppm_scale()
    spec = data.astype(float) - np.median(data)
    
    if solv_ppm is not None:
        solv_mask = (ppm >= (solv_ppm - solv_w)) & (ppm <= (solv_ppm + solv_w))
        solute_max = np.max(spec[(~solv_mask) & (ppm >= 0) & (ppm <= 11)])
        spec_norm = (spec / solute_max) * norm_val
        spec_norm[solv_mask] = np.clip(spec_norm[solv_mask], -5, norm_val * 1.35)
    else:
        spec_norm = (spec / np.max(spec)) * norm_val
        
    return ppm, spec_norm

# ==============================================================================
# 2. 单独绘制一个样品的“结构式 + 单张核磁”标准图
# ==============================================================================
def draw_single_nmr_panel(ax, struct_img_path, rel_path, title_text, solv_text,
                          solv_ppm, solv_w, ppm_left, ppm_right, peak_items,
                          color=fs.c("CPD3_VANOH"), struct_width_ratio=0.28):
    """
    在指定的 Axes 区域内绘制：左侧结构式 + 右侧单溶剂核磁谱图
    """
    ppm, spec = load_and_process_spec(rel_path, solv_ppm, solv_w, norm_val=22)
    mask = (ppm >= ppm_right) & (ppm <= ppm_left)
    
    # 绘制谱线与基线
    ax.plot(ppm[mask], spec[mask], color=color, lw=0.75, zorder=2)
    ax.axhline(0, color="#E5E5E5", lw=0.45, ls="--", zorder=1)

    # ★ 必须先固定坐标范围：下面的字号→数据单位换算、标签边界钳位都依赖它。
    #   （曾把 set_xlim/ylim 放在放标签之后 → 换算用了默认 (0,1) 区间，
    #     导致窄面板里的峰标签溢出画框。）
    ax.set_xlim(ppm_left, ppm_right)
    ax.set_ylim(-4, 44)   # 顶部留白足够，避免峰标注贴住上边框
    
    # 精确峰顶吸附 + 自动放置（不压线、不压其他标签；颜色跟随谱线）
    items = []
    for approx_p, label_text, _dy in peak_items:
        w = np.where(np.abs(ppm - approx_p) <= 0.15)[0]
        if len(w) > 0:
            idx_m = w[np.argmax(spec[w])]
        else:
            idx_m = np.argmin(np.abs(ppm - approx_p))
        # 双行标签在本画布内放不下（层高翻倍 → 层数减半），统一压成单行
        items.append((ppm[idx_m], label_text.replace("\n", " "), spec[idx_m]))

    fig = ax.figure
    fig.canvas.draw()
    mm_per_px = 25.4 / fig.dpi
    bb = ax.get_window_extent()
    y0, y1 = ax.get_ylim()
    span_x = abs(ppm_left - ppm_right) or 1.0
    mm_per_ppm = bb.width * mm_per_px / span_x
    mm_per_au = bb.height * mm_per_px / max(y1 - y0, 1e-9)
    font_pt = fs.script_safe("annot")
    # 用实测包围盒高度（这些标签是双行，名义字号会低估约一倍）
    _w, _h_mm = fs.measure_text_boxes_mm(ax, [t for _, t, _ in items], font_pt)
    text_h = _h_mm / mm_per_au

    def _floor(x, hw, p=ppm, s=spec):
        m = (p >= x - hw) & (p <= x + hw)
        return float(np.max(s[m])) + 0.8 if m.any() else 0.8

    # 面板标题（图外左上）的包围盒换算到数据坐标，作为不可侵占的障碍区
    fig.canvas.draw()
    _rend = fig.canvas.get_renderer()
    _tb = ax.title.get_window_extent(_rend)
    _inv = ax.transData.inverted()
    (_tx0, _ty0), (_tx1, _ty1) = _inv.transform([(_tb.x0, _tb.y0), (_tb.x1, _tb.y1)])
    obstacles = [(min(_tx0, _tx1), max(_tx0, _tx1), min(_ty0, _ty1), max(_ty0, _ty1))]

    n, dropped = fs.place_trace_labels(
        ax, items, base_y=max(it[2] for it in items) + 3.0,
        text_h=text_h, tier_step=text_h + 1.2, mm_per_unit=mm_per_ppm,
        floor_of=_floor, ceil_of=lambda x, hw: np.inf,
        color=color, fontsize=font_pt, obstacles=obstacles)
    if dropped:
        print(f"  [标注弃用] {title_text}: {dropped}")
        
    ax.set_xlabel("Chemical Shift $\\delta$ (ppm)", fontsize=fs.FONT["axis"],
                  weight="bold", labelpad=3)
    # 与 XRD / FTIR 统一：刻度朝内、四边闭合框（不设 direction，继承全局设置）
    ax.tick_params(length=3.0, width=0.8, labelsize=fs.FONT["tick"], pad=3)
    ax.set_yticks([])

    for sp in ax.spines.values():
        sp.set_visible(True)
        sp.set_color(fs.c("AXIS"))
        sp.set_linewidth(0.8)

    # 标题与溶剂信息
    ax.set_title(f"{title_text} ({solv_text})", fontsize=fs.FONT["panel"],
                 weight="bold", pad=6, loc="left")

# 各样品的红字编号配置（完全对齐分子式.pptx！）
CONFIG_C2 = {
    "title": "(a) Compound 2 (KY-2)",
    "solv": "in CDCl$_3$, 500 MHz",
    "rel": "2/1", "solv_ppm": 7.26, "solv_w": 0.04,
    "ppm_left": 10.5, "ppm_right": 0.5, "color": fs.c("CPD2_VANCHO"),
    "struct": STRUCT_ROOT / "struct_compound2.png",
    "peaks": [
        (9.87, "1\n(9.87)", 0),
        (7.41, "2,3\n(7.41)", 0),
        (6.98, "4\n(6.98)", 0),
        (4.17, "5\n(4.17)", 0),
        (3.92, "9\n(3.92)", 5), # 错开
        (3.70, "8\n(3.70)", 0),
        (2.57, "7\n(2.57)", 0),
        (2.21, "6\n(2.21)", 0),
    ]
}

CONFIG_C3 = {
    "title": "(b) Compound 3",
    "solv": "in CDCl$_3$, 400 MHz",
    "rel": "3/2", "solv_ppm": 7.19, "solv_w": 0.08,
    "ppm_left": 8.0, "ppm_right": 0.5, "color": fs.c("CPD3_VANOH"),
    "struct": STRUCT_ROOT / "struct_compound3.png",
    "peaks": [
        (6.79, "2,3,4\n(6.79)", 0),
        (4.55, "1 (–CH$_2$OH)\n(4.55)", 0),
        (4.02, "6\n(4.02)", 0),
        (3.80, "5\n(3.80)", 5), # 错开
        (3.62, "9\n(3.62)", 0),
        (2.48, "8\n(2.48)", 0),
        (2.08, "7\n(2.08)", 0),
        (1.53, "H$_2$O", 0),
    ]
}

CONFIG_C4 = {
    "title": "(c) Compound 4",
    "solv": "in DMSO-d$_6$, 400 MHz",
    "rel": "4/1", "solv_ppm": 2.50, "solv_w": 0.06,
    "ppm_left": 8.5, "ppm_right": 0.5, "color": fs.c("CPD4_VANNH2"),
    "struct": STRUCT_ROOT / "struct_compound4.png",
    "peaks": [
        (6.88, "2,3,4\n(6.88)", 0),
        (4.40, "1\n(4.40)", 0),
        (3.90, "6\n(3.90)", 0),
        (3.74, "5\n(3.74)", 5), # 错开
        (3.03, "–CH$_2$NH$_2$\n(3.03)", 0),
        (2.50, "DMSO", 0),
        (1.79, "7,8\n(1.79)", 0),
    ]
}

CONFIG_HAMBDA = {
    "title": "(d) Triple-Modified HA (HAMBDA)",
    "solv": "in D$_2$O, 500 MHz",
    "rel": "5/1", "solv_ppm": 4.70, "solv_w": 0.12,
    "ppm_left": 8.5, "ppm_right": 0.5, "color": fs.c("MOD_HA"),
    "struct": STRUCT_ROOT / "struct_hambda.png",
    "peaks": [
        (6.08, "a (=CH$_2$)\n(6.08)", 5),
        (5.67, "b (=CH$_2$)\n(5.67)", 0),
        (4.70, "D$_2$O (//)\n(4.70)", -2),
        (3.65, "HA ring (H$_2$–H$_6$)\n(3.3–3.9)", 3),
        (1.93, "c (–COCH$_3$)\n(1.93)", 0),
    ]
}

# ==============================================================================
# 3. 绘制 2x2 出版级总图 (Figure 2)
# ==============================================================================
fig2x2 = plt.figure(figsize=fs.canvas("GRID2x2"))
gs2x2 = fig2x2.add_gridspec(2, 2, hspace=0.36, wspace=0.25)

configs = [CONFIG_C2, CONFIG_C3, CONFIG_C4, CONFIG_HAMBDA]

for i, cfg in enumerate(configs):
    r, c = divmod(i, 2)
    # 每个 cell 再分为 [结构式, 谱图]
    sub_gs = gs2x2[r, c].subgridspec(1, 2, width_ratios=[0.32, 0.68], wspace=0.08)
    ax_struct = fig2x2.add_subplot(sub_gs[0])
    ax_spec = fig2x2.add_subplot(sub_gs[1])
    
    # 左侧放结构式图片
    if cfg["struct"].exists():
        im = Image.open(cfg["struct"])
        ax_struct.imshow(im)
    ax_struct.axis("off")
    
    # 右侧放对应溶剂的核磁谱图
    draw_single_nmr_panel(
        ax=ax_spec,
        struct_img_path=cfg["struct"],
        rel_path=cfg["rel"],
        title_text=cfg["title"],
        solv_text=cfg["solv"],
        solv_ppm=cfg["solv_ppm"],
        solv_w=cfg["solv_w"],
        ppm_left=cfg["ppm_left"],
        ppm_right=cfg["ppm_right"],
        peak_items=cfg["peaks"],
        color=cfg["color"]
    )

# 导出 2x2 总图
out_2x2 = ROOT / "Fig2_NMR_Combined_2x2.png"
fs.qa_report(fig2x2, "NMR 2×2 组合图")
fig2x2.savefig(out_2x2, dpi=DPI, bbox_inches="tight")
fig2x2.savefig(ROOT / "Fig2_NMR_Combined_2x2.pdf", bbox_inches="tight")
fig2x2.savefig(ROOT / "Fig2_NMR_Combined_2x2.svg", bbox_inches="tight")
print("已生成 2x2 复合总图:", out_2x2)

# ==============================================================================
# 4. 同时导出 4 张独立的 SI 附录图 (Figure S1 ~ S4)
# ==============================================================================
for i, cfg in enumerate(configs):
    fig_si = plt.figure(figsize=fs.canvas("SQ"))
    gs_si = fig_si.add_gridspec(1, 2, width_ratios=[0.30, 0.70], wspace=0.08)
    ax_str = fig_si.add_subplot(gs_si[0])
    ax_spc = fig_si.add_subplot(gs_si[1])
    
    if cfg["struct"].exists():
        im = Image.open(cfg["struct"])
        ax_str.imshow(im)
    ax_str.axis("off")
    
    draw_single_nmr_panel(
        ax=ax_spc,
        struct_img_path=cfg["struct"],
        rel_path=cfg["rel"],
        title_text=cfg["title"],
        solv_text=cfg["solv"],
        solv_ppm=cfg["solv_ppm"],
        solv_w=cfg["solv_w"],
        ppm_left=cfg["ppm_left"],
        ppm_right=cfg["ppm_right"],
        peak_items=cfg["peaks"],
        color=cfg["color"]
    )
    
    si_name = f"Fig_S{i+1}_{cfg['rel'].replace('/', '_')}_NMR.png"
    fs.qa_report(fig_si, f"NMR SI {cfg['rel']}")
    fig_si.savefig(ROOT / si_name, dpi=300, bbox_inches="tight")
    plt.close(fig_si)
    print("已生成独立 SI 图件:", si_name)

print("全部出版级核磁套图生成完毕！")
