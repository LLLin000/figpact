# PLATE 能力矩阵：输入类型 × 可测项

实测口径（不可妥协）：`eff_pt` = 同图内同字号对照字形 `Ag` 的绘制后
`Text.get_window_extent(renderer)` 高度（figure dpi 换算）× 实测导出比 `k`；
`k` = 目标宽 / 实测导出宽（临时目录 `savefig` 实测，`bbox_inches` 影响计入，
导出后重 `draw` 避免 renderer 单位陷阱）；线宽取渲染后实际值；`k>1` 报
`infeasible`。方法字符串见每张图 `measurement_basis`。

| 输入 | 能测（测什么、依据/精度） | 不能测 |
|---|---|---|
| **代码**（脚本+YAML/契约） | 画布 mm（配置+导出实测）；每字号 `role_eff_pt`（对照字形实测，精度 ~0.01pt）；每 gid 线宽（渲染后实际值）；`k`（实测导出，6位小数）；文本 bbox（px）；越界（图元 extent vs figure 页矩，同单位 px）；文本 bbox 与曲线折线相交（逐段相交实测，逐项给 gid） | —（唯一能承诺 `k≡1` 的来源：统一即改源码画布到目标宽） |
| **矢量**（PDF/SVG） | PDF：页面物理尺寸（`page.rect` pt→mm）；仍为文字时的位置/字号（span dict）；路径 bbox（drawings rect）。只读，不渲染 | 已转曲（无内嵌文字）时的字号与字形；字体缺失时的字号可靠性；SVG 无固定页面尺寸，其字号/线宽无 pt 上下文 |
| **位图**（PNG/JPEG/TIFF） | 像素尺寸；DPI→物理尺寸（Pillow；DPI 缺失记 `dpi_assumed:true`，默认 300）；摆放位置 | **字号/线宽不可恢复**（只能估算）；**不得报规格达标** |

回执字段：`measurable_specs` / `unmeasurable_specs` / `measurement_basis`
（方法+renderer+dpi，对照字形说明）。位图回执恒含
`spec compliance MUST NOT be reported for bitmaps`。
