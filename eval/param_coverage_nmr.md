# 参数全集覆盖审计报告 - 08 NMR.py

- 脚本: `D:\L\AI\figpact\examples\nmr\08 NMR.py`
- 配置: `D:\L\AI\figpact\examples\nmr\nmr.yaml`
- 总属性数: 159

## 1. 五类属性统计

| 分类 | 属性项数 | 占比 | 简要说明 |
| :--- | :---: | :---: | :--- |
| 已暴露为 YAML 参数 | 72 | 45.3% | 已在配置文件和 list_params 中声明为可编辑参数 |
| 全局样式（figure_style 统一） | 23 | 14.5% | 由统一出版规范锁死（字族、色板、边框/刻度线宽、虚线样式等） |
| 科学锁定（峰位、显示窗、归一化、归属） | 29 | 18.2% | 涉及实验科学真实性（仪器原始数据、显示范围、官能团/峰归属、化学位移定标） |
| 由其他参数派生 | 10 | 6.3% | 由几何约束、实测文本包络框或前序参数算法求解派生，不可单独设置 |
| 未覆盖 | 25 | 15.7% | 属于图元可见特征但尚未归入上述四类的未管辖项 |

## 2. 未覆盖项清单及建议归类

| 序号 | Artist 类型 | GID / 标识 | 属性 | 当前状态 | 建议归类与理由 |
| :---: | :--- | :--- | :--- | :--- | :--- |
| 1 | Line2D (Curve) | `fig2_nmr.main.curve.vancho` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 2 | Line2D (Curve) | `fig2_nmr.main.curve.vanoh` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 3 | Line2D (Curve) | `fig2_nmr.main.curve.vannh2` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 4 | Line2D (Curve) | `fig2_nmr.main.curve.hama` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 5 | Line2D (Guide) | `fig2_nmr.main.guide.vancho.9p83` | linestyle (引线线型：实线/点虚线) | 未覆盖 | 建议归类：全局样式（统一实线细线，避免视觉琐碎） |
| 6 | Text (PeakLabel) | `fig2_nmr.main.peak.vancho.9p83` | rotation (峰标注旋转角) | 未覆盖 | 建议归类：全局样式（统一水平摆放） |
| 7 | Line2D (Guide) | `fig2_nmr.main.guide.hama.6p18` | linestyle (引线线型：实线/点虚线) | 未覆盖 | 建议归类：全局样式（统一实线细线，避免视觉琐碎） |
| 8 | Text (PeakLabel) | `fig2_nmr.main.peak.hama.6p18` | rotation (峰标注旋转角) | 未覆盖 | 建议归类：全局样式（统一水平摆放） |
| 9 | Line2D (Guide) | `fig2_nmr.main.guide.vanoh.4p62` | linestyle (引线线型：实线/点虚线) | 未覆盖 | 建议归类：全局样式（统一实线细线，避免视觉琐碎） |
| 10 | Text (PeakLabel) | `fig2_nmr.main.peak.vanoh.4p62` | rotation (峰标注旋转角) | 未覆盖 | 建议归类：全局样式（统一水平摆放） |
| 11 | Line2D (Guide) | `fig2_nmr.main.guide.vancho.3p91` | linestyle (引线线型：实线/点虚线) | 未覆盖 | 建议归类：全局样式（统一实线细线，避免视觉琐碎） |
| 12 | Text (PeakLabel) | `fig2_nmr.main.peak.vancho.3p91` | rotation (峰标注旋转角) | 未覆盖 | 建议归类：全局样式（统一水平摆放） |
| 13 | Line2D (Guide) | `fig2_nmr.main.guide.vannh2.3p03` | linestyle (引线线型：实线/点虚线) | 未覆盖 | 建议归类：全局样式（统一实线细线，避免视觉琐碎） |
| 14 | Text (PeakLabel) | `fig2_nmr.main.peak.vannh2.3p03` | rotation (峰标注旋转角) | 未覆盖 | 建议归类：全局样式（统一水平摆放） |
| 15 | Line2D (Guide) | `fig2_nmr.main.guide.hama.2p02` | linestyle (引线线型：实线/点虚线) | 未覆盖 | 建议归类：全局样式（统一实线细线，避免视觉琐碎） |
| 16 | Text (PeakLabel) | `fig2_nmr.main.peak.hama.2p02` | rotation (峰标注旋转角) | 未覆盖 | 建议归类：全局样式（统一水平摆放） |
| 17 | Line2D (Guide) | `fig2_nmr.main.guide.vancho.3p68` | linestyle (引线线型：实线/点虚线) | 未覆盖 | 建议归类：全局样式（统一实线细线，避免视觉琐碎） |
| 18 | Text (PeakLabel) | `fig2_nmr.main.peak.vancho.3p68` | rotation (峰标注旋转角) | 未覆盖 | 建议归类：全局样式（统一水平摆放） |
| 19 | Spine(left) | `axes.spine.left.visible` | visible (边框可见性开关) | 未覆盖 | 建议归类：全局样式（figure_style 统一四边框封闭原则） |
| 20 | Spine(right) | `axes.spine.right.visible` | visible (边框可见性开关) | 未覆盖 | 建议归类：全局样式（figure_style 统一四边框封闭原则） |
| 21 | Spine(bottom) | `axes.spine.bottom.visible` | visible (边框可见性开关) | 未覆盖 | 建议归类：全局样式（figure_style 统一四边框封闭原则） |
| 22 | Spine(top) | `axes.spine.top.visible` | visible (边框可见性开关) | 未覆盖 | 建议归类：全局样式（figure_style 统一四边框封闭原则） |
| 23 | XAxis | `axes.xaxis.minor_ticks` | minor_ticks / tick_density (次刻度开关与密度) | 未覆盖 | 建议归类：全局样式（由 figure_style 统一配置 minor_locator，避免各图风格割裂） |
| 24 | YAxis | `axes.yaxis.minor_ticks` | minor_ticks / tick_density (次刻度开关与密度) | 未覆盖 | 建议归类：全局样式（由 figure_style 统一配置 minor_locator，避免各图风格割裂） |
| 25 | Legend | `fig2_nmr.main.legend` | handlelength / labelspacing (图例内部间距紧凑度) | 未覆盖 | 建议归类：由其他参数派生（按 legend_font_pt 等比缩放，无需单独旋钮） |

