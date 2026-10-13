# G7 下一阶段计划（方向调整版）

**状态**：设计定稿候选，**未实施**。本文是 G7 的活计划（live plan）；`docs/G6B_FINAL_ADJUDICATIONS.md` §七 保留 G6b 收口时的原始裁定记录，冲突处以**本文**为准。
**作者裁定**：用户 2026-10-14 调整投资重点（不是推翻 G7 P1）。
**调研全文**：`docs/research/R1…R6`（每条事实带 URL；本文只引用结论，不重复引用链）。

---

## 0. 已完成（截至 `25239c0`）

| 项 | 提交 | 状态 |
|---|---|---|
| G7 **P0a** 双状态机（`source_commit_state` / `figure_verification_state`） | `6840c9b` | 已实现，含"同秒等长重写导致验证证据静默错误"的真实缺陷修复 |
| G7 **P0b** FTIR 确定性构图 + D-5 根因更正 | `a49e5c9` / `40af773` | 已实现；真实根因是**样式只在 import 时 apply**（与 NMR P0 同类） |
| G7 **P1-a** 图上拖动 + 即时预览（松开一次真实 evaluate） | `9331f69` | 已实现，拖动期间零后端调用 |
| G7 **P1-b** 选区上下文（scene/constraints/impact，只读） | `a784dba` | Hub 内部方法已实现；**HTTP 未接线** |
| 浏览器套件抖动 | `5f9f4f4` | 查到两个真缺陷（固定 sleep 断言、端口落 Chromium 黑名单），非调大超时了事 |

**未完成**：P1.5、拖动→验证→接受→**保存**的闭环、Final-size Style、Agent HTTP 接线。

---

## 1. 本轮方向调整（用户裁定）

| 顺序 | 工作 | 决定 |
|---|---|---|
| 1 | **P1.5** 源修订误判修复 | 立即处理 |
| 2 | 拖动→验证→接受→**保存**的完整体验 | 只补既有能力之间的连接，**不重写 History** |
| 3 | **Final-size Style**：不同尺寸代码图统一最终规格 | **替代原大规模 P2**，作为下一核心功能 |
| 4 | Agent 选区上下文 HTTP 接线 | 真实需要时补一条**受控只读**入口；不做复杂自动排版 |
| 暂缓 | 广泛 Python 脚本覆盖率研究 | 只针对**真实遇到**的高频写法逐步扩展 |
| 暂缓 | G6a 第三刀、综合 profiler | 完整流程出现明确瓶颈后再决定 |

**理由（用户原话要点）**：不追求"支持多少种 Python 绘图写法"这个数字，否则会变成没有尽头的 AST 适配；允许 Agent 在安全约束下做小范围作者化，比给每种结构写通用解析规则更省成本。

---

## 2. P1.5：源修订误判（可信性缺陷）

### 2.1 现状不是"一个竞态"，而是五条独立通道（行号已核）

| 通道 | 位置 | 机制 | 后果 |
|---|---|---|---|
| **M1** | `figpact/session.py:117-138` `script_fingerprint` → `intents.py:620-627` `_guard` | 指纹累加 `size:st_mtime_ns`，用 `!=` 判定 | **touch 即拒**（内容未变） |
| **M2** | `intents.py:101-103` → `intents.py:328-333` `_source_fresh()` | 记录含 `mtime_ns`，整字典相等比较 | 内容相同也判"不新鲜"；与 `agent_api.py:90-92` 承诺（按内容、不按 mtime）自相矛盾 |
| **M3** | `intents.py:695`（`_rebuild` 起第二个 `FigureSession`）、`publish.py:59-63`（目标目录写 `.tmp_<name>`）、stage 目录（仅 `.gitignore` 声明）、同目录 `SKILL.md` | 全目录 `rglob` + 绝对路径为键 | 合法生成物进入输入身份 |
| **M4** | 基线与复核各取"此刻的" `state['artifact_outputs']` | 排除集变化 ⇒ 集合必不同 | 结构性版本：即使无任何外部改动也可能误拒 |
| **M7** | `intents.py:794-798` | 判定发生在 `_rebuild` **之后** | 窗口=整个重建 ⇒ 与"负载下偶发"吻合 |

