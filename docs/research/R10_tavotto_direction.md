# R10：Tavotto 的能力与方向——它是否已占住「整版 + 规格检查」？

> 调研日期 **2026-10-15**。本地副本：`C:/Users/Lin/.omp/plugins/cache/marketplaces/tavotto/`
> （`origin = https://github.com/Tavotto/Tavotto.git`；HEAD `6457447`，2026-10-15 01:59Z；
> 工作树为**单提交浅克隆**，`git tag` 为空，提交历史仅 1 条 → 本地只能核**当前快照**，
> 路线图/历史必须查 GitHub）。
> 标注约定：**【事实】= 有本地文件+行号或 URL 可核；【推断】= 本文判断；「未找到」= 查过但没找到。**

---

## 0. 一句话结论（先给不利结论）

**【事实+推断】Tavotto 已经做了「多面板拼版 + 跨面板统一规格检查 + 阻断导出」这一整套，
而且做得比本仓库深。**「全版面（plate）」这个位置**已经被它占住**：

- 它有**整版画布**（mm 制页面、多面板落位、拼版导出为单一 PDF）；
- 它有**跨图/整版级规格检查**，且**字号按最终物理尺寸（fontsize × scale）判**——
  这正是 `G8DIFF_TASK.md` 第 4 行猜测的方向；
- 检查有**四档严重级 + 阻断语义**（error 默认阻止导出），阈值来自**一份版本化 JSON**，
  Python 与 TS 两个求值器共读（`publication.json`），并且**进了 proof report 留档**；
- Agent 面有** 9 个 MCP 工具 + 完整 JSON Schema + `structuredContent` 结构化回执**。

**【事实】唯一真正的空白在「写回」**：Tavotto 的写回**不把视觉改动写成 Python**
（`overrides` 只在文档里重放），脚本写回是一个 **Proposed 状态、不进 1.0、
且明令禁止 Agent/MCP 触发**的独立动作。这对 figpact 是**唯一还没被占住的差异点**，
详见 §3。

---

## 1. 多图 / 整版（plate）层面：**已做，且是一等公民**

### 1.1 整版是产品主叙事之一

- 【事实】`PRODUCT.md:30-38`：**Product Purpose** 写着「打开 matplotlib 已经画出来的图，
  点标题、图例、曲线，就地修改；**把多个面板按毫米排成一页**；按期刊规则预检；导出投稿级 PDF / PNG」。
  「成功 = 「Figure 1」做完了，而脚本一次都没有重跑。」
  `D:/L/AI/figpact` 外的路径 → 绝对路径
  `C:/Users/Lin/.omp/plugins/cache/marketplaces/tavotto/PRODUCT.md:30-38`。
- 【事实】`README.md:97-110`（「Build the page」）：面板**以脚本画的物理尺寸落在 mm 制的页面上**；
  拖动、相互吸附、对齐、分布、分组；**bind panels into a row, column or grid that reflows when a size changes**；
  「(a)(b)(c) 面板标号来自一条命令」；标注（文字/箭头/形状/任意角度）叠在上面，
  并有科研「家具」预设（可逆反应箭头、比例尺、放大框）。
- 【事实】代码侧落点：
  - 布局组重排是纯函数：`web/src/lib/layoutGroups.ts:55` `reflowPatches(doc, g)`（整组重排只重分配组内相对位置，`layoutPinned` 原地不动）。
  - 面板标号：`web/src/store/actions.ts:272`「按阅读顺序给所有面板添加 (a)(b)(c) 标签」；
    阅读顺序判据 `web/src/lib/geometry.ts:340`（先按行、行内容差 5mm，再按列）。
  - 文档模型有 pages/objects（`web/src/lib/projectDocs.ts`、`web/src/types/document`）。
- 【事实】功能登记表 `docs/features/registry.json`（58 条，用户可见功能的唯一清单，门禁
  `scripts/ci/feature_registry.py`）里与整版相关的 active 条目：
  `canvas.page-fit-and-placement`（换画布尺寸自动重新取景/大图等比缩放/页面外画淡）、
  `canvas.proportional-scale-snap`、`canvas.multi-context-bar-align`、
  `figure.cross-figure-align`（**图内编辑时，拖元素/子图缩放手柄会吸到别的图里的同类元素和页面参考线上**）、
  `problems.subplot-cards`（一张组图拆成 (a)(b)(c) 卡片，可只修一个子图）。
- 【事实】导出侧：整版合成走 `rendercore`（ADR 0065「外来页与位图的矢量合成」，Accepted），
  每个原矢量面板以 **Form XObject** 整页矢量搬运、**文字层保留**（README:239-246）。
  ADR 0065 裁决了页盒（TrimBox→CropBox→MediaBox）、/Rotate、/UserUnit、crop/翻转/旋转顺序
  （唯一出处 `rendercore/placement.py::place()`）、面板 opacity、镜像不退位图，等等。

