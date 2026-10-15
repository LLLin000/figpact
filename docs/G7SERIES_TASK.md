# G7-README-SERIES 任务书：从"难看的图"到"完美的图"的系列图

**基线**：`D:/L/AI/figpact` @ `master`。用户要求（原话要义）：**做一张不太好看的图，然后把它调整到完美，做一系列图**。
**硬红线**：全部数据必须**自己编**（公式生成、固定种子），**绝不允许**使用 `examples/nmr`、`examples/ftir`、任何真实测量或用户图件；截到的图/渲染的图里不得出现任何真实数据。

## 目标文件
- 扩 `examples/demo/`（可加 `demo_stages.py` 或让 `demo_figure.py` 支持 stage 参数）
- **新建** `tools/readme/render_series.py`（渲染系列图）
- **新建** `docs/readme/series-*.png`（系列图产物）
- 更新 `README.md`（在"逐步演示"之后加一节"从难看 to 出版"）
- **禁止**改 `figpact/*.py` 的既有语义、`examples/nmr/*`、`examples/ftir/*`；无 git 写操作

## 1) 先造一张**难看**的合成图（plausible ugly，不是乱画）
参考真实的"新手用默认参数画出来的图"，至少命中 5 类问题：
1. **标注重叠**：两个峰只差 0.06 ppm 的标注互相压在一起；
2. **曲线挤在一起**：样品间纵向间距太小，谱线互相压；
3. **图例压住数据**；
4. **画布过小/边距不足**：文字挤到边缘、刻度拥挤；
5. **规格不统一**：字号档位杂乱、线宽不一致、颜色刺眼。

## 2) 一步一步调到"完美"（每一步都是**真实参数变更 + 真实重渲染**）
系列至少 5 张，每张对应**一个可解释的动作**，例如：
| 阶段 | 动作 | 对应真实参数 |
|---|---|---|
| `series-01-ugly.png` | 起点 | 初始配置 |
| `series-02-spacing.png` | 拉开样品间距 | `pitch_mm` / `group_y_mm` |
| `series-03-canvas.png` | 放大画布与边距 | `canvas_w_mm` / `canvas_h_mm` |
| `series-04-labels.png` | 解决标注重叠（分道/最小净空） | `label_lanes` / `label_min_gap_mm` / `peak_label_shifts_mm` |
| `series-05-typography.png` | 统一字号档位与线宽 | `axis_font_pt` / `tick_font_pt` / `peak_font_pt` / `line_width` |
| `series-06-perfect.png` | 收尾：图例归位、无越界 | `legend_*` 等，直到审计无不可行项 |

要求：
- 每张图**必须**同时给出**可复核的数字**：用 `figpact final-size`（只读审计）或等价测量，报该阶段的**实测**项（字号 effective pt、标注是否重叠/越界、曲线净距、线宽）。
- `series-01` 必须**可证明地差**（给数字：如 2 处标注重叠、图例压线、文字越界 X mm）；`series-06` 必须**审计无不可行项**。
- 阶段之间的差异必须**只来自参数**，不得手改渲染代码糊弄。

## 3) 渲染与截图
- 每张系列图：**整图预览**（清晰可读，建议 1600 px 宽、标注阶段文件名）。
- 如条件允许，再补 1–3 张**检查器内**的截图（拖动/审计面板），但**不得**为凑图而摆拍；做不到就只用真实渲染图。
- `tools/readme/render_series.py` 必须**可重复运行**（固定种子、输出确定）。

## 4) README 新增一节
- 标题类似「从一张难看的图到出版规格」。
- 每张图一句话说明**改了什么参数**、**数字怎么变好**（前后对照表）。
- 明确说明：**所有数据为自造**；**图为真实渲染**；工具**只报数据**，审美决定权在人。

## 交付证据（缺一不可）
1. `docs/readme/series-*.png` 的**文件清单与字节数**。
2. `tools/readme/render_series.py` 的**真实运行输出**（含每阶段耗时）。
3. **每个阶段的数字对照**（起点的"差"必须量化；终点必须无不可行项）。
4. README 更新后的相关段落原文。
5. 说明可重复性（再跑一次结果是否一致）。

## 环境
`TEMP/TMP/TMPDIR/MPLCONFIGDIR` 指向 `D:/L/AI/figpact-archive/g6b-v2/tmp*`；`MPLBACKEND=Agg`；`PYTHONDONTWRITEBYTECODE=1`；`D:/programs/Python/python.exe -B -X utf8`。
