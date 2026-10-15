# R12 — 把多张代码图拼成一张投稿图（plate）：代码路线上有什么、缺什么

> 任务书 `docs/G8DIFF_TASK.md` 路线 R12。方法：**先核本地源码与仓库既有事实，再检索一手来源**。
> 标【事实】的来自本地文件（给路径+行号/函数名）或已抓到的官方页面/GitHub/PyPI；标【推断】的为本文判断；
> 无法确证写「未找到」。**不利于我们的发现照写。** 调研日期 2026-10-15。
>
> 本文与 `docs/research/R6_panel_assembly.md` 的分工：R6 已系统梳理了**拼版规则来源**（期刊对组合图的一致性/面板字母/缩放/矢量嵌入/面板间距的原文）与 **R 生态 + 手工拼版**两条线的机制。**R12 只补代码路线的“全版面（plate）总盘 + 缺口 + 占位判断 + 最小能力”**，期刊原文引用不重复，需要时直接引 R6 的条目号。

---

## 0. 结论先行（一句话）

**【推断】「整版」不是无人区，但“整版”被占住的是“已画好的成品面板往一页上摆 + 按一份期刊 profile 预检”这一条**——这条已由 **Tavotto（本地源码）**、**FigureGuild Figure Assembler（在线）**、**plotstyle（Python）** 三家实实在在占住，且 Tavotto/plotstyle 都做到了“按最终尺寸算有效字号、整图统一校验”。
**仍未被占住的那条是**：（a）**多个独立代码图各自回源码、按同一份整版契约重渲染**，使 $k\equiv 1$ 由构造保证（不是“摆上去再缩”）、（b）**整版级、跨图角色统一（字号/线宽/面板字母一档到底）的可核验报告**、（c）**改一处（一个整版契约字段）能驱动整版重建并给出对外可消费的结构化证据/回执**。R6 §3.4 已给出现场证据：业界的整版一致性检查**至今是“人拿尺子 / 用复印机缩 50% 看”**（Nature/Chicago/PALASS/JAS 原文），**没有任何代码工具把这张表变成可测量、可阻断的判据**。这就是我们可以占的位置。

---

## 1. 现有手段各能做什么（代码路线盘点）

### 1.1 组内拼版原语（把“面板”摆进一张 Figure）

| 手段 | 能做什么 | 关键限制（一手来源） |
|---|---|---|
| matplotlib `subfigures` / `GridSpec` | 一图多面板、嵌套子图、共享轴；官方一等公民 | 无“跨图角色”概念；`fontsize` 是绝对 pt，**改 figsize 不改 pt**（R6 §4.0 引 matplotlib 官方措辞） |
| R `patchwork` | `+`/`&`/`*` 加全局 theme；`plot_annotation(tag_levels='a')` 统一面板字母；`plot_layout(widths=unit(42,'mm'))` | `widths=` 数值是**相对比例**；绝对 mm 要 grid unit **且**把设备物理宽设对，否则轴标签/图例被算进面板再拉扯（R6 §2.1） |
| R `cowplot` | `plot_grid(align=,rel_widths=,labels=,label_size=)` | `align` 只对齐 ggplot 轴边缘；`rel_widths` 相对值；不声明 mm、不改字号（R6 §2.2） |
| R `egg::set_panel_size` | 把 gtable 面板设成**绝对 grid unit**（唯一直接支持绝对面板尺寸的） | 不管主题；作者原话“plots should not be rescaled (otherwise the fonts would be distorted)”（R6 §2.3） |
| R `gridtext` / `gridExtra` | 富文本标签、`arrangeGrob` 拼版 | 同上，不解决绝对 pt 与整版校验 |
| `svgutils.compose` | 合并多个 SVG 成一张 | 事后合并=事后缩放，字号随文件走；无 mm/pt 校验（R6 §1.4 结论） |
| LaTeX `subcaption`/`subfig`、`TikZ` | 页面级拼版、对齐、样式复用；TikZ 手册明确“**Do not scale graphics** … create them 'at the right size'” | 非 Python；需自家排版管线（R6 §1.4 引 tikz.dev/guidelines） |
| `matplotlib` + `Figure.add_axes` 手工 mm 定位 | 按 mm 摆多个 axes | 无跨图契约、无校验、无回执 |

