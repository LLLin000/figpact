# G6b 三臂 Agent 盲测协议 v2（修订版，短复验前冻结）

> **历史不可改。** `docs/G6B_THREE_ARM_PROTOCOL.md`（v1）与 `docs/G6B_PILOT_REPORT.md`（pilot 记录）
> 保持逐字节不变。本文件是**新文件**，即 v2；两者冲突时，**尚未开跑的轮次以本文件为准**，但 v1 与
> pilot 已经写下的事实（谁在哪条题上做了什么、哪些条件成立或不成立）不追溯改写。
>
> **本文件的地位。** 本文件只冻结 v2 协议与**进入条件**，不含任何三臂性能/成功率结论。正式三臂
> 比较**尚未放行**，顺序是：**冻结 v2 → 短复验（四层每层一题 × 3 臂 = 12 trial）→ 通过 §8.2 的进入
> 条件 → 才跑正式轮（≥10 配对任务）**。任何数值只能出现在实验记录文件里（pilot 的数值在 pilot
> 报告里；短复验与正式轮的数值在各自的记录文件里）。
>
> **pilot 数据的用法。** pilot 的 12 条 trial 全部保留在 `I:/figpact-test-archive/g6b-pilot/`
> （`{armL,armA,armV}.json`、`*-summary.md`、`armA-evidence/`、`armV-tmp/`、`armL-trial/`），只作
> **机制与格式证据**：不得当作能力覆盖率或效率的比较数据、不得并入 v2 的分母、不得与
> `docs/G6_PROFILE_NOTES.md` 的引擎分母或 `README.md` P3.1 的 ~4.1% 互相折算或相乘（v1 红线 5 继续有效）。

## 0. v2 相对 v1 的修订总表

| # | v1 / pilot 暴露的问题 | v2 的处理 | 落点 |
|---|---|---|---|
| 1 | 模型冻结为 `opencode-go/step-5-preview-free`（已不存在），pilot 实际为 `opencode-go/deepseek-v4.1-flash:high` | 逐字冻结实际模型与推理档，写明决定来源；正式运行前核对可用性 | §3.4 |
| 2 | 隔离程序未写死（pilot 臂 L/A 首跑同会话顺序跑 4 题、且跑在 HEAD 而非冻结 commit） | 每条 trial 四条硬隔离 + 可执行的泄漏检查 | §4 |
| 3 | token、构建数三臂都不可量（或只有一臂可量） | token：能取到就同通道，取不到就降级不可测；构建数：**统一外部计数器** | §5.1、§5.2 |
| 4 | 臂 A 的白名单里没有源码写回路径，A16 结构性做不到，v1 未定义该记什么 | 定义为**结构性未完成**（D1 未完成；不记正确拒绝、不记误拒） | §2.5、§3.3 |
| 5 | A16 的题面没逐字定义目标改动（pilot 两臂目标值不同：+0.15 vs +0.50 mm） | A16 拆为 **A16a / A16b**，题面（gid、+0.50 mm、夹具、判据）逐字冻结，保留追溯 | §2.2 |
| 6 | 哪些 trial 需要真人选区未定义 | 每题登记"选区来源"，人工交互指标单列 | §6 |
| 7 | `try_layout` 回执不含实测毫米 | 实测毫米**只能**取自独立重建；`try_layout`/配置数值永不充当实测 | §5.3 |
| 8 | 臂 L 白名单"现有全量预览"含糊；臂 L 做不到授权写回算什么未定义 | 臂 L 五项逐项权限表 + 统一结果枚举 | §3.2、§3.3 |
| 9 | 基线老化：`9e3161e` 上同进程第二次 `IntentSession` 构造必失败（`8af3b25` 已修） | 三臂统一到同一 commit；`9e3161e` 只作 G6a 的**独立**引擎对照 | §1.1 |
| 10 | v1 §3.1 给臂 V 列的 `SourceAuthoringAdapter` / `Planner` / `ActionCatalog` 在树里并不存在 | 白名单**存在性核对**：只允许写实际存在的入口 | §1.4、§3.4 |
| 11 | 单一成功率的分子分母把"结构性不支持"和"执行效率"混在一起 | 两个分母：D1 能力覆盖率、D2 共同可执行任务效率 | §2.4 |
| 12 | A08 引线端点两臂读数不一致（臂 L 0.08 mm / 臂 V +0.15 mm） | 已核对（§8.4）：**量的不是同一个量**（对象 bbox 中心 vs 端点）且**不是同一个标注**（`vancho.3p91` vs `vanoh.4p62`）；v2 收编其四条判定与六条进入条件 | §5.3、§7、§8.4 |

## 1. 统一引擎基线（三臂同源，只用白名单区分）

### 1.1 冻结 commit 清单

| 项 | 冻结值 | 依据 / 说明 |
|---|---|---|
| **三臂统一引擎 commit** | `12e751cdeab699078a4f5a1835ca41f28af27b3b` | 2026-10-13 主线 `refs/heads/master`；含 G2–G5b（选区、计划/授权/写回、history）与 G6a 两项优化 |
| 三臂代码来源 | 上述**同一 commit** 的三份**独立提取树**（每臂一份，每条 trial 一份） | 本协议只比较**工作流/白名单差异**；混用引擎版本 = 该轮作废（§9 红线 9） |
| G6a 引擎优化对照（**不进三臂结论**） | 优化前 `9e3161e4b4e8e4a35ec284083679e33a39d0985d`；优化后 `7d581b14289beb44591321b720a2a53027d9905a`、`aa0f7ca4afbf59a8e3e82012bf76d15a020a82fc` | `docs/G6A_OPTIMIZATION_RESULTS.md`；作为**独立**的引擎级对照单独报告，不得与三臂数字合并 |
| 提取树生成 | `git -C <repo> archive <commit> \| tar -x -C <trial_root>/tree` 或 `git -C <repo> worktree add --detach <trial_root>/wt <commit>` | 每条 trial 一份（§4） |
| 冻结期纪律 | 轮次期内上述 commit 不得修改；确需修改 → 整轮作废重跑并记录变更 | v1 §1 工作目录纪律继续有效 |

### 1.2 夹具哈希（逐题一份，禁止原地改仓库夹具）