### 2.2 成熟设计的定论（R4）

1. **身份必须用内容哈希**，`size+mtime` 两个方向都错：漏拒（同尺寸同 mtime 的就地改写；git 源码注释原文 `/* nanosecond timestamped files can also be racy! */`，谓词用 `<=` 即"相等或更老 ⇒ 强制复算内容"）；误拒（`touch` 即变；Make 的该假设被 à la carte 明确点出）。
   **Windows 加倍危险**：FAT32 mtime 分辨率 **2 秒**；文件时间只在句柄关闭时保证。
2. **输出不参与输入身份；输出的*路径名*才参与动作身份**（Bazel：action = inputs + output **names** + 命令行 + 声明环境）。
3. **Ninja 官方手法直接可用**：记录**命令开始时刻**（`record_mtime = edge->command_start_time_`）而非输出完成时间——这样"动作期间被改的输入"不会被"输出刚写"掩盖。
4. **"动作期间输入变化 ⇒ 作废"是 TOCTOU（CWE-367）**；正确形态是 **动作前一次性快照（集合 + 内容哈希 + 开始时刻）→ 动作 → 按**同一集合**复核 → 有界重试一次**；**不得**动作后重新推导集合（自己污染自己）。
5. 不要照抄：Make `.LOW_RESOLUTION_TIME`（方向相反的放宽）、SCons `MD5-timestamp` 默认档（官方自述 1 秒窗口漏判）、Bazel `--experimental_guard_against_concurrent_changes`、按**后缀**排除产物、Windows `st_ctime`（3.12 起弃用 + NTFS tunneling）。

### 2.3 采用的方案（A，必要时叠加 B）

- **A（推荐）**：内容哈希 + **冻结集合** + 同一集合复核，判定点移到 `_rebuild` **之前**快照、之后只复合同一集合。
- **B（可选）**：有界重试一次 + 记录证据（`attempts`、两次快照差异）。
- **C（结构性最优，代价大）**：把产物移出脚本目录（`out/`），身份天然干净——需动契约与 examples 布局，**待用户裁定**（见 §6 问题 2）。
- 输入/输出分类原则：**受保护输入** = 脚本、配置、科学数据；**合法生成物** = 输出图、`__pycache__`、`.tmp_*`、stage 目录——后者的**路径名**参与动作身份，**内容不参与**输入身份。

### 2.4 验收（用户口径）

> 验收目标**不是**"让 `STALE_REVISION` 消失"，而是**真正过期必须拒绝、没有过期不能误拒**。

回归矩阵（参考 Ninja `build_test.cc` 的 VirtualFileSystem + `fs_.Tick()` + 断言执行次数；仓库已有骨架 `eval/verify_real_cutover.py:1178-1223`、`:1227-1307` 可扩）：

| 场景 | 期望 |
|---|---|
| touch 脚本（内容不变） | **不**误拒 |
| 同尺寸 + 同 mtime 就地改写 | **必须**拒绝 |
| mtime 2 秒量化（FAT 类） | 按内容判定，不按时间 |
| 动作期间外部改源码/科学输入 | **必须**拒绝 |
| 动作期间产生 `.tmp_*`、`__pycache__`、stage 目录 | **不**误拒 |
| 并发写日志/引擎自身写入 | 不误拒（或其变化属声明产物） |
| 契约新增 output 名字 | 动作身份变化可解释；不误拒 |
| 连续构图 N 次无外部变化 | 零 `STALE_REVISION` |

---

## 3. 拖动 → 验证 → 接受 → 保存 闭环

### 3.1 缺口（事实，非推断）
拖动松开只调 `evaluateCurrentIntent()`，**只验候选**；即使通过也不写文件，页面明示"只保留在当前服务中，未保存到文件"。这是**产品体验未闭环**，不是实现错误。