### 1.2 代码路线的“成品图归档/校验”工具（新出现，直接相关）

- **`plotstyle`（Python, 现 1.2.4）**【事实】：`plotstyle.use("nature")` 设字符/尺寸/DPI；`style.subplots()` 建**多面板图并自动打面板字母**（`panel_label_case`/`panel_label_weight` 来自 journal spec，默认小写粗体 a,b,c）；`validate(fig, journal=...)` 对**整张 figure** 做维度/字号/线宽/色盲/DPI 检查，返回 `ValidationReport`（PASS/WARN/FAIL + 建议），`report.passed` 无 FAIL 时为真，可 CI 非零退出。来源：https://plotstyle.readthedocs.io/en/stable/api/validation.html ；https://plotstyle.readthedocs.io/en/stable/guides/multi_panel.html ；https://pypi.org/project/plotstyle/ 。
- **`pubfig`（Python, Galaxy-Dawn）**【事实】：panel-first——`export_panels()` 逐面板导出干净素材（可去标题）+ `panel-index.json`，再到 Figma 拼；`batch_export()` 按 publication spec 做 relayout。声称跨面板字号/间距一致。来源：https://github.com/galaxy-dawn/pubfig ；https://pypi.org/project/pubfig/ 。
- **`figurepatch`（Python, 0.1.0）**【事实】：`|`/`/` 运算符拼多面板，`constrained_layout` 防重叠，自动加粗左上角 A/B/C 标签。来源：https://pypi.org/project/figurepatch/ 。
- **`tueplots` / `matplotlib-publishutil` / `PubPlotLib` / `cosmic_toolbox` paper styles**【事实】：按会议/期刊设 sizing/fonts，属“样式基线”而非拼版。（web_search 汇总，来源见 §5）

### 1.3 桌面/在线拼版器（“成品面板排版”路线的占位者）

- **Tavotto（本地源码 `C:/Users/Lin/.omp/plugins/cache/marketplaces/tavotto/`）**【事实】——**本轮的胜负手**：
  - 对象层级明确是“一页多面板”：`docs/adr/0001-project-canvas-tab-object.md` 定义 **Project / Canvas / Tab / Object** 四层，Canvas 承载 `page, objects, guides, layoutGroups`；**`page` 是 mm 一等对象**（`src/tavotto/engine/preflight.py:32` → `"page": {"w_mm","h_mm","margin_mm"}`；`exportreq.py:269` `page_w_mm/page_h_mm`）。
  - **出版规范是一份版本化 canonical JSON**（`src/tavotto/profiles/publication.json`，`default_profile: lab-publication-v1`, `version: 1.1.0`），Python 引擎与 TS 前端**共读同一份**（ADR 0006）。字段含 `widths_mm`（单栏 80 / 双栏 150 + `tolerance_mm`）、`allowed_aspect_ratios`、`min/absolute_min/max_font_size_pt`、`min_raster_dpi`、`line_widths_pt` 四档、`axis_policy`、`legend_policy`、`cjk_fallback`、**`severity`（检查项→等级）**。
  - **整版预检**（`src/tavotto/engine/preflight.py`）【事实】：`_check_page` 存在；severity 里有 `page-width:error` / `page-aspect:warn` / `out-of-page:error` / `outside-margin:warn`；`_check_panel_fonts`（:334）逐面板算 **`eff = fontsize × scale`**（:339 `scale = panel.get("scale",1.0)`），注释原文（:15-17）：“字号一律按最终物理尺寸判…面板被缩到 60% 摆上版面时，读者拿尺子量到的是 fontsize × scale。只看原始 fontsize 会让『缩一缩就放行』成为常态，而那正是投稿被拒的头号原因。”
  - **两个求值器（Python + TS）靠 golden 向量对齐**，只比判据不比措辞（ADR 0006）。
  - **导出带 JSON 留档（proof/config）**，可读回“这张图按哪套规矩过的检”。
  - **边界**：刻意“**不发明图的内容**”，新面板仍来自脚本；写回是**override**（下次打开重放到脚本新一次运行上），**不是**把整版契约落回脚本。