下表是 2026-10-13 在 `D:/L/AI/figpact` 工作树实测的值。**冻结时必须在提取树内用同一命令重算并逐字相等**；
不等 = 提取树与工作树不一致，冻结清单未成立，**不得开跑**。命令：

```text
sha256sum "<path>"        # 在 <trial_root>/tree 内执行，逐字记录
```

| 夹具路径 | sha256（2026-10-13 实测） | 用途 |
|---|---|---|
| `examples/nmr/08 NMR.py` | `22728d695821abfe2ea695ff1767ed289e7f3feb746e7bfcda655290259462cf` | A08 / A09 / A11（L1、L2、L3 的真实 NMR 题） |
| `examples/nmr/nmr.yaml` | `84a40f0ee122a5a78ac6c0d6a452d6bed18cd2012a063cb26ecfe7a025b6b98b` | 同上（配置侧） |
| `examples/python_native/simple_figure.py` | `fe298676aa8277db9420c61483ede491fef16c0ef1a7ca53392f589e2642b663` | **A16a**（已声明 `LAYOUT_MM` 绑定，唯一排版来源） |
| `examples/ftir/plot_ftir.py` | `524b1c86d6a5018abb1f561f32e960f15a5f2fddde80ac6935d141ea14150362` | 跨图泛化备用题（正式轮可选） |
| `examples/ftir/ftir.yaml` | `d6946d9286ffc3f9bdebf519006e6e437500c9158634aad641e81323fec03d49` | 同上 |
| **A16b 夹具**（尚未登记） | 冻结时定稿（见下） | **A16b**（无任何布局绑定的 legacy 脚本） |

**A16b 夹具要求（必须在正式轮冻结前完成，未登记 = 不得开跑正式轮）**：

1. 由 `examples/python_native/simple_figure.py` 派生：**删掉**模块级 `LAYOUT_MM` 映射，把两个标签的
   毫米位移**字面量内联**进 `ax.text` 坐标；科学曲线、采样、画布毫米、DPI、标签文本（`A` / `B`）、
   gid 命名（`intent.main.label.A` / `intent.main.label.B`）与对外接缝
   （`FIGURE_ID / SCOPES / load_science / build_scene / build_figure_and_registry`）逐字不变。
   即：A16a 与 A16b 两个夹具**唯一差别**是绑定形态（已声明 vs 未声明），使两个子场景可比。
2. 以**只新增夹具**的独立提交进仓库（不得顺手改引擎、`examples/nmr`、`examples/ftir`、既有测试）。
3. 在该提交上登记：路径、`sha256sum` 值、提交哈希、以及"该脚本确实没有 `LAYOUT_MM` 声明"的核对命令
   `grep -n "LAYOUT_MM" <fixture>` 的**空输出**证据。

### 1.3 判据版本（判据包）

判据包 = 引擎 commit + 下列文件的 sha256（提取树内实测）+ 容差 + strict 范围。三臂**逐字相同**，
不得对任何一臂放宽。

| 判据文件 | sha256（2026-10-13 实测，冻结时以提取树重算为准） |
|---|---|
| `figpact/qa.py` | `a54c8f4678563a18a0f5195e68c17363d6c7b1e7e6b8fb368aa53b4fee31a706` |
| `figpact/science.py` | `25089df2fce469998f6bbae1137a4b3bdb227c6d04ba375071c72b0ff8aa2f0f` |
| `figpact/geometry.py` | `e58934816a860876f667e991ccf4a7bb1b976c3e43d9201dd4b7ee9b33c10754` |
| `figpact/intents.py` | `4771d0dc75f34bd6f8ff45cf6cd169718f9827c77c454e836d9c660125f056aa` |
| `figpact/session.py` | `7832c9dba801707a2e80c7d3f4d06f85ca55a3e51b8704d311e24d42dcd858bc` |
| `figpact/hub.py` | `b3b2ccca7ef1a6fc51f484b7017d967916af60201765379bbafe7bdaf4b10f08` |
| `figpact/inspector_server.py` | `6f7d3f9dc6ef1fa9aacb36fbdbd3d4af466cb3ab48f57b84ff2861a1db0077df` |
| `figpact/authoring.py` | `e0cf1239b782793c6a4e64688c12817fb4c33a7120d8307b8f15897d8c10a30f` |
| `figpact/python_native.py` | `99af396f4b3fd89cb609a5c5c4cd654bae277eb268f38a7dad73777c4bf1744f` |
| `figpact/source_writes.py` | `61c4c1f4bd57058e12e56211b71971bf2dfac7145e96e792a15adda6ace938a7` |
| `figpact/history.py` | `7c0a61b2d9e6150cd4018641a52f514f02a2146fd3eae99cdce25fa246fed98b` |
| `figpact/agent_api.py` | `b680dbc461f3c413a38af4f82b5d24624570f4ef63fe45f2bc73a8d71ceb1ae8` |

**判据包签名**（记录进每条 trial 与轮次记录）：

```text
sha256sum <上表 12 个路径按路径字典序> | sha256sum
```

**容差与判定**：`tolerance_mm = 0.01`（与引擎实测所用一致）；目标残差逐目标判定，须 ≤ 0.01 mm
**且** Target / Science / Impact / QA 各项均为 PASS。v1 §5 里"0.005 mm 是任务误差上限"一句在 v2 中
不再作为判据：0.005 mm 与引擎 `tolerance_mm=0.01` 不同源，且 pilot 三题实测残差量级为
1.4e-15 / 2.1e-15 / 3.9e-15 mm（pilot 报告 §2），两项阈值都不改变任何既有判定结论。
光栅读数（px→mm）不是判据（§5.3）。

### 1.4 白名单存在性核对（开跑前的硬检查）

v1 §3.1 给臂 V 列出的 `SourceAuthoringAdapter` / `Planner` / `ActionCatalog` 在 `12e751c` 的树里
**不存在**（`grep -rn "class \(SourceAuthoringAdapter\|ActionCatalog\|Planner\)" figpact/` 无匹配）。
v2 因此只允许把**实际存在的入口**写进白名单。核对命令（在提取树内执行，结果记入轮次记录）：