### 1.2 页面尺寸与 mm 口径

- 【事实】页面在画布上是 mm 制；面板带 `rect_mm`/`scale`（`src/tavotto/engine/preflight.py:32-49` 的 `SPEC_DOC`）。
- 【事实】profile 里 `widths_mm: {single: 80.0, double: 150.0, tolerance_mm: 0.5, allow_custom: true}`
  （`src/tavotto/profiles/publication.json:11-16`），并有 `allowed_aspect_ratios`（16:9 / 4:3 / 1:1）
  与 `aspect_tolerance: 0.04`（同文件 `:17-22`）。
- 【推断】Tavotto 的 mm 口径是**「面板物理落位 + 页面物理尺寸」**，没有 figpact 那种
  `frame/render/units/measurement-uncertainty/tolerance` 的**测量不确定性**分层；它的容差是
  工程常量（`EPS_MM=0.05`、`FIGURE_CLIP_EPS_MM=0.3`，`preflight.py:53,63`），不是可声明的测量模型。

### 1.3 对我们的意义（不利发现）

- 【推断】**「测量扩展到全版面（plate）」不是可占位置**。Tavotto 已经：整版 mm 画布、
  跨图对齐/吸附、面板标号、组重排、整版预检、矢量拼版导出。我们在 `G8DIFF_TASK.md:4`
  猜测的方向，**已被它实现并写进 README 主视觉**。
- 【事实】甚至「跨图角色统一」也部分做了：`figure.cross-figure-align`（跨图同类元素吸附）
  与整版级预检（每个 panel 带自己的 `scale`，字号/线宽按 `×scale` 判，见 §2）。

---

## 2. 期刊规则检查与阻断语义：**已做，是它的核心卖点**

### 2.1 规则清单（本地路径 + 行号）

权威文件**只有一份**：`src/tavotto/profiles/publication.json`（200 行，随 wheel 分发）。
两个求值器：`src/tavotto/engine/preflight.py`（1091 行，给 MCP server）与
`web/src/lib/preflight.ts`（1215 行，给画布/导出对话框）；两者靠
`tests/golden/preflight_vectors.json` 对齐（pytest 与 vitest 各跑一遍同一份向量）。
规则文档：`docs/rules/backend/profiles-and-preflight.md`（唯一全文）。

**`lab-publication-v1`（version 1.1.0）实际规则（`publication.json`）**：

| 组 | 值 | 行号 |
|---|---|---|
| 页宽 | single 80.0 / double 150.0 mm，`tolerance_mm` 0.5，`allow_custom` | `:11-16` |
| 比例 | 16:9 / 4:3 / 1:1，`aspect_tolerance` 0.04 | `:17-22` |
| 字体族 | 拉丁 Times New Roman（`latin_accepted` 9 项）；**替代品黑名单** `latin_substitutes_flagged`（DejaVu / Arial / Helvetica / sans-serif） | `:23-30` |
| 中文 fallback | `required: true`；preferred 方正小标宋；accepted 25 项（Noto/Source Han/微软雅黑/宋体/黑体/PingFang…） | `:31-43` |
| 字号 | 默认 9.0；`min_effective_font_size_pt` **8.0**；`absolute_min_font_size_pt` **8.0**；max 12.0 | `:44-47` |
| DPI | `min_raster_dpi: 300` | `:48` |
| 格式 | 矢量 pdf/svg；栅格 png/tif/tiff/jpg；默认导出 pdf+png；默认 DPI 600 | `:49-54` |
| 线宽 | 档位 `[0.5, 0.75, 1.0, 1.5]` pt，容差 0.08 | `:55-56` |
| 坐标轴 | 刻度朝内、封闭四边、次刻度 opt-in、轴标题格式 `Title (unit)` + 正则、外框线宽 `[0.75,1.0]`、最多 10 个刻度标签 | `:57-65` |
| 图例 | 无框；字号 8.0–9.0 | `:66-70` |
| 色系 | 推荐 Crameri Scientific colour maps（按 semantic 分组，URL 给出）；**劝阻** jet/rainbow/hsv/gist_rainbow/nipy_spectral；`auto_recolor: false` | `:71-83` |
| 字重 | 只轴标题加粗，其余常规；按角色，**只作建议** | `:84-92` |
| 严重级 | 39 个 check_id → error / warn / suggestion / not_verifiable 的映射 | `:93-131` |

**第二份 profile** `free-form-v1`（`:133-198`）：只做技术性检查（缺素材/渲染失败/越界/DPI），
尺寸与字体规范降级为提示；字号下限 6.0 / 绝对下限 5.0。

### 2.2 检查项实现（`preflight.py`）

- 【事实】`_check_page`（`:205-252`）：页宽（不是单/双栏 → `page-width`）、页面比例（→ `page-aspect`）。
- 【事实】`_check_panel_state`（`:255-288`）：缺素材、渲染失败、陈旧渲染（脚本已更新未重建）、
  **未应用 override**（→ error，`unapplied-override`）。