- **FigureGuild Figure Assembler（在线）**【事实】：选期刊→canvas 宽按 mm（Nature 89/183、Cell 85/170、Science 90/185、PNAS/eLife 87/178、PLOS 85/170、custom）；**自动 A–Z 面板字母（左上、粗体 Arial）**；**统一 2–4 mm 间隙 + 网格吸**；导入 TIFF/PNG/PDF 面板；按 300/600/1200 DPI 导 TIFF、PDF。文案直接点名退改原因：“wrong figure width, inconsistent panel spacing, missing or incorrectly styled panel labels, and mismatched fonts across panels”。来源：https://figureguild.com/figure-assembler 。**注意**：其“2–4 mm 间隙”是第三方惯例，R6 §5 已判定主流刊物**未给**硬数字。

---

## 2. 缺口（逐条给证据）

> 每条：**要什么 → 现状证据 → 缺口在哪**。区分“别人做了”（对我们不利，照写）与“没人做”（我们的位置）。

### 2.1 跨图角色统一（字号 / 线宽 / 面板字母一档到底）

- **要什么**：多张独立代码图进同一 Figure 后，轴标题/刻度/标注/线宽各**归到唯一档位**，面板字母大小写/字重/位置**全图同档**。期刊硬要求：Science “maximum of 3 sizes / Are the font sizes consistent?”、Nature “same font throughout all figures”、JEEG 单字号 MUST、Chicago “one font point size throughout”（R6 §1.1 原文与 URL）。
- **现状证据（占位者）**：**Tavotto** 有 `min/max_font_size_pt` 与 `legend_policy` 的 min/max，且**逐面板按 `scale` 算有效字号**并给 severity；**plotstyle** `validate(fig)` 检查 typography（字号范围）+ 自动面板字母（大小写/字重由 spec 给）。→ **这一条在“成品图”层面已被占住。**
- **缺口**：**两者都不保证“多张独立代码图各回源码、按同一档位重渲染”**。Tavotto 是 override（不动脚本、不重跑源码逻辑）；plotstyle 是**在一张 figure 内**设样式，不负责“把 Fig1.py 与 Fig2.py 两张各自独立生成、画布尺寸不同的代码图拉到同一契约下重建”。**“跨图角色统一 = 回码重建”这一步没人做。**【推断】

### 2.2 最终尺寸下 `k ≡ 1`

- **要什么**：成品宽 = 声明宽（$k=1$），字号/线宽才天然一致。R6 §1.3/§4.0 已论证：官方只许缩不许放（IEEE/JAS/Wiley）、“按最终尺寸做不要缩放”（TikZ/egg/Chicago/PALASS）、`bbox_inches='tight'` 会偷走 $k$。
- **现状证据（占位者）**：**Tavotto** 承认“面板被缩到 60% 摆上版面”这一现实，于是**用 `eff=fontsize×scale` 事后补偿**——即它走的是“摆上去可能有 $k\ne1$，然后用换算把有效字号补回来/拦下来”，**不是**“按最终尺寸生成、$k\equiv1$”。**FigureGuild** 同样“选期刊→canvas 宽按 mm”，属事后按 mm 摆。
- **缺口**：**“让 $k\equiv1$ 由构造保证”这条（源头按最终 mm 重渲染）在整版层面没人做**。R6 §4.4 已把它写成 figpact 的“默认路径”，但**目前 figpact 只做到单图**：`figpact/final_size.py:152` `k = target_width_mm / measured_w`，`audit_figure()` 是**逐 script/逐 scope** 的只读审计（:126 签名），`apply_final_size()`（:396）按单 script 写回 `canvas_w_mm/canvas_h_mm`。**跨图的“同一份整版契约驱动多脚本”没有。**

### 2.3 整版级规则校验与报告

