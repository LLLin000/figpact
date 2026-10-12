# G6b Pilot 报告（协议可跑通性验证）

> **这是 pilot 记录，不是正式轮，也不是性能结论。** 本文件只回答「`docs/G6B_THREE_ARM_PROTOCOL.md`
> 的协议能不能跑通、每条 trial 产出了什么可复核的实测证据」。
> 4 条题 × 3 臂 = 12 条 trial 的数字**不足以也不允许**用来宣称提速、成功率或做臂间胜负比较；
> 本文件通篇不含任何性能/成功率结论。
>
> 按协议 §6 红线 8，实验数值只在另外的实验记录文件里出现——本文件就是那份记录，
> 协议正文保持不含数值；两者的关系与修订入口见本文件 §4 与协议 §8。

---

## 1. 工作事实

| 项 | 事实 |
|---|---|
| 运行日期 | 2026-10-13 |
| 规模 | 3 臂 × 4 题 = **12 trial**，**0 条丢弃**（无超预算、无作废、无事后剔除） |
| 题目与层 | A09（L1 位置调整）、A08（L2 复杂标注）、A11（L3 约束冲突）、A16（L4 无 YAML），四层全覆盖（协议 §2.2） |
| 臂 | **臂 L 旧手工**（只读 FS + 纯文本编辑候选 + 现有全量预览/`--strict`，无 Hub、无 history）、**臂 A 现 Agent API**（`figpact agent` 五操作 + `IntentSession.evaluate/decide` + 只读 Scene + Hub G5a 只读/试算面）、**臂 V vNext**（Inspector Demo + Planner/Oracles + adapter + Hub 完整闭环 + 外置 state + history） |
| 受试模型（逐字） | `opencode-go/deepseek-v4.1-flash:high`（三臂实际相同）；协议 §3.2 参照标识 `opencode-go/step-5-preview-free` 已不存在 → 见 §4 修订 1 |
| 预算 | N=30 次工具调用 / M=40k 输出 token / T=20 min（协议 §3.2 建议默认值；三臂相同）。四题最高 12 次工具调用，**均未触限** |
| 基线 commit | 冻结基线 `9e3161e`（协议 §1）；实际运行基线见下表「基线偏离」 |
| 量测口径 | 画布毫米、左下原点、右/上为正；位移取自 evaluate 实测或**独立重建**的 `bounds_mm`/`runs_mm`，不拿配置数字当位移达成 |
| 仓库改动 | 三臂都**未改动**仓库文件（臂 A/L 给 sha256 逐字节前后相同，臂 V 给 `find -newermt` 与磁盘 diff 证据）；臂 V 的 4 个本地服务已停止 |

**基线偏离（必须记录，非静默）**

- 臂 L 首跑运行在仓库 HEAD `00ba419` 而非冻结 `9e3161e`，且 4 题由**同一个会话顺序执行**（无逐题独立 worktree）——协议 §1 工作目录纪律与 §4.1 通过条件 3 的实证违反，见 §3 第 3 条。
- 臂 A 首跑同样落在 HEAD `00ba419`，发现后改用 `git archive 9e3161e` 提取树重跑，**记录以提取树那一遍为准**；被作废的那遍原始证据另存 `armA-evidence/HEAD-pass/`，未删除、未改写数值。
- 臂 V 在仓库当前工作树上运行；其冻结 commit 在协议 §7 清单里仍是「待定」项 → 见 §4 修订 9。
- 臂 A 在冻结 `9e3161e` 上复现了一个真实缺陷：同一进程内对**同一 script+config**第二次构造 `IntentSession`/`FigureSession` 必定失败（`ContractError: 布局契约未通过校验：Dangling parameter objects: ['canvas_w_mm']`）；该缺陷已在 `8af3b25` 修复。

**逐题隔离做法**

- 每题一份独立临时目录、独立 state home（history/journal/blob）、独立 `TEMP/TMP/TMPDIR`/`MPLCONFIGDIR`、独立 `session_id` 与端口（臂 V：A09=8791、A08=8792、A11=8793、A16=8794，仅回环）；夹具逐题从冻结树复制，**不得**原地改仓库夹具。
- 上一题/上一臂的目标、候选、state、history 一律不带入（A09 与 A08 用同一张 NMR 图，目录/state/会话互不相通，各自 `history.sqlite3` 只有自己那条检查点）。
- 臂 A/L 的隔离偏差见上；臂 V 的隔离成立。

---

## 2. 逐题结果表