```text
grep -n "def build_repair_spec"     figpact/authoring.py        # 作者化提案（只描述，不写文件）
grep -n "def locate\|LAYOUT_NAME"   figpact/python_native.py    # 已声明 LAYOUT_MM 的 AST 定位
grep -n "def plan_source_change\|def apply_source_change\|def recover_pending" figpact/source_writes.py
grep -n "def do_GET\|def do_POST"   figpact/inspector_server.py # /api/selection /api/tasks /api/plans /apply
python -B -X utf8 -m figpact agent --help                       # 五操作是否仍在
```

规则：白名单里每一条能力项必须能指到具体文件 + 函数/路由；指不到的条目**从白名单删除**或写明
"不可用（不存在）"，并据此更新该臂在相关题上的路径裁定（§2.4）。

## 2. 任务分母与两个报告分母

### 2.1 追溯：v1 的 26 条与 15 条不动

- v1 的 26 条逐条裁定（纳入 15 / 排除 11）与四层编号**逐字保留**，v2 不重写那张表。
- v2 只在**一处**改动分母构造：把 **A16 拆成 A16a 与 A16b** 两个子场景（用户裁定，见 §2.2）。
  原 A16 仍在 v1 的表里；v2 的分母里它的位置由 A16a + A16b 取代（15 − 1 + 2 = **16 条**）。
- 每条 trial 记录必须带追溯字段 `parent_scenario: A16`（A16a/A16b 都写），报告里不得只写子编号
  而丢掉与原 A16 的关系。**不得**把原 A16 悄悄换成另一个任务，也不得让 A16a/A16b 覆盖原 A16 的
  历史事实（pilot 的 A16 事实仍按 pilot 报告原文引用）。

### 2.2 A16a / A16b 逐字题面

| 项 | **A16a**（新增子场景，正式实验前先注册；本文件即注册） | **A16b**（原 A16 的同形延续） |
|---|---|---|
| 考什么 | 已声明布局绑定下的**受控源码编辑工作流**（授权 → 写回 → 重建 → 科学基线） | **真正的 legacy Python 适配**：脚本里没有布局绑定，靠 Agent 作者化改代码 |
| 夹具 | `examples/python_native/simple_figure.py`（§1.2 哈希） | A16b 夹具（§1.2 要求，冻结时登记哈希） |
| 题面目标（逐字） | 标签 `intent.main.label.A` **上移 +0.50 mm**（`dx=0`、`dy=+0.50`，画布毫米、左下原点、右/上为正），并**持久写回源码** | 同上：`intent.main.label.A` 上移 +0.50 mm 并持久写回源码 |
| 允许的改动 | 只允许该标签的排版位移；其它标签、曲线、科学荷载不变 | 允许在源码里引入一条显式布局参数（或等效布局表达式），但科学荷载不变 |
| 正确结果 | 授权写回后：磁盘 == 计划 after；独立重建 Δy = +0.50 mm（残差 ≤ 0.01 mm）；旧科学基线指纹与 gid 集合逐位不变 | 同左；且新引入的布局入口必须**由源码声明**（不是运行期改 Artist） |
| 与原 A16 的差别（必须写进报告） | 绑定形态 = **已声明**（`LAYOUT_MM`） | 绑定形态 = **未声明**（需作者化） |
| pilot 对照 | 无（新增子场景） | pilot 的 A16 事实（臂 L 无授权写回、臂 A 无源码写回入口、臂 V 走授权写回，两臂目标值不一致 +0.15 / +0.50 mm）作为**机制证据**引用，不作数值对照 |

**为什么短复验的 L4 槽位取 A16a**：短复验只要求四层各一题；A16a 是新注册、且把最重的机器
（授权写回 + 重建 + 旧科学基线）压在一次 trial 里；A16b 需要一份新夹具（§1.2），列为**正式轮**的
进入条件，正式轮的题集必须同时含 A16a 与 A16b。

### 2.3 v2 冻结题集（短复验用，四层各一题）

| 层 | 题 | 夹具 | 目标（逐字） | 正确结果类型 | 选区来源 |
|---|---|---|---|---|---|
| L1 位置调整 | A09 | `08 NMR.py` + `nmr.yaml` | 起点声明 `[0.2,-0.1]` → 目标绝对 `[0.2,+0.05]`（即 +0.15 mm） | 完成 | harness_published |
| L2 复杂标注 | A08 | `08 NMR.py` + `nmr.yaml` | `fig2_nmr.main.peak.vancho.3p91` 上移 +0.15 mm，`fig2_nmr.main.guide.vancho.3p91` 跟随 | 完成 | harness_published |
| L3 约束冲突 | A11 | `08 NMR.py` + `nmr.yaml` | +15 mm（超出 `SHIFT_LIMIT_MM=10.0`） | 正确拒绝 / 报冲突 | harness_published |
| L4 无 YAML | A16a | `simple_figure.py` | `intent.main.label.A` 上移 +0.50 mm 并写回源码 | 完成（需授权写回） | human_page |

### 2.4 两个分母（分别报告，不得互相顶替）

**D1 能力覆盖率** = 三臂面对**同一题集**，各自能否完整达成用户目标。结构性不支持计入未完成。

- D1a **路径覆盖率**（不依赖运行，冻结时裁定）：分子 = 该臂在题上有 **≥1 条合法实现路径** 的题数；
  分母 = 题集大小。裁定依据 = §3 的逐项权限表 + §1.4 的入口存在性；**冻结前裁定完毕，跑完不得改**。
  同题至少一臂为 0 → 该题**只能进 D1，不进 D2**。
- D1b **结果覆盖率**（来自运行）：分子 = 该臂在该题上产出**正确结果**（完成 / 正确拒绝，见 §3.3）
  的题数；分母 = 题集大小。`结构性未完成`、`失败`、`误拒`、`误接受`、`超预算` 均**不计入分子**。
- 报告必须给出**本轮选题清单内**（短复验 4 条；正式轮为冻结的 ≥10 条）的逐题 × 逐臂矩阵，
  不允许只给汇总数；16 条冻结分母里未选中的题另表列出并写明未选原因。

**D2 共同可执行任务效率** = **只在三臂 D1a 全为真的题**上比较：