- **要什么**：把 R6 §3.3 那张“declared / measured / k / effective pt / verdict”表，做成**整版**可核验报告并可阻断。
- **现状证据（占位者）**：**Tavotto preflight 已经是整版级的**（page 检查 + 逐面板有效字号 + severity 阻断 + JSON proof）；**plotstyle `validate(fig)`** 对整张 figure 出 `ValidationReport`（PASS/WARN/FAIL + 建议 + CI 退出码）。**这一条也被占住。**
- **缺口**：**报告口径**。Tavotto 用 `eff=fontsize×scale`（**声明换算**），plotstyle 判的是**当前 figure 的实测**，两者都**不以“回源码重建后的实测 tight bbox / 实测 glyph”为准**。figpact 的独有口径是“**声明的是目标，实测的是事实**”（R6 §4.0/§4.3；`final_size.py` 已实测 `measured_export_mm`）。**“整版级 + 回码重建后实测 + 逐条可豁免（结构化 diagnostic key）”** 尚未有人提供。（figpact 单图侧已有 `qa.py` 的结构化 `Diagnostic` 与 `Exemptions`，见 §3。）

### 2.4 改一处能整版重跑

- **要什么**：改**一个**整版契约字段（如 `typography.text_pt: 7→8`、`gap_mm`、某 scope 的 `final_width_mm`），能让**整版所有面板重渲染**且结果确定。
- **现状证据**：**Tavotto** 靠 override 重放（改一处 → 下次打开重放到脚本新一次运行），但**不写回脚本**、且改的是“摆位/覆盖”，不是“整版契约→多脚本重建”。**patchwork/cowplot/egg** 是 R 语言在**一次**拼版代码里统一主题（“改一处”=改那段 R 代码），**不跨“各自独立的 Python 代码图”**。**FigureGuild** 是在线编辑器，非代码驱动。
- **缺口**：**“整版契约 → 驱动多个独立 Python 脚本按同一契约重渲染 → 确定复现”这条链路没人做。** figpact 有原子写回 + 漂移检查 + `source_commit_state/figure_verification_state`（`source_writes.py`, `python_native.py:525` 的“写前基线 + 写后重建两份实测”），但作用域仍是**单 script**。

### 2.5 对外可消费的证据 / 回执

- **要什么**：给 agent/CI/编辑一份结构化、稳定的回执（改了哪些角色、$k$、实测 pt/线宽、哪些被豁免、按哪套 profile 过的检）。
- **现状证据（占位者）**：**Tavotto** 导出 JSON proof/config（含 profile id/journal、severity 结果）；**plotstyle** `ValidationReport`（结构化 CheckResult）；**figurelint** 支持 CI exit code（R8 §9）。
- **缺口**：**“整版 + 回码重建 + 逐条豁免不串 + 稳定 diagnostic key”** 的组合没有。figpact 已有**结构化 diagnostic key**（`qa.py:29` `diagnostic_key() = (rule_id, scope, object_ids)`，注释明确“‘3p68’与‘2p02’是两条缺陷”）与 **`Exemptions`（按结构 key 豁免，`publish.py:66`）**，但**只覆盖单图 QA**，未提升到整版。

### 2.6 缺口小结表

| 缺口 | Tavotto | plotstyle | FigureGuild | R 生态 | figpact 现状 | 我们可占 |
|---|---|---|---|---|---|---|
| 跨图角色统一（成品层） | ✅ 有效字号/图例档 | ✅ 整图 typography + 自动字母 | ⚠️ 字体一致仅声明 | ⚠️ 一次拼版内 theme | 单图角色（`FINAL_KEYS`） | ❌ 已被占 |
| 跨图角色统一（**回码重建**） | ❌ override 不落脚本 | ❌ | ❌ | ❌ | 单 script | ✅ **可占** |
| 整版 $k\equiv1$（源头生成） | ❌ 事后换算补偿 | ❌ | ❌ 事后按 mm 摆 | egg 面板级、非跨脚本 | 单 script 只读审计 | ✅ **可占** |
| 整版规则校验/报告 | ✅ preflight + JSON | ✅ ValidationReport | ⚠️ 仅导出期 | ❌ | 单图 QA + 单图 final-size | ⚠️ 口径可差异化 |
| **回码重建后实测**为准 | ❌ 声明换算 | ⚠️ 当前 figure 实测 | ❌ | — | ✅ 单图已实测 | ✅ **可占** |
| 改一处整版重跑 | ⚠️ override 重放 | ❌ | ❌ | ⚠️ 改 R 代码 | 单 script 写回 | ✅ **可占** |
| 对外结构化回执（含豁免不串） | ✅ JSON proof | ✅ report | ❌ | ❌ | ✅ 单图 diagnostic key | ⚠️ 提升到整版即可 |