### 3.2 成熟设计的定位（R5）
- **Lightroom 最贴本例**：编辑态在 catalog，写回是显式 `Save Metadata to File`，并有 `Metadata File Needs To Be Updated` 脏指示器。figpact「候选」≈ catalog，「保存脚本」≈ Save to File。
- **纯内存事务 + 显式提交**是 CAD 的通行做法（FreeCAD `openTransaction/commitTransaction/abortTransaction`，undo 栈**不进文件**）→ 正好支持"补闭环、不重写 History"。
- **写回源码只有两条正交安全策略**，且都**不存在半写状态**：
  - (A) **拒绝即安全**：写前校验失败就不写（`git apply` 默认 all-or-nothing、`black --check`）；
  - (B) **旁路恢复**：改动放原文之外的载体（Vim `.swp`、Emacs `#file#`、VS Code Backups），确认后才写回。
- **反面教材**：`nbconvert --inplace`（官方仅一句 "Be careful with that"）、papermill 周期自动写盘、jscodeshift 默认就写盘、black 逐文件原地截断写（无跨文件事务）。

### 3.3 采用的形态

**候选列表 + 显式提交**（IntelliJ Refactoring Preview / Word "Accept All" / Power BI pending banner 同构）：
1. 每次通过验证的拖动/evaluate 进入**待保存候选区**，带 `base_script_sha256`（对应 P0a 的证据绑定）。
2. 保存 = ①**漂移检查**（磁盘脚本 sha 与候选 `base_script_sha256` 比对，不一致 → 拒绝并说明，参考 lisplens `WriteError::Drift{expected,actual}`）②**一次性生成整脚本文本** ③**原子替换**（temp → fsync → rename，保留权限）④**写后重新 evaluate**。
3. 单次原子写 ⇒ 磁盘只有"旧/新"两态，**"写一半"在物理上不存在**。
4. **不把恢复标记写进脚本**（脚本是 SSOT）；需要兜底就用可随时删除的**独立 sidecar**。
5. 界面沿用 P0a 语义：只有 `source_commit_state=COMMITTED` 且 `figure_verification_state=PASS` 才显示"已保存并通过验证"。

---

## 4. Final-size Style（下一核心功能）

### 4.1 要解决的期刊级硬问题（R1/R6）

- 期刊的字号/线宽**一律按最终印刷尺寸**定义；出版社**只缩不放**（IEEE 明说），缩放比一变印刷 pt 与有效 dpi 同步变化 → 文字不可读、细线消失（Nature / Elsevier "hardly legible" / Wiley / PLOS）。
- **同一 Figure 内多面板必须规格一致**，这是硬条款而非审美：
  - Science：字号档位 **≤3**，自检项 literally *"Are the font sizes consistent?"*；Sci.Adv **直接禁 PPT 来源图**。
  - IEEE：*"same font type/size/label style across all graphics"*；Nature：*"same font throughout all figures"*；Elsevier：uniform look / consistency in size。
- **npj 的关键一句**：*"each panel of a multipart figure should be sized so that the whole figure can be reduced by the same amount"* —— 期刊要求**所有面板共享同一缩放比**。这直接否定了"两个不同源宽的图各自缩到目标宽"的常规做法。
- 换算关系：`final_pt = design_pt × k`，`k = 最终占位宽 / 渲染画布宽`。
  本例：`k_NMR = 42/48 = 0.875`、`k_FTIR = 38/48 = 0.7917` → 同一 7 pt 源字号在成品上是 **6.125 pt vs 5.542 pt（差 0.583 pt / 8.3%）**；FTIR 现有标注 4.7 pt → **3.72 pt，跌破所有期刊下限**。这正是用户预判的"原来放得下的标注缩到 38 mm 后可能放不下"。

### 4.2 仓库现状：语义已经对了，缺的是跨图角色表

两份 yaml 已写死正确语义（原文）：

> `canvas_w_mm`：拼版里的**实际占位尺寸**，**不是"先画大再缩放"**。改大 → 面板物理变大，字号不变（字号是 pt）。

> （FTIR）字号或间距挤不下时，查看实际净距和超限 mm，再自行调整。

即：**不自动缩字**这条原则在配置层已存在。缺的是 ①跨图统一的**角色级规格**；②在最终尺寸下的**实测**与**越界报告**。

