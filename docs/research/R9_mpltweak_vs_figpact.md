# R9：mpltweak vs figpact — 对照与推进方向

## 0. 关键来源与访问时间

- mpltweak 仓库（GitHub，MIT）：https://github.com/shdbl/mpltweak（页面显示 Languages: Python；License: MIT；Stars: 1；Forks: 0；Issues: 0）  
- README（中）：https://github.com/shdbl/mpltweak/blob/main/README.md  
- 给 Agent 的接口文档：https://github.com/shdbl/mpltweak/blob/main/docs/agent.md  
- 边界与口径：https://github.com/shdbl/mpltweak/blob/main/docs/boundaries.md  
- PyPI 最新版：https://pypi.org/project/mpltweak/（最新 **0.1.11**；Python `>=3.9`；分类器含 `Development Status :: 3 - Alpha`）：https://pypi.org/pypi/mpltweak/json。  
- Conduid 元数据（MCP/星星/最近提交）：https://conduid.com/servers/mpltweak。  
figpact 侧事实来源：`docs/G7STRATEGY_TASK.md`、`CONTEXT.md`、仓库结构（`figpact/final_size.py`、`figpact/source_writes.py`、`figpact/science.py` 等）。

> 【事实】标记可验证事实；未找到则标「未找到」。【推断】标记判断。

---

## 1. mpltweak 到底是什么

### 1.1 目标与交互形态
- 【事实】mpltweak 是一个交互式 **matplotlib 多面板布局** 编辑器：像 PPT 里拖动图片一样拖动/对齐/ SNAP 子图、图例、colorbar，调整字号，再把参数写回 Python 脚本。仓库主页：https://github.com/shdbl/mpltweak  
- 【事实】GUI 形态是**桌面窗口**，依赖图形后端：`pip install mpltweak`（命令行）或 `pip install "mpltweak[qt]"`（PyQt5 窗口）；Windows/macOS 官方 Python 自带 tkinter 可开“弱化版”。装法与退出码（0/1/2/4）在 README.md：https://github.com/shdbl/mpltweak/blob/main/README.md  
- 【事实】操作包括拖动面板、边/角缩放、多选对齐/均分、边缘吸附参考线、裁白边（Ctrl+F）、空格切换线框模式（cartopy 全量重绘 494ms→169ms）、悬停文 字按 `+`/`-` 调字号：README.md gif 与 interaction 文档 https://github.com/shdbl/mpltweak/blob/main/docs/interaction.md  

### 1.2 是否修改原始 Python 源码
- 【事实】**是，直接写回源文件（或在预览确认后写）**。两种模式：  
  1) 源码里该值是**字面量**时，AST 原位替换那几个数字；  
  2) 否则在文件末尾追加一段**自包含调整块**（追加块，不新增 import，保留原逻辑）。  
  源码：`src/mpltweak/writeback.py`（README 提及）；入口命令 `mpltweak apply <脚本> --write`。docs/verify.md：https://github.com/shdbl/mpltweak/blob/main/docs/verify.md  
- 【事实】写回内含三层验证：语法、重跑脚本、语义（图上位置/字号与参数一致），任一层不过默认**回滚**；`--keep-unverified` 可保留未验证写回。`--verify-fast` 只做 `ast.parse`（docs/agent.md：https://github.com/shdbl/mpltweak/blob/main/docs/agent.md）。

### 1.3 最终尺寸 / 字号 / 验证
- 【事实】**figsize / 画布适配** 是它能动的：README 提及 `Canvas fit`、裁白边、调整 figure size **影响 figsize**，且交互里有 fit-to-canvas。  
- 【事实】它会**重跑**脚本做验证：弱化的 CLI/开窗都会在无头 `Agg` 子进程里跑你的脚本；`check` / `describe` 也执行脚本。`docs/exec-boundaries.md`、`docs/boundaries.md`（https://github.com/shdbl/mpltweak/blob/main/docs/boundaries.md）。  
- 【事实】没有发现 **期刊列宽/mm/publish profile/DPI lint** 的硬规范。README/docs 强调的是 panel 位置、字号、裁剪和 figure size；查询 docs 与首页未见 Nature/Science/Elsevier 宽度或 300 DPI 检查器。为证据计，我们只确认了 README + agent + boundaries + params/interaction 的入口，完整 repo 本研究未全部下载；该结论应记作 **“未找到（未在已读 docs/首页见到）”**。  
- 【事实】用户脚本要能在无头环境无人值守跑通，否则不适用（需要数据/联网/交互时会卡死）。docs/boundaries.md §1：https://github.com/shdbl/mpltweak/blob/main/docs/boundaries.md#L1

