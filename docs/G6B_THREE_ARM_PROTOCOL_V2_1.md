# G6b 三臂 Agent 盲测协议 v2.1 修订（delta）：作为 v2 的权威替换，正式轮使用「v2 + v2.1」作为同一份工具

> **本文件的地位。** 这是 `docs/G6B_THREE_ARM_PROTOCOL_V2.md`（v2）的**权威修订（delta）**。v2 仍是
> 基础正文；**正式轮把「v2 + v2.1」当作同一份工具使用**：v2.1 列出的条款**逐字替换/新增**对应位置，
> 未提及的 v2 条款继续有效；**两者冲突处以本文件为准**（冲突处 = 本文件 §1–§7 点名替换的每一句）。
> 本文件不含未在 v2 中定过位的条款：每一条都写明「替换 v2 的哪一节 / 哪一句」；本文件**不新增任务、
> 不新增分母、不新增指标**。
>
> **历史不可改。** `docs/G6B_THREE_ARM_PROTOCOL.md`（v1）、`docs/G6B_PILOT_REPORT.md`（pilot）、
> `docs/G6B_THREE_ARM_PROTOCOL_V2.md`（v2）、`docs/G6B_V2_SHORT_VERIFICATION.md`（短复验记录）
> **一律逐字节不动**。本文件是新文件，只改「正式轮从哪一版读条款」。
>
> **事实来源。** 本文件的每一条修订都来自**短复验三臂独立发现**（`docs/G6B_V2_SHORT_VERIFICATION.md`
> §4）与轮次产物归档 `D:/L/AI/figpact-archive/g6b-v2/`。短复验的数值仍是机制证据，**不是**能力/效率
> 结论（v2 文首「pilot 数据的用法」「短复验的数值用法」继续有效）。
>
> **本文件不改变短复验的裁定**：短复验通过四项通过条件，正式轮「条件性放行」；v2.1 就是那个条件。

---

## 0. 修订索引（七条，一节一对照；第二批 v2.2 见 §10）

| # | 修订项 | 性质 | **替换 v2 的位置** |
|---|---|---|---|
| 1 | 哈希与行尾基准（统一 `git -c core.autocrlf=false archive`；登记值双口径；「以执行时树内重算为准」的唯一含义） | 替换口径 + 新增双口径表 | §1.1「提取树生成」表行（:45）；§1.2 说明句与命令块（:50–54）；§1.3 表头重算句（:82）；§10 两行（:510、:511–512）；§4 第 1 条（:278–279） |
| 2 | 判据包签名的**唯一拼接命令**与登记要求 | 替换 + 新增 | §1.3「判据包签名」代码块（:97–100）；§10「判据包签名」行（:512）；§7 `criteria_signature` 行（:383） |
| 3 | §5.2 自检命令改为**会话级** | 替换 | §5.2 第 3 条（:322–323）；§8.1 第 4 条（:412）；§10「外部构建计数器」行（:519） |
| 4 | 硬约束 H4：`TEMP`/`MPLCONFIGDIR`/`state` 不得放在脚本目录内 | 新增 + 替换括注 | §4 第 3 条（:282–284）；§4 泄漏检查 (2)（:295）；§10「per-trial 目录 / state / 端口」行（:521）；§3.3 `discarded` 行（:264） |
| 5 | 路径基准 `I:/...` → `D:/L/AI/figpact-archive/` | 逐处替换 | 文首（:12）；§8.4 取证段（:454–457）；§8.4 进入条件 5（:478）；§10「A08 端点核对」行（:523） |
| 6 | token 与构建数口径（不可测则声明 M 未执行；构建数缺统一计数器则单臂记录、不比） | 替换 + 升级为正式轮默认状态 | §3.1「推理预算」行（:230）；§5.1 第 3 条（:310–311）；§5.2 末条（:324–325）；§8.2 第 2、6 条（:422–423、:429）；§10 三行（:515、:519、:520） |
| 7 | 人时单列口径（真人等待永远计入 `human_wall_clock_s`，不进 agent 侧） | 替换 + 冻结实例 | §5.4（:348–353）；§6.3（:367–372）；§7 时间字段行（:386）；§8.2 第 7 条（:430） |

**读法**：下文每一节 = 「替换位置」+「替换后文本（逐字）」+「依据」+「正式轮检查方式」。凡标
**「替换后文本」**的引文，正式轮的记录、报告、冻结清单**按该文本读**，不得沿用 v2 原句。

**第二批修订（v2.2）见 §10**：冻结 commit 重定（`f101113…`，替换 v2 §1.1 的 `12e751c…`；先由 `12e751c…` 重定为 `0bcf870…`，再**二次重定**为 `f101113…`，因作者化 Gate 到 `f101113` 才存在）、
提取命令唯一化（删 `worktree add` 备选）、科学输入 SHA-256 manifest 冻结、A16b 的 D1a 裁定待锁定；
§8 清单新增第 16–19 条对应之。

---

## 1. 哈希与行尾基准（替换 v2 §1.1、§1.2、§1.3、§4.1、§10 两行）

### 1.1 唯一提取基准（替换 v2 :45「提取树生成」行、§4.1 第 1 条、§10 :510 行）

**问题（短复验三臂一致）**：本机 `core.autocrlf=true` 且**工作树本身行尾混用**。`git archive` 默认
模式会把文本文件 CRLF 化，于是 §1.2 的三件夹具**没有任何单一 archive 模式能同时复现登记值**：
默认模式对 `08 NMR.py` / `nmr.yaml` 等于登记值、对 `simple_figure.py` 不等；`-c core.autocrlf=false`
（commit 原始字节）恰好相反。判据包 12 件同因：登记值 12/12 等于**工作树字节**，commit 字节只有
6/12 相同（其余 6 件仅行尾不同、内容一致）。

**替换后文本（v2 :45 行整行）**：

```text
| 提取树生成（**唯一**） | `git -c core.autocrlf=false archive --format=tar <commit> | tar -x -C <trial_root>/tree` | 每条 trial 一份（§4）；`-c core.autocrlf=false` 是**强制项**，缺它 = 提取树行尾不确定 = 该轮作废。**`<commit>` = §10.1 重定的新基线 `f101113476cf3f0113ccbb5e054d700d8c0a433a`**；`worktree add` 备选**已删除**（§10.2） |
```

- **命令写法纪律**：`-c` 必须置于子命令之前（`git -c core.autocrlf=false archive …`）。短复验记录里
  写作 `git archive -c core.autocrlf=false`（臂 V 的简写）；写成 `git archive -c …` 会被 `git archive`
  当作未知选项而失败，故正式轮一律以本节命令为准，简写不再出现。