---

## 3. 结论与 3 条可演示最小能力

### 3.1 “整版”是不是没人占住的位置？

**不是“整版整体无人占”**——**成品面板排版 + 期刊 profile 预检这条已被 Tavotto（本地源码证据最硬）、FigureGuild、plotstyle 三家占住**，并且 Tavotto/plotstyle 都做到了“按最终尺寸算有效字号 + 整图统一校验 + 结构化报告”。**【事实，对我们不利，照写】**

**但“整版”里有一条明确没人占**——**“多个各自独立的代码图，按同一份整版契约回源码重渲染，使 $k\equiv1$ 由构造保证，并给出以回码重建后实测为准的整版级、可豁免、可重跑的回执”**。**判据**：上述 §2.1/2.2/2.4/2.5 的“回码重建”列，**三家占位者全是 ❌**；而业界至今用“人拿尺子/复印机缩 50%”核一致性（R6 §3.4，Nature/Chicago/PALASS/JAS 原文），**没有代码工具把这张表变成可测量、可阻断的判据**。

**【推断】**我们应把位置锚在**“整版契约 → 多脚本重建（$k\equiv1$）→ 实测回执”**，而**不**去重造 Tavotto/plotstyle 已占的“成品面板拖摆 + profile 预检”。差异化锚点：**回源码**（vs Tavotto override）、**实测为准**（vs Tavotto 声明换算）、**跨独立脚本的同一契约**（vs plotstyle 单 figure 内、patchwork 单次拼版）。

### 3.2 三条可演示的最小能力 + 验收标准

> 三条都**挂在既有面上**（`final_size.py` / `qa.py` / `source_writes.py`），**不新建引擎、不新建 `plate.yaml` 真值体系**（遵循 `docs/G7C2_TASK.md:32` 与 `G7_PLAN.md:29` 的既有边界）。核心新增只有**一个“整版契约（plate contract）”只读聚合层**：它读多份既有的 per-scope 审计结果，不产生第二套样式真值。

#### 能力 1 — 整版契约下的多脚本角色统一（回码重建，$k\equiv1$）

- **可演示**：给一份最小整版契约（`plate: {final_width_mm_total, gap_mm, typography:{text_pt, panel_label_pt, line_pt}}` + 每 scope 的 `final_width_mm`），**一条只读命令**同时审计 NMR 与 FTIR 两脚本（`examples/nmr`、`examples/ftir`），打印一张“scope × role：declared_pt / measured_export_mm / k / effective_pt@target / verdict”的整版表；`--apply` 时**退回各脚本**就地受控修改（复用 `apply_final_size` 的最小受控修改 + 写回 + 重建验证），使**两脚本的 `canvas_w_mm` 与共享字号档一致**。
- **验收标准（可核对）**：
  1. 整版表里每个 scope 的 `measured_export_mm ≈ declared final_width_mm`，即 **$k\in[0.999,1.001]$**（实测 tight bbox，不是声明值；沿用 `final_size.py:150` 的 `_measure_export_mm`）。
  2. 各 scope 的 `text_pt` 实测集合 **`max-min ≤ 0.25 pt`**（R6 §4.3 阈值），任一 text artist 实测 pt **≥ profile 下限**（默认 5 pt），线宽实测 **≥ 0.28 pt**。
  3. 对 `examples/nmr`+`examples/ftir` 的真实数字复现 README 的两行（NMR 42 mm: k=1.0001, axis 8.0/tick 7.0；FTIR 38 mm: k=1.0007, label 4.7→3.7 pt ⚠），且**放不下时如实报告 `infeasible`，不缩字**。