- 【事实】`_check_panel_raster`（`:291-317`）：**等效 DPI** = `px_w / (w_mm/25.4)`，低于 300 报 error；
  并且**位图内部文字字号报 `not_verifiable`**（「没有矢量文字层，请人工确认」）。
- 【事实】**字号按最终物理尺寸判**：`_check_panel_fonts`（`:334-481`）里 `eff = size * scale`（`:358`），
  低于绝对下限（`<=` 不算过）报 `font-below-absolute-floor`，低于严格下限报 `font-too-small`，
  超过上限报 `font-too-large`；模块 docstring `:15-17` 明说理由：「只看原始 fontsize 会让
  『缩一缩就放行』成为常态，而那正是投稿被拒的头号原因」。
  **同一逻辑对线宽也成立**（`:571-591` 外框、`:609-629` 数据线、`:630-653` 图例示意线，全部 `eff = lw * scale`）。
- 【事实】字体族替代（`:390-413`）、**中日韩 fallback**（`:414-439`，用 manifest 报的 `cjk_family`
  而非族名，避免把回退链画得好好的中文误报成方框）、**字形覆盖**
  （`:440-467`，`glyphs_missing` → error `glyph-missing`；`glyphs_fallback` → suggestion `glyph-substituted`）。
- 【事实】坐标轴：`tick-direction`、`spines-not-enclosed`、`spine_linewidth` 档位、
  `axis-label-format`（正则）、`tick-label-count`（`_check_panel_axes` `:483-735`）。
- 【事实】图例：`legend-frame`、`legend-font-size`（`eff = size*scale` 落在 [8,9]）。
- 【事实】色系：`discouraged-colormap` / `palette-semantic`（`:657-683`）。
- 【事实】数据语义（**只给建议，绝不替用户裁决**）：`bar-without-errorbar`、`fit-without-ci`
  （靠 `_FIT_WORDS` 正则 `fit|拟合|regression|回归|trend|linear`）、`palette-line-markers`（`:697-735`）。
- 【事实】几何：`_check_geometry`（`:746-811`）越出页面、超出边距、重叠、文字压轴；
  `_check_texts`（`:825-908`）、`_check_panel_clipping`（`:977-1012`，元素超出图幅，
  容差 `FIGURE_CLIP_EPS_MM = 0.3` mm，理由写在 `:55-63`：布局框≠墨迹，0.56mm 的探出已是可见裁切）。

### 2.3 阻断语义

- 【事实】`summarize()`（`:1044-1056`）返回四档分组 + `counts` + **`blocking: len(errors)>0`**，
  docstring 明写「MCP 与导出对话框都用它做『能不能导出』的判据」。
- 【事实】`tavotto_export` 工具描述
  （`codex-plugin/mcp/tavotto_mcp/server.py:469-503`）：「**先跑一遍预检**：有 error 且没有
  `explicit_confirm` 时**一张图都不出**」；`explicit_confirm` 只在「用户明确要求带着这些问题也要导出」时才置 true。
- 【事实】四档语义（`docs/rules/backend/profiles-and-preflight.md:42-45`）：
  `error` 默认阻止导出、显式确认才放行且写进 proof；`warn` 放行必展示；
  `not_verifiable` 查不了、需人工确认并写进 proof；`suggestion` 全给数据语义类。
  **没登记的检查项兜底为 warn**（刻意不是 suggestion）。
- 【事实】阈值来源**唯一**：`docs/rules/backend/profiles-and-preflight.md:6-11`「规则的唯一权威文件是
  `publication.json`…**绝不在任一侧硬编码同一条规则**」，并记录了旧代码
  （`preflight.ts` 里 6pt/300dpi、ExportDialog 里 85/150/180mm）各写一份的教训。
  `:24-25`：「**阈值一个字都不许写进求值器**，缺键时的兜底只有 `profiles.FALLBACK_MIN_FONT_SIZE_PT` 一处」。
- 【事实】ADR 0029（`docs/adr/0029-style-spec-profiles.md`）：最小字号只留**一个数 8pt**
  （删掉了更严的 8.5pt）；Style / Spec / Export 三层各有唯一出处；
  **项目里存绑定 + 当时生效的规则全文快照**（`FigureDocument.profile =
  {id, journal?, snapshot?, snapshotVersion?, follow?}`），「有没有新版」的判据是**内容不等**而非版本号，
  同步由用户确认；模板升级后旧图不会悄悄换一套判据。
- 【事实】期刊自定义走**覆盖而非 fork**：`journal` 是浅合并补丁（几个子对象深合并），
  结果带 `derived_from`/`journal` 并**写进 proof report**（ADR 0006 §1、README:741-747）。