- §4 第 1 条（:278–279）与 §10「提取树生成命令」行同样按本行读。
- **基线重定（§10.1）**：v2 §1.1 :42 行的统一 commit `12e751c…` **作废**，三臂改用
  `f101113476cf3f0113ccbb5e054d700d8c0a433a`（含 A16b 夹具 **与作者化写回 Gate**；
  `0bcf870…` 为一次重定、`f101113…` 为二次重定，理由见 §10.1）；`worktree add` 备选**删除**（§10.2）。

**依据**：短复验 §4.1、§4 处置 1；`D:/L/AI/figpact-archive/g6b-v2/armV-summary.md` §5.1；
`armL/harness-hashes-and-eol.md`、`armL/hashes-eol.md`；`criteria-lineending-table.txt`。

**正式轮检查**：三臂对同一夹具各算一次，**commit 字节口径逐题逐字相等**（§1.2 表第二列）。

### 1.2 夹具哈希：双口径登记 + 判等对象（替换 v2 :50–54 的说明句与命令块）

**替换后文本**：

> 下表登记**两种口径**：`worktree`（2026-10-13 工作树实测，= v2 §1.2 原登记值）与 `commit`
> （`git -c core.autocrlf=false archive` 提取所得，**正式轮的判等对象**）。冻结时**必须在提取树内
> 用本节命令重算**，并与 `commit` 列**逐字相等**；不等 = 提取树与冻结 commit 不一致，冻结清单未成立，
> **不得开跑**。`worktree` 列只作追溯，**不得**用作判等。
>
> **唯一命令（在 `<trial_root>/tree` 内执行，逐字记录）**：
>
> ```text
> sha256sum "<path>"
> ```
>
> **新基线复算（2026-10-13，`f101113476cf3f0113ccbb5e054d700d8c0a433a` 提取树内实测）**：下表
> `commit` 列的六个值已在 `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113/tree/` 内**逐格逐字复现，
> 无任何数值变更**（`worktree` 列同日亦 6/6 复现）。原因：六件夹具在 `0bcf870 → f101113` 之间**未被
> 改动**（该区间只改 `figpact/authoring.py`、`figpact/hub.py` 与 `docs/`/`tools/`/`tests/`）。
> 命令原文、三口径原始输出见
> `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113-freeze-values.md` §2。

| 夹具路径 | `worktree` 口径（v2 §1.2 原登记值） | `commit` 口径（**正式轮判等对象**） | 默认 archive（CRLF 化，仅追溯） |
|---|---|---|---|
| `examples/nmr/08 NMR.py` | `22728d695821abfe2ea695ff1767ed289e7f3feb746e7bfcda655290259462cf` | `0047841e22915b7a37eb81816bbd7b4f09d3ff97463b644c32f06d8b5ba9cc7a` | = `worktree` |
| `examples/nmr/nmr.yaml` | `84a40f0ee122a5a78ac6c0d6a452d6bed18cd2012a063cb26ecfe7a025b6b98b` | `e857ca5b76cdb40fbbde2689761a585756350e31f572222ca13f1462e158e6af` | = `worktree` |
| `examples/python_native/simple_figure.py` | `fe298676aa8277db9420c61483ede491fef16c0ef1a7ca53392f589e2642b663` | `fe298676aa8277db9420c61483ede491fef16c0ef1a7ca53392f589e2642b663` | `9cdf99f7974515f0ae431ccfda97131a1a20d2e200453a88eb3371e174dcf960` |
| `examples/ftir/plot_ftir.py` | `524b1c86d6a5018abb1f561f32e960f15a5f2fddde80ac6935d141ea14150362` | `fd29ea3ba2eb165c6722c936beb8ef401d13181f6b2724c01a3a8f1ffe7b827e` | = `worktree` |
| `examples/ftir/ftir.yaml` | `d6946d9286ffc3f9bdebf519006e6e437500c9158634aad641e81323fec03d49` | `50ce21b5c9847a2f23bf308d0bc1304e3050feee3230dd4c55d49db26c8e484c` | = `worktree` |
| **A16b 夹具** `examples/python_native/legacy_plain.py` | `dba9f6f95c3707e94403137f1844fa67c2806c74cea9dba3ababc8d0de88635b` | 同上（新增文件：工作树字节 = commit 字节；blob `d25d58136aa7cbc32b13e2c9d1c1d9f50439f252`；`grep -n LAYOUT_MM` 空输出） | `4763bc9a35e1fdf72de940ab502ed6d1110d40c52a24beec5f9eca12af56e51b` |

- **「以执行时树内重算为准」的唯一含义**（替换 v2 §1.3 :82 的表头重算句）：判等发生在**执行时**
  （冻结那一刻）的**提取树字节**上，且该树必须由 §1.1 的**唯一命令**生成；因此判等口径 ≡
  `commit` 列。v2 表格里的「登记值」列（= `worktree` 口径）**身份降级为追溯引用**，不再充当判等对象。
- **随附收编（短复验 §4.3、§4 处置 3）**：`examples/nmr/核磁原始数据` **未被 git 跟踪**，
  `git archive` 带不出来 → 三臂必须把它从工作树**只读复制**进各自的 NMR 提取树（本轮臂 V 复制 88 个
  文件）；复制动作发生在**夹具哈希核对之后**，且**不得**修改工作树或仓库。此项举记录进冻结清单。

**依据**：短复验 §1、§4.1、§4 处置 1、3；`armL/harness-hashes-and-eol.md`（逐件 `tree` / `tree_LF` /
登记值三列比对与 CR 字节数）；`armV-summary.md` §5.1、§5.2。

**正式轮检查**：逐 trial 记录 `fixture_hashes` 用 `commit` 口径；三臂同题逐字相等；A16b 已登记。

---

## 2. 判据包签名的唯一拼接命令（替换 v2 :100 代码块 与 §10 :512 行）

**问题（短复验三臂互不相等）**：同一个 commit 的判据包签名是三个值——臂 L
`f16105cdf96b8fd38cf38be52008ba4a56124b5e0dd1dd46df25e8d1d94e8a46`、臂 A
`1ededaec3a82e9021b56c9c4ae183999a83a62c63021ccecb08c5cd5aadd3e1e`、臂 V
`ef070f56047568cd99c71e3d55f3813599de9ac2932e78b6d5693dc473341200`。差异**只来自
archive 行尾模式 + 拼接方式**，内容一致。**统一口径前不得宣称「逐字相同」**。

