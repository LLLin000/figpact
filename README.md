# figpact

**直接改 Python 科研图的排版细节，并让不同尺寸的小图在最终投稿尺寸下规格统一——改动可复现地回到源文件，且每一步都有真实测量作证。**

figpact 面向两个具体痛点：

1. **改图上某个标注的位置，要反复改 Python、导出、看图、再改。** figpact 让你在真图上选中标注、拖动、看到毫米读数，松手后用**真实重建**验证，确认后**写回源文件**；下次重跑脚本，改动还在。
2. **两张尺寸不同的图放进同一张论文 Figure，最终字号与线宽不一致。** figpact 先**只读审计**在目标宽度下每个角色会落到几个 pt，再按最终尺寸**重新渲染**（不是事后缩放 PDF），放不下的地方**如实报告**而不是偷偷缩字。

许可证 **MIT**。设计取舍与阶段计划见 [`docs/G7_PLAN.md`](docs/G7_PLAN.md)；历史验收记录在 `docs/`（G0–G6b）。

---

## Quickstart

```bash
git clone https://github.com/LLLin000/figpact.git && cd figpact
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
figpact ui --script examples/demo/demo_figure.py --config examples/demo/demo.yaml
```

浏览器打开终端里打印的地址。**演示图 `examples/demo/` 的全部数据由公式生成**（固定随机种子），不含任何真实测量。

---

## 逐步演示

下面每一步都是一次真实操作，截图由真实浏览器抓取（`tools/readme/capture_tour.py`，对着 `examples/demo/`）。

### 1. 启动：图加载完成

<img src="docs/readme/01-launch.png" width="820" alt="启动后的检查器界面">

页面加载的就是脚本渲染出来的图；顶栏显示尺寸核对结果。

### 2. 选中一个标注

<img src="docs/readme/02-select.png" width="820" alt="选中一个峰标注">

悬停即高亮、点击即选中，显示它的 GID 与**这张图允许对它做什么**（能不能改、能不能验证）。

### 3. 拖动：本地即时预览

<img src="docs/readme/03-drag.png" width="820" alt="拖动中的幽灵轮廓与毫米读数">

拖动时只有本地绘制：幽灵轮廓、联动引线幽灵、贴光标的**毫米读数**。**期间不重建 Matplotlib、不请求后端**——所以拖动手感是即时的。

### 4. 松手：真实重建验证

<img src="docs/readme/04-verified.png" width="820" alt="松手后的真实验证回执">

松手后才向引擎要一次真实重建。回执里的实测位移、误差与各项检查都来自这次重建——**预览本身不是证据**，没通过就不会出现"通过"字样。

### 5. 后续步骤：接受 → 保存 → 重启后一致

保存链（待保存区列出目标文件、参数变更与源码差异 → 显式确认 → 原子写入 → 写后重新验证）已在后端与页面上实现，并由真实浏览器用例守着：

```
tests/browser/test_save_flow.py                    2 passed
tests/test_save_loop_g7b.py   （真实 NMR 夹具）    3 passed
```

其中 NMR 全旅程的实测：位移 **0.1500000000000039 mm**（目标 0.15，误差 **3.9e-15**）、保存回执 **COMMITTED + PASS**、配置落盘 `[0.0, 0.15]`、**全新会话从磁盘重建后一致**；拒绝授权与取消时磁盘**逐字节不变**。

> **已知限制（如实说明）**：上面 5 这一步**尚未在合成演示图上截到图**。演示图目前只具备"示范位置"能力，接受/保存仍被禁用（引擎要求会话声明 science manifest 才允许重新绘图验证，演示图的声明还没接上）。因此本教程的截图覆盖到**第 4 步（真实验证）**；保存链的证据是上表的测试与实测数字，**不是摆拍**。

---

## 从一张难看的图到出版规格

所有数据由公式生成（固定种子），图是真实渲染；工具**只报数据**，审美决定权在人。

| 阶段 | 准备调什么（意图） | 怎么调（键：旧值→新值） | 预期结果 | 实际结果（实测数字 + 结论） |
|---|---|---|---|---|
| 01 起点 | 无（记录基线问题） | — | — | 越界 4 处、text/curve 重叠 3 处、字号 5.0 pt（图例 4.5 pt 不可行）、clipped 4 |
| 02 | 拉开样品间距，让曲线不再互相压 | `pitch_mm` 0.32→0.78 | 曲线净距拉开、越界减少 | text_curve 4→? 实测 text_bbox 0、clipped 4、图例仍压数据 |
| 03 | 放大画布与边距，给文字留位置 | `canvas_w_mm`/`canvas_h_mm` 66/40→96/62 | 有效字号≥5 pt、边距不挤 | text_bbox 0、clipped 3、infeasible 1 |
| 04 | 解决近峰标签互叠 | `label_min_gap_mm` 0→1.8 + `peak_label_shifts_mm` 分道 | 标签分道、互不重叠、贴各峰 | text_bbox 0、clipped 3、infeasible 1 |
| 05 | 统一字号档位与线宽 | `axis_font_pt`/`tick_font_pt`/`peak_font_pt`/`line_width` | 各角色一档、≥5 pt、线宽一致 | text_bbox 0、clipped 3、infeasible 0 |
| 06 | 图例移出数据区并收尾 | `legend_anchor_x`/`legend_cols` 0.5/1→0.98/1 | 图例不压数据、无裁切、无空白撑开 | text_bbox 0、text_curve 0、clipped 0、rendered_labels 3/3、infeasible [] |