- 【事实】**没有找到**「字体嵌入检查」这一条 check_id（在 `preflight.py` 里 grep `embed|嵌入` 无命中）。
  它检查的是**字形覆盖 / 回退**（`glyph-missing`/`glyph-substituted`）与**族白名单**，
  字体嵌入在渲染层由 allowlist 保证（ADR 0060：文件字节 sha256 白名单，集合外 → `.notdef` + Problems 里一条 +
  ToUnicode 仍回原字）。【推断】这是「嵌入是否成功」的**结构性保证**，而非「检查项」——与我们的
  「字体嵌入检查」在**语义上等价**，只是实现位置不同。

### 2.4 对我们的意义

- 【推断】**「期刊规则检查 + 阻断语义」也不是空白**。Tavotto 的实现比 figpact 的 R1 研究更完整：
  它有第二份 profile（自由排版）、期刊覆盖机制、快照绑定、
  「登记的才是 error、没登记兜底 warn」的治理、以及**把确认也写进 proof**的留档。
- 【事实】我们**强于**它的地方目前只有一处可考：**测量不确定性 / tolerance 分层**
  （Tavotto 的容差是常量，`EPS_MM=0.05` 等）。

---

## 3. 写回 Python 到底做到什么程度：**这是唯一的真空白**

### 3.1 现状：默认**不写脚本**

- 【事实】`PRODUCT.md:44-45`：「**改动始终挂在脚本上**。每次修改存为文档旁的 override，
  在下一次打开时重放到脚本的全新一次运行上；撤销、版本历史、导出质量重渲染都建立在同一机制上。」
- 【事实】`PRODUCT.md:59-60`：「用户的脚本与图**只读**，除非显式『写回原文件』
  （写回会从头重跑脚本证明结果一致；可按项目锁死）」——注意这里的「写回原文件」是
  **写回图文件（PDF/PNG）**，不是 Python。
- 【事实】`overrides.py:1-11`：文档每次发**全量** override 列表 `[{gid, prop, value}]`，
  worker 维护 applied/originals 两张表以支持 undo；`overrides.py:75` 每次 apply 前 `fig.canvas.draw()`。
- 【事实】`tavotto_apply_overrides` 工具描述（`server.py:323-333`）末句：
  **「不会改用户的 Python 源码。」**
- 【事实】v0.18.0 release notes（`docs/release-notes/v0.18.0.md`）在「Input paths that need a script change
  get a reviewable repair」一节末句明写：
  **「This repairs input paths; it does not write arbitrary visual figure edits back into Python.」**
- 【事实】唯一会改脚本的既有路径是 `engine/scriptedit.py`（ADR 0110），它**只替换数据路径字符串常量**
  （docstring `:1-14`），有一次性确认令牌（绑定浏览器会话 + 写前写后 sha256、单次、10 分钟）、
  四条静态自检、`_block外一个字节不动`、可 `undo()` 只撤销那几处。

### 3.2 脚本写回：设计已完成，但**状态是 Proposed 且不进 1.0**

- 【事实】`docs/adr/0094-script-writeback.md`（日期 2026-09-26，**状态：Proposed**）是完整设计：
  - **形态 A（推荐）**：在脚本 import 段之后插入**一段带标记的代码块**（`# >>> Tavotto 调整 >>>` …），
    按 savefig 的 stem 认图，`_install` 包住 `Figure.savefig` 钩子。**整段删除即逐字节恢复原样。**
  - **不是**只改 override：写回后**同一次事务里把这几条 override 从文档去掉**（`§三.6`，防重复应用）。
  - **验证**：prepare → verify → commit，任一环不过 409、原脚本零改动。
    verify 用一次性 worker 跑新脚本，与热态过 `_compare_manifests`（几何）+ **像素门**
    （`pdfbackend.compare_png` 逐 RGBA，`REPLAY_PIXEL_TOL`），**worker 一条 warning 即阻断**。
  - **版本/漂移检查**：跨两份文件的**前滚日志**（`<data_dir>/script_writeback/journal/<txn>.json`，
    记写回前/后 sha256，原子写+fsync），打开项目与渲染前逐条恢复；
    按**磁盘脚本此刻的哈希**判「等于前 / 等于后 / 都不是（→ `needs_user`，绝不自动选一边）」。
    有未收尾日志时**不渲染**热 worker 不起。
  - **备份**：两处（项目内 `tavottofile/script-backups/…` + 数据目录镜像），
    写不进去则整次 409；第一条标 `pristine` **永不自动清理**，其余保留最近 20 条。
  - **漂移/外部改脚本**：磁盘 sha256 ≠ 写回后记下的 → **绝不静默覆盖**，给「只移除 Tavotto 段」/
    「整份恢复」两个选项；块本身被改过则只给第二项。
  - **多图/循环/辅助模块**：按 stem 认图全部成立；同一进程多份写回脚本用**按脚本绝对路径登记的注册表**，
    同名 stem 只认调用栈上那份，认不出则告警且**一步都不调**。
  - **覆盖率**：249 个 (类, prop) 键中，**6 个（2.4%）原则上永不写**（色条 orientation/extend、
    3D 轴箭头六个——只用私有 API），其余 243 有公开 API 路子；spike 82 条实测
    第一轮 69（84%）→ 开两条路线后 **81/82（98.8%）**，加兜底 82/82。
  - **Agent 接口 v1 不开放**（`§七.3` Q4）：MCP 结果里最多一句「可在 Tavotto 里写回脚本」；
    `§七.4` 把它写成**判据**——AST 门禁禁止 `codex-plugin/`、`engine/ai_*`、`specfix`、
    样式与刷新代码出现提交端点调用；提交端点只收**同一浏览器会话**发的一次性令牌。
  - **发布节奏**（`§十三`）：**建议不进 1.0 GA**，排在 1.0 之后第一个 minor。