## 3. 详细属性分布清单 (前 15 条抽样)

| Artist 类型 | GID | 属性 | 分类 | 归类理由 |
| :--- | :--- | :--- | :--- | :--- |
| Line2D (Curve) | `fig2_nmr.main.curve.vancho` | linewidth (谱线线宽) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 line_width |
| Line2D (Curve) | `fig2_nmr.main.curve.vancho` | vertical_gap (垂直层间距) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 stack_gap / layer_gap |
| Line2D (Curve) | `fig2_nmr.main.curve.vancho` | display_shift_dy (纯显示位移) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 shifts_mm |
| Line2D (Curve) | `fig2_nmr.main.curve.vancho` | data_xy (波长/化学位移与吸光度数值) | 科学锁定（峰位、显示窗、归一化、归属） | 仪器采集原始物理数据、定标结果与吸光度转换，不可人为修改 |
| Line2D (Curve) | `fig2_nmr.main.curve.vancho` | color (谱线系列颜色) | 全局样式（figure_style 统一） | 由 figure_style.MATERIAL 调色板按样品材料属性全局统一分配 |
| Line2D (Curve) | `fig2_nmr.main.curve.vancho` | solid_capstyle (曲线线端样式) | 未覆盖 | 未在 YAML 参数中开放单独线帽调节 |
| Line2D (Baseline) | `fig2_nmr.main.baseline.vancho` | vertical_position (基线位置) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 layer_gap / shifts_mm |
| Line2D (Baseline) | `fig2_nmr.main.baseline.vancho` | linestyle / linewidth / color | 全局样式（figure_style 统一） | 虚线样式由 figure_style 全局统一 (#E2E2E2, lw=0.45, ls='--') |
| Line2D (Curve) | `fig2_nmr.main.curve.vanoh` | linewidth (谱线线宽) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 line_width |
| Line2D (Curve) | `fig2_nmr.main.curve.vanoh` | vertical_gap (垂直层间距) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 stack_gap / layer_gap |
| Line2D (Curve) | `fig2_nmr.main.curve.vanoh` | display_shift_dy (纯显示位移) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 shifts_mm |
| Line2D (Curve) | `fig2_nmr.main.curve.vanoh` | data_xy (波长/化学位移与吸光度数值) | 科学锁定（峰位、显示窗、归一化、归属） | 仪器采集原始物理数据、定标结果与吸光度转换，不可人为修改 |
| Line2D (Curve) | `fig2_nmr.main.curve.vanoh` | color (谱线系列颜色) | 全局样式（figure_style 统一） | 由 figure_style.MATERIAL 调色板按样品材料属性全局统一分配 |
| Line2D (Curve) | `fig2_nmr.main.curve.vanoh` | solid_capstyle (曲线线端样式) | 未覆盖 | 未在 YAML 参数中开放单独线帽调节 |
| Line2D (Baseline) | `fig2_nmr.main.baseline.vanoh` | vertical_position (基线位置) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 layer_gap / shifts_mm |