| D2 指标 | 口径 |
|---|---|
| 完成时间 | `agent_wall_clock_s`（**不含**真人等待，§5.4）；逐题 + median/P95 |
| 工具调用 | 受试 Agent 侧真实往返次数（含失败往返）；逐题 + median/P95 |
| 首次正确率 | `attempt=1` 且独立重建复核 + Target Oracle 全 PASS 的题数 / D2 题数；重试后的成功**不计**首次成功 |
| 目标残差 | 独立重建实测位移 − 目标位移（逐目标、带符号、带轴）；判定阈值 0.01 mm |

**按任务类别适配（D2 同时收"完成类"与"正确拒绝类"题，口径必须分开写）**：

| 任务类别 | 首次正确率的判据 | 目标残差 |
|---|---|---|
| 完成类（A09、A08 等） | `attempt=1` + 独立重建复核 + Target Oracle 全 PASS | 独立重建实测位移 − 目标位移（阈值 0.01 mm） |
| 正确拒绝类（A11 等） | `attempt=1` **且**正确拒绝、依据三元组成立、无违规候选、无静默 no-op | **不适用**：无候选；记为"不适用（正确结果为拒绝）"，改为记录"拒绝后独立重建的位移"（期望为 0.0 mm / 与基线逐位相同） |

完成时间与工具调用两类题同口径（`agent_wall_clock_s`、真实往返次数）。

**禁止**：D2 里放进任一臂结构性不支持的任务；也不得用某臂"实际跑了但结构性做不到"的任务去证明
另一臂更快。D2 为空集时如实写"本轮无共同可执行任务"，不得伪造对照。

**短复验的裁定（逐题给出，不需要再判断）**：

| 题 | D1a：臂 L | D1a：臂 A | D1a：臂 V | 归入 |
|---|---|---|---|---|
| A09 | 有 | 有 | 有 | D1 + D2 |
| A08 | 有 | 有 | 有 | D1 + D2 |
| A11 | 有 | 有 | 有 | D1 + D2（正确拒绝类，效率仍可比） |
| A16a | **无**（无授权写回通道） | **无**（白名单无源码写回路径） | 有 | **仅 D1** |

### 2.5 正确拒绝子分母 / 误接受 / 误拒（冻结）

- **拒绝子分母**（v1 §2.3 冻结，不变）：A11、A12、A13、A15、A17、A18、A19。短复验里只有 A11 命中。
- **正确拒绝率** = 分子（明确拒绝或报冲突，且给出三元组依据：哪条声明、实测是什么、做了或没做什么；
  未提交违规候选；未静默 no-op；未擅自扩权）÷ 分母（该 7 条中**本轮实际选入**的题 × 每臂 trial 数）。
- **错误接受率** = 在同一条拒绝子分母上，受试者**提交了违规候选 / 声称成功 / 静默 no-op / 越权**的
  trial 数 ÷ 同一分母。与正确拒绝率**并列报告**（figpact 的价值包含"不可行或科学风险不明时明确拒绝"）。
- **误拒** = 在**非**这 7 条的可做任务上的拒绝；计入 D1b 的失败，不得记进正确拒绝。
- **结构性未完成**（v2 新增的结果类型）= 该臂白名单里根本不存在产生正确结果所需的机制。它
  **不是**正确拒绝，**不是**误拒，**不是**失败：只在 D1b 记未完成、在 D1a 记 0，并在报告里写明是
  哪个机制缺失（例如臂 L 缺授权写回、臂 A 缺源码写回入口）。pilot 里臂 L 的 A16"做不到授权"
  因此**不**记作正确拒绝（与 pilot 报告 §5 的写法一致：当时按协议缺失记 failure；v2 起改为结构性未完成）。

## 3. 三臂冻结与逐项权限

臂字母仍按 v1 §3：**臂 L 旧手工 / 臂 A 现 Agent API / 臂 V vNext**；报告必须写全称。

### 3.1 三臂共用的冻结项

| 项 | 冻结要求 |
|---|---|
| 引擎 commit | 三臂同源（§1.1） |
| 模型 | 见 §3.4；三臂逐字相同；受试 Agent 不得自选或临时更换（红线 1） |
| 推理预算 | 三臂逐字相同：单题单会话，工具调用 ≤ **N=30**、输出 token ≤ **M=40k（仅当 token 可测时才是约束，见 §5.1）**、墙钟 ≤ **T=20 min**。超限 = 该 trial 记 failure，**不补不重试** |
| 题面与夹具 | 同一题三臂用同一夹具、同一题面**原文**、同一保护范围；题面不得按臂改写 |
| 输入可比较性 | 题面必须**显式**给出目标 gid（或对象唯一标识）与目标位移；因为臂 L 看不到选区，只写"用户选中的那个标签"的题面会让臂 L 拿不到可比较输入，该题不得进 D2 |
| 判据 | §1.3 判据包三臂一致，不得放宽 |
| 逐题独立 | 见 §4；上一题的目标/候选/累积状态/history 一律不带入 |
| 交付口径 | 三臂都在 §5.3 的同一测量口径下量实测位移；不许拿"配置数字变了"当"物理位移达成" |
| 盲法 | 产出物改名 `trial-<random-id>`，判分者不知道来自哪臂；记录员与判分者分离；臂顺序随机化（v1 §4.4 继续有效） |

### 3.2 逐项权限矩阵（含臂 L 的五项，逐项写清）

