# 参数全集覆盖审计报告 - plot_ftir.py

- 脚本: `D:\L\AI\figpact\examples\ftir\plot_ftir.py`
- 配置: `D:\L\AI\figpact\examples\ftir\ftir.yaml`
- 总属性数: 98

## 1. 五类属性统计

| 分类 | 属性项数 | 占比 | 简要说明 |
| :--- | :---: | :---: | :--- |
| 已暴露为 YAML 参数 | 35 | 35.7% | 已在配置文件和 list_params 中声明为可编辑参数 |
| 全局样式（figure_style 统一） | 18 | 18.4% | 由统一出版规范锁死（字族、色板、边框/刻度线宽、虚线样式等） |
| 科学锁定（峰位、显示窗、归一化、归属） | 17 | 17.3% | 涉及实验科学真实性（仪器原始数据、显示范围、官能团/峰归属、化学位移定标） |
| 由其他参数派生 | 6 | 6.1% | 由几何约束、实测文本包络框或前序参数算法求解派生，不可单独设置 |
| 未覆盖 | 22 | 22.4% | 属于图元可见特征但尚未归入上述四类的未管辖项 |

## 2. 未覆盖项清单及建议归类

| 序号 | Artist 类型 | GID / 标识 | 属性 | 当前状态 | 建议归类与理由 |
| :---: | :--- | :--- | :--- | :--- | :--- |
| 1 | Line2D (Curve) | `fig2_ftir.annotated.curve.ha` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 2 | Line2D (Curve) | `fig2_ftir.annotated.curve.zno` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 3 | Line2D (Curve) | `fig2_ftir.annotated.curve.hama` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 4 | Line2D (Curve) | `fig2_ftir.annotated.curve.hama_cu_zno` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 5 | Line2D (Curve) | `fig2_ftir.annotated.curve.gel` | solid_capstyle (曲线线端样式) | 未覆盖 | 建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺） |
| 6 | Rectangle | `shade_band.3200_3550` | edgecolor / linestyle (阴影带两侧边界虚线) | 未覆盖 | 建议归类：全局样式（统一默认无边界虚线，保持画面干净） |
| 7 | Rectangle | `shade_band.1580_1680` | edgecolor / linestyle (阴影带两侧边界虚线) | 未覆盖 | 建议归类：全局样式（统一默认无边界虚线，保持画面干净） |
| 8 | Rectangle | `shade_band.1380_1450` | edgecolor / linestyle (阴影带两侧边界虚线) | 未覆盖 | 建议归类：全局样式（统一默认无边界虚线，保持画面干净） |
| 9 | Rectangle | `shade_band.1000_1100` | edgecolor / linestyle (阴影带两侧边界虚线) | 未覆盖 | 建议归类：全局样式（统一默认无边界虚线，保持画面干净） |
| 10 | Rectangle | `shade_band.400_560` | edgecolor / linestyle (阴影带两侧边界虚线) | 未覆盖 | 建议归类：全局样式（统一默认无边界虚线，保持画面干净） |
| 11 | Text (BandLabel) | `fig2_ftir.annotated.band.oh` | rotation (标签文字倾斜角) | 未覆盖 | 建议归类：全局样式（严格保持 0 度水平放置，期刊严禁斜字标签） |
| 12 | Text (BandLabel) | `fig2_ftir.annotated.band.coo_cc` | rotation (标签文字倾斜角) | 未覆盖 | 建议归类：全局样式（严格保持 0 度水平放置，期刊严禁斜字标签） |
| 13 | Text (BandLabel) | `fig2_ftir.annotated.band.coo` | rotation (标签文字倾斜角) | 未覆盖 | 建议归类：全局样式（严格保持 0 度水平放置，期刊严禁斜字标签） |
| 14 | Text (BandLabel) | `fig2_ftir.annotated.band.coc` | rotation (标签文字倾斜角) | 未覆盖 | 建议归类：全局样式（严格保持 0 度水平放置，期刊严禁斜字标签） |
| 15 | Text (BandLabel) | `fig2_ftir.annotated.band.zn_o` | rotation (标签文字倾斜角) | 未覆盖 | 建议归类：全局样式（严格保持 0 度水平放置，期刊严禁斜字标签） |
| 16 | Spine(left) | `axes.spine.left.visible` | visible (边框可见性开关) | 未覆盖 | 建议归类：全局样式（figure_style 统一四边框封闭原则） |
| 17 | Spine(right) | `axes.spine.right.visible` | visible (边框可见性开关) | 未覆盖 | 建议归类：全局样式（figure_style 统一四边框封闭原则） |
| 18 | Spine(bottom) | `axes.spine.bottom.visible` | visible (边框可见性开关) | 未覆盖 | 建议归类：全局样式（figure_style 统一四边框封闭原则） |
| 19 | Spine(top) | `axes.spine.top.visible` | visible (边框可见性开关) | 未覆盖 | 建议归类：全局样式（figure_style 统一四边框封闭原则） |
| 20 | XAxis | `axes.xaxis.minor_ticks` | minor_ticks / tick_density (次刻度开关与密度) | 未覆盖 | 建议归类：全局样式（由 figure_style 统一配置 minor_locator，避免各图风格割裂） |
| 21 | YAxis | `axes.yaxis.minor_ticks` | minor_ticks / tick_density (次刻度开关与密度) | 未覆盖 | 建议归类：全局样式（由 figure_style 统一配置 minor_locator，避免各图风格割裂） |
| 22 | Legend | `fig2_ftir.annotated.legend` | handlelength / labelspacing (图例内部间距紧凑度) | 未覆盖 | 建议归类：由其他参数派生（按 legend_font_pt 等比缩放，无需单独旋钮） |