### 3.3 对我们的意义（**这是 R10 最重要的发现**）

- 【推断】**figpact 目前的「写回 Python / 可重跑」差异点在 Tavotto 这边是「设计完成、但被明确推迟且拒绝 Agent 触发」**。
  这既是**风险**（他们随时可以做出来，设计已含像素门 + 漂移日志，比我们预想的更硬），
  也是**机会**（v1 窗口里这块是空的，且他们自设了「Agent 不能替用户改脚本」的禁令）。
- 【事实】**他们的写回形态是「追加一个 savefig 钩子块」，不是「把每条 override 落回原生语句」**，
  且明确拒绝就地改 AST 字面量作为默认（82 条里只有 22% 能干净表达，且 `tight_layout` 顺序会变）。
  【推断】如果 figpact 走「override → 原生调用点原位改写」的路线，那是**与 Tavotto 不同的写回语义**。

---

## 4. Agent 接口：**9 个工具 + 完整 schema + 结构化回执**

【事实】MCP 工具清单（`codex-plugin/mcp/tavotto_mcp/server.py:160-584`，`_tools()`）：

| # | 工具 | 行号 | 作用 |
|---|---|---|---|
| 1 | `tavotto_health` | `:164` | 引擎版本 / 内嵌画布资源 / 允许的项目根；`probe_worker=true` 顺带探测渲染解释器 |
| 2 | `tavotto_open_figure` | `:184` | 打开一张图 → session_id / manifest / 预览 SVG / canonical patch hash / 出版规范；支持 `stems`/`discover_stems` 批量 |
| 3 | `tavotto_apply_overrides` | `:323` | 应用 override（**全量列表语义**）并重渲染 |
| 4 | `tavotto_normalize_figure` | `:380` | 保留原图的规范化（改尺寸/字体/最小字号），四件事同时成立才算成功 |
| 5 | `tavotto_preflight` | `:449` | 出版规范体检（四档） |
| 6 | `tavotto_export` | `:469` | 导出（**先预检**，有 error 且无 `explicit_confirm` 一张图都不出） |
| 7 | `tavotto_verify_replay` | `:505` | 自检：热态 == 全新 worker 全量重放 |
| 8 | `tavotto_refresh_project` | `:520` | 改过绘图脚本后刷新项目（**不执行用户代码**） |
| 9 | `tavotto_session_state` | `:556` | 会话当前快照（只读，不重渲染） |
| — | `tavotto_close_session` | `:574` | 关闭会话 |

- 【事实】**schema 稳定性**：每个工具都有完整 `inputSchema`（`type: object` + `properties` +
  `additionalProperties: false`），必填项显式 `required`。README 也称「nine tools」。
- 【事实】**回执是结构化的**：`server.py:8-11`「`structuredContent` 里机器可读的全量 JSON
  （Codex 拿来继续干活、widget 拿来更新画布）。**失败一律 `isError: true` + 机器可读 `code`，不吞。**」
  `manifest` / SVG 这类大字段只进 `structuredContent`、不进 `content` 文本。
  失败码是**闭集**（如 `workdir_confirmation_required`、`dependency_preparation_required`、
  `script_needs_arguments`、`script_changed`、`dependency_impact_required`、
  `dependency_impact_changed`、`workspace_root_too_broad`）。
- 【事实】有**载荷预算**机制：超过宿主事件上限时按定长字段裁剪、`elided` 字段说明省了什么、去哪儿取
  （`server.py:65-147`，`HANDLE_ONLY_KEYS` / `HANDLE_PREFLIGHT_KEYS = (counts, blocking, needs_confirm,
  detailed_text, code, error)`）。
- 【事实】另有 `engine/receipt.py`：ExecutionReceipt（ADR 0053/0070）——「这次到底是谁、在哪、用什么跑的」，
  身份三分（`private_invalidation_key` 含机器路径 / `public_identity` 不含 / 文件 hash 在别处），
  `completeness` 两档（complete / partial），**自报必须来自跑了脚本的那个进程**，
  否则拒收（`runtime_rejected`）。