| 能力项 | 臂 L 旧手工 | 臂 A 现 Agent API | 臂 V vNext |
|---|---|---|---|
| 1. 文件读取 | **允许**（只读）：题面给定脚本/YAML/夹具、引擎源码、自己的读数输出 | **允许**（只读）：Scene 快照 / `inspect` 声明与关系；只看结构化回执 | **允许**（只读）：**含目标 fixture 源码全文**（作者化改代码必须有源码上下文）——这一条是对 v1 §3.1"不允许读完整脚本源码"的**显式修订**，因为 A16b 的目标在 v1 那句下自相矛盾 |
| 2. 候选编辑 | **允许，但仅限纯文本**编辑**候选副本**：`<trial_root>/<task>/candidate/` 下的 YAML / 脚本副本；无 AST 定位、无 RepairSpec、无 CAS | **允许**：`figpact agent` 五操作 + `IntentSession.evaluate/decide` + 只读 Scene/Inspector（Hub G5a 只读/试算面） | **允许**：`inspector_demo`（Demo 页）+ Inspector 服务 + `hub.py` 完整闭环 + `python_native`(AST 定位) + `authoring.build_repair_spec`(提案) + `source_writes`(journal 写回) + `history.py` |
| 3. 预览 | `figpact render`（整图 PNG，输出到 trial 输出目录） | `render_preview`（revision 命中缓存的 PNG）+ 只读 Inspector 视图 | Demo 页真实帧 + `render_preview` |
| 4. 验证 | `figpact try`（内存试算：位移/QA 差异/参数区间）、`figpact validate`、`figpact export --strict`（**只校验**，输出到 trial 目录；写仓库或正式产物目录 = 越权事件） | `evaluate` 的 Oracle 汇总回执（science/qa/target/impact + `measured_delta_mm`） | 同臂 A，另有重建实测与 Impact/Science Oracle 汇总 |
| 5. **授权写回** | **不允许**：无 plan / grant / before bytes / journal / CAS 通道；需要授权写回才能正确完成的题 → **结构性未完成**（§2.5），不记正确拒绝、不记误拒 | **不允许**：Hub 不授予源码写入（既有事实：`POST /api/tasks{source_write:true}` → 403）；`/api/plans` + `/apply` + 页面授权面**不在**臂 A 白名单内 | **允许，且只在授权下**：`/api/plans`（PENDING）→ 真人在真实页面点授权（单次使用 grant）→ `/api/plans/<id>/apply`；before bytes + 冻结科学基线 + CAS 必须成立 |
| 6. Hub / 选区 | **不可见、不使用**（无 Hub 通道） | 只读/试算面：`GET/POST /api/selection`、`POST /api/tasks{kind:geometry}`、`/api/intents/evaluate`、`/api/intents/decision`；**不得**替用户操作 UI | 完整闭环：单可写 Worker、`selection_seq` / `event_seq` / `revision`、session invalidation |
| 7. 历史记录 | 无（不产生 history） | 可用既有 `IntentSession(history=True)`，记录不完整（非本协议要求） | 必须记录（accept/undo/reopen 全链路 + `source_change` 检查点） |
| 8. 交付物 | 候选副本（YAML；源码类题另加候选脚本副本）+ 自己的读数原文 | 候选 YAML；源码类题另交授权写回后的候选脚本（本白名单下不可用） | 候选 YAML + 候选脚本（若授权）+ history 记录 |

「现有全量预览」在 v2 的逐字定义 = **第 3、4 项列出的 CLI 集合**（`render` / `try` / `validate` /
`export --strict`），不含 Hub、不含 Inspector 页面、不含选区。光栅读数只作参考（§5.3）。

### 3.3 结果枚举（每条 trial 必落在其中之一，互斥）

| 结果 | 含义 | 计入 |
|---|---|---|
| `completed` | 正确结果达成，独立重建复核通过 | D1b 分子；在 D2 题集内进 D2 |
| `correct_refusal` | 拒绝子分母上明确拒绝/报冲突且依据成立 | D1b 分子；正确拒绝率分子 |
| `mis_accept` | 拒绝子分母上提交违规候选/声称成功/静默 no-op/越权 | 错误接受率分子；D1b 不算达成 |
| `mis_refusal` | 可做任务上拒绝 | D1b 不算达成（记误拒） |
| `structural_unsupported` | 白名单缺产生正确结果所需机制（§2.5） | 仅 D1a=0、D1b 未完成 |
| `failed` | 有路径但未达成（含超预算、崩溃、题面未完成） | D1b 不算达成 |
| `discarded` | 作废重跑（须写明原因；原记录保留不删） | 进报告的分母完整性表，不进任何分子 |

### 3.4 模型冻结与核对

| 项 | 值 / 要求 |
|---|---|
| 冻结模型标识（逐字） | `opencode-go/deepseek-v4.1-flash:high` |
| 决定来源 | 用户改定「用当前 task 默认模型」；pilot 三臂实际受试模型即此标识（pilot 报告 §1） |
| 核对动作（正式运行前必做，逐条落盘） | ① 逐字记录实际模型 ID；② 记录推理档（`high`）与提供方；③ 记录该标识在运行当日**可用**的证据（一次最小调用回执）；④ 记录三臂的运行器配置（同一标识、同一档） |
| 不可用时的处理 | 三臂**统一**换为当日默认模型并重新记录；**只换一臂 = 该轮作废** |
| 与预算的关系 | 模型可用性核对与 §5.1 的 token 通道核对同一次完成（同一条最小调用既验模型也验 usage 通道） |

## 4. 隔离程序（每条 trial 四条硬要求，逐条留证）

1. **独立提取树**：`git -C <repo> archive <commit> | tar -x -C <trial_root>/tree`
   （或 `git -C <repo> worktree add --detach <trial_root>/wt <commit>`）。树内夹具 sha256 必须等于 §1.2。
2. **独立进程**：该 trial 的入口在独立子进程内起；臂 V 的 Hub/Inspector 服务每 trial 独立端口
   （pilot 用过 8791–8794，只绑回环）与独立 `session_id`；trial 结束必须停掉该 trial 起的进程。
3. **独立状态目录**：`FIGPACT_STATE_HOME=<trial_root>/state`（**必须在脚本/配置目录之外**——放在
   脚本目录下会被 history 合法拒绝，pilot/G5b 已有实例）、`TEMP=TMP=TMPDIR=<trial_root>/tmp`、
   `MPLCONFIGDIR=<trial_root>/mpl`、`PYTHONDONTWRITEBYTECODE=1`。
4. **独立会话**：每 trial 新建会话；上一题/上一臂的目标、候选、history、checkpoint 一律不带入
   （A09 与 A08 用同一张图，也必须目录/state/会话互不相通）。

**同一时刻只跑一条 trial**（避免共享 MPL 缓存与资源竞争）；确实要并发 → 每条 trial 自己的
`MPLCONFIGDIR` / `TEMP`，并在报告里声明并发事实。

**泄漏检查（每 trial 收尾执行并留证）**：