**替换后文本（v2 :100 代码块整块）——判据包签名的唯一定义**：

> 判据包签名 = 「§1.3 表格 12 个路径，**按路径字节序升序**（`LC_ALL=C`），显式列在同一行、
> **不使用 glob**，`sha256sum` 的输出流（每行 `<hex><两个空格><path>\n`，UTF-8，
> LF 行尾）整体再做一次 `sha256sum`」。**行尾基准 = §1.1：文件取自
> `git -c core.autocrlf=false archive` 的提取树**（= commit 原始字节）。
>
> ```bash
> cd <trial_root>/tree
> LC_ALL=C sha256sum \
>   figpact/agent_api.py figpact/authoring.py figpact/geometry.py figpact/history.py \
>   figpact/hub.py figpact/inspector_server.py figpact/intents.py figpact/python_native.py \
>   figpact/qa.py figpact/science.py figpact/session.py figpact/source_writes.py \
>   | LC_ALL=C sha256sum
> ```
>
> 命令原文、12 个逐文件值（`commit` 口径）与签名值三项**必须一起**登记进正式轮冻结清单；
> 每条 trial 的 `criteria_signature`（§7）**必须逐字等于**冻结清单里的签名值。
> 拼接顺序与分隔符不许改动（含不加 `-z`、不加排序管道、不加路径前缀重写）。

**两口径记录（追溯用，不作判等）**：

| 口径 | 拼接签名值 | 来源 |
|---|---|---|
| `commit` 原始字节（= 正式轮判等口径；**已按新基线 `f101113` 树内重算，2026-10-13**） | `163b0df0852ff8f859e54d78c7d0941bfd5e39924e03ff97c09001e1012ffe5d` | `baseline-f101113/criteria-hashes-commit-bytes.txt` / `baseline-f101113-freeze-values.md` §4（旧基线值 `ef070f56…` 见 `criteria-hashes-commit-bytes.txt`，仅追溯） |
| `worktree` 字节（= v2 §1.3 原登记值口径，**仅追溯；当前工作树已前移故不再等价**） | `005fe9626019ec93b2e087066f57d957ada06c270b2cec443212faf31617c5e3` | `criteria-hashes-worktree.txt` / `armV.json` |

**新基线复算（2026-10-13，`f101113476cf3f0113ccbb5e054d700d8c0a433a` 提取树内实测）**：正式轮判等口径的
签名在新基线树内重算为 **`163b0df0…`（相对旧基线 `ef070f56…` 已变）**；12 个逐文件值中
`figpact/authoring.py`（`e0cf1239…` → `14530e52…`）与 `figpact/hub.py`（`b3b2ccca…` → `1028d743…`）**已变**，
其余 10 件**未变**。**原因（精确）**：`0bcf870 → f101113` 只改动判据包 12 件里的 2 件 ——
`git diff --name-status 0bcf870 f101113 -- figpact/` 输出 `M figpact/authoring.py`、`M figpact/hub.py`
（= 作者化写回 Gate 落地），其余 10 件零改动 → **签名必须变、实测已变**。
（上一轮：`12e751c → 0bcf870` 之间 `figpact/*.py` **零改动**，故当时签名**预期不变、实测亦不变** = `ef070f56…`；
该值现降级为旧基线追溯值。）`worktree` 口径登记值 `005fe962…` **不可在当前工作树复现**（现为
`60ef1206…`）：① 工作树行尾混用（12 件引擎文件中 6 件 CRLF、6 件 LF，而提取树 12/12 纯 LF）；
② HEAD = `f101113`，`authoring.py`/`hub.py` **内容已变**。该登记值已被复现为「**基线内容 +
当日工作树行尾混合**」，只作历史证据，**不作判等、不改动**。命令原文与原始输出见
`D:/L/AI/figpact-archive/g6b-v2/baseline-f101113-freeze-values.md` §4、§6；12 个逐文件值落盘
`D:/L/AI/figpact-archive/g6b-v2/baseline-f101113/criteria-hashes-commit-bytes.txt`（该文件整体再哈希 =
`163b0df0…`）。

**可复核性（本次实测，非推断）**：把已落盘的 12 行 `sha256sum` 输出流**逐字节**再 `sha256sum`，
新基线 `commit` 口径文件得到 `163b0df0…`、旧基线 `worktree` 口径文件得到 `005fe962…` —— 即本节命令的
**语义与两个登记值一致**，三臂 `f16105cd…` / `1ededaec…` / `ef070f56…` 的差异被完全定位为
「**提取模式 + 拼接方式**」，与文件内容无关。
（输入文件 = 新基线 `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113/criteria-hashes-commit-bytes.txt`
与旧基线 `D:/L/AI/figpact-archive/g6b-v2/criteria-hashes-worktree.txt`，均为 ASCII/LF、**无表头、12 行**，
路径恰好是本节命令里的字节序升序。）

**正式轮检查**：三臂各算一次该命令 → 签名**逐字相等**；不等 = 该轮不进正式轮（替换 v2 :512
「待冻结时算出并逐字记录」的状态描述）。短复验的 `f16105cd…` / `1ededaec…` / `ef070f56…` 三个值
（连同 `005fe962…`）**只作历史证据**，任何一个都**不得**直接充当正式轮登记值。

**依据**：短复验 §4.2、§4 处置 2；`criteria-lineending-table.txt` 末行；`armV-summary.md` §5.5。

---

## 3. §5.2 自检命令改为**会话级**（替换 v2 :322–323 第 3 条、§8.1 :412、§10 :519）

**问题**：v2 §5.2 建议的自检命令（「直接执行 `simple_figure.py`，或 `figpact render`」）**不产生计数
行**——这些路径由**脚本自身/子进程**建图，从不构造 `FigureSession`，被包装的
`FigureSession._call_builder` 恒不被调用。计数 0 行**不得**读作「没有构建」。

**替换后文本（v2 §5.2 第 3 条整条）**：