| 题 | 层 | 臂 L 旧手工 | 臂 A 现 Agent API | 臂 V vNext |
|---|---|---|---|---|
| **A09** | L1 | 正确：起始 `[0.2,-0.1]` → 目标绝对 `[0.2,0.05]`，实测相对 dy +0.15 mm、残差 `[0,0]` | 达成：evaluate 实测 `[0,0.14999999999999858]`、error 1.4e-15、独立重建 `[0,0.15]`、残差 `[0,0]`、attempts 1、tool_calls 7、wall 36 s | 达成：实测 +0.15000000000000213 mm（残差 2.1e-15）、独立重建 Δy=+0.15、窗口内构建 3 次、tool_calls 10、wall 16.29 s |
| **A08** | L2 | 正确：dy +0.15 mm、残差 0.000、引线文字端跟随 0.08 mm、**科学锚点端不动**、strict exit 0 | 达成：evaluate 实测 `[0,0.15000000000000213]`、error 3.9e-15、**guide 科学端点误差 0**、独立重建 `[0,0.15]`、tool_calls 4、wall 39 s | 达成：**引线科学端点误差 0.0**、标注端跟随 +0.15 mm、独立重建复现、构建 3 次、tool_calls 7、wall 22.47 s |
| **A11** | L3 | 正确拒绝：`ConfigError『超出 ±10.0 mm』`（exit 1，构建未开始），保留 +15 mm 目标、未扩限、无违规候选 | 正确拒绝 `OUT_OF_RANGE`：依据出自 `08 NMR.py:168 SHIFT_LIMIT_MM=10.0` 与契约 bounds ±10；`target_delta_mm` 保留 `[0,15]`；commit→`NO_CANDIDATE`；脚本与配置 sha256 前后逐字节相同；拒绝后独立重建位移 0.0 mm；tool_calls 11、wall 28 s | 正确拒绝：同一条声明与实测（请求 `[0,15]` 第 1 分量 15.0 越界）→ `OUT_OF_RANGE/FAILED`、无候选、零写入、目标原样保留；tool_calls 2、wall 1.58 s |
| **A16** | L4 | **未完全达成**：候选脚本副本新增可写参数并实测 dy +0.15 mm、科学 sha 不变；但臂 L 无授权 journal / before bytes / CAS，**无法走授权写回**，未对原文件写盘 | **结构性做不到**：白名单内无源码写回操作（`agent status` 只有 snapshot/inspect/try_layout/render_preview/commit/status/close）；`try_layout(LAYOUT_MM…)`→`INVALID_VALUE`；`IntentSession(figure=…)`→`can_evaluate=False`、evaluate→`NEEDS_AUTHORING`；Hub `POST /api/tasks{source_write:true}`→403；无写盘（sha256 前后相同） | **达成**：`NEEDS_AUTHORING` 边界 → 计划 PENDING → **真人在真实页面授权（60 s，AUTHORIZED）** → apply `COMMITTED_AND_VERIFIED`；磁盘 == 计划 `after_sha256`；history `source_change` 检查点 `2ca4b434…`；独立重建 Δy=+0.49999999999999645，**旧科学基线指纹与 gid 集合逐位不变**；tool_calls 12、wall 72.56 s |

补充事实（不作性能解读）：

- A11 的拒绝依据可复核为三元组：**哪条声明**（`peak_label_shifts_mm.<scope>.<label>` 的 `bounds=(-SHIFT_LIMIT_MM, +SHIFT_LIMIT_MM)`，`SHIFT_LIMIT_MM=10.0`，`examples/nmr/08 NMR.py:168`，且该范围不是 YAML 键、页面无入口可改大）、**实测是什么**（用户目标 `[0,15]` 第 1 分量 15.0 落在 `[-10,10]` 外 → `OUT_OF_RANGE` 原文）、**做了什么/没做什么**（无候选、零写入、未扩限、未静默 no-op、未擅自动用源码写入路由）。
- 臂 V 的 A16 墙钟 72.56 s 含 60.0 s 等真人授权（人的时间，不是 Agent 计算时间）；A09/A08/A11 的选区由 harness 经 `POST /api/selection` 发布，只有 A16 的选区由真人在页面产生。
- 臂 V 侧 `run_inspector.py` 是 trial 侧 harness（挂在 `_call_builder` 上做真实构建计数、打开 `history=True`），不在仓库里；服务端本身不暴露构建计数 → 见 §3 第 4 条。
- 四题 `science_violations` 全为 0；三臂都**未下任何性能/成功率结论**。

---

## 3. 五条通过条件（协议 §4.1）逐条裁定

1. **三臂入口都能真跑起来** → **成立**（三臂各 4 题全部实际执行；A16 在臂 A 结构性不可做属协议缺陷，非入口故障）。
2. **每条 trial 产出完整记录字段、无 null 冒充** → **部分成立**：字段齐全，但三臂 `output_tokens` 全部 `null`（无 token 计量通道）、臂 A `real_figure_builds` 为 `null`（冻结 commit 无计数）——都注明了原因，未用 0 或估计值冒充。
3. **逐题独立/worktree 隔离真的成立** → **不成立**：臂 L 首跑在同会话顺序 4 题且运行于 HEAD `00ba419` 而非冻结 `9e3161e`；臂 A 首跑同样落在 HEAD，发现后改用 `git archive 9e3161e` 提取树重跑（预跑证据另存 `armA-evidence/HEAD-pass/`）。
4. **残差/构建数/工具调用/token/墙钟能被现实量出** → **部分成立**：残差、工具调用、墙钟三臂可量；构建数只有臂 V 可量（3/3/–）；token 三臂不可量。
5. **正确拒绝判定可被第二人用同一 checklist 复现** → **成立（有证据）**：A11 由臂 A 与臂 V **各自独立**给出同一条依据（`SHIFT_LIMIT_MM=10.0` / bounds ±10 与实测 15.0 越界）与同一结果（OUT_OF_RANGE、目标保留、零写入、未扩限）。