![](docs/readme/series-01-ugly.png)
![](docs/readme/series-02-spacing.png)
![](docs/readme/series-03-canvas.png)
![](docs/readme/series-04-labels.png)
![](docs/readme/series-05-typography.png)
![](docs/readme/series-06-final.png)

再跑一次：`python tools/readme/render_series.py` 输出确定；本次实测每阶段耗时 ~0.1 s 渲染 + ~0.2 s 审计。

## 最终尺寸统一（痛点二）

同一张论文 Figure 里，**所有面板共享同一缩放比**是期刊的硬要求。figpact 的做法是**按最终尺寸重渲染**，而不是把大图缩下来。

```bash
figpact final-size ...        # 只读审计：先出数，再决定改什么
```

真实数字（`examples/nmr` 与 `examples/ftir`，只读审计）：

| 图 | 目标宽 | 实测导出宽 | k | 轴标题 | 刻度 | 标注 | 线宽 |
|---|---|---|---|---|---|---|---|
| NMR | 42 mm | 41.995 mm | **1.0001** | 8.0 pt | 7.0 pt | 峰标注 6.0 → 4.8 pt ⚠ | 0.8 pt |
| FTIR | 38 mm | 37.973 mm | **1.0007** | 8.0 pt | 7.0 pt | 官能团标注 4.7 → **3.7 pt** ⚠ | 0.8 pt |

受控修改只覆盖**三个角色**（轴标题 / 刻度 / 曲线线宽），写回走既有 YAML 精确补丁 + 漂移检查 + 原子替换，写后重新审计。

**放不下时说放不下**，不自动缩字：

```
infeasible: label_font_pt effective 4.703pt < 5pt; legend_font_pt effective 4.703pt < 5pt
spatial_risk: FTIR label bottom overflow 0.697 mm; Line2D top overflow 2.632 mm (×2)
```

可选取舍：**加宽图 / 移动标注 / 显式指定局部字号**。figpact 不会为了凑宽度去改科学视口、缩字或裁谱线。

---

## 支持边界

- **预览 ≠ 验证**；**写盘 ≠ 科学验证**。只有源码已提交**且**独立重建通过，界面才会说"已保存并通过验证"；写盘成功但验证失败时，页面说的是"源码已写入，但图形验证失败"。
- **不是任意脚本都能编辑**：可编辑需要脚本声明参数契约（`layout_contract()`）与科学基线；没有绑定或绑定歧义时，figpact **拒绝并说明原因**，而不是猜。
- **无 YAML 的图**可以只读测量与示范，但不能保留修改。
- 只信任**本地**脚本；figpact **不是** OS 级沙箱。

### 新图型接入检查：统计曲线与误差棒

`examples/statistics/statistical.py` 使用固定合成均值/标准误数组，只声明现有接入协议，
没有为统计图新增适配器。这是协议内新图型检查，不是独立人员盲测，也不是任意零接入脚本支持。
隔离副本实跑：100×75 mm → 80×60 mm，目标轴标题/刻度 8 pt、线宽 0.8 pt。

| 角色 | 发现与扰动验证 | apply 后实测 |
|---|---|---|
| 轴标题 | verified | 8.003 pt |
| 刻度 | verified | 8.003 pt |
| 图例 | verified，compare-only | 7.003 pt，未强制统一 |
| 曲线线宽 | rejected：共享参数还改变未声明的误差棒 LineCollection | 1.2 pt，源码参数未改，不冒充达标 |

视图、6 个 Line2D 的数据坐标和 2 个误差棒集合的线段均前后相等；重复 apply 配置字节不变。
空间校验仍报告 FAIL，不能将该图称为整图通过。草稿允许 `source_commit_state=COMMITTED`
且 `figure_verification_state=FAIL`，但子结果、plate 聚合结果和 CLI 顶层 `status` 均为 `FAILED`
（对象审计阻断时为 `AUDIT_BLOCKED`），`plate unify --apply` 返回退出码 1。
receipt 保留真实的 `COMMITTED / FAIL`，不将验证失败误写为未提交，也不让干净的后续审计抹掉 FAIL。
现有 Apply 是工作草稿保存，不是 Strict 发布；失败图不能作为已验证的正式产物。