| 角色（现有键） | NMR | FTIR | 备注 |
|---|---|---|---|
| 轴标题 `axis_font_pt` | 8.5 | 8.5 | 已一致 |
| 刻度 `tick_font_pt` | 8.0 | 8.0 | 已一致 |
| 峰/标签 `peak_font_pt` / `label_font_pt` | 6.0 | **4.7** | 跨图不一致，且 FTIR 缩到 38 mm 后 3.72 pt |
| 图例 `legend_font_pt` | 6.0 | 4.7 | 跨图不一致 |
| 备注 `note_font_pt` | 5.5 | 6.5 | 跨图不一致 |
| 线宽 `line_width` | 0.75 | 0.85 | 跨图不一致 |
| 画布宽 `canvas_w_mm` | 48 | 48 | 相同源宽，但目标 42 / 38 |
| 科学字体 `figure_style.py` | 有 | 有 | 已有共享样式模块 |

### 4.3 matplotlib 侧的正确做法（R2 实测）

- matplotlib **没有**"按最终尺寸重算字号"的机制：`figsize` 与 `fontsize/linewidth` 是两个独立常量。生态里唯一"单旋钮整体缩放"是 seaborn `base_context × {paper .8, notebook 1, talk 1.5, poster 2}`（`seaborn/rcmod.py`），R 侧是 ggplot2 `base_size=11`、cowplot `rel_small=12/14`。
  → figpact 采用 **角色表 + scale 因子**，**不**照抄固定 pt。
- SciencePlots 只对了一半：把栏宽写进样式（`ieee`/`nature` 均 `figure.figsize: 3.3, 2.5`）却写死 7/8 pt；且 `science.mplstyle` 把 **`savefig.bbox: tight`、`pad_inches: 0.05` 写进样式**，而 `nature.mplstyle` **注释掉了这两行**，理由原文："Use virtually all space when we specify figure dimensions" → **规格与 tight 互斥**的一手证据。
- **测量陷阱（本机 mpl 3.10.8 实测，必须写进实现约束）**：
  1. `Artist.get_window_extent` 的**单位跟随当前缓存 renderer**：`savefig(dpi=600)` 后再测，同一 text 从 73.5 px → 440.25 px；只有再 `savefig(dpi=100)` 才复原，**`dpi=100` 关键字救不回来**。
  2. **`Text.get_window_extent(dpi=X)` 是混单位**（源码里 `# dpi is unused`，尺寸来自 renderer）→ **禁用该关键字**。
  3. **draw 之前测量不抛异常**，静默返回 `height=0` 的退化 bbox → 必须显式 draw。
  4. `Figure.get_tightbbox` 返回 **inches**（其它 artist 返回 px）；实测 `输出 = tight + 2*pad`，tight 对 figsize 斜率 1 → **一步收敛**。
  5. `TextPath` 单位 pt、严格线性、无需 renderer，但是 **ink bbox、无换行/对齐** → 只能当预测；`FT2Font` 官方标注 *"private and provisional"*。
- **`bbox_inches='tight'` 是隐藏杀手**（R6）：声明 42 mm 而 tight bbox 实测 44.7 mm 时 `k ≠ 1` → **必须实测，不信声明**（与本仓库既有"声明≠实测"原则同构）。
- 工具侧陷阱：Illustrator 默认**描边不随缩放**，Inkscape 默认**随缩放** → 同一套操作跨软件必翻车（导出时需显式说明）。

### 4.4 拟采用的设计（最小面，复用既有能力）

**原则：按最终尺寸渲染 → `k ≡ 1` → 一致性由构造保证。**

1. **配置**（把既有 `canvas_w_mm` 的语义提到 figure 级，不造新概念；裁定 3 = 共享 profile + 每图覆盖）：
   - 图级：`figure.final_width_mm`（目标占位宽）、`figure.gap_mm`；既有 `canvas_w_mm` 保持"渲染画布宽"，两者相等即 `k=1`。
   - **共享 profile**（如 `styles/plate.yaml`）：`typography.<role>.{policy, pt, min_pt, max_pt, deadband, budget_source}` 与 `panel_label.{case, pt, placement}`；合并顺序 **profile < 图级覆盖 < 会话内候选**。
   - 既有 `axis_/tick_/legend_/note_/label_/peak_font_pt` 保留为角色实例，由 profile 映射到角色名，**不新增平行词汇**。
