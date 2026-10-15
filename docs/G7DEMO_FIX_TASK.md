# G7-DEMO-FIX 任务书：把演示图做成**真正的科研图**（肉眼验收）

**基线**：`D:/L/AI/figpact` @ `master`。
**用户原话**：`你自己用视觉看一下，这他妈是标准的科研图吗，完全有遮挡有重叠各种错误`。
**父代理已肉眼复核**，当前 `docs/readme/series-01-ugly.png` 与 `series-06-perfect.png` **都不可接受**，实测缺陷：
1. `Cluster I-a` 与 `Cluster I-b` 的**文字互相叠印**（渲染成 "Clustter I-b"）；
2. `Cluster III-a`/`Cluster III-b` 同样叠印，且**压在曲线上**；
3. `Peak B` 标签**飘在曲线中间**，远离对应峰；
4. **图例是大框压在数据中央**（起点图里压住蓝色峰）；
5. 绿色峰**超出坐标框顶部被裁**；
6. 只有 `Intensity (a.u.)`，**没有 x 轴标签**；
7. 出现**幽灵重影文字**（偏移副本）；
8. 字号/线宽观感不一致，噪声块状难看。

## 红线
- **全部数据自造**（公式 + 固定种子）；**绝不引用** `examples/nmr`、`examples/ftir` 或任何真实/用户数据。
- 图必须是**真实渲染**产物，禁止手改图像。
- **无 git 写操作**（父代理统一提交）。

## 目标文件
- 重做 `examples/demo/demo_figure.py`（**自己写布局与标注逻辑**，不要再抄 NMR 那套带 ghost 位移的实现）、`examples/demo/demo_*.yaml`（各阶段配置）
- 重写 `tools/readme/render_series.py`
- 覆盖 `docs/readme/series-*.png`
- 更新 `README.md` 相应表格与图片（保留既有 UI 截图章节）

## 图要长成什么样（可检查的视觉标准）
1. **零文字重叠**：任意两个文本 bbox **不相交**（含同一峰的两个簇标签）。
2. **零遮挡**：图例、注释**不得覆盖任何数据曲线**；图例放到坐标区**之外**（右侧或底部边距），或放在曲线不经过的空区且经程序验证不相交。
3. **零裁切**：任何文本、刻度、峰尖、坐标框都**完整在画布内**；峰尖不得出框。
4. **标签贴在正确的峰上**：标签水平位置与其峰位的水平差 ≤ 一个小的显式阈值（给数字），并在峰上方留固定净空；两个相邻峰用**分道（竖直错开）** 或**最小净空**规则分开。
5. **规格统一**：同角色同字号；轴标题/刻度/标注/图例各一档；曲线线宽一致（如 0.8 pt）。
6. **完整轴语义**：x 轴有标题与单位（如 `δ (ppm)`，反向轴），y 轴有标题；坐标框闭合、刻度朝内或朝外**一致**。
7. **干净的数据观感**：噪声不要块状；曲线颜色区分度好、不刺眼。
8. **拼版尺寸合法**：画布按毫米给出，`k ≡ 1`（实测导出 ≈ 声明），字号在**最终尺寸**下均 `≥ 5 pt`。

## 系列（先丑后美，但**每一步都必须"像真图"**）
至少 6 张，起点是"新手默认参数的糟糕图"，但**糟糕 = 排版问题（挤、暗、乱），不是文字互相叠印到不可读**：
| 文件 | 内容 |
|---|---|
| `series-01-ugly.png` | 画布过小、曲线挤、图例压数据、字号过小/不统一、标签挤在一起（**仍不允许文字叠印**；重叠只允许"贴得太近"） |
| `series-02-spacing.png` | 拉开曲线间距 |
| `series-03-canvas.png` | 放大画布与边距 |
| `series-04-labels.png` | 标签分道/最小净空，贴回各自峰 |
| `series-05-legend.png` | 图例移出数据区 |
| `series-06-final.png` | 统一字号与线宽、补齐轴标签、无越界 → **满足上面 8 条全部标准** |

（原名 `series-06-perfect.png` 误导，改为 `series-06-final.png`；README 里同步改。）

## 必须**程序化**验证（不许只靠眼睛，也不许只靠审计字段）
在 `render_series.py` 里对每张图输出一份 `docs/readme/series_report.json`，字段至少：
- `text_bbox_overlaps`: 两两文本 bbox 相交的对数与具体 gid（**终点必须为 0**）
- `legend_data_intersection`: 图例 bbox 与曲线 bbox 是否相交（**终点必须为 false**）
- `clipped_texts` / `clipped_artists`: 越出画布的对象数与 gid（**终点必须为 0**）
- `label_peak_offset_mm`: 每个标签与其峰的水平偏差（**终点必须 ≤ 显式阈值**）
- `fonts_pt` / `line_widths`: 各角色实测值（**终点同角色必须一致、且 ≥5 pt**）
- `canvas_mm` / `measured_export_mm` / `k`

**用真实渲染后的 renderer 测量**（注意 `docs/research/R2_restyle_implementations.md` 的测量陷阱：不要用 `get_window_extent(dpi=...)`；测量前显式 `draw()`；单位跟随缓存 renderer）。

## 交付证据（缺一不可）
1. 六张图的清单与字节数。
2. `series_report.json` 的**关键字段原文**（起点 vs 终点对照；终点必须满足全部硬门槛）。
3. `render_series.py` 的真实运行输出（每阶段耗时）。
4. README 更新后的段落原文。
5. 说明"文字重叠检测"是怎么算的（用哪个 bbox API、阈值是多少），**可复核**。

## 环境
`TEMP/TMP/TMPDIR/MPLCONFIGDIR` 指向 `D:/L/AI/figpact-archive/g6b-v2/tmp*`；`MPLBACKEND=Agg`；`PYTHONDONTWRITEBYTECODE=1`；`D:/programs/Python/python.exe -B -X utf8`。
