# G6b v2 短复验记录（4 题 × 3 臂 = 12 trial）

> **这是短复验（short verification）记录，不是正式轮，也不是性能/成功率结论。**
> 本文件只回答一件事：`docs/G6B_THREE_ARM_PROTOCOL_V2.md`（v2）在**统一引擎基线 + 逐题硬隔离**
> 下能不能真跑通、四条通过条件（协议 §8.2 进入条件的前置四项）各条成立与否、以及短复验自身
> 暴露了哪些**必须先修**的问题。
> 4 题 × 3 臂 = **12 条 trial** 的数字**不足以也不允许**用来宣称提速、成功率或做臂间胜负比较；
> 本文件通篇不下任何性能/成功率结论，也不做跨臂构建数比较（理由见 §3 第 4 条与 §6）。
>
> 本文件与 v1/v2/pilot 的关系：`docs/G6B_THREE_ARM_PROTOCOL.md`（v1）、
> `docs/G6B_PILOT_REPORT.md`（pilot 记录）、`docs/G6B_THREE_ARM_PROTOCOL_V2.md`（v2）**逐字节不变**，
> 本文件是**新文件**；短复验的数值只出现在本文件里，协议正文保持不含数值。

---

## 1. 工作事实

| 项 | 事实 |
|---|---|
| 运行日期 | 2026-10-13 |
| 规模 | 3 臂 × 4 题 = **12 trial**，**0 条丢弃**（无超预算、无作废、无事后剔除） |
| 题目与层 | A09（L1）、A08（L2）、A11（L3）、**A16a**（L4），四层各一题（协议 §2.2） |
| 臂 | 臂 **L 旧手工**（只读 FS + 纯文本编辑候选 + 现有全量预览，未用 Hub / 选区 / history / 授权写回）、臂 **A 现 Agent API**（`figpact agent` 五操作 + `IntentSession` + 只读 Scene/Inspector + Hub G5a **只读**面）、臂 **V vNext**（`/api/plans` + 页面令牌 + `/apply`，仅 A16a 走授权写回） |
| 受试模型（逐字） | `opencode-go/deepseek-v4.1-flash:high`（三臂逐字相同） |
| 统一引擎 commit | `12e751c`（`12e751cdeab699078a4f5a1835ca41f28af27b3b`，协议 §1.1；三臂同源，只用白名单区分） |
| 锁定 gid | A09/A08：`fig2_nmr.main.peak.vancho.3p91` + 引线 `fig2_nmr.main.guide.vancho.3p91`；A16a：`intent.main.label.A`（三臂互核一致） |
| 归档根（**变更**） | `D:/L/AI/figpact-archive/g6b-v2/` —— **轮次产物归档根自本轮起改为 `D:/L/AI/figpact-archive/`**；pilot 的 `I:/figpact-test-archive/` 路径**已不可达**：本环境 `I:` 盘已不存在（只剩 `C:` / `D:`），旧 I: 产物在本机不可读，任何指向 I: 的复跑/对照都必须改写为归档根路径 |
| 量测口径 | 画布毫米、左下原点、右/上为正；位移取自 evaluate 实测或**独立重建**的 `bounds_mm`/`runs_mm`，不拿配置数字当位移达成 |
| 隔离 | 三臂各自**逐 trial 独立提取树 + 独立进程 + 独立 state + 独立会话**；均留四项泄漏检查证据（`git status --porcelain` 前后逐字相同；端口 8795–8798 与探针端口 11038 已停、无残留进程） |
| 仓库改动 | 无（三臂均未改动仓库文件；A16a 的写回落在夹具提取树副本上，不落仓库） |

**归档根变更的后果（必须记录，非静默）**

- pilot 记录里所有 `I:/figpact-test-archive/g6b-pilot/...` 引用在本环境**无法复核**（`I:` 盘不存在）。
  引用 pilot 证据时只能引用 `docs/G6B_PILOT_REPORT.md` 内的**已记录数值**，不得声称"已重读 pilot 原始 JSON"。
- 本轮起，"归档根"在协议与记录文件里统一写作 `D:/L/AI/figpact-archive/<轮次>/`；正式轮建根时须同步修订协议 §7 的路径清单。

**逐题隔离做法**

- 每题一份独立临时目录、独立 state home（history/journal/blob）、独立 `TEMP/TMP/TMPDIR`/`MPLCONFIGDIR`、独立 `session_id` 与端口（均回环），夹具逐题从冻结树复制，**不得**原地改仓库夹具。
- A09 与 A08 用同一张 NMR 图但目录/state/会话互不相通；上一题/上一臂的目标、候选、state、history 一律不带入。

---

## 2. 逐题结果表