- 【事实】多宿主：Codex 插件、Claude Code 插件、DeepSeek Harness bundle、WorkBuddy
  （`docs/adr/0103`、`0104`、`0109`），`docs/implementation/multi-host-mcp/`。
- 【事实】授权收窄（v0.18.0）：**MCP 授权必须点名项目，不接受整个 home 目录或其祖先**
  （`workspace_root_too_broad`）。

**【推断】Agent 面 Tavotto 强于 figpact**：9 个稳定工具 + 闭集错误码 + 结构化回执 + 载荷预算
+ 多宿主分发（marketplace/plugin-stable 渠道）。

---

## 5. 路线图 / issue / release notes：**正在做的是打包/CI/原生体验，不是「整版 + 规格检查」**

### 5.1 GitHub 元数据（URL，2026-10-15）

- 【事实】https://github.com/Tavotto/Tavotto —— **Stars 496 · Forks 23 · Issues 205 · Language Python ·
  License AGPL-3.0**。描述：「Make AI-generated scientific figures editable without losing the code behind them.」
- 【事实】PyPI：https://pypi.org/project/tavotto/ （README 徽章引用；本地 `marketplace.json` 的插件
  `ref: plugin-stable`，`homepage: https://github.com/Tavotto/Tavotto`）。
- 【事实】marketplace 描述：「Tavotto：论文级 matplotlib 出图与出版规范预检（Claude Code 插件）」。
- 【事实】**没有 GitHub Releases 页面的 tag 数据可核**（本地浅克隆 `git tag` 空）；
  版本号来自仓库内 `docs/release-notes/v0.1.1 … v0.18.0`（23 个文件）+ `UNRELEASED.md`。

### 5.2 当前 open issue（最新 12 条，URL: `https://github.com/Tavotto/Tavotto/issues`）

【事实】近 12 条**全是工程/分发/CI/桌面原生**问题，**没有一条**关于整版规格、跨图统一、
期刊规则扩展或写回脚本：

- #1096 项目设置接受相对导出/备份目录（cwd 基准）· #1092 出口看护对 `#[cfg(test)]` 误报 ·
  #1091 agent_verify 产物绑定 · #1090 bridgeboot 帧误判 · #1088 Windows e2e cross-figure-align 间歇超时 ·
  #1086 runroute 静态侧误升高置信 · #1084 perf_macos_window compare 证据 ·
  #1080 [P1] nightly 真窗口用例 5 条红（GetMenu 为空）· #1075/#1074 macOS 包重复带 CPython（23MB / 17MB）·
  #1071 原生救援后续 · #1066 一键打开并运行恢复路径。
- 【事实】**roadmap label 查询返回同一批 issue**（`?q=is:issue+label:roadmap`），
  说明**没有单独的 roadmap 标签在用**，也**没有公开的 milestone/roadmap 文档**（未找到）。

### 5.3 Release notes 指向

- 【事实】`docs/release-notes/UNRELEASED.md`：待发条目**只有一条**——Codex on Windows 后台环境修复与
  重试退避（`0x800700e8`、`TAVOTTO_MCP_NO_AUTO_PROVISION=1`）。**没有整版/规格/写回的新条目。**
- 【事实】v0.18.0（最新已发布，`docs/release-notes/v0.18.0.md`）方向：
  布局时间线与命名检查点、缺失输入重定位与**可选**改写脚本路径常量、
  脚本 `input()` 交互、一键环境修复、方向键微调、多选排版栏、
  共享色条成组、远程实例窗口、Claude Code / DSH / WorkBuddy 宿主、
  「更安静的编辑器」、问题面板按子图分卡片。**写回脚本只在「Changed」区出现一句：
  「Writeback history is part of the writeback dialog」**（指的是写回**原图文件**的历史）。
- 【事实】v0.17.0：切到 RenderCore（PyMuPDF 退役）、镜像/半透明面板保持矢量、
  PNG 记录真实分辨率、Intel Mac dmg 首发、**图例字号现在缩放整个图例盒**、
  样式值与 inspector 尺寸改成 page pt。
- 【事实】`docs/1.0-release-readiness.md`（2026-08-21 建立）是**稳定化退出条件**而非功能路线图：
  1.0 的判据是「收敛（convergence）」——P0/P1 归零、结构性不变式全绿、跨 matplotlib 版本矩阵、
  三平台绿、分发冒烟绿；§4 是 **Post-1.0 architecture backlog**（图例重建幂等、alias/originals 建模、
  `honours_stroke_style` 例外、CompatBench 声明式分类、按对扫 harness、Collection 能力表、多宿主色条）
  ——**全部是引擎内部结构，没有一条是「整版规格」或「写回脚本」**。