> - **自检必须是会话级命令**：命令必须构造 `FigureSession` / `IntentSession` 并至少触发一次真实
>   整图构建，即计数器所包装的 `FigureSession._call_builder` 真的被调用。**会话构造本身就会构建**
>   （`_capture_baseline()` → `_call_builder`），故任何「起一个会话」的命令都是合格自检。
> - **否证（逐字保留为纪律）**：直接执行夹具脚本、`figpact render` / `export` / `validate` / `try`
>   以及任何「把脚本当子进程跑」的路径**都不产生计数行**；0 行**不得**读作「没有构建」，也不得据此
>   把该臂的 `real_figure_builds` 记 0。
> - **唯一自检命令（模板，臂 V 已实测留证）**：
>
>   ```bash
>   cd <trial_root>/tree
>   FIGPACT_TRIAL_TREE=$PWD \
>   PYTHONPATH=<harness> FIGPACT_BUILD_COUNTER=<trial_root>/out/builds-probe.txt \
>   TEMP=<trial_root>/tmp TMP=<trial_root>/tmp TMPDIR=<trial_root>/tmp \
>   MPLCONFIGDIR=<trial_root>/mpl PYTHONDONTWRITEBYTECODE=1 \
>   python -B -X utf8 <harness>/measure.py \
>     examples/python_native/simple_figure.py <empty-config.yaml> \
>     examples/python_native/simple_figure.py <empty-config.yaml> \
>     intent 120 intent.main.label.A
>   ```
>
>   期望：计数器文件**新增 4 行**（同一夹具自比的基线 + 候选两次会话构建）。`<empty-config.yaml>`
>   内容为 `{}`。
> - **等价备选（同口径，正式轮任选其一，但三臂必须用同一条）**：仓库入口的会话命令——
>
>   ```bash
>   cd <trial_root>/tree
>   printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"snapshot","params":{}}' | \
>     PYTHONPATH=<harness> FIGPACT_BUILD_COUNTER=<trial_root>/out/builds-probe.txt \
>     TEMP=<trial_root>/tmp TMP=<trial_root>/tmp TMPDIR=<trial_root>/tmp \
>     MPLCONFIGDIR=<trial_root>/mpl PYTHONDONTWRITEBYTECODE=1 \
>     python -B -X utf8 -m figpact agent --script examples/python_native/simple_figure.py \
>       --config <empty-config.yaml> --scope intent
>   ```
>
>   期望：**≥1 行**（会话构造即采基线）。
> - **留证**：命令原文 + 自检件路径 + 新增行数基线三项一起登记（正式轮冻结清单「外部构建计数器」行）。
> - **占位符定义**：`<harness>` = v2 §5.2/§8.1(7) 要求的**轮次 harness 目录**（内含 `sitecustomize.py`
>   计数器；`measure.py` = §5.3 的独立重建取数脚本）。`<trial_root>` 见 v2 §4/§10。

- §8.1 第 4 条（:412）随之读作：「§5.2 的**会话级自检命令**执行通过，且**每一条三臂可量的命令**都
  产出计数行」。
- §10 :519 行状态由「待冻结时自检」改为「**待冻结时按 §5.2 会话级命令自检并登记命令原文**」。

**依据**：短复验 §4.3、§4 处置 3；`armV.json` `environment_findings[2]`；
自检件 `D:/L/AI/figpact-archive/g6b-v2/trials/A16a/out/probe/builds-probe.txt`（4 行）；
`harness/sitecustomize.py`（包装对象 = `figpact.session.FigureSession._call_builder`）。

---

## 4. 硬约束 H4：`TEMP` / `MPLCONFIGDIR` / `state` **不得**放在脚本目录内（新增；替换 v2 :282–284 括注、§4 泄漏检查 (2) :295）

**引擎原因（正式事实，不是经验总结）**：`figpact/session.py` 的 `script_fingerprint()` 以
`script.parent.rglob('*')` 把**脚本目录整树**的每个文件按 `size:mtime_ns` 计入源指纹（仅排除
`__pycache__` / `.pyc` 与声明为产物的路径）；`FigureSession._sync()` 在每次候选操作前比对
`module_revision`，一旦不等就 `_reload()` **整会话重载**。把 `TEMP` / `MPLCONFIGDIR` / `state`
放进脚本目录 → 每次建图都在脚本目录里写文件、改 mtime → 指纹在 `try_layout → commit` 之间变化 →
候选被**静默重载丢弃** → `NO_CANDIDATE`（不报错、不提示、不落盘）。

**替换后文本（v2 §4 第 3 条整条）**：

> 3. **独立状态目录（硬约束 H4）**：`FIGPACT_STATE_HOME=<trial_root>/state`、
>    `TEMP=TMP=TMPDIR=<trial_root>/tmp`、`MPLCONFIGDIR=<trial_root>/mpl`、
>    `PYTHONDONTWRITEBYTECODE=1`。
>    **H4：上述任一路径（含 `state` 下的 `history/`、journal、blob 子目录）不得与该 trial 的绘图脚本
>    所在目录相同或位于其下**（即不得落入 `script_fingerprint()` 的 `rglob` 覆盖范围）；隔离目录一律
>    放 `<trial_root>/{tmp,mpl,state}`，脚本目录是 `<trial_root>/tree/examples/...`。
>    **违反后果**：候选在 `try_layout → commit` 之间被 `_sync()` 静默重载丢弃（`NO_CANDIDATE`），
>    该 trial 作废重跑并须写明原因（§3.3 `discarded`）。
>    另注：`FIGPACT_STATE_HOME` 放在脚本目录下还会被 history 合法拒绝（v2 原句保留为次级理由）。

- §4 泄漏检查第 (2) 项（:295）改为：`ls <trial_root>/state` **＋目录布局核对**（`<trial_root>/tmp`、
  `mpl`、`state` 均不在 `<trial_root>/tree` 下）——两项都留证。
- §10 :521 行改读作：`<trial_root>/{tree,tmp,mpl,state,out}`，**`tmp`/`mpl`/`state` 不得在 `tree/` 内**。
- §3.3 的 `discarded` 语义（:264）与 §2.5（`structural_unsupported` 的定义）**不变**：H4 违反
  产生的作废**不是**结果类型，只走 `discarded` 并计进「报告的分母完整性表」。

**依据（留档）**：短复验 §4 引擎发现与处置 4；臂 A 的 A09 首次 pass 因此作废，原档
`D:/L/AI/figpact-archive/g6b-v2/armA/attempt0-A09/raw.json`（臂 A 记录 `records_extra.discarded`）。

**正式轮检查**：逐 trial 核对目录布局（泄漏检查 (2)）；轮次日志中不得再出现 A09 类静默 `NO_CANDIDATE`。

---

## 5. 路径基准：`I:/...` → `D:/L/AI/figpact-archive/`（逐处替换）