#### 能力 2 — 整版级规则校验与阻断报告（以回码重建后实测为准）

- **可演示**：一条只读命令（如 `figpact plate-check`）输出整版级结构化报告：每条含 `rule_id / scope / object_ids / severity / measured / threshold`，规则至少覆盖 R6 §4.3 的 `CANVAS_WIDTH_MISMATCH`、`FONT_SIZE_INCONSISTENT`、`FONT_BELOW_MIN`、`LINE_BELOW_MIN`、`SCALE_OUT_OF_BAND`（$k>1$ 或 $<0.5$）、`PANEL_LABEL_INCONSISTENT`、`UNMEASURED`；`--strict` 时 `/异常项非空/` → 非零退出。
- **验收标准**：
  1. **判据报“实测 pt/mm”而非“声明 pt”**（与 `final_size.py` 实测口径一致；`UNMEASURED` 不填 0、不估计）。
  2. 复用 **`qa.py:29` `diagnostic_key()`** 的结构化 key，**豁免按 (rule, scope, object_ids) 生效且不串**（演示：豁免 scope-NMR 的一条缺陷**不**顺带豁免 scope-FTIR 的同类缺陷，对应 `publish.py:66` 既有语义）。
  3. **不照抄第三方数字**：面板字母大小写/字号、gap 全部 profile 化（Nature 小写 8 pt vs Science 大写 10 pt vs SciAdv 9 pt 互斥；R6 §1.2）；`SCALE_OUT_OF_BAND` 只拒 $k>1$、$\le1$ 放行（R6 §1.3/§4.5 第 3 条）。

#### 能力 3 — 改一处整版重跑 + 对外可消费回执

- **可演示**：改整版契约**一个**字段（如 `typography.text_pt: 7.0→8.0`，或某 scope `final_width_mm`），一条命令**重建整版所有面板**并输出一份**确定**的回执 JSON（含：改了哪一项、每 scope 重建前后实测表、$k$、阻断项、豁免、按哪份 profile 过的检）；同输入重跑**逐字节一致**。
- **验收标准**：
  1. **确定性**：同契约连跑两次回执 JSON **逐字节相同**（沿用 `tools/readme/render_series.py` 的“输出确定”口径）。
  2. **改一处 → 整版动**：只改 `text_pt` 时，回执中**每个 scope 的 `effective_pt` 都变**、且**几何（面板摆位/轴范围）不变**；只改某 scope `final_width_mm` 时**只有该 scope 的 `k` 与实测宽变**。
  3. **回执可消费**：结构化字段稳定（`rule_id/scope/object_ids/measured/threshold/severity`），能被 agent/CI 直接读；**不含“未验证即通过”**——`render`/`commit` 级别严守既有 `source_commit_state` / `figure_verification_state` 的两态语义，**不承诺“整批原子发布”**（`publish.py` 明确是逐文件原子替换，非崩溃一致事务）。

### 3.3 明确不做 / 不照抄（对齐 R6 §4.5 与 G7 边界）

1. **不重造 Tavotto/plotstyle 已占的“成品面板拖摆 + profile 预检”**——那已占住，重造无差异。
2. **不做“拼版图层”（把已渲染面板贴到画布再缩放）**——PGF/egg/Nature Reviews 一致指出这条必然致字体失真与可编辑性下降（R6 §1.4）。
3. **不引入 `plate.yaml` 第二套样式真值、不新建 `source_writer_v2`**（`G7C2_TASK.md:32`）；新增只是**只读聚合 + 既有写回面**。
4. **不把第三方“2–4 mm 间隙”“uppercase only”当规范**（R6 §5 已判定非官方）。

---

## 4. 本地证据索引（可核对）