| 题 | 层 | 臂 L 旧手工 | 臂 A 现 Agent API | 臂 V vNext |
|---|---|---|---|---|
| **A09** | L1 | `completed`；候选−默认 `[+0.2,+0.05]`，候选−起点 `[0,+0.14999999999999858]`，残差 1.4e-15 | `completed`；中心 `[0,+0.15]`（绝对 `[0.2,0.05]`），残差 `[0,0]`；构建 12；tool_calls 18；墙钟 9.141 s | `completed`；y +0.15000000000000036，残差 3.6e-16 |
| **A08** | L2 | `completed`；标注端 `[0,+0.15000000000000213]`、**引线科学端误差 `[0,0]`**、标注端 `[0,+0.1500000000000039]`、bbox 中心 `[0,0.075…]`（**单列，不与端点并表**） | `completed`；科学端误差 0.0 / 标注端 `[0,+0.15]` / bbox 中心 `[0,+0.075]`；构建 12；tool_calls 5；墙钟 9.240 s | `completed`；y +0.15000000000000213，残差 2.1e-15；**科学端绝对坐标逐位不动**，标注端 `[0,+0.15]` |
| **A11** | L3 | `correct_refusal`；加载期 `ConfigError … 超出 ±10.0 mm`；拒绝前后 nodes **逐位相等**、位移 `[0,0]` | `correct_refusal`；声明 `SHIFT_LIMIT_MM=10.0`/bounds `[-10,10]`；`try_layout→OUT_OF_RANGE`、`evaluate→OUT_OF_RANGE`（保留 `target_delta_mm=[0,15]`）、`decide→INVALID_INTENT`、`commit→NO_CANDIDATE`；未写盘未扩限 | `correct_refusal`；拒绝后 `[0,0]`、指纹逐位相同 |
| **A16a** | L4 | `structural_unsupported`（候选副本可改但**无授权写回**；夹具 sha256 前后逐字节相同） | `structural_unsupported`（白名单无源码写回入口：`try_layout(LAYOUT_MM)→INVALID_VALUE`、`IntentSession(figure=…)→can_evaluate=false/NEEDS_AUTHORING`、Hub `source_write:true→403`） | **`completed`**：计划 `0dbb03c478a94a6bbe5cd538e6c135ce` → 真人在 `http://127.0.0.1:8798/` 点授权（铸造后 **39.977 s**，计入 `human_wall_clock_s`）→ apply 200 `COMMITTED_AND_VERIFIED`；**磁盘 sha256 `88ba0a44…0729` == 计划 after**（before `fe298676…b663` == 夹具字节）；history 检查点 `3c37a6dab01047bca22218ad79cedc0d`；gid 集合 7/7 与曲线指纹逐位不变；独立重建 +0.4999999999999929（残差 −7.1e-15） |

补充事实（不作性能解读）：

- A08 的 `bbox 中心` 与 `端点` **量的不是同一个量**，本表**单列**、不与端点并表；逐条核对见
  `D:/L/AI/figpact-archive/g6b-v2/A08-endpoint-reconciliation.md`。
- A16a 臂 V 的墙钟含 **39.977 s 等真人授权**（计入 `human_wall_clock_s`，是人的时间，不是 Agent 计算时间）；A09/A08/A11 的选区由 harness 发布，只有 A16a 的选区由真人在页面产生。
- 三臂都**未下任何性能/成功率结论**。

---

## 3. 四项通过条件逐条裁定

1. **隔离成立** → ✅：三臂各自逐 trial 独立提取树 + 独立进程 + 独立 state + 独立会话，均留四项泄漏检查证据（`git status --porcelain` 前后逐字相同；端口 8795–8798 与探针端口 11038 已停、无残留进程）。
2. **三臂题面逐字相同、gid 写死** → ✅：A09/A08 锁定 `fig2_nmr.main.peak.vancho.3p91` + 引线 `fig2_nmr.main.guide.vancho.3p91`；A16a 锁定 `intent.main.label.A`；三臂互核一致。
3. **权限一致（按各臂白名单逐项声明）** → ✅：臂 L 未用 Hub/选区/history/授权写回；臂 A 只用五操作 + IntentSession + 只读 Scene/Inspector + Hub G5a 只读面；臂 V 仅 A16a 走 `/api/plans` + 页面令牌 + `/apply`。
4. **指标口径可用** → ✅（**有保留**）：每字段有值或 `null`+原因；**token 三臂全线不可测**（无 usage 通道）→ 已声明 **M=40k 未被验证执行**；构建数仅单臂可得（臂 A 12/12/10/4、臂 L 5/5/2/2）且**不做跨臂比较**。

---

## 4. v2 自身的三处缺陷 + 一条引擎发现

**v2 的三处缺陷（下轮前必须修；三臂独立报告一致）**