```text
(1) 树内夹具：sha256sum <fixture>            # 必须逐字等于 §1.2 登记值
(2) 状态目录：ls <trial_root>/state          # 只含本 trial 的 checkpoint/plan/journal，且 id 可列
(3) 仓库无改动：git -C <repo> status --porcelain   # 空
(4) 进程：本 trial 起的端口/进程已停止（netstat / 进程名核对）
```

(3) 为空是硬要求：任何 trial 都不得改仓库夹具、YAML、脚本或正式产物；确需写盘时只能写
`<trial_root>` 内。

## 5. 计量口径（三臂一致）

### 5.1 token

- 优先取**运行器给出的真实用量**（in / out / reasoning）。通道必须在冻结前**实测一次**（§3.4 的最
  小调用：能从回执或运行器日志读到 usage 才算可测）。
- 能测 → 三臂同通道、同字段；报告写原始回执位置。
- **测不到 → 该臂 token 记「不可测」并写明原因**；此时输出 token 上限 **M=40k 降级为"未执行"**，
  并必须在报告里逐字声明"token 上限未被强制执行"，**不得**声称 40k 已被执行，**不得**填 0 或估计值。
- 某臂可测、另一臂不可测时：token 只作**单臂**记录，**禁止**跨臂比较。
- 工具调用数与人可读的墙钟不受此影响，仍是可执行的预算项。

### 5.2 统一外部构建计数器（跨臂可比的前提）

- 机制（三臂共用，仓库外、不改引擎）：trial harness 目录里放一个 `sitecustomize.py`，通过
  `PYTHONPATH=<harness>` 注入每条 trial 的**每个** Python 子进程，包装
  `figpact.session.FigureSession._call_builder`，每次真实调用向 `$FIGPACT_BUILD_COUNTER` 追加一行。
- 计数语义：**1 行 = 1 次真实整图构建**；缓存命中的预览 PNG、`render_preview` 的 revision 命中
  **不产生行**；backend 内部开销不计。
- 自检（冻结前做一次，留证）：跑一条已知会构建的命令（例如直接执行 `simple_figure.py`，或
  `figpact render`），确认计数器文件**新增行**，并把该命令与行数记为基线。
- 只有**三臂都能产出计数**时才做跨臂构建数比较；任一臂不可量 → 该指标记「不可测」，并**禁止**跨臂
  比较构建数（pilot 就是反例：只有臂 V 可量）。

### 5.3 毫米位移与目标残差

- **主口径（唯一判据）= 独立重建**：判分者从该 trial 的提取树 + 冻结夹具 + 该 trial 候选，在**独立
  进程**里重建同一张图，取 `bounds_mm` / `runs_mm`（画布毫米、左下原点、右/上为正），
  残差 = 实测位移 − 目标位移，逐目标（含引线两端）记录。
- **次口径（只记录，不作判据）**：受试者自己看到的读数（臂 L 的 `figpact try`、臂 A/V 的 evaluate
  回执）。报告里必须标明来源是"受试者自报"。
- **`try_layout` 回执里的参数值永远不算实测**（pilot 修订 7）。
- 光栅读数（px→mm）只在独立重建不可用时出现，必须标注 ±0.05 mm 量级不确定度（pilot 臂 L 的 A16
  读数约 ±0.042 mm），且降为参考、不进判定。
- 引线位移**一律按端点**报，禁止用对象 bbox 中心冒充端点位移。三臂必须报同一组字段：
  `guide_scientific_endpoint_error_mm`（科学端 = 引线锚在谱线上的那一端，同 gid 同端点的绝对 mm
  坐标差，逐位比对）与 `guide_label_endpoint_delta_mm`（标注端 = 接文字的那一端，带符号 `[dx, dy]`）。
  端点定义、取自哪次重建、单位与精度必须写在记录里；缺任一端点字段 → 该 trial **不入比较分母**。
- 读数工具只能给对象级聚合量的臂（如臂 L 的 `figpact try`：bbox 中心差 ÷ `figure.dpi/25.4`、
  0.05 mm 过滤、输出精度 0.01 mm），必须在**同一条记录**里并列给出 `guide_bbox_center_delta_mm`
  并注明口径与精度；该量**不得**与另一臂的端点量相减、求平均或并表比较。
- 位移恒为**候选 − 基线**，基线恒为夹具默认（不得用候选里的声明值当基线或当实测）。

### 5.4 真人等待必须单列

每条 trial 记录至少三个时间字段：`agent_wall_clock_s`（Agent 侧执行）、`human_wall_clock_s`
（真人点选/授权/等待）、`total_wall_clock_s`（= 前两者 + 其它）。三臂都有真人参与的时刻（例如
A16a 的授权）必须落在 `human_wall_clock_s`：pilot 臂 V 的 A16 总墙钟 72.56 s 里含 60.0 s 真人授权等待，
**不得**把它解释成 Agent 计算慢，`human_wall_clock_s` 也不得进入 D2 的完成时间。

### 5.5 工具调用与墙钟

- 工具调用数 = 受试 Agent 侧真实往返次数（**含失败往返**），backend 内部调用不计。
- 墙钟用真实 `started_at` / `finished_at` 记录，**不得**事后补写（v1 §4.3）。
- 超预算（N / T，以及 token 可测时的 M）→ 该 trial 记 `failed`，不补不重试。

## 6. 真人选区与人工交互指标

1. **每题登记"选区来源"**（冻结表内一列，短复验见 §2.3）：
   - `harness_published`：由 harness 经 `POST /api/selection` 发布，逐字给出 gid 与几何（三臂同一份输入）；
   - `human_page`：真人在真实页面点选/授权产生（只有臂 V 的链路能消费）。
2. **输入可比较性**：无论选区来源，题面必须显式给出 gid 与目标位移（§3.1）。
3. **人工交互指标（单列，不参与 D2 效率比较）**：
   - `human_actions`（真人点击/授权次数）；
   - `human_wall_clock_s`（§5.4）；
   - `human_decision_required`（是否必须人类裁决，例如 A13 的耦合方案请示）；
   - `human_selection_source`（上表取值）。
   人工选区差异只作为**人机交互事实**报告，**不得**用来证明某臂更强或更快。
4. 相同题三臂的**输入条件**（题面 + 目标 + 夹具 + 允许改动范围）必须一致；臂间唯一的差异是 §3.2
   的白名单与接口能力。