- 【事实】`docs/1.0-release-readiness.md:83-89`「1.7 不要求的事」：不要求 review 零发现、
  不要求支持每个 artist、不要求架构达最终形态。
- 【事实】ADR 0094 §十三明确：**写回脚本建议不进 1.0**，排在 1.0 之后第一个 minor。

### 5.4 结论：方向判断

- 【推断】**「整个版 + 规格检查」不是它「正在做的下一件事」，而是它「已经做完的事」**。
  它当前投入在：1.0 稳定化收敛、桌面/多宿主分发、CI 与性能门禁、环境与原生体验。
- 【推断】它的 roadmap 在 **1.0 收敛纪律**下：功能面暂停扩张，写回脚本被明确推迟到 1.0 之后。
  ——**这给 figpact 一个时间窗**，但**不是能力窗**：整版与规格检查的能力窗**已经关闭**。

---

## 6. 逐问回答（R10 五个问题）

| # | 问题 | 回答 | 关键证据 |
|---|---|---|---|
| 1 | 多图/整版（plate）？ | **已做，且是一等公民**：mm 制页面、多面板落位、吸附/对齐/分布/分组、组重排、面板标号一条命令、整版矢量拼版导出（Form XObject，文字层保留）、页面尺寸与 mm 口径完整 | `PRODUCT.md:30-38`；`README.md:97-110,239-246`；`layoutGroups.ts:55`；`actions.ts:272`；ADR 0065 |
| 2 | 期刊规则检查 + 阻断语义？ | **已做，是核心卖点**：**一份**版本化 `publication.json`（39 个 check_id、四档严重级）；两求值器（py 1091 行 / ts 1215 行）靠 golden 向量对齐；**字号与线宽按最终物理尺寸 ×scale 判**；**error 默认阻止导出**，`explicit_confirm` 才放行；阈值来源唯一、不许硬编码进求值器；期刊覆盖 + 快照绑定 + proof report 留档 | `publication.json` 全文；`preflight.py:205-1041`；`rules/backend/profiles-and-preflight.md:6-45`；ADR 0006/0029 |
| 3 | 写回 Python 到什么程度？ | **默认不写**（`apply_overrides`「不会改用户的 Python 源码」）。唯一在设计中的写回是 **ADR 0094，状态 Proposed、不进 1.0、v1 对 Agent 不开放**；形态是「追加 savefig 钩子块」而非落回原生语句；含像素门 verify、跨文件前滚日志、双备份、漂移两选项、2.4% 键永不写（私有 API） | `PRODUCT.md:44-45,59-60`；`server.py:332`；`v0.18.0.md`（"does not write arbitrary visual figure edits back into Python"）；`adr/0094-script-writeback.md` 全文 |
| 4 | Agent 接口完整清单 / schema / 结构化回执？ | **9 个工具**，每个有完整 `inputSchema` + `additionalProperties: false`；**`structuredContent` 结构化回执**，失败 `isError: true` + 机器可读**闭集** `code`；载荷预算与 `elided`；另有 ExecutionReceipt（ADR 0053/0070）；**多宿主**（Codex/Claude Code/DSH/WorkBuddy） | `server.py:160-584,8-11,65-147`；`engine/receipt.py`；ADR 0103/0104/0109 |
| 5 | 路线图/issue/release notes 正在做什么？特别是否朝「整版 + 规格检查」走？ | **没有朝那个方向走——因为已经走完了**。最近 12 条 open issue 全是工程/分发/CI/桌面；UNRELEASED 只有一条 Windows 环境修复；v0.18.0 主题是布局时间线/缺失输入/交互/环境/宿主；1.0 是**收敛纪律**（P0/P1 归零 + 不变式），§4 backlog 全是引擎内部结构。写回脚本被 0094 明确推迟到 1.0 后 | `github.com/Tavotto/Tavotto/issues`（12 条）；`release-notes/UNRELEASED.md`；`v0.18.0.md`；`1.0-release-readiness.md`；ADR 0094 §十三 |

---

## 7. 不利发现汇总（按任务书要求必须写）

1. 【事实+推断】**「全版面」已被占住**，不是可占位置。Tavotto 的整版不是附加功能，
   而是产品主叙事（`PRODUCT.md:30-38`「把多个面板按毫米排成一页」）+ README 主视觉
   （`assets/readme/layout.png`、`workbench.png` 都是 (a)(b)(c) 三面板 150×112.5mm）。
2. 【事实+推断】**「期刊规则检查 + 阻断」已被占住且更强**：它比我们多出
   「第二份 profile（自由排版）」「期刊覆盖 + 快照绑定 + 内容不等判新版」
   「没登记的检查项兜底 warn」「确认也写进 proof」「字号/线宽按 ×scale 判最终物理尺寸」
   「位图内部文字如实报 not_verifiable，绝不假装通过」。