**环境事实**：本机 `I:` 盘**已不存在**（只剩 `C:` / `D:`）。归档根**唯一**为
`D:/L/AI/figpact-archive/<轮次>/`（短复验 = `g6b-v2`）。

| v2 位置 | 原文 | 替换后文本 |
|---|---|---|
| 文首「pilot 数据的用法」（:12） | `I:/figpact-test-archive/g6b-pilot/` | `D:/L/AI/figpact-archive/g6b-pilot/`（**本环境不存在**；pilot 原始 JSON **不可达**） |
| §8.4 取证段（:454） | 「因为核对当时 `I:` 盘不可用，**逐字节复核尚未做**」 | 「`I:` 盘**永久不可用**（非临时）；原件逐字节复核**不可执行**，引用一律以转录件为限」 |
| §8.4 取证段（:456–457） | 「文件当前暂存 `local://…` 与 `C:/tmp/recon/…`；`I:` 挂回后落位为 `I:/…/A08-endpoint-reconciliation.md`」 | 「核对件**已落位** `D:/L/AI/figpact-archive/g6b-v2/A08-endpoint-reconciliation.md`；不再有 `I:` 落位动作」 |
| §8.4 进入条件 5（:478） | 「**`I:` 盘恢复后**：按核对件 §0 的表格对 `armL/armV/armA.json` 与三份 `*-summary.md` 做逐字节复核」 | 「**原件不可达条件下的替代核对**：复核对象 = 核对件 §0 列出的转录件（pilot 会话 `G6bArm*.jsonl` 的 write payload）；状态必须如实登记为『**原件不可达 + 转录口径**』，**不得**声称已对 pilot 原始 JSON 做逐字节复核」 |
| §10「A08 端点核对」行（:523） | 「已引用；**待 `I:` 恢复后逐字节复核**（§8.4 条件 5）」 | 「已引用；**原件不可达**，按 §8.4 条件 5 的替代核对口径登记」 |

- **全局措辞纪律（新增）**：任何记录/报告提到 pilot 产物路径时一律写
  `D:/L/AI/figpact-archive/g6b-pilot/…`（并注明不可达）；**不得**再出现 `I:/...`，也不得声称
  「已重读 pilot 原始 JSON」。pilot 数值引用只能来自 `docs/G6B_PILOT_REPORT.md` 内的已记录数值。

**依据**：短复验 §1「归档根变更的后果」共 4 条、§6「未复核」；核对件
`D:/L/AI/figpact-archive/g6b-v2/A08-endpoint-reconciliation.md` §0。

---

## 6. token 与构建数口径（替换 v2 :230、:310–311、:324–325；收紧 §8.2 :422–423、:429）

### 6.1 token：正式轮**沿用「不可测」**，M 声明为未执行（替换 v2 §5.1 第 3 条）

**替换后文本（v2 :310–311 整条）**：

> - **测不到 → 该臂 token 记「不可测」并写明原因**；此时输出 token 上限 **M=40k 降级为「未执行」**，
>   并在**轮次记录**里逐字声明：**「本轮 token 上限 M=40k 未被验证执行」**。**不得**填 0、**不得**
>   填估计值、**不得**用 `null` 冒充 0。
>   **正式轮默认状态 = 不可测**（短复验三臂全线不可测，无 usage 通道）：只有在冻结时用 §3.4 的
>   最小调用**实测到** usage 通道，才允许把 M 恢复为约束；恢复时必须三臂同通道、同字段，并在冻结
>   清单登记原始回执位置。**短期不可测 → 长期不可测的降级声明必须写进轮次记录，不得只写在摘要里。**

- v2 §3.1「推理预算」行（:230）随之读作：`N=30` 与 `T=20 min` 是**可执行**约束；`M=40k` 按 §5.1
  的**实测结果**决定是否为约束（正式轮默认 = 未执行）。
- §8.2 第 2 条（:422–423）保留，并加一句：降级声明**逐字**出现于轮次记录，措辞以上句为准。

### 6.2 构建数：能注入统一计数器才比较，否则单臂记录、不比（替换 v2 §5.2 末条）

**替换后文本（v2 :324–325 整条）**：

> - **跨臂比较的充要前提 = 三臂可量且口径同一**（都经 `FigureSession._call_builder`、都用 §5.2 的
>   `sitecustomize` + `FIGPACT_BUILD_COUNTER` 注入）。只有**三臂都能产出计数行**时才做跨臂构建数比较；
>   任一臂不可量 → 该指标记「不可测」，**禁止**跨臂比较。
> - **不得混口径**：只能给对象级/脚本级计数的臂（如包装 `matplotlib.figure.Figure.__init__` 的
>   自建计数器）必须**在记录里标明包装对象**，其值与另一臂的 `_call_builder` 行数**不得相减、
>   求平均、并表或折算**（与 §5.3 的「端点量 vs bbox 中心量」同一条纪律）。
> - **单臂记录仍是必填**：不可比时逐臂给出原始行数与命令原文，写明「单臂记录，不作跨臂比较」。
>   （短复验即此状态：臂 A 12/12/10/4、臂 L 5/5/2/2 行，**未**做跨臂比较。）

- §8.2 第 6 条（:429）保留原文，并加：报告必须逐字写「单臂记录，不作跨臂比较」。
- §10 三行：`预算 N / M / T`（:515）按 §6.1 读；`外部构建计数器`（:519）按 §3 与本节读；
  `token 通道`（:520）状态改为「短复验实测：**不可测** → 正式轮按不可测登记并声明 M 未执行」。

**依据**：短复验 §3 第 4 条（有保留：token 全线不可测、构建数仅单臂）、§6；臂 L 的
`counter_B_declared_extension`（`armL.json`）；`armV-summary.md` §5.6。

---

## 7. 人时单列口径（替换 v2 §5.4 末句、§6.3、§7 字段行、§8.2 第 7 条）

**替换后文本（v2 §5.4 末句，:352–353 段末）**：

> 三臂**只要有任何真人参与的时刻**（A16a 的选区点选与授权铸造、A13 类方案请示等），该时长**永远**
> 落在 `human_wall_clock_s`：**不进** `agent_wall_clock_s`、**不进** `total_wall_clock_s` 的 agent 侧
> 汇总口径、**不进** D2 的完成时间。**冻结实例（正式轮的读数基准）**：本轮 A16a 臂 V 的真人授权等待
> = **39.977 s**（`D:/L/AI/figpact-archive/g6b-v2/armV.json`，A16a 记录），pilot 臂 V A16 的 60.0 s
> 继续作为历史实例保留，两例均**不得**被解释为 Agent 计算慢。