## 3. 详细属性分布清单 (前 15 条抽样)

| Artist 类型 | GID | 属性 | 分类 | 归类理由 |
| :--- | :--- | :--- | :--- | :--- |
| Line2D (Curve) | `fig2_ftir.annotated.curve.ha` | linewidth (谱线线宽) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 line_width |
| Line2D (Curve) | `fig2_ftir.annotated.curve.ha` | vertical_gap (垂直层间距) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 stack_gap / layer_gap |
| Line2D (Curve) | `fig2_ftir.annotated.curve.ha` | display_shift_dy (纯显示位移) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 shifts_mm |
| Line2D (Curve) | `fig2_ftir.annotated.curve.ha` | data_xy (波长/化学位移与吸光度数值) | 科学锁定（峰位、显示窗、归一化、归属） | 仪器采集原始物理数据、定标结果与吸光度转换，不可人为修改 |
| Line2D (Curve) | `fig2_ftir.annotated.curve.ha` | color (谱线系列颜色) | 全局样式（figure_style 统一） | 由 figure_style.MATERIAL 调色板按样品材料属性全局统一分配 |
| Line2D (Curve) | `fig2_ftir.annotated.curve.ha` | solid_capstyle (曲线线端样式) | 未覆盖 | 未在 YAML 参数中开放单独线帽调节 |
| Line2D (Curve) | `fig2_ftir.annotated.curve.zno` | linewidth (谱线线宽) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 line_width |
| Line2D (Curve) | `fig2_ftir.annotated.curve.zno` | vertical_gap (垂直层间距) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 stack_gap / layer_gap |
| Line2D (Curve) | `fig2_ftir.annotated.curve.zno` | display_shift_dy (纯显示位移) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 shifts_mm |
| Line2D (Curve) | `fig2_ftir.annotated.curve.zno` | data_xy (波长/化学位移与吸光度数值) | 科学锁定（峰位、显示窗、归一化、归属） | 仪器采集原始物理数据、定标结果与吸光度转换，不可人为修改 |
| Line2D (Curve) | `fig2_ftir.annotated.curve.zno` | color (谱线系列颜色) | 全局样式（figure_style 统一） | 由 figure_style.MATERIAL 调色板按样品材料属性全局统一分配 |
| Line2D (Curve) | `fig2_ftir.annotated.curve.zno` | solid_capstyle (曲线线端样式) | 未覆盖 | 未在 YAML 参数中开放单独线帽调节 |
| Line2D (Curve) | `fig2_ftir.annotated.curve.hama` | linewidth (谱线线宽) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 line_width |
| Line2D (Curve) | `fig2_ftir.annotated.curve.hama` | vertical_gap (垂直层间距) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 stack_gap / layer_gap |
| Line2D (Curve) | `fig2_ftir.annotated.curve.hama` | display_shift_dy (纯显示位移) | 已暴露为 YAML 参数 | 已暴露为 YAML 参数 shifts_mm |