## 7. trial 记录 schema（字段 / 获取方式 / 不可测写法）

| 字段 | 获取方式 | 不可测 / 缺失时的写法 |
|---|---|---|
| `trial_id` | 随机 id（盲法命名） | 不适用 |
| `task_id` / `layer` / `parent_scenario` | 冻结题集（A16a/A16b 必须写 `A16`） | 不适用 |
| `arm` | L / A / V（全称也写） | 不适用 |
| `engine_commit` / `criteria_signature` | §1.1 / §1.3 | 不适用 |
| `fixture_hashes` | `sha256sum`（树内） | 不适用 |
| `model_id` / `reasoning_effort` | §3.4 逐字 | 必须逐字，不许"默认" |
| `started_at` / `finished_at` / `agent_wall_clock_s` / `human_wall_clock_s` / `total_wall_clock_s` | 实时记录 | 不适用 |
| `tool_calls` | 受试侧往返计数（含失败） | 不适用 |
| `output_tokens` / `input_tokens` | 运行器 usage | `null` + 原因（并声明 M 未执行） |
| `real_figure_builds` | §5.2 外部计数器行数 | `null` + 原因；不可量则不做跨臂比较 |
| `outcome` | §3.3 枚举 | 只能取枚举值 |
| `attempt` | 整数 | 不适用 |
| `target_delta_mm` / `measured_delta_mm_rebuild` / `residual_mm` | §5.3 独立重建，逐目标 | 不可测 = `null` + 原因，不得用配置值顶替 |
| `measured_delta_mm_self_reported` | 受试者自报（标明来源） | `null` + 原因 |
| `guide_scientific_endpoint_error_mm` / `guide_label_endpoint_delta_mm` | 独立重建，端点量，两端分开（§5.3） | `null` + 原因；缺一则该 trial 不入比较分母 |
| `guide_bbox_center_delta_mm` | 只能给聚合量的臂填：并注明口径与精度（dpi、过滤阈值、输出精度） | `null` + 原因；不得与端点量相减或并表 |
| `science_violations` | 科学荷载比对（含 `xlim/ylim`、归属文本、比例尺） | 不适用 |
| `target_oracle` / `science_oracle` / `impact_oracle` / `qa` | 判据包回执（PASS/FAIL/unverified） | `unverified` 必须写明原因 |
| `refusal_evidence` | 三元组：哪条声明 / 实测是什么 / 做了或没做什么 | 正确拒绝的 trial 必填 |
| `writeback` | 是否有授权写回；`before_sha256` / `after_sha256` / 磁盘比对 | 无写回时写"无" |
| `human_*`（§6.3） | 实时记录 | 不适用 |
| `isolation` | §4 四条 + 泄漏检查四项结果 | 任一项缺证据 = 该 trial 作废 |
| `raw_request` / `raw_response` | 原文归档（不加工、不摘要替代） | 不适用 |
| `discard_reason` | 仅 `discarded` | 必填 |

## 8. 进入条件

### 8.1 短复验的进入条件（v2 冻结时必须全绿）

1. §1.1 commit 与三份提取树就位；§1.2 夹具哈希在树内重算一致；§1.3 判据包签名算出并记录。
2. §1.4 白名单存在性核对完成，缺失项已从白名单删除或标"不可用"。
3. §3.4 模型逐字记录 + 可用性证据；§5.1 token 通道**实测**过一次（可测或明确不可测，二者都要有回执）。
4. §5.2 外部构建计数器自检通过（至少一臂产出计数行）。
5. §2.3 题面、§3.2 白名单、§2.4 D1a 裁定、短期盲法命名规则与判分 checklist 版本号全部定稿。
6. §8.4 A08 端点核对结论已落盘并引用原文；未落盘则该项是**显式进入条件**（见 §8.4）。
7. 短复验 harness（含 `sitecustomize` 计数器、trial 目录骨架、随机化顺序表）就位。
8. 记录员与判分者分离且已指定。

### 8.2 短复验的通过条件（12 条 trial = 4 题 × 3 臂，缺一即未通过）

1. 三臂入口都真的能起来并完成 12 条 trial（含 `structural_unsupported` 的如实记录，不得把结构性
   不支持伪装成执行失败或成功）。
2. 每条 trial 的 §7 字段齐全；**无 null 冒充**：不可测的字段必须带原因，且 §5.1/§5.2 的降级声明
   已写入轮次记录。
3. §4 的四条隔离与四项泄漏检查**逐条有证据**，无跨题/跨臂污染。
4. 两个分母都算得出：D1 覆盖 4 题 × 3 臂逐题矩阵；D2 只在 §2.4 裁定的 A09/A08/A11 上计算
   （A16a 必须落在"仅 D1"）。D2 为空集时如实写"本轮无共同可执行任务"。
5. 实测毫米**全部**来自独立重建；`target_delta_mm` 与 `measured_delta_mm_rebuild` 都有值（或都写明不可测）。
6. 构建数在**能产出计数行**的臂上有值；不可量的臂记不可测，且报告未做跨臂比较。
7. `agent_wall_clock_s` 与 `human_wall_clock_s` 分开记录，A16a 的授权等待落在人工一侧。
8. A11 的正确拒绝判定能被第二个人用同一 checklist 独立复现（拒绝依据三元组一致）。
9. 盲法成立：产出物无臂标签，判分者事后才揭盲；揭盲后若某臂独占某类题，必须显式说明。
10. 无仓库改动（`git status --porcelain` 为空）、无越权发布、无扩限。
11. 12 条 trial 全部落盘（含失败与 `discarded`），无静默删除；产物路径逐条列出。
12. 报告明确写：本轮只是 v2 可执行性核对，**4 题 × 单次**，不得作为能力覆盖率/效率的对外结论。

**短复验的数值用法**：可作为机制证据与 v2 通过条件的判定依据，**不得**作为三臂能力/效率比较结论
（无重复、无配对样本量、无随机化对照）。

### 8.3 正式轮的进入条件

- §8.2 的 12 条全通过。
- 题目清单（≥10 条，**配对** = 同题跨臂）冻结：从 v1 §2.2 的 15 条经 §2.1 拆分后的 16 条里选，
  四层均有代表，且**必须含 A16a 与 A16b**（L4 两条）。选中的题全部进 D1；其中三臂 D1a 全为真的
  子集进 D2，选材要求 D2 题数 ≥ 8（否则题目清单重选，不得事后拿 D1 的题去凑效率）。