### 1.4 可靠性与许可/活跃度
- 【事实】**MIT License**（README License 段：https://github.com/shdbl/mpltweak/blob/main/README.md#L315；LICENSE 文件存在；PyPI classifiers 未列出 license，以 repo LICENSE 为准）。
- 【事实】**活跃度（公开数据，2026-10-15）**：GitHub 元数据 Stars 1、Forks 0、Issues 0；Conduid 页面显示 last commit 5 days ago。PyPI 最新 **0.1.11**（2026-10 期间多轮 0.1.x），分类器 `3 - Alpha`。  
  - Conduid：https://conduid.com/servers/mpltweak  
  - PyPI：https://pypi.org/project/mpltweak/  
- 【事实】自 reported 的测试规模：静态语料 10,158 份脚本（唯一按 sha256）、真跑 1,780 份、GUI 交互 13,000 次离屏 + 6,000 手势、随机语法 1,000 例、CLI 组合 5,880 种；全库可原位写回 97.8%（3,531/3,610）。README 实测表与 docs/reliability.md：https://github.com/shdbl/mpltweak/blob/main/docs/reliability.md  
- 【事实】Agent 接口：`mpltweak describe/check/apply --json`、`schema`、JSON 参数文件；MCP 只暴露 describe/check/schema/apply 子集（`apply_layout` 只读默认 `.tweak_params/<脚本>.json`，**不接受** `--params` 路径）；另有 `skills/mpltweak/SKILL.md`。docs/agent.md：https://github.com/shdbl/mpltweak/blob/main/docs/agent.md  

---

## 2. 逐项对比矩阵

| 能力 | mpltweak | figpact | 其他代表工具 |
|---|---|---|---|
| 交互式 GUI 拖图 | 桌面 Qt/Tk GUI，拖 panel/图例/colorbar，多选对齐/均分，snap，裁白边，fit canvas | 有浏览器 Inspector + 测量/选区/拖动（mm 预览），以 accepted operation 写回 | PPT-like drag 多在 GUI；patchwork/cowplot 组版 |
| 场景与测量 | 读 rendered 布局，导出位置/字号 JSON；`check` 对齐/等大/间距/字号/越界/重叠 + 轴范围不一致 | 以 mm 为中心：frame/render/units/measurement uncertainty/tolerance，画板物理尺寸 | paperlint/checker 类做指标检查 |
| 选区与稳定身份（GID） | 未见 docs 提 GID；panel 多用 axes index，块写回仍要求可静态认出 obj | 有稳定/短暂身份、accepted op、 binding proof（CONTEXT.md 用语） | 未找到统一 GID 惯例 |
| 拖动与预览 | ghost preview + 对齐 guides；松手落位 | mm 预览 + desired overlay/accepted op；非 edit 无写 | 无 Preview 仅回退 |
| 真实验证 | 三层：AST/重跑/语义；失败默认 rollback | 三层 accepted+render check + source verification（Task 描述）+ dual state | 多数只改文本 |
| 写回源文件与安全 | AST 两路（原位/block），自动备份（tweak.bak + pid 备份），`revert`，语料验证 97.8% | atomic write + drift check + `source_commit_state` / `figure_verification_state` | 用户手动 |
| 科学不变量保护 | 不动数据/文本内容，只动 layout/字号/figsize（README 强调） | 明确科学 payload/image window/axes 保护； fingerprint/QA | 无 |
| 最终尺寸/跨图规格 | 通过 figsize/crop 调图，**未见 journal mm profile/DPI lint** | 最终尺寸只读审计 + 最小受控修改；journal spec 研究库 R1 | check_figure_size 等 journal tool |
| 多面板拼版 | 就是它的核心：GridSpec/subplots 的 axes-level 调整 | panel-level measurement/relations；与 assembler 协作定位 | patchwork/cowplot/svgutils/figurefirst |
| Agent / 自动化 | schema + `describe/apply/check --json` + MCP subset + SKILL.md | 只读 agent context + protocol；agent 发 PR 可驱动 accepted 工作流 | CLI checkers 可 CI |
| 审计与报告 | check JSON + verify_passes / semantic_basis / error_code | QA fingerprint、notes/figures、publication checks | linters |
| 可复现性/ reversible | 自动备份 + revert + revert.bak | history checkpoint / operation history + drift detection | git |