2. **只读测量入口**：`figpact typography <figure>` 打印 `declared / measured / k / effective_pt` 表（复用 `snapshot()`；`scene.py` 已抓 `font_size_pt`，`inventory.py` 已抓 fontsize/linewidth）。
3. **`render --strict` 阻断项**：`CANVAS_WIDTH_MISMATCH`、`FONT_SIZE_INCONSISTENT`、`FONT_BELOW_MIN`、`LINE_BELOW_MIN`、`SCALE_OUT_OF_BAND`、`PANEL_LABEL_INCONSISTENT`、`UNMEASURED`。
4. **报告格式**（R3 的标准化诊断四件套，直接照字段填）：
   `rule_id / severity / scope / object_ids / role + token + token_source / boundary / measured / budget + budget_source / excess / deadband / declared vs rendered / resolutions[]{description, applicability, cost} / preferred`
   - `applicability` 借 rustc 四级；"error/warning 不得给修复建议，只有 help 可以"；"避免 warning fatigue"；同缺陷只报一条。
   - 位置从"`file:line:col`"换成"**边界 id + 毫米矩形 + 对象 id**"。
5. **红线 R1–R7**：R1 只有 opt-in 才可缩；R2 有界且留记录；R3 **溢出 = 阻断，余量不阻断**；R4 给候选不替用户选；R5 死区与预算**分字段**；R6 缩字必须**同时**显示声明值与渲染值；R7 同缺陷一条。
6. **预算带来源**：Nature *"8 pt bold 面板标签；其余文字最小 5 pt、最大 7 pt；线宽 0.25–1 pt at final size"* —— 与仓库既有 `check_glyph_floor(min_pt=5.0)` / `audit_pdf(min_pt=5.0)` **同源**，建议把 `5.0 pt` 从默认值**升格为带引用的角色预算**；线宽全局取交集 **0.5 pt** 才覆盖 ACS。
7. **面板字母必须 profile 化**（四家互斥）：Nature 小写 8 pt bold（框内）/ Science 大写 10 pt / SciAdv 9 pt / JEEG `a)` 8 pt bold（**禁框内**）→ 大小写、字号、位置都是 profile 字段。

### 4.5 拼版级计算：输入 / 输出 / 呈现（提案，待用户选型）

**用户 2026-10-14 定位**（要点原文）：

> Tavotto 其实很缺少整体的计算能力，就算算好了也很难改回 python，所以我才比较想做我们自己工具的整体计算能力，但是具体怎么呈现，输入输出是什么感觉还是没想好。

→ **分工因此清楚**：Tavotto = 单图可视化编辑 + 单图出版体检（下游检查）；**figpact 拥有"跨图整体计算 + 结果写回 Python/YAML"**。两者**不共享真值的第二份副本**：figpact 产出规格与报告，Tavotto 的 preflight 作为**独立下游复检**（结论可交叉验证，但字段不重复定义）。

#### 输入（三选一或组合）

| 方案 | 形态 | 优点 | 缺点 |
|---|---|---|---|
| **I1 拼版规格文件**（推荐） | 一份可版本化的 `plate.yaml`：面板列表（图件/脚本 + `final_width_mm`）+ `extends` 共享角色规格 | 单一真值、可 diff、可复现、可评审；"两张图共享规格"就是**一个文件** | 多一个文件要写（可由命令生成） |
| I2 纯命令行 | `plate --panel nmr=42mm --panel ftir=38mm --role axis=8pt ...` | 一次性、零新文件 | 不可复现/不可评审；命令长 |
| I3 只写各图 yaml | 每图各自 `final_width_mm` + 角色值 | 不新增概念 | 无处表达"共享规格" → 必然漂移（与裁定 3 冲突） |

**推荐：I1 为主，I2 作为"编辑入口"** —— 命令行参数只负责**写入/更新**规格文件（`plate set axis=8pt`），真值始终在文件里。

#### 输出（四件，互相独立）