- §6.3（:367–372）保持不变，仅补一句：`human_wall_clock_s` 与 `human_actions` 一样**单列**，
  臂间**不得**据此比较「谁更强/更快」。
- §7 字段行（`started_at / finished_at / agent_wall_clock_s / human_wall_clock_s /
  total_wall_clock_s`）改为：五个字段**逐条必填**；`total_wall_clock_s` 的构成必须**显式写出**
  （agent + human + 其它），不得只给总数。
- §8.2 第 7 条（:430）保留原文，并把 A16a 的 **39.977 s** 作为该条的**期望样例**写入轮次记录。

**依据**：短复验 §1「补充事实」第 2 条、§3 第 4 条、§6；§4 处置表未涉及该项，v2 自身表述已对，
本修订只做**不可绕过化**与实例冻结。

---

## 8. 正式轮进入条件合并清单（**v2 §8 + 本文件 v2.1**）

**顺序**：先满足 v2 §8.2 的 12 条（短复验已全通过，见 `docs/G6B_V2_SHORT_VERIFICATION.md` §3，逐字节不动）
→ 再逐条满足下表 → 才开跑正式轮。任一条未勾选 = **不得开跑**。

| # | 条件 | 来源 | 状态 |
|---|---|---|---|
| 1 | 短复验四项通过条件成立、12 trial 0 丢弃、四项证据可复核 | v2 §8.2（1–12） | ✅ 已完成 |
| 2 | 正式轮题目清单冻结：≥10 条配对，四层均有代表，**必含 A16a 与 A16b**，D2 题数 ≥8 | v2 §8.3 | 待做 |
| 3 | **A16b 夹具**已提交并登记 `sha256sum`（含「无 `LAYOUT_MM`」的空输出证据） | v2 §1.2、§8.3 | 已落地：`examples/python_native/legacy_plain.py`，sha256 `dba9f6f9…635b`、`grep -n LAYOUT_MM` 空输出、`plan_layout_edit → NEEDS_AUTHORING`（零写入）、`build_repair_spec` schema 对齐；**须落在 §10.1 新基线内**（该文件首次进仓库于 `0bcf870`） |
| 4 | 三臂用 **同一 commit + §1.1 唯一提取命令**（`git -c core.autocrlf=false archive`）各建提取树；commit = **§10.1 的 `f101113476cf3f0113ccbb5e054d700d8c0a433a`** | v2 §1.1 + **v2.1 §1.1、§10.1、§10.2** | 待做 |
| 5 | 夹具哈希按 **`commit` 口径**在树内重算并逐字相等；`worktree` 口径同时登记 | v2 §1.2 + **v2.1 §1.2** | 待做 |
| 6 | 判据包 12 值（`commit` 口径）+ **§2 唯一拼接命令的原文** + 签名值三件一起登记进冻结清单；每条 trial 的 `criteria_signature` 等于登记值 | v2 §1.3 + **v2.1 §2** | 待做 |
| 7 | §3.4 模型逐字记录 + 可用性证据；**token 通道按 §6.1 实测**（默认结论「不可测」也须有回执） | v2 §3.4、§5.1 + **v2.1 §6.1** | 待做 |
| 8 | **会话级**构建计数器自检通过并登记命令原文与行数基线；三臂用同一条自检命令 | v2 §5.2、§8.1(4) + **v2.1 §3** | 待做 |
| 9 | **H4 目录布局**：逐 trial `tmp`/`mpl`/`state` 均在 `tree/` 之外；泄漏检查 (2) 含布局核对 | v2 §4 + **v2.1 §4** | 待做 |
| 10 | **路径基准**：冻结清单、题面、记录里 `I:/...` 全部改写为 `D:/L/AI/figpact-archive/...` 并注明不可达 | v2 文首、§8.4、§10 + **v2.1 §5** | 待做 |
| 11 | §1.4 白名单存在性核对完成（缺失项已删或标「不可用」）；§2.4 的 D1a 16 行裁定冻结 | v2 §1.4、§2.4、§8.3 | 待做 |
| 12 | §8.4 的 7 条进入条件落地；条件 5 按 **v2.1 §5** 的替代口径（原件不可达 + 转录口径）登记 | v2 §8.4 + **v2.1 §5** | 待做 |
| 13 | 预算/模型/判据签名/D1a 裁定/题目清单**在轮次期内冻结**；需改 = 整轮作废重跑 | v2 §8.3、§9 红线 13 | 待做 |
| 14 | 人时口径落地：`human_wall_clock_s` 单列、A16a 真人等待计入人侧 | v2 §5.4、§6.3 + **v2.1 §7** | 待做 |
| 15 | 作废条件写明并可执行：判据放宽 / 模型或预算不一致 / 隔离破坏 / 冻结项事后修改 → 整轮作废 | v2 §8.3、§9 | 待做 |
| 16 | **冻结 commit 重定**：三臂统一基线 = `f101113476cf3f0113ccbb5e054d700d8c0a433a`（含 A16b 夹具 **与作者化写回 Gate**；由 `0bcf870…` 二次重定，理由见 §10.1）；六件夹具哈希与判据包签名在**该基线提取树内重算**；禁止「旧 commit 提取 + 手工补文件」 | **v2.1 §10.1** | 已重算并登记（`f101113` 树内值见 `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113-freeze-values.md`）；判据包签名已变（`ef070f56…` → `163b0df0…`，因 `authoring.py`/`hub.py` 改动），六件夹具值未变 |
| 17 | **提取命令唯一化**：只用 `git -c core.autocrlf=false archive`；`worktree add` 备选删除 | **v2.1 §1.1、§10.2** | 文本已定（命令唯一化已落文）；执行待做 |
| 18 | **科学输入冻结**：NMR 未跟踪原始科学文件建 SHA-256 manifest（relpath/size/sha256），三臂复制后逐文件校验一致 | **v2.1 §10.3** | 待做（manifest 由独立单元产出，路径见 §10.3） |
| 19 | **A16b 的 D1a 裁定**：作者化写回 Gate 完成后锁定 | **v2.1 §10.4** | **已锁定**：Gate 已落地（`authoring.plan_authoring_binding` + hub `kind="authoring_edit"`，authorize/apply 复用同一校验链，测试 7 用例 + 3 subTest 通过）→ **臂 V 路径存在**；臂 L（无授权写回）与臂 A（白名单无源码写回入口）为 `structural_unsupported`。**且 Gate 已在冻结基线 `f101113…` 内**（`f101113` 提取树内 `grep` 命中 `figpact/authoring.py:550`、`figpact/hub.py:51`；理由见 §10.1，证据见 `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113-freeze-values.md` §3），故该「已锁定」在冻结基线下证据成立。正式轮按此裁定记录，不得临时扩大任何臂的写权限 |