---

## 3. 真重叠区（撞车点）

1. **都把“布局”与“内容”分开**，且对象 targeting 都谨慎：mpltweak “只管样式和位置，不发明内容”；figpact payload 保护。  
2. **都把拖动结果确定性写回源码**（mpltweak AST + 三层验证；figpact accepted + source write + verification state）。  
3. **都面向 agent 友好接口**（JSON/CLI check；figpact agent context/protocol）。  
因此用户会把它们看成同一类工具。【推断】

---

## 4. 各自独有（含“我们弱于它”）

**mpltweak独有（它强）**
- 桌面 GUI、快捷手势、多选对齐/均分、snap、crop、fit canvas、colorbar/legend 拖拽、字号悬停调。  
- 超大规模语料 writeback/CLI 组合测证 + 可复现证据 tag `evidence-0.1.10/0.1.11`。  
- `revert` + 双备份策略，工程上可直接 recover。  
- 公共参数 schema + MCP + SKILL.md，降低 prompt learning 成本。  

**figpact独有（我们强）**
- **最终发布尺寸**作为一等对象：mm/in units、最终尺寸只读审计与最小受控修改、QA/fingerprint。  
- **双 verification state**（source commit state / figure verification state）+ drift check。  
- 从 inspector 到 accepted op → history checkpoint 的 provenance，保护 runtime/science。  
- 文档明确的 tolerance/uncertainty 区分与以 mm 审计的空间关系。  

**我们弱于 mpltweak 的项（必须写）**
- 桌面拖图交互成熟度与操作速度（wireframe 169ms 级）；我们是测量/拖动/mm 预览，而它更像 PPT 布局器。  
- writeback 外部证据：它公开 97.8% / 10,158 脚本语料与复算命令；我们目前没有可公开的同等规模证据包。  
- 跨 axes layout helpers（align/equal space/distribution）；如果用户想“整篇论文整整齐齐”，它更顺手。  
- CLI/lint onboarding 与 skill 分发： schema + SKILL.md 已以内建体验提供， ours protocol 兼 容 heavier。

---

## 5. 不该竞争的领域

- **不应重造多面板拖图 GUI 的交互细节**（snap/align/distribute/wireframe）：这已经由 mpltweak 的 desktop-first 路线占据。  
- **不应把 marketing claim 对准“恢复” same breadth**。相反把差异锚在 publication reality（final size/indices/invariants）。【推断】

---

## 6. 三条最值得投入方向

### B1. 把 accepted/edit verification loop 做成外部可用、可复现的能力
理由：我们 unique value 是“验证后写回 + drift check”，而 runtime agent/MATLAB 用户都需要 reliable write path。把 `verify_passes`, `semantic_basis`, `error_code` 风格结构化证据对齐 mpltweak 公开模式。  
风险：头壳重跑 burden；无头环境 script; slower loops.

### B2. 最终发布尺寸 + 科学不可变体做不可替代
理由：mpltweak 不做 journal mm profile/DPI/anatomy QA；我们的 final size audit + science payload protection 是 ture edge。  
风险：需要更多 empirical validator datasets and documentation; narrow niche.

### B3. 协作/bridging 而非替代
理由：用户可先在 mpltweak 排 layout，再经 figpact check publication size/invariants。双方 complementary. 只需 import parameter JSON / re-exec mapping; avoids competing UI.  
风险：上游 breaking / reliance on external schema; bridge maintenance.

---

## 7. 证据不足/未找到（明确记录）

- 未找到 mpltweak 的 peer-review/journal profile support（mm dimensions, DPI thresholds, final printed text sizes）。  
- 未找到 mpltweak 代码 AST 定位函数内部（我们未下载源码 internals; 仅 docs/README/structural tree); 机制描述基于 README/docs.  
- 未找到 figpact journal profile exact rows within repo? `docs/research/R1_journal_final_size_specs.md` 存在（未本任务内打开）, 证据可支持 B2.  
- 无法确认 mpltweak issue velocity beyond Conduid/GitHub metadata; current docs point Issues: 0, Conduid claims 1 star and 0 forks.

---

## 结论一句话

mpltweak 在“桌面式密度拖动+交互布局写回” stronger and far more evidence; figpact 应把 payload-safe verification + final-size/invariant audit deepened rather than replicate GUI.方向见 B1/B2/B3 先后.