可复跑的真实发现→确认→扰动→写盘→CLI 退出码检查（在临时副本中运行，不修改示例）：

```bash
python -m pytest tests/test_statistical_unify.py -q
```

G15 已在冻结引擎上运行第三方 Matplotlib gallery 的多 Axes、统计与混合对象样本，
分开检查原始脚本和仅协议声明两种条件。结果**不支持宣称任意陌生脚本已经可编辑**；
缺入口、缺绑定、源文提示错配与正确拒绝分别记账。
协议、逐项指标、有效性勘误和复跑入口见 [G15 报告](docs/G15_REPORT.md)。

### Verified Style Overlay：不改原 Python 的受控样式（G16 / R2）

没有原生 YAML 参数的可信 Figure，可通过独立 JSON Overlay 持久化三种已验证操作：
xlabel/ylabel 字号、某一轴的可见主刻度字号、唯一连接数据 Line2D 的线宽。
不支持任意方法、误差棒 Collection、柱形、散点、图例或 AST 自动改写。
Overlay 不是原始 Python 源码改写；原始科学程序和配置保持不变。

```bash
python -m figpact overlay inventory --script tools/g15/B/g15b_errorbar_decl.py --scope ax0
# 将 inventory 中选定对象的 id 写入 edits.json：
# [{"target_id": "<inventory 中的精确 id>", "value": 0.8}]
python -m figpact overlay apply --script tools/g15/B/g15b_errorbar_decl.py --scope ax0 --edits edits.json --overlay style.json
python -m figpact overlay render style.json --output edited.png
```

重建时由引擎按结构指纹和源依赖哈希重新定位，不以遍历序号猜对象；缺失、歧义、漂移均拒绝。
更新既有 Overlay 需 `--expected-sha256`（包括同状态重试）；`--edits` 是增量新增/更新，未提及目标保持不变。
重复 `--remove <target_id>` 显式移除已保存目标，移除后恢复原程序样式；移除最后一项得到可重建的空 Overlay。
空请求不会清空已有状态。同请求重复目标、增改与移除冲突、未知移除目标均拒绝，不改变已保存字节。
合并后的**全部目标**重新构建并联合审计，不仅验证最后编辑项；相同完整状态不会累积或重写文件。
局部审计与整图 QA 分开：只有显式 `--allow-draft` 才保存局部通过、整图失败的草稿，
回执为 `COMMITTED_DRAFT / FAIL`，退出码仍为 1，失败草稿不渲染为已验证产物。
首次创建为完整临时文件的原子排他安装；更新复用现有原子替换，沿用单写者约束（非多进程 CAS）。
跨盘声明会保存绝对路径并标记不可移植；普通路径引用与依赖内容均受校验。
声明的 RAW/science inputs 缺失、不可读取或声明 hook 报错均明确拒绝；未声明依赖才是合法空集合。
当前只保护显式 wrapper/RAW/config/science inputs，**不自动追踪所有 Python import 的传递依赖闭包**；辅助科学模块应显式声明。

三个异构陌生图的真实 R2 验收与限制见 [G16 报告](docs/G16_REPORT.md)。
连续编辑、新进程重开、删除与拒绝不落盘证据见 [G17 报告](docs/G17_REPORT.md)。

### 在正式 Inspector 中连续改样式（G18）

```bash
python -m figpact ui --script tools/g15/B/g15b_barchart_decl.py --scope main --overlay work/style.json --port 0
```

打开终端地址，画布点选轴标签/刻度 → 右侧改数值 → **预览样式** → 查看旧值、新值与影响范围 → **确认保存**。
预览不写正式 Overlay；继续选其他对象会保留已保存编辑。“恢复原始”显式移除该目标覆盖，不影响其他目标。
关闭服务后用同一命令重开可恢复状态。位置编辑与样式控制分开，源路径仅启动时指定；HTTP不接受任意路径或方法。
秒级独立验证不会伪装成即时完成，耗时可展开查看。浏览器证据、安全拒绝和极简性审查见 [G18 报告](docs/G18_REPORT.md)。
提交已成功但后续界面重建失败时，页面保留“文件已保存”事实并禁用旧帧编辑，重新打开后恢复；不把显示故障误报为未保存。
真实 FTIR/NMR/统计图的接入成本、QA阻断与5轮性能测量见 [G19 试用报告](docs/G19_REPORT.md)。
“对象有控制权但整图 QA 失败”和“对象存在但无控制权”分别说明；不为示例通过而移动原图图例或降低字形下限。


## 测试

```bash
node --test tests/inspector/test_inspector.js     # 前端纯逻辑
python -m pytest tests/browser -q                  # 真 Chromium + 真服务
python -m pytest -q                                # 其余
```