| 输出 | 内容 | 为什么需要 |
|---|---|---|
| **O1 源码写回** | 更新各图 YAML（`final_width_mm`、角色 pt、线宽），必要时才动 Python；沿用 P1.5/P0a 的安全链（漂移检查 → 一次性整文件生成 → 原子替换 → 写后复验） | **Tavotto 做不到的那一步**；也是"科学可复现"的前提：真值留在脚本里 |
| **O2 终尺寸图** | 按 `k≡1` 重渲染出**恰好 42 mm / 38 mm** 的矢量图（PDF/SVG）+ 实测规格表（declared vs measured、effective pt、k、线宽） | 直接可拼版；且证明"声明=实测" |
| **O3 报告** | 机器可读 JSON + 人读文本：`locked` 角色不一致 = 阻断；`bounded` 越界 = 阻断、区间内不一致 = 仅报告；每条带 `resolutions[]{description, applicability, cost}` | 你需要的"取舍清单"，而不是代码替你决定 |
| **O4 拼版校样** | figpact 自己把两张图按最终宽度并排渲染成**一张校样图**（含毫米标尺/参考线） | 这是"**整体计算能力**"唯一能被眼睛验证的形式；不依赖 Tavotto，也不改任何源文件 |

#### 呈现（命令面）

```
figpact plate check  <plate.yaml>   # 只测量与报告（不写任何文件）——先看数再决定
figpact plate apply  <plate.yaml>   # 写回 YAML/Python（走漂移检查+原子写+写后复验）
figpact plate proof  <plate.yaml>   # 出 O4 拼版校样 + O2 终尺寸图 + 规格表
```

- **check → 看数 → apply** 的顺序把"先报告后改动"固化进工作流，符合你"遇到空间不足应报告需人工取舍"的要求。
- Inspector 侧后续可加一个**跨图规格面板**（同表渲染），但**不是**先用条件；命令面即可闭环。
- 单位口径统一为 **mm（占位）与 pt（字体/线宽）**，与既有 yaml 注释一致。

**待你选型**：① 输入以 I1 文件为主（+ I2 作编辑入口）是否同意；② 输出四件中哪些是这一轮必须（我建议 O1+O2+O3 必须，O4 作为"整体能力"的可见证据也建议做）。

### 4.6 角色策略：目标不是"把所有字统一"（用户 2026-10-14 修正）

用户口径原文：

> 这个字号统一的事情不是百分百一定的，还有很多因素需要考虑，可能只需要标题大小什么统一，里面可能由于内容多少和空间多少需要灵活一点，所以我觉得这里我没法给出一个明确的答复，并且让代码一下子把所有字统一起来也是不现实的。

据此，角色表**不得**是"全部字号锁定为同一值"，而是**每个角色带一条策略**：

| 策略 | 含义 | 典型角色 | 工具的职责 |
|---|---|---|---|
| `locked` | 跨图**必须完全一致**（拼版硬条款） | 轴标题、刻度、曲线线宽、（可选）面板字母 | 不一致 = **阻断**（`FONT_SIZE_INCONSISTENT` 等） |
| `bounded` | **允许随内容/空间灵活**，但必须在**区间**内且留痕 | 峰/官能团标注、图例、备注 | 越出区间 = **阻断**；区间内不一致 = **只报告**（declared vs rendered） |
| `free` | 不作跨图要求 | 局部小注、临时说明 | 只在低于**绝对地板**时阻断 |

配套字段：`budget {min, max, preferred}`、`deadband`（避免临界抖动反复报警）、`budget_source`（引用的期刊条款或用户声明）。
- **余量 ≠ 溢出**：只有溢出才阻断（R3），余量只在报告里显示。
- **绝不自动缩字**；`bounded` 的灵活度是给用户**报告与取舍**用的，不是给代码自行决定的（若将来要 opt-in 有界缩字，必须同时显示 declared/rendered 并留记录）。
- 因此 Final-size Style 的验收**不是**"两张图所有字一样大"，而是：**`locked` 角色确实一致；`bounded` 角色在预算区间内且实测值有据可查；越界的都被报告出来。**