1. **行尾基准**：本机 `core.autocrlf=true` 且工作树行尾混用 → §1.2 的三件夹具**没有任何单一 archive 模式能同时复现**；§1.3 登记值 12/12 等于**工作树字节**（`005fe962…`），而 commit 字节只有 6/12 相等（`ef070f56…`）。臂 V 已改用 `git archive -c core.autocrlf=false` 并**同时给出两种口径哈希**。
2. **判据包签名三臂互不相等**：臂 L `f16105cd…`、臂 A `1ededaec…`、臂 V `ef070f56…` —— 差异**只来自行尾与拼接方式**，内容一致。轮次记录在统一口径前**不得**宣称"逐字相同"。
3. **§5.2 自检命令不符**：直接跑 `simple_figure.py` 或 `figpact render` **不产生计数行**（脚本自建图，不走 `FigureSession._call_builder`）；改用会话级命令后自检通过（+4 行）。另：`examples/nmr/核磁原始数据` 未被 git 跟踪，三臂是**只读复制**进各自的 NMR 提取树。

**引擎发现（臂 A 报，需记录）**

- `FigureSession._sync` 以**脚本目录整树指纹**判源改动：把 `TEMP`/`MPLCONFIGDIR`/`state` 放进脚本目录，会让候选在 `try_layout → commit` 之间被**静默重载丢弃**（→`NO_CANDIDATE`）。臂 A 的 A09 首次 pass 因此作废并保留在 `armA/attempt0-A09/raw.json`（`records_extra.discarded`）。

**处置建议**

| # | 项 | 处置（下轮前） | 验证方式 |
|---|---|---|---|
| 1 | 行尾基准 | 判定包/夹具**统一用 `git archive -c core.autocrlf=false` 提取**，并把工作树/commit 两种口径一并登记（臂 V 的做法升级为全局约定） | 三臂对同一夹具各算一次，两种口径**逐题逐字相等** |
| 2 | 判据包签名 | 签名输入**先规范化行尾、再规范化拼接顺序**（路径排序 + 固定分隔符），签名算法与输入口径写进 v2.1 正文 | 三臂判据包签名**逐字相等**；不等 = 该轮不进正式轮 |
| 3 | §5.2 自检命令 | 把自检命令改为**会话级命令**（经 `FigureSession._call_builder`），并把"`examples/nmr/核磁原始数据` 未跟踪 → 只读复制"写进 v2.1 §1.2 夹具表 | 自检输出+4 行计数行；提取树只读复制证据留档 |
| 4 | 引擎发现 | 把 **"`TEMP`/`MPLCONFIGDIR`/`state` 不得放在脚本目录"**写成 v2.1 的**硬约束**（隔离目录一律放在脚本目录之外，或明确排除在指纹之外） | 逐 trial 检查目录布局；A09 类静默 `NO_CANDIDATE` 不再出现 |

---

## 5. 裁定

**短复验：通过四项通过条件。** §3 四条逐条成立；12 trial 0 丢弃；隔离、题面/gid 锁定、权限白名单、指标口径四项均留下可复核证据。

**正式轮：条件性放行。** 放行条件不是"直接跑"，而是**先出 v2.1**：

1. 修行尾基准与判据签名口径（§4 处置 1、2）——否则三臂的任何"逐字相同"声明都不成立；
2. 修 §5.2 自检命令（§4 处置 3）；
3. 把 **"tmp/state 不得放脚本目录"** 写成硬约束（§4 处置 4）；
4. token 口径**沿用"不可测"**：不引入估计值、不用 `null` 冒充 0，M=40k 继续标注为"未被验证执行"。

**v2.1 未落地前，不得启动正式轮**；v2.1 冻结后再按协议 §8.2 的进入条件逐项核对（含 A16b 夹具登记等未完成项）。

---

## 6. 未做与未宣称

- **未下任何性能/成功率结论**：本轮不做臂间胜负、不报提速倍数、不报成功率（分子分母的定义问题协议 §2.4 仍在）。
- **未做 token 计量**：三臂全线不可测（无 usage 通道）；未用估计值、未用 0 冒充。
- **未做跨臂构建数比较**：构建数仅单臂可得（臂 A 12/12/10/4、臂 L 5/5/2/2），口径未统一前不作比较。
- **未做**：正式轮（≥10 配对任务）、A16b、跨图泛化题（FTIR 备用题）、`human_wall_clock_s` 的臂间比较、pilot 与短复验数据合并。
- **未复核**：pilot 的 `I:` 盘原始产物（本环境不可达），引用 pilot 仅限 `docs/G6B_PILOT_REPORT.md` 内已记录数值。

---

## 附：产物位置

归档根 `D:/L/AI/figpact-archive/g6b-v2/`：

- `armL.json`（44.8 kB）/ `armA.json`（47.8 kB）/ `armV.json` + 三份 `*-summary.md`
- `A08-endpoint-reconciliation.md`
- `criteria-hashes-commit-bytes.txt` / `criteria-hashes-default-archive.txt` / `criteria-hashes-worktree.txt` / `criteria-lineending-table.txt`
- `harness/`、`trials/`、`criteria-*.txt`

**`I:` 盘在本环境已不存在**（只剩 `C:/`、`D:/`），旧 I: 产物不可达。