3. 【事实】**它的「Agent 面」明显强于 figpact**：9 工具 + 闭集错误码 + 结构化回执 +
   载荷预算 + 四个宿主渠道 + 一键安装。
4. 【事实】**它的工程证据密度高**：golden 向量双求值器对齐、反空门禁纪律、
   `1.0-release-readiness.md` 里的「抽掉不红」教训、跨 matplotlib 版本矩阵、
   写回 spike 的 56 种崩溃组合 + 5 个反证变异。【推断】figpact 在「可公开核验的证据包」上处于劣势
   （R9 已记过 mpltweak 的同类劣势）。
5. 【事实】**496 stars / 205 issues / AGPL-3.0**：活跃、有真实用户反馈量（R9 里 mpltweak 是 1 star）。
6. 【事实】**AGPL-3.0-only**：对 figpact 的含义是——不能直接取其代码（除非我们也要 AGPL），
   只能作为能力基准。【推断】也意味着它不太可能成为我们可依赖的上游组件。

---

## 8. 我们仍能站的位置（诚实版）

- 【推断】**唯一还没被占住的差异**：**「把视觉改动落回 Python 源码」+「Agent 可编程驱动」**。
  Tavotto 明确把这两件事**拆开并各自封死**：写回脚本既不进 1.0，又禁止 Agent/MCP 触发
  （ADR 0094 §七.3/§七.4 写成 AST 门禁）。
  ——它的理由是「改用户脚本必须是人亲手确认的导出动作」，这是**产品价值观**，不是能力缺口。
- 【推断】**次好的差异**：**测量不确定性 / tolerance 分层**。Tavotto 的容差是工程常量
  （`EPS_MM=0.05`、`FIGURE_CLIP_EPS_MM=0.3`、`line_width_tolerance_pt=0.08`），
  没有可声明的测量模型。【推断】「以 mm 为单位的测量 + 不确定性 + tolerance」
  仍是 figpact 可站的位置（与 R9 §4 的判断一致）。
- 【推断】**不能站的位置**（已关闭的能力窗）：多面板拼版/整版 mm 画布、跨图对齐吸附、
  面板标号、整版级规格检查、阻断导出与 proof 留档、MCP 结构化回执。这些都已在 Tavotto 里实现并发布。
- 【事实-风险】**倒计时**：ADR 0094 的设计已含**像素门 verify + 跨文件前滚日志 + 漂移两选项**，
  比 figpact「restore 靠备份」的做法更硬。一旦他们做完，我们唯一的差异点也没了。
  【推断】如果 figpact 要走这条路，**必须**在「Agent 可编程 / 可 CI / 可批量」这个
  Tavotto 自设禁令的另一面建差异化（它是「人亲手确认的一次导出」，我们可以是「可自动化的规格落回」）。

---

## 9. 未找到 / 未确证（明确记录）

- **未找到**公开的 GitHub roadmap / milestone / project 看板（`label:roadmap` 查询返回普通 issue）。
- **未找到**「字体嵌入检查」这一条 `check_id`（`preflight.py` 里 grep `embed|嵌入` 无命中）；
  字体嵌入由渲染层 allowlist 结构性保证（ADR 0060），**不是**一条检查项。
  → 若我们把它算成「我们独有的检查项」，这个说法**站不住**（语义等价、位置不同）。
- **未找到** Tavotto 对 `.py` 脚本**是否在 repo 内**的 tag/release 二进制可核：
  本地浅克隆无 tag，GitHub Releases 的具体 tag 列表本次未逐条核（只有 `/releases/latest` 徽章）。
- **未确证** Tavotto 的 issue 总量 205 中关于「整版/规格」的具体条数（本次只核了默认列表 + roadmap 查询首页，
  未做全量 205 条分页检索）。【推断】从 12 条样本与 UNRELEASED 看，主题集中在工程面，但这是**抽样**。
- **未确证** `tavotto_preflight` 在**多面板整版**场景下的实际输出（本地没有跑起来验证；
  「字号按 ×scale 判」与「面板级 scale」是从 `preflight.py:15-17,358,571-591,609-629` 的代码与注释读出的）。
- **未找到** figpact 之外、是否还有第三方工具同样占住「整版 + 规格检查」（R12 的职责，不在 R10）。

---

## 10. 给 R11 / R12 的交接（一句话）

R10 判定：**「整版」与「规格检查」两个位置已被 Tavotto 占住（且做得更深）**；
真正的空白收窄到 **「视觉改动可编程地落回 Python」**——而 Tavotto 对这块有**明确的产品禁令**
（ADR 0094 §七.3：Agent 不开放；§十三：不进 1.0）。R12 应据此判断：
「整版是不是没人占住」的答案**是否**（Tavotto 占住），
因此 §3 的「3 条可演示最小能力」应改为**「写回 + Agent 可编程」的最小能力 + 验收标准**，
而不是整版级规则校验与报告。