---

## 4. 协议修订清单（正式轮前必须先修）

按协议 §4.1 原话：**缺一即协议不成立，先修协议再跑正式轮。** 本节 9 条与
`docs/G6B_THREE_ARM_PROTOCOL.md` §8 逐条一致；**这些修订未应用前不得开始正式轮**。

1. **模型标识**：协议 §3.2 冻结的是 `opencode-go/step-5-preview-free`，但用户已改定「用当前 task 默认模型」，实际为 `opencode-go/deepseek-v4.1-flash:high`（臂 L 已按红线 1 报告不一致）→ 逐字改写为实际受试模型标识，并写明该决定来源。
2. **隔离程序必须写死**：每题一个**独立 worktree/提取树**（`git archive <冻结 commit>` 或 `git worktree add`）+ **独立会话**；臂 L/A 首跑违反即为例证。
3. **token 与构建数**：要么给 harness 一个真实 token 通道、并在三臂统一注入构建计数器，要么在协议里把这两项降级为「不可量（null+原因）」并同步修改 §5 指标口径。
4. **臂 A 的 A16**：该臂白名单内不存在源码写回路径 → 要么把 A16 从臂 A 的分母剔除并写明理由，要么修改臂 A 的允许工具（会破坏「现 Agent API」的定义）。
5. **A16 的题面必须逐字定义目标改动**：字面形态「新增 `LAYOUT_MM` 键」在 Hub plan 路由不可表达（缺键一律 `NEEDS_AUTHORING`），臂 V 实际走的是「可授权的那条源码级改动」。
6. **哪些 trial 需要真人选区**：臂 V 的 A09/A08/A11 选区由 harness 经 `POST /api/selection` 发布，仅 A16 的选区与授权来自真人页面 → 协议要写明每题是否必须真人点击。
7. **`try_layout` 回执不含实测毫米**（只有 status 与配置数值）→ §5 的「实测物理位移」只能取自 evaluate 或独立重建，写进口径。
8. **臂 L 白名单「现有全量预览」含糊**（A08/A09 毫米读数取自 `figpact try`，A16 只能靠光栅读数 ±0.042 mm）；**A16 在臂 L 的「做不到授权」记 failure 还是正确拒绝**，协议未定义。
9. **基线老化提示**：臂 A 在冻结 `9e3161e` 上复现了「同进程第二次 `IntentSession` 构造失败」，该缺陷已在 `8af3b25` 修复 → 正式轮须明确受试基线（建议用当前 HEAD 并在协议里记录 commit）。

---

## 5. 未做与未宣称

- **不是正式轮**：本文件是 pilot 记录，12 条 trial 只验协议机制；正式轮按协议 §4.2 另行进行。
- **不下性能/成功率结论**：不宣称提速，不做臂间胜负比较，不把本文件数字与 `docs/G6_PROFILE_NOTES.md`（引擎级 evaluate 分母）或 `README.md` P3.1 的 ~4.1% 互相折算或相乘（红线 5）。
- **token 全线不可量**：三臂受试 Agent 都没有对自身输出 token 的计量出口，一律记 `null` 并附原因，**不填 0、不给估计值**。
- **构建数只有臂 V 可量**；臂 A 的 `real_figure_builds` 记 `null` 并附原因。
- **未跑项目测试/lint**；未执行 git 写操作；未修改仓库任何文件。
- **未宣称**：A16 在臂 L 的「做不到授权写回」按协议缺失定义记 failure（未记作正确拒绝）；A11 的所谓「省掉一次构建」是实现事实，不当作性能结论。

---

## 6. 产物位置

- 逐题记录：`I:/figpact-test-archive/g6b-pilot/{armL,armA,armV}.json`
- 臂小结：`I:/figpact-test-archive/g6b-pilot/{armL,armA,armV}-summary.md`
- 原始证据：`armA-evidence/`（含 `HEAD-pass/` 作废预跑）、`armV-tmp/<task>/{trial-evidence.json,builds.log}`、`armL-trial/{A08,A09,A11,A16}/`
- 隔离目录：`armV-tmp/`、`armV-state/`、`armA-code/`（`git archive 9e3161e` 提取树）、`armA-tasks|armA-tmp|armA-mpl|armA-state/`、`armL-tmp|armL-state|armL-mpl/`
- 协议与修订入口：`docs/G6B_THREE_ARM_PROTOCOL.md`（正文冻结不删改，§8 = 本文件 §4 的同一份清单）