- A16b 夹具（§1.2）已提交并登记哈希。
- 三臂 commit 相同；判据包签名一致；模型与预算逐字记录；随机化顺序表已生成。
- 作废条件写明：判据被放宽 / 模型或预算不一致 / 隔离被破坏 / 冻结项被事后修改 → 该轮作废重跑。

### 8.4 A08 引线端点的待核项（引用或显式进入条件）

- **事实**：pilot 臂 L 报"引线文字端跟随 0.08 mm"，臂 V 报文字端/标注端 +0.15 mm、科学端误差 0.0。
- **必须核对三件事**：① 是否**同一个引线端点**（文字端 vs 科学端）；② 是否**同一方向**（+y）；
  ③ 是否**同一坐标定义**（画布毫米、左下原点、右/上为正、同 renderer/DPI、取自独立重建的
  `runs_mm`/`bounds_mm`）。
- **核对方法（可执行）**：在 §1.1 的提取树内，对 `examples/nmr/08 NMR.py` 的
  `fig2_nmr.main.guide.vancho.3p91` 取 `runs_mm` 两端，独立重建 before/after，比较科学端与文字端
  各自的有符号位移（期望：科学端 `(0,0)`、文字端 `(0,+0.15)`）。
- **落盘要求**：结论写入 `I:/figpact-test-archive/g6b-pilot/A08-endpoint-reconciliation.md`。
  - 若该文件**已存在**：v2 的冻结清单与轮次记录必须引用其路径与结论原文（一行引用）。
  - 若**尚未出现**：本项是**显式进入条件**——正式轮（以及需要 A08 毫米读数的任何比较）开跑前必须
    完成核对并落盘，否则不得开跑；核对文件里要逐字写明：同一端点 / 同一方向 / 同一坐标定义三者是否
    成立，以及 0.08 mm 与 +0.15 mm 的差异来源（不同端点、还是光栅读数误差，还是未解释）。
  - 若差异**无法解释**：进入正式轮的"待解释项"清单，且在解释清楚之前**不得**用 A08 的任何毫米读数
    支撑任何结论。

## 9. 红线（违反任一条 → 该轮作废）

v1 §6 的 8 条全部继续有效，另加：

9. **不得混引擎版本**：三臂必须用同一 commit 的独立提取树；把"新交互流程 + 新 Hub/Adapter + G6a 优化
   + 修复"打包成一条臂的区别，等于测不出工作流差异。`9e3161e` 与 G6a 优化只作**独立**引擎对照。
10. **不得用结构性不支持的任务证明效率**：D2 只收三臂 D1a 全为真的题；结构性不支持只能进 D1 的
    覆盖率，并如实标 `structural_unsupported`。
11. **不得把不可测写成数字**：token 不可测就写不可测并声明 M 未执行；构建数不可量就不做跨臂比较；
    毫米只能来自独立重建；`try_layout`/配置数值永不充当实测。
12. **不得把真人时间算成 Agent 时间**：`human_wall_clock_s` 单列，且不进 D2 完成时间。
13. **不得事后改冻结算表**：§2.4 的 D1a 裁定、题目清单、判据包签名、模型/预算在轮次期内冻结；
    需改 → 整轮作废重跑并记录。
14. **不得改 v1 与 pilot 报告**：`docs/G6B_THREE_ARM_PROTOCOL.md`、`docs/G6B_PILOT_REPORT.md`
    逐字节不变；pilot 数值不得并入 v2 分母、不得折算或相乘（v1 红线 5）。
15. **不得把臂定义偷换**：臂 A 不得临时拿到 `/api/plans` + `/apply` 或页面授权面；臂 L 不得使用
    Hub/选区；臂 V 的源码读取范围按 §3.2 第 1 项，不得把"读源码"说成越权、也不得让其它臂拿到
    System 级入口。

## 10. 冻结清单（定稿表；未勾选 = 不得进入对应阶段）

| 项 | 值 / 获取方式 | 状态 |
|---|---|---|
| 三臂统一引擎 commit | `12e751cdeab699078a4f5a1835ca41f28af27b3b` | 已定（§1.1） |
| 提取树生成命令 | `git archive <commit> \| tar -x`（每 trial 一份） | 已定（§4.1） |
| 夹具哈希 | §1.2 六行 | 现有 5 项已测；A16b 夹具待提交登记 |
| 判据包签名 | §1.3 的 12 个 sha256 + 拼接签名命令 | 待冻结时算出并逐字记录 |
| 容差 | `tolerance_mm = 0.01` | 已定（§1.3） |
| 模型 / 推理档 | `opencode-go/deepseek-v4.1-flash:high` | 待正式运行前核对可用性并留证（§3.4） |
| 预算 N / M / T | N=30 / M=40k（**仅 token 可测时才是约束**）/ T=20 min | 已定（§3.1、§5.1） |
| 短复验题集 | A09 / A08 / A11 / A16a | 已定（§2.3） |
| D1a 裁定 | §2.4 四行 | 已定（短复验）；正式轮 16 行待裁定 |
| 选区来源 | A09/A08/A11 = `harness_published`；A16a = `human_page` | 已定（§2.3、§6） |
| 外部构建计数器 | `sitecustomize` + `FIGPACT_BUILD_COUNTER`，自检留证 | 待冻结时自检 |
| token 通道 | 运行器 usage（可测/不可测都要留回执） | 待冻结时实测 |
| per-trial 目录 / state / 端口 | `<trial_root>/{tree,tmp,mpl,state,out}`；臂 V 每 trial 独立端口 | 待生成 |
| 盲法命名与 checklist 版本号 | 随机 `trial-<random-id>`；checklist 版本号逐字记录 | 待定稿 |
| A08 端点核对 | `I:/figpact-test-archive/g6b-pilot/A08-endpoint-reconciliation.md` | **显式进入条件**（§8.4） |
| A16b 夹具 | §1.2 要求（派生 + 只加夹具的独立提交 + 哈希） | **显式进入条件**（正式轮前） |