**明确不做**：不发明新布局系统；不做自动缩字（缩字只能由角色策略显式 opt-in 且有界）；不做跨图相对位置求解；不引入 tight 进规格样式（与规格互斥）。

---

## 5. 唯一验收场景（用户给定）

用户有两张已做好、原本尺寸不同的代码图（NMR 48 mm、FTIR 48 mm），要放进同一张论文 Figure。用户在 PPT/Illustrator 里决定最终宽度后告诉 figpact：

> NMR 最终宽 42 mm，FTIR 最终宽 38 mm。两张图轴标题统一 8 pt、刻度 7 pt、曲线线宽 0.8 pt。原有科学内容不要变，峰标注尽可能保持原位置。

系统需完成：找到两张图已有对应样式参数 → 在指定最终尺寸下**重新渲染** → 确认轴标题/刻度/线宽的**最终规格** → 保持科学数据、峰归属与受保护显示语义不变 → **对无法容纳的文字报告问题，而不是擅自修改科学内容** → 导出可直接拼版的两张图。

**成功标准**：这件事只需很少操作，不必"改 Python → 导出 → 缩放 → 再改 Python"来回。

---

## 6. 设计裁定记录（2026-10-14）

| # | 问题 | 裁定 | 影响 |
|---|---|---|---|
| 1 | P1.5 的产物/排除策略 | **按声明的输出名排除，产物留在原地** | 不动契约与 examples 布局；身份改为"内容哈希 + 冻结集合 + 同集合复核"；需显式分类 `.tmp_*`、`__pycache__`、stage 目录、同目录非输入文件 |
| 2 | 缩放路线 | **各自按最终宽度重渲染，`k ≡ 1`** | 一致性由构造保证；报告里的 `k` 仍需**实测**（tight bbox 会让 k≠1） |
| 3 | 规格存放 | **共享 profile 文件 + 每图可覆盖** | 新增 profile 概念与合并规则（profile < 图级覆盖 < 会话内候选） |
| 4 | 是否统一全部字号 | **不统一全部** → 改为**按角色分策略**（`locked` / `bounded` / `free`，见 §4.6） | 工具只强制 `locked` 一致；`bounded` 越界才阻断，区间内不一致只报告 |
| 5 | 目标期刊 | **未定**（本次未选） | 默认按**交集**取地板：字号 ≥5 pt、线宽 ≥0.5 pt；宽度档位与面板字母规则做成 profile 字段，待定刊后填 |
| 6 | 拼版工具 | **用户当前用 Tavotto 编辑器，尚未决定最终拼版方式**；待 R7 调研（`docs/research/R7_tavotto_integration.md`）给出 Tavotto 已有能力与边界 | **figpact 不得与 Tavotto 造两套并行规格**：谁负责体检、谁负责换算，待 R7 结论后定 |

**P1.5 与上表全部解耦**，可立即开工（用户已把"先修 P1.5"定为第 1 步）。

---

## 7. 参考来源

- `docs/research/R1_journal_final_size_specs.md` —— 期刊宽度/字号/线宽/分辨率与"按最终尺寸"的官方理由链。
- `docs/research/R2_restyle_implementations.md` —— matplotlib/生态的角色表与缩放机制、测量 API 陷阱（本机实测）。
- `docs/research/R3_roles_and_overflow_reporting.md` —— 角色令牌、溢出报告先例、诊断字段集与 R1–R7。
- `docs/research/R4_revision_tracking.md` —— 内容哈希 vs mtime、Bazel/Ninja/git 的输入输出身份处理、TOCTOU 缓解。
- `docs/research/R5_edit_accept_save_loop.md` —— 编辑器暂态/提交语义、写回源码的安全策略、staging 先例。
- `docs/research/R6_panel_assembly.md` —— 组合图一致性的期刊硬条款、R 生态对照、缩放翻车根因与最小设计。
- 旧设计包 `docs/figpact-vnext-kit/`（基线 `fe48fee`，2026-10-11，未跟踪）：其"实施顺序/阶段表"已被本文取代；架构原则（Agent-neutral、Geometry-intent-first、不默认改 Python）仍然有效。