| 事实 | 本地路径 / 函数 |
|---|---|
| 单图 final-size 只读审计，$k=$ 目标宽/实测宽 | `figpact/final_size.py:126 audit_figure()`、`:150 _measure_export_mm()`、`:152 k=` |
| 单图受控修改（写回 `canvas_w_mm/h_mm` + 三角色） | `figpact/final_size.py:396 apply_final_size()` |
| 角色档位键（axis/tick/peak/label/legend/note + line_width） | `figpact/final_size.py:21 FONT_KEYS / :23 LINE_KEYS` |
| 结构化诊断 key（规则, scope, object_ids），豁免不串 | `figpact/qa.py:29 diagnostic_key()`、`:14 Diagnostic` |
| 逐文件原子发布（非事务）+ 结构化豁免 | `figpact/publish.py:35 publish()`、`:66 Exemptions` |
| 写回后“两份实测”验证 | `figpact/python_native.py:525` |
| mm/pt 换算 | `figpact/units.py` |
| CLI 面（final-size 只读 / final-size-apply 受控） | `figpact/cli.py:633 cmd_final_size`、`:650 cmd_final_size_apply` |
| 明确“不引入 plate.yaml / 不新建新体系” | `docs/G7C2_TASK.md:32`、`docs/G7_PLAN.md:29,38,230` |
| 期刊一致性/缩放/矢量/面板字母原文（R12 不重复） | `docs/research/R6_panel_assembly.md §1–§3` |
| 宽度/字号/线宽硬数字 | `docs/research/R1_journal_final_size_specs.md §1` |

**Tavotto 本地源码索引**（`C:/Users/Lin/.omp/plugins/cache/marketplaces/tavotto/`）：`src/tavotto/profiles/publication.json`（版本化 profile + severity）、`docs/adr/0001-project-canvas-tab-object.md`（Project/Canvas/Object + `page`）、`docs/adr/0006-codex-mcp-app-and-publication-profile.md`（Python/TS 共读 profile、golden 向量、override 不落脚本）、`src/tavotto/engine/preflight.py:32`（page 模型）、`:205 _check_page`、`:334 _check_panel_fonts`（`eff=fontsize×scale`）、`:269 exportreq.py`（`page_w_mm/page_h_mm`）。

---

## 5. 来源与访问

- Tavotto 本地源码（见上）；Tavotto 在线简介 https://www.tavotto.com/ 、https://pypi.org/project/tavotto/ （0.8.0/0.18.0：mm 多面板、可导入排列多面板、版本化 profile 阻断导出）。
- FigureGuild Figure Assembler https://figureguild.com/figure-assembler （访问 2026-10-15）。
- plotstyle https://pypi.org/project/plotstyle/ ；validation https://plotstyle.readthedocs.io/en/stable/api/validation.html ；multi-panel https://plotstyle.readthedocs.io/en/stable/guides/multi_panel.html 。
- pubfig https://github.com/galaxy-dawn/pubfig 、https://pypi.org/project/pubfig/ ；figurepatch https://pypi.org/project/figurepatch/ 。
- matplotlib `subfigures`/`GridSpec`、patchwork/cowplot/egg/svgutils/TikZ/LaTeX：一手来源与原文引用见 `docs/research/R6_panel_assembly.md §1–§2`（不重复）。
- 期刊整图一致性/缩放/面板字母/矢量嵌入/面板间距原文：同 R6 §1；宽度/字号/线宽硬数字见 `docs/research/R1_journal_final_size_specs.md`。

## 6. 未找到 / 存疑

- **未找到**任何代码工具把“**多个各自独立的 Python 代码图**按同一整版契约**回源码重建**（$k\equiv1$）并出**以回码重建后实测为准**的整版级回执”。这也是本文判定的可占位置。
- **未找到**主流期刊对“面板间距 = X mm / 缩放比 ≤ X%”的硬数字（同 R6 §5）。
- Tavotto 的 `source` 写回是否包含“整版契约落回脚本”**未找到证据**；其 PRODUCT.md 明确写回是 override 且“不发明图的内容”【事实】，据此判为**不落整版契约**【推断】。
- FigureGuild 是否有 API/代码驱动或结构化回执：**未找到**（页面为在线编辑器）。
- `pubfig`/`figurepatch` 声称的“跨面板一致”是否含**实测校验**：**未找到**实测证据；描述为导出期 relayout【事实】。