---

## 9. 本文件未改、未定义、未宣称

- **未改任何其它文件**：v1 / pilot / v2 / 短复验记录逐字节不动；本文件是新增文件。
- **未新增条款**：§1–§7 全部是 v2 已有位置的**替换或收紧**（H4 是把 v2 §4 第 3 条的括注升级为
  硬约束并附引擎原因；无新指标、无新分母、无新任务）。**唯一的新增条款节 = §10**（基线重定、
  提取命令唯一化、科学输入冻结、A16b 裁定待锁定），同样不新增任务/分母/指标。
- **未宣称**：不对三臂做能力/效率结论；不用短复验数值做臂间胜负；不声称已对 `I:` 上的 pilot 原件
  做逐字节复核；不声称 token 已可测；不声称构建数已可跨臂比较。
- **未定义项**：本文件不引入任何 v2 未出现过的术语；`discarded` / `structural_unsupported` /
  `correct_refusal` / `mis_accept` / `mis_refusal` 全部沿用 v2 §3.3 的既有枚举。

---

## 10. v2.2 补充（基线重定 + 科学输入冻结）

**地位**：本节是 v2.1 相对 v2 的**第二批修订**（按用户裁定 2026-10-13 第 1–4 条落地）。以下四条
**逐字替换/新增**对应位置；与 §1–§9 或 v2 冲突处以本节为准。本节只改「正式轮用哪个基线、怎么提取、
科学输入怎么冻结、A16b 裁定何时锁」，**不新增任务、不新增分母、不新增指标**。

### 10.1 冻结 commit 重定（替换 v2 §1.1 :42「三臂统一引擎 commit」行与 :509 行）

**问题**：v2 §1.1 把三臂统一 commit 固定为 `12e751cdeab699078a4f5a1835ca41f28af27b3b`，但
**A16b 夹具 `examples/python_native/legacy_plain.py` 直到 `0bcf870` 才首次进仓库** → 严格按
「v2 + v2.1」执行会出现「A16b 必须在场、但冻结树里没有该文件」的矛盾。

**二次重定理由（2026-10-13 用户裁定）**：A16b 的 D1a 裁定（§10.4 / §8 第 19 条）依赖
**作者化写回 Gate**（`authoring.plan_authoring_binding` + hub `kind="authoring_edit"`），而该 Gate
**到 `f101113` 才落地**（`0bcf870` 树内 `grep -rn "plan_authoring_binding" figpact/` 与
`grep -rn "authoring_edit" figpact/` **均空输出**）→ 若冻结在 `0bcf870`，臂 V 的 A16b 完整路径在冻结树内
**不存在**。故按 v2.1 §10.1 允许的「冻结时的明确后续提交」把基线由 `0bcf870…` **二次重定**为 `f101113…`。

**替换后文本（v2 §1.1 :42 行整行）**：

```text
| **三臂统一引擎 commit（v2.2 重定）** | `f101113476cf3f0113ccbb5e054d700d8c0a433a` | 含 A16b 夹具 `examples/python_native/legacy_plain.py` **与作者化写回 Gate**；冻结时若改用明确后续提交，须在冻结清单登记**同一提交全值**且三臂一致 |
```

- **旧值作废**：`12e751cdeab699078a4f5a1835ca41f28af27b3b` 不再作为三臂统一基线；任何臂**不得**
  混用 `12e751c` 或其派生树。v2 §1.1 :509 行（§10 表「三臂统一引擎 commit」）与 v2 §1.1 其余
  引用同样按本行读。`0bcf870…` 为**一次重定（已被本行二次重定取代）**，仅作历史记录。
- **三臂全部使用同一新基线**：`f101113476cf3f0113ccbb5e054d700d8c0a433a`（或冻结时登记的**明确
  后续提交全值**）。
- **六件夹具哈希（§1.2 表）与判据包签名（§2）必须在该新基线的提取树内重算**，重算值登记进
  冻结清单并**逐字**充当判等对象。**重算已完成（2026-10-13，`f101113` 提取树内实测）**：六件夹具
  `commit` 值**未变**；判据包签名由 `ef070f56…` **变为 `163b0df0…`**（`authoring.py`/`hub.py` 改动所致）。
  命令原文、原始输出与两基线对比见 `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113-freeze-values.md`；
  登记文件 `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113/criteria-hashes-commit-bytes.txt`。
- **禁止**：从旧 commit（如 `12e751c`）提取树、再手工补入 `legacy_plain.py` 等文件，却仍声称
  「三臂同一冻结 commit」——该做法判为冻结清单未成立，**不得开跑**。
- **依据**：用户裁定（2026-10-13）第 1 条 + 二次重定裁定；A16b 夹具首次进仓库于 `0bcf870`，
  作者化写回 Gate 首次进仓库于 `f101113`。

### 10.2 提取命令唯一化：删除 `worktree add` 备选（替换 §1.1 表行与其括注）

**替换后文本**：§1.1 的提取命令**唯一**为

```text
git -c core.autocrlf=false archive --format=tar <commit> | tar -x -C <trial_root>/tree
```

- `git -c core.autocrlf=false worktree add --detach <trial_root>/wt <commit>` **备选已删除**，
  正式轮任何位置不得出现。
- **理由**：`worktree add` 走检出路径，会重新施加检出过滤规则（本机 `core.autocrlf=true`），
  **重新引入行尾差异** → 与 §1.2 的 `commit` 口径判等冲突。
- **写法纪律不变**：`-c` 必须置于子命令之前；不得写作 `git archive -c core.autocrlf=false`。
- 三臂提取树**只能**由本命令生成；其它路径生成的树不得用于判等。

### 10.3 科学输入冻结：未跟踪原始科学文件必须建 SHA-256 manifest（新增进入条件）

**问题**：NMR 例子的原始科学文件（`examples/nmr/` 下未被 git 跟踪者）**未被 git 跟踪**，
`git archive` 带不出来。§1.2「随附收编」只写「从工作树只读复制」**不足以**冻结科学输入——必须有
**逐文件哈希证据**，不得只靠「复制自同一目录」的文字声明。

**要求**：

- 为这批文件建立 **SHA-256 manifest**，逐文件登记 **相对路径（relpath）/ 大小（字节）/ SHA-256**。
- **manifest 路径**：`D:/L/AI/figpact-archive/g6b-v2/nmr-science-manifest.json`（由独立单元产出，
  本文件只引用该路径）。
- **manifest 格式**：JSON，`files` 为按 relpath 排序的数组，每项 `{relpath, size, sha256}`
  （relpath 相对 `--root`、POSIX 分隔符；size 字节；sha256 小写 hex）；另有
  `file_count` / `total_bytes` / `root` / `algorithm` / `chunk_bytes` / `include_untracked_only` /
  `skip_dirs` / **`ignored_relpaths`**（建表时被 git 跟踪而排除的 5 个路径：
  `08 NMR.py` / `NMR_generate_all.py` / `figure_style.py` / `nmr.yaml` / `SKILL.md`）；**无时间戳**，
  同树重建字节一致。
- **范围（口径）**：`examples/nmr/` 下**全部未被 git 跟踪**且未被忽略规则排除的文件，排除
  `.git/` 与 `__pycache__/` —— 即 88 个 `核磁原始数据/` 仪器文件 + 11 个 `Fig2_*/Fig_S*` 导出图件，
  合计 **99 个文件 / 4,278,572 字节**；被 git 跟踪的 5 个源文件（`08 NMR.py` / `NMR_generate_all.py` /
  `figure_style.py` / `nmr.yaml` / `SKILL.md`）**不在内**（它们走 §1.2 夹具哈希），2 个
  `__pycache__/*.pyc` 被剪枝排除（非科学输入，各臂会重新生成，纳入会假失败）。
- **校验命令（工具：`D:/L/AI/figpact/tools/science_manifest.py`，stdlib 无第三方包）**：

  ```bash
  python tools/science_manifest.py --verify \
    D:/L/AI/figpact-archive/g6b-v2/nmr-science-manifest.json \
    --root <该臂的 examples/nmr 副本>
  ```

  任何缺失 / 多出 / size 或内容不同 → 退出码 1；退出码 **0 = 一致、2 = 用法或 IO 错**。
  **verify 端不需要 git、也不要求副本处于仓库内**（排除规则已固化进 manifest，校验只按 relpath 比对），
  故三臂把科学输入拷到任意目录（worktree 或裸目录）都能直接跑；`--root` 省略时用 manifest 里记录的
  原始根；**relpath 是身份**，故副本换绝对路径仍可校验。
- **判等**：三臂把该集合只读复制进各自 NMR 提取树后，**逐文件 SHA-256 必须与 manifest 一致**；
  任一处不一致 = 科学输入未冻结，**不得开跑**。若各臂会在自己树里重跑出图（`Fig2_*` / `Fig_S*`
  是示例**产物**而非输入），则对**拷贝那一刻**的树校验，或只校验 `核磁原始数据/` 子树。
- 复制动作发生在**夹具哈希核对之后**，且不得修改工作树或仓库（§1.2 随附收编不变）。

### 10.4 A16b 的 D1a 裁定：**待作者化写回 Gate 完成后锁定**

- **状态：已锁定（Gate 已落地）**——`authoring.plan_authoring_binding` + hub `kind="authoring_edit"` 已实现并通过测试（7 用例 + 3 subTest），authorize/apply 复用同一校验链。**且 Gate 现已在冻结基线内**：`f101113` 提取树内 `grep -rn "plan_authoring_binding" figpact/` 与 `grep -rn "authoring_edit" figpact/` 均命中（`figpact/authoring.py:550`、`figpact/hub.py:51`），故本条的「已锁定」在新基线 `f101113…` 下证据成立（证据见 `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113-freeze-values.md` §3）。
- **能力边界结论**：臂 V 具备 A16b 的完整路径（提案 → 计划 → 页面授权 → 写入 → 独立重建验证 → history）；臂 L 无授权写回、臂 A 白名单无源码写回入口 → 两者在 D1a 记 `structural_unsupported`。正式轮不得临时扩大任何臂的写权限。
- **当前能力边界（实测，Gate 已落地后）**：`hub.create_plan()` 支持 `kind="layout_edit"`（`LAYOUT_MM` 绑定，经 `python_native.plan_layout_edit`）与 **`kind="authoring_edit"`**（无绑定脚本的最小显式绑定补丁，经 `authoring.plan_authoring_binding`，journal 由 `source_writes` 管理）；两者的 authorize/apply/cancel 复用同一校验链。当目标无
  `LAYOUT_MM` 时返回 **`NEEDS_AUTHORING`**，**不铸造计划**（零写入）。
- 因此 A16b 的 D1a 判据（`correct_refusal` / `mis_accept` / `mis_refusal` 的归类）在 Gate 完成前
  **不得写入冻结清单**；Gate 完成后按 v2 §2.4 的 16 行裁定口径锁定，并在冻结清单登记锁定时刻与证据。
- **已落地证据（§8 第 3 条）**：`examples/python_native/legacy_plain.py` 无 `LAYOUT_MM`
  （`grep -n LAYOUT_MM` 空输出）、`plan_layout_edit → NEEDS_AUTHORING`（零写入）、
  `build_repair_spec` schema 对齐。

### 10.5 对 §1–§9 的影响

- §1.1 表行的 `worktree add` 括注**已删**（§10.2）；`<commit>` 占位符 = §10.1 的新基线。
- **基线已重定（影响清单）**：冻结 commit 由 `0bcf870…` **二次重定**为 `f101113476cf3f0113ccbb5e054d700d8c0a433a`（§10.1），因为 A16b 的 D1a 裁定（§10.4 / §8 第 19 条）所需的作者化写回 Gate 到 `f101113` 才存在。受影响的登记值：**判据包签名 `ef070f56…` → `163b0df0…`**、逐文件 `authoring.py` 与 `hub.py` 两值；**不受影响**：§1.2 六件夹具 `commit` 值（未变）、判据包其余 10 个逐文件值（未变）。`§10.4`/`§8 第 19 条` 的「已锁定」在新基线下保持有效（§10.4）。
- §1.2 六件夹具哈希与 §2 判据包签名：**已在 `f101113` 新基线内重算完成**（六件夹具值未变；判据签名变为 `163b0df0…`），登记值见 `D:/L/AI/figpact-archive/g6b-v2/baseline-f101113-freeze-values.md`。
- §8 清单新增第 16–19 条（对应本节四条）。
- §9「未新增条款」：§10 是本文件唯一的新增条款节。
