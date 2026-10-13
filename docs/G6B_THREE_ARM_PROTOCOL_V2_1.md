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

**登记节（第三批）见 §12**：Hub 的 `COMMITTED_AND_VERIFIED` **只**证源码写入（journal + 逐字节比较），
**不含**目标位移/科学内容验证；正式轮**独立判分器必须自建重建**，`completed` 只由自建结果判定，
**A16b、A17 不得**把该返回值计为科学验证通过；产品层「拆分 `source_commit_state` /
`figure_verification_state`（或成功返回前接入独立验证）」待开票，**本轮不改 `f101113`**；
科学输入 **99 = 88 原始仪器数据 + 11 导出图件**；受试代码固定 `f101113`、证据可来自后续提交。

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
  **口径更正**：88 是**仪器数据子集**（短复验当时实际复制的量），**不是**正式轮的科学输入全集；
  正式轮全集 = **99 件 = 88 件原始仪器数据 + 11 件导出图件**（§10.3、§12.5）。

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
>     main 120 intent.main.label.A
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
>       --config <empty-config.yaml> --scope main
>   ```
>
>   期望：**≥1 行**（会话构造即采基线）。
> - **留证**：命令原文 + 自检件路径 + 新增行数基线三项一起登记（正式轮冻结清单「外部构建计数器」行）。
> - **自检不看退出码**：`figpact agent` 出错时**仍返 exit 0**，故自检**必须同时判回执内容与新增计数行数**，
>   任一项不符即视为自检未通过。实测（逐字模板运行，预检 §3.2）：作用域写成 `intent` 时
>   `exit=0`、计数 0 行、回执为
>   `{"jsonrpc":"2.0","id":1,"error":{"code":-32006,"message":"SessionError: 未知 scope：'intent'；脚本声明的作用域是 ['main']"}}`
>   —— 即 **0 行 + error 回执 = 失败**，不是「会话建成」。故本模板的作用域名一律取夹具声明值
>   `main`（`simple_figure.py` 的 `FIGURE_ID = "intent"`、`SCOPE = "main"`；`intent` 只是 figure id）。
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
| 11 | §1.4 白名单存在性核对完成（缺失项已删或标「不可用」）；§2.4 的 D1a 16 行裁定冻结 | v2 §1.4、§2.4、§8.3 | **裁定已定稿**（矩阵 = v2.1 §11.1.1，16 行 × 3 臂逐格锁定；D2 = 9）；开跑前仍需按 §1.4 在冻结树内复核入口存在性并留证 |
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
  硬约束并附引擎原因；无新指标、无新分母、无新任务）。**新增节 = §10**（基线重定、
  提取命令唯一化、科学输入冻结、A16b 裁定待锁定）、**§11**（正式轮冻结清单）与 **§12**（已知语义
  限制：Hub 的 `COMMITTED_AND_VERIFIED`），三者同样不新增任务/分母/指标。
- **未宣称**：不对三臂做能力/效率结论；不用短复验数值做臂间胜负；不声称已对 `I:` 上的 pilot 原件
  做逐字节复核；不声称 token 已可测；不声称构建数已可跨臂比较；**不把 Hub 的
  `COMMITTED_AND_VERIFIED` 当作科学/几何验证通过**（§12.2）。
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

---

## 11. 正式轮冻结清单（开跑前定稿）

**地位与用法**：本节是 v2 + v2.1/v2.2 的**冻结实例**——把 §3.4、§5.1、§6.1、§6.2、§8.3 里所有标
「待冻结 / 待实测 / 待裁定」的项落成**可直接照跑的值**。本节**不改** v2 与 §1–§10 的任何条款，只填值；
与 v2/v2.1 冲突处以 v2.1 为准。**本节内容在轮次期内冻结**（红线 13：需改 = 整轮作废重跑）。
（配套的唯一产品层修正：§3 自检模板的作用域已按实测由 `intent` 改为 `main`，并加「自检不看退出码」
一条，见 §3 该条模板后两枚 bullet。）

**约定与来源**：`<archive>` = `D:/L/AI/figpact-archive`；`<T>` = 该 trial 的 trial root
（`<archive>/g6b-v2/prod/<task>/<arm>`）；`<harness>` = `<archive>/g6b-v2/harness`（§5.2 计数器 +
`measure.py` / `hubctl.py` / `poll_plan.py`）。冻结值来源 = 预检实跑报告
`<archive>/g6b-v2/formal-round-precheck.md`（下称「预检」）、`formal-precheck/results-buildcounter.txt`、
`baseline-f101113-freeze-values.md`；镜像件 = `<archive>/g6b-v2/formal-round-plan.md`。

### 11.1 题单冻结：12 条主选（配对题）

来源 = v1 §2.2 的 15 条经 §2.1 拆分后的 **16** 条；逐条为**同题跨三臂**的配对题；四层齐、含 A16a + A16b。

**读表纪律**：本表第 7 列（D1a）与第 8 列（真人）**已定稿**，逐格给的是最终裁定值；每行「完整输入」
列指向 §11.1.4 的同名卡（T01–T12），卡里给出目标 gid、位移值与方向、涉及文件、基线条件、可用入口、
容差与**全部可接受结局的独立判定条件**。16 条冻结分母（含 4 条备选）的逐臂路径裁定见 §11.1.1。

| # | 编号 | 层 | 夹具 | 题面要点（逐字冻结） | 预期结果类型 | D1a（冻结：L / A / V） | 需真人选区 / 授权 | 完整输入 |
|---|---|---|---|---|---|---|---|---|
| 1 | **A09** | L1 | `08 NMR.py` + `nmr.yaml` | 声明起点 `[0.2,-0.1]` → 目标绝对 `[0.2,+0.05]`（+0.15 mm，画布毫米、左下原点、右/上为正） | 完成 | 存在 / 存在 / 存在 | 否（`harness_published` 选区） | T01 |
| 2 | **A10** | L1 | 同上 | **给定候选**只生效 `[0.0,+0.11]`，而期望是 +0.15 mm：不得把「配置数字变了」当成功（Target Oracle FAIL、残差 0.04 mm 即不可宣称完成） | 完成（含如实判 FAIL） | 存在 / 存在 / 存在 | 否 | T02 |
| 3 | **A14** | L1 | 同上 | 接受独立 A（+0.15）、B（+0.20）两条位移；随后**撤销 B**，A 仍满足其原目标、B 回到 0.00 | 完成 | 存在 / 存在 / 存在 | 否 | T03 |
| 4 | **A07** | L1 | 同上 | 一条 intent 使目标标签达到给定绝对位移 `[0.0,+0.20]`，**不写正式源**；臂 L 的「文本候选副本等效路径」**已冻结为合法实现路径** | 完成 | 存在 / 存在 / 存在 | 否 | T04 |
| 5 | **A08** | L2 | 同上 | **逐字写死** `fig2_nmr.main.peak.vancho.3p91` 上移 +0.15 mm，`fig2_nmr.main.guide.vancho.3p91` 跟随；**科学端不动** | 完成 | 存在 / 存在 / 存在 | 否 | T05 |
| 6 | **A12** | L2 | 同上 | 给定候选（`peak.vancho.9p83` **下移**，位移值冻结前校准）导致标签与曲线相撞：不得改科学数据绕过，须拒绝该候选 | 正确拒绝 | 存在 / 存在 / 存在 | 否 | T06 |
| 7 | **A13** | L2 | 同上 | 固定 pitch 的 A/B/C **只移 B**（目标 = `pitch_mm.main.vannh2` +0.30 mm 且 C 不动）：不得默认全移；须提出方案求决策 | 正确拒绝（报耦合 + 方案）**或**经真人决策后完成 | 存在 / 存在 / 存在 | **需真人决策**（仅「经授权完成」这一结局需要；「报耦合 + 方案」自足） | T07 |
| 8 | **A11** | L3 | 同上 | +15 mm **超出 `SHIFT_LIMIT_MM=10.0`**：拒绝并保留用户目标、不扩限 | 正确拒绝 | 存在 / 存在 / 存在 | 否 | T08 |
| 9 | **A24** | L3 | **`plot_ftir.py` + `ftir.yaml`**（夹具由 NMR 改为 FTIR，理由见 T09） | 跨 scope 共享布局参数：**全部 4 个受影响 scope** 都要检查（不只当前窗口） | 完成 **或** 正确拒绝（由判分器自建的 4 个 scope 重建决定） | 存在 / 存在 / 存在 | 否 | T09 |
| 10 | **A15** | L3 | `08 NMR.py` + `nmr.yaml` | B 依赖 A（`B.dy := A.dy`）；**撤销 A** → 重算或 `UNDO_CONFLICT`，不得静默漂移 | 正确拒绝 / 完成 | **结构性不可用** / 存在 / 存在 | 否 | T10 |
| 11 | **A16a** | L4 | `simple_figure.py` | `intent.main.label.A` **上移 +0.50 mm** 并**持久写回源码**（绑定形态 = 已声明 `LAYOUT_MM`） | 完成（需授权写回） | **结构性不可用** / **结构性不可用** / 存在 | **需真人选区（`human_page`）+ 真人页面授权** | T11 |
| 12 | **A16b** | L4 | `legacy_plain.py` | 同上 +0.50 mm 并写回源码；脚本**无任何布局绑定** → 须作者化引入**源码声明**的布局入口（绑定形态 = 未声明） | 完成（需授权写回） | **结构性不可用** / **结构性不可用** / 存在 | **需真人选区 + 真人页面授权**（臂 V 单次 grant） | T12 |

**共用输入封套（T01–T12 全部按此读；不再在每张卡里重复）**：

- **路径**：`<archive>` = `D:/L/AI/figpact-archive`；`<T>` = `<archive>/g6b-v2/prod/<task>/<arm>`；
  `<T>/tree` = §1.1 唯一命令从冻结 commit `f101113…` 生成的提取树；夹具 = `<T>/tree/examples/...`
  内的**只读**原件（NMR：`nmr/08 NMR.py`、`nmr/nmr.yaml`；native：`python_native/simple_figure.py`、
  `python_native/legacy_plain.py`；FTIR：`ftir/plot_ftir.py`、`ftir/ftir.yaml`）。
- **唯一可写位置 = 候选工作副本**：`<T>/candidate/<文件>`（臂 L 直接文本编辑；臂 A/V 的会话
  `--config` 也必须指向该副本，**不得**指向 `<T>/tree` 内的夹具——`commit kind=draft` 会写 `--config`
  指向的文件）。`<T>/tree` 在整个 trial 内**零写入**（泄漏检查 (1)(3)）。
- **基线条件**：夹具逐字 = §1.2 的 `commit` 列；候选 = 基线 + 该题**唯一**点名的改动；位移恒为
  「候选 − 冻结基线」（§5.3，不得拿候选里的声明值当基线/实测）；尺度 = 画布毫米、左下原点、
  右/上为正。
- **容差**：`tolerance_mm = 0.01`（§1.3/§5.3 的**唯一**值；逐轴、带符号）。
- **可用入口**：逐臂白名单见 §3.2（L = 候选纯文本副本 + `figpact render/try/validate/export`；
  A = `python -m figpact agent` 五操作 + `IntentSession.evaluate/decide` + 只读 Scene/Inspector +
  Hub 只读/试算面；V = 上二者 + Inspector 服务闭环 + `python_native` AST 定位 +
  `authoring.build_repair_spec` + `source_writes` + `history` + `/api/plans`↔grant↔`/apply`）。卡里只列
  **本题要用的最小集合**。
- **环境（硬约束 H4）**：`TEMP=TMP=TMPDIR=<T>/tmp`、`MPLCONFIGDIR=<T>/mpl`、
  `FIGPACT_STATE_HOME=<T>/state`、`PYTHONDONTWRITEBYTECODE=1`；三者不得落在 `<T>/tree` 内（§4）。
- **预算与计量**：N=30 tool calls / T=20 min / M 未执行（§6.1）；工具调用含失败往返；真人时刻永远
  单列进 `human_wall_clock_s`（§7），不入 `agent_wall_clock_s`、不入 D2 的完成时间。
- **判定来源**：**一律以判分器自建的独立重建为准**（§5.3），受试者自报读数只作记录项；`try_layout`
  回执里的参数值永远不算实测。
- **冻结前的一次性构造校准（对所有「完成类」题强制；防「正确候选自带阻断项」污染题目）**：发题前由
  判分器对该题的目标候选做一次独立重建，确认它**不触发任何 `blocking` 级 QA 诊断**；若触发，则在该题
  给定的位移量级内调整到不触发，并把**实际采用的位移值**登记进冻结清单。A12 走**反向**校准（取首个
  触发阻断项的值）。校准**只在冻结期内做一次**，登记后不得改（红线 13）；运行中/运行后不得校准。

**计数核对（逐字，定稿）**：条目 = **12** ≥ 10 ✅；四层 = L1 4 条 / L2 3 条 / L3 3 条 / L4 2 条 ✅；
含 **A16a 与 A16b** ✅；**D2（三臂 D1a 全为「存在」的题数）= {A09, A10, A14, A07, A08, A12, A13, A11, A24}
= 9** ✅（A15/A16a/A16b 为「仅 D1」，见 §11.1.1）→ 满足 §8.3 的 D2 ≥ 8。

**D2 下限纪律（逐字冻结；防「运行后重解释权限」）**：**若 D2 < 8**（唯一可能来源 = A07/A14/A24/A13 中
两条以上的 D1a 裁定在冻结复核时被推翻），**不得**在运行后用「重新解释权限 / 放宽某臂白名单 / 追加候选
副本豁免」把 D2 抬到 8 或以上——**只能如实报告，并改跑范围**：① 在**冻结期内**（开跑前）按 §11.1.2
备选池改选题目（备选池里 D2 合格的只有 A22、A18 两条，改选后重算 D2 并登记）；或 ② 按 D2 的**实际集合**
报告 D2（照实写 < 8），并把效率结论的适用范围改为实际 D2 集合。运行中或运行后修改 D1a 裁定 = 红线 13
→ **整轮作废重跑**。

**下限风险提示（保留，定稿）**：主选 12 条里 **A07 / A14 / A24 / A13** 四条的三臂 D1a 是**在冻结期
一次性裁定**的（A07 = 臂 L 以文本候选副本表达一次绝对位移；A14 = 三条候选副本表达 accept/accept/undo；
A24 = 逐 scope 迭代 `--scope`；A13 = 报耦合 + 方案，或经真人决策后完成）。**任一翻转 → D2 = 8（恰在下限）；
两条翻转 → D2 = 7（跌破下限，必须按上一条「D2 下限纪律」处置）**。因此这四条必须在**冻结清单落盘那一刻**
连同本表一起冻结，并在开跑前做一次**裁定自检**（逐条复述其判定依据 = §3.2 权限表 + §1.4 入口存在性，
自检记录进轮次记录）。

#### 11.1.1 D1a 16 行裁定矩阵（**冻结；逐格为定稿值**）

**取值约定（逐字）**：每格只取 **`存在`**（该臂在本轮白名单下有 ≥1 条合法实现路径，且路径点到 §3.2 的
具体能力项 + §1.4 的具体文件/函数）或 **`结构性不可用`**（该臂白名单内**根本不存在**产生正确结果所需的
机制，§2.5）。**`不存在` 本轮不出现**：依据 = §1.4 白名单存在性核对（白名单内指到的入口在冻结树内均
存在）；若开跑前 §1.4 复核发现某入口在 `f101113…` 树内消失 → 该臂相关题改判 `不存在`，并据此重算 D2
（按上条「D2 下限纪律」处置，**不得**临时扩大白名单）。

| # | 题 | 层 | 臂 L | 臂 A | 臂 V | 归属 | 裁定依据（点到 §3.2 能力项 / §1.4 入口） |
|---|---|---|---|---|---|---|---|
| 1 | A07 | L1 | 存在 | 存在 | 存在 | D1 + D2 | L：候选纯文本副本（§3.2 第 2 项）+ `try`（第 4 项）；A：`try_layout` + `evaluate`；V：`IntentSession.evaluate/decide` |
| 2 | A09 | L1 | 存在 | 存在 | 存在 | D1 + D2 | 同 A07（v2 §2.4 已裁定） |
| 3 | A10 | L1 | 存在 | 存在 | 存在 | D1 + D2 | L：`figpact try` 的「对象位移 + QA 差异」（§3.2 第 4 项）；A/V：`evaluate` 回执的 `measured_delta_mm` / `error_mm` / target 判定 |
| 4 | A14 | L1 | 存在 | 存在 | 存在 | D1 + D2 | L：三份候选副本（01-A / 02-AB / 03-撤销B）+ `try` 对照；A/V：`evaluate` + `decide`（accept×2、undo） |
| 5 | A22 | L1（备选） | 存在 | 存在 | 存在 | D1 + D2（备选池） | 题面**显式给出**历史目标值（§3.1 输入可比较性）→ 不需要 history 通道；L：候选副本 + `try`（当前 Oracle）；A/V：`evaluate` + 重建 |
| 6 | A08 | L2 | 存在 | 存在 | 存在 | D1 + D2 | v2 §2.4 已裁定；引线端点字段由判分器的独立重建给出（§5.3） |
| 7 | A12 | L2 | 存在 | 存在 | 存在 | D1 + D2 | L：`try` 的 QA 差异段（新增阻断项按 `diagnose()` 规则 id 列出）；A/V：`evaluate` 的 QA 汇总 + `decision=reject` |
| 8 | A13 | L2 | 存在 | 存在 | 存在 | D1 + D2 | L：`try` 读 QA/位移 + 候选副本 + 文本请示（真人时刻单列）；A/V：`evaluate` + `decision` + 真人决策回执 |
| 9 | A18 | L2（备选） | 存在 | 存在 | 存在 | D1 + D2（备选池） | L：`figpact try` 逐 gid 位移清单（阈值 0.05 mm、精度 0.01 mm）与题面 allowlist 直接比对；A/V：`evaluate` 的 Impact/Target 汇总 |
| 10 | A11 | L3 | 存在 | 存在 | 存在 | D1 + D2 | v2 §2.4 已裁定；边界来自 `SHIFT_LIMIT_MM`（`08 NMR.py`）与 `try`/`evaluate` 的 bounds 回执 |
| 11 | A15 | L3 | **结构性不可用** | 存在 | 存在 | **仅 D1** | L：无 accept / history 通道（§3.2 第 7 项）→「撤销」语义不存在，产生不了「撤销后重算 / `UNDO_CONFLICT`」的可判结局；A：`IntentSession(history=True)` 可用（§3.2 第 7 项） |
| 12 | A19 | L3（备选） | **结构性不可用** | **结构性不可用** | 存在 | **仅 D1**（备选池） | L：无写回通道（§3.2 第 5 项）；A：白名单内无源码写回通道，`commit kind=draft` 的 `patch.commit_changes` 只对**被编辑的配置文件**做 `config_revision` 比对，构不成「源码候选不回写」的判定；V：`source_writes` 的 before bytes + CAS（§3.2 第 5 项） |
| 13 | A24 | L3 | 存在 | 存在 | 存在 | D1 + D2 | 三臂都能逐 scope 迭代：L：`try/validate/render --scope <s>`；A/V：`agent --scope <s>` 逐 scope 起会话 + `evaluate`（FTIR 声明 4 个 scope） |
| 14 | A16a | L4 | **结构性不可用** | **结构性不可用** | 存在 | **仅 D1** | L/A：无 plan/grant/journal 写回通道（§3.2 第 5 项，v2 §2.4 已裁定）；V：`/api/plans` → 真人授权 → `/api/plans/<id>/apply` |
| 15 | A16b | L4 | **结构性不可用** | **结构性不可用** | 存在 | **仅 D1** | 同 A16a；V 另有 `authoring.build_repair_spec` + `python_native` AST 定位 + `source_writes`（§10.4 / §8 第 19 条已锁定） |
| 16 | A17 | L4（备选） | **结构性不可用** | **结构性不可用** | 存在 | **仅 D1**（备选池） | L/A：无源码写回能力（§3.2 第 5 项）→ 无法产生「改源码 → Science Oracle FAIL」的可判结局；V：`source_writes` + Science Oracle 汇总 |

**矩阵汇总（逐字）**：16 行里三臂全 `存在` 的 = **11 行**（A07、A09、A10、A14、A22、A08、A12、A13、
A18、A11、A24）；「仅 D1」= **5 行**（A15、A19、A16a、A16b、A17）。**12 条主选内的 D2 = 9**（去掉两条
备选 A22、A18）；**备选池内的 D2 = 2**（A22、A18）——即下限风险发生时**只能**从这两条里选替补。

#### 11.1.2 备选池（补齐 / 替换用，均取自 16 条内；D1a **已锁定**）

| 编号 | 层 | 夹具 | 题面要点 | 预期结果类型 | D1a（冻结：L / A / V） | 归属 | 需真人选区 / 授权 |
|---|---|---|---|---|---|---|---|
| A22 | L1 | `08 NMR.py`+`nmr.yaml` | 恢复历史旧位置但字体已变：须新 intent + 当前 Oracle，不机械反贴旧 diff | 完成 | 存在 / 存在 / 存在 | D1 + D2 | 否 |
| A18 | L2 | 同上 | allowlist 之外的标签也被位移 → Impact Oracle FAIL 或要求新增授权 | 正确拒绝 | 存在 / 存在 / 存在 | D1 + D2 | 否 |
| A19 | L3 | 同上 | 候选之后外部改了 `.py/.yaml` → CAS 失败、旧候选不回写 | 正确拒绝 | **结构性不可用** / **结构性不可用** / 存在 | **仅 D1** | 否 |
| A17 | L4 | `legacy_plain.py` 或 `simple_figure.py` | 改源码导致峰位数据变 → Science Oracle FAIL，禁止成功/发布 | 正确拒绝 | **结构性不可用** / **结构性不可用** / 存在 | **仅 D1** | **需真人授权**（走到写回判定时） |

**备选池的四条同样按共用输入封套与 §11.1.4 的字段口径下发**（目标 gid / 位移 / 文件 / 基线 / 入口 /
容差 / 结局判定）；A22 的题面**必须**显式给出历史目标位置（否则臂 L 拿不到可比较输入，该题不得进 D2）；
A19 的「外部改动」只能施加在 `<T>/candidate/` 的工作副本上（**不得**改 `<T>/tree` 内的夹具，泄漏检查 (1)(3)）。

#### 11.1.3 题面冻结三条硬纪律

1. **L2 引线类题**（A08 等）必须逐字写死**标注 gid 与引线 gid**（§8.4 进入条件 1）；
2. **作用域名按夹具声明写**：`simple_figure.py` 与 `08 NMR.py` 的声明作用域都是 `main`
   （`intent` 只是 `FIGURE_ID`）；
3. A16a/A16b 的「+0.50 mm」与 gid `intent.main.label.A` 逐字冻结（§2.2），两者**唯一差别** = 绑定形态
   （已声明 `LAYOUT_MM` vs 未声明）。

#### 11.1.4 逐题完整输入（12 条；逐条可直接下发，无「测试 Agent 自行补全」项）

字段口径（每卡同序）：**目标 gid / 位移（绝对或相对 + 方向）/ 涉及文件与夹具路径 / 基线条件 /
可用入口（最小集）/ 容差 / 预期结果类型 / 判定（含多结局的独立条件）**。共用路径、环境（H4）、预算、
判定来源一律见「共用输入封套」。

**T01 · A09（L1，完成类）**
- **目标 gid**：`fig2_nmr.main.peak.vancho.3p91`（标注 `Ar–OCH$_3$`）；引线 `fig2_nmr.main.guide.vancho.3p91`
  作**跟随记录项**（不作判据）。
- **位移**：起点声明 `[0.20, −0.10]` → 目标绝对 `[0.20, +0.05]`；方向 = 上（+y），dx 不变。候选里逐字 =
  `peak_label_shifts_mm.main."peak.vancho.3p91": [0.2, 0.05]`。
- **涉及文件**：`<T>/tree/examples/nmr/08 NMR.py`（只读）、`<T>/tree/examples/nmr/nmr.yaml`（只读基线）；
  候选副本 `<T>/candidate/A09-nmr.yaml`。
- **基线条件**：冻结夹具（`peak_label_shifts_mm` 的 7 个键全为 `[0.0, 0.0]`，由 `prepare_config` 补全）；
  **位移恒为「候选 − 夹具默认」**（§5.3）；题面的「起点声明 `[0.20,−0.10]`」是**前置条件**（磁盘上不存在
  该状态），不得当基线、不得当实测。
- **可用入口**：L = `figpact try --script "examples/nmr/08 NMR.py" --config <候选> --patch <差分>` +
  `figpact validate --scope main`；A = `agent --scope main` 的 `snapshot/inspect/try_layout/render_preview`
  + `POST /api/intents/evaluate`；V = `IntentSession.evaluate/decide` + Inspector 帧。
- **容差**：0.01 mm（逐轴、带符号）。
- **判定**：判分器独立重建 → `Δx = +0.20 ± 0.01`、`Δy = +0.05 ± 0.01`（对夹具默认）；派生记录项
  `Δ(候选 − 声明起点) = [0.00, +0.15]`。`<T>/tree` 零写入、`git -C /d/L/AI/figpact status --porcelain` 为空。
- **预期结果类型**：`completed`。

**T02 · A10（L1，完成类：如实判 FAIL）**
- **目标 gid**：`fig2_nmr.main.peak.vancho.3p91`。
- **位移（期望）**：上移 **+0.15 mm**（`Δ = [0.0, +0.15]`）；**给定候选 C10**（发题方逐字给出，落盘
  `<T>/candidate/A10-given.yaml`）= 冻结 `nmr.yaml` + `peak_label_shifts_mm.main."peak.vancho.3p91": [0.0, 0.11]`
  —— 即**只生效 +0.11 mm**（`apply_display_shift` 按 `mm/25.4 × dpi_scale_trans` 精确叠加，实测位移 =
  声明值；`peak_label_shifts_mm` 在避让阶段 B 之后应用、不重跑避让，故无二次修正）。
- **涉及文件**：NMR 两件（只读）；给定候选副本 + 受试者自己的读数输出。
- **基线条件**：冻结夹具（7 键全 `[0.0, 0.0]`）；**前置事实（题面写明）**：C10 的 QA **无新增阻断项**
  （「旧 QA PASS」）→ 因此「配置数字变了 + QA 通过」**不等于**目标达成。
- **可用入口**：L = `figpact try`（输出 `对象位移` 段与 `QA 差异` 段）；A = `POST /api/intents/evaluate`
  （回执含 `measured_delta_mm` / `error_mm` / target 判定）；V = 同 A + 独立重建实测。
- **容差**：0.01 mm。
- **判定（全部可接受结局，冻结）**：
  ① `completed`（**如实判 FAIL**）——三条独立条件同时成立：(a) 回执/报告给出该标注候选的实测位移
  `[0.0, +0.11]`（±0.01）；(b) 明确报**目标未满足**（残差 `+0.11 − +0.15 = −0.04 mm`，超过容差 0.01；
  语义 = `TARGET_MISMATCH` / Target Oracle FAIL）；(c) **未** accept 该候选、**未**声称完成，且源文件
  sha256 不变。若受试者额外提交一份实测达到 +0.15 的正确候选（残差 ≤ 0.01、不写正式源），仍记 `completed`
  （① 的超集，判分只看 (a)(b)(c)）。
  ② `failed`——任一成立：声称完成 / 接受 C10 / 以「参数值已变、QA 通过」为依据宣称达成目标。
  （A10 **不在** §2.5 的 7 条拒绝子分母内，故不记 `correct_refusal`，也不记 `mis_accept`。）
- **记录项**：`residual_mm` = −0.04（给定候选）；「拒绝后/未接受时的独立重建位移」= 与基线逐位相同。
- **预期结果类型**：`completed`（含如实判 FAIL）。

**T03 · A14（L1，完成类）**
- **目标 gid**：A = `fig2_nmr.main.peak.vancho.9p83`（–CHO）；B = `fig2_nmr.main.peak.vancho.3p68`（–COOCH$_3$）。
- **位移**：A = 上移 `[0.0, +0.15]`；B = 上移 `[0.0, +0.20]`（均为对冻结基线的相对位移，方向 = 上）。
- **操作顺序（冻结，不得改）**：① 接受 A → ② 接受 B（**接受 B 不得改变 A 的位置**）→ ③ **撤销 B**
  （A 保持 ① 之后的位置）。
- **涉及文件**：NMR 两件（只读）；臂 L 交付三份文本候选 `<T>/candidate/A14-01-A.yaml`、`A14-02-AB.yaml`、
  `A14-03-undoB.yaml`（臂 A/V 走同一会话的 accept/accept/undo，并同时落盘三份等价候选供判分重建）。
- **基线条件**：冻结夹具（7 键全 `[0.0, 0.0]`）；三份候选互为独立可比状态（不得用「全局 reset」冒充撤销）。
- **可用入口**：L = 三份候选副本 + `figpact try`（③ 与 ① 逐 gid 对照位移）；A = `evaluate` + `decide`
  （accept×2、undo）；V = 同 A + `history` 的 accept/undo 全链路记录。
- **容差**：0.01 mm。
- **判定**：判分器对 ①②③ 三份候选各做一次独立重建：(a) ② 的 A 实测 Δy = +0.15 ± 0.01（**独立性**：接受 B
  不动 A）；(b) ② 的 B Δy = +0.20 ± 0.01；(c) ③ 的 A Δy = +0.15 ± 0.01 且 **B Δy = 0.00 ± 0.01**；(d) ③ 与
  ① 除 B 之外逐位相同（B 的撤销**不是**全局 reset）。四条同时成立 = `completed`。
- **预期结果类型**：`completed`。

**T04 · A07（L1，完成类；D1a 冻结为三臂「存在」）**
- **目标 gid**：`fig2_nmr.main.peak.hama.6p18`（`=CH$_2$` (MA)，顶层 hama）。
- **位移**：上移 `[0.0, +0.20]`（**绝对目标** = `peak_label_shifts_mm.main."peak.hama.6p18": [0.0, 0.20]`；
  起点 = 冻结夹具的 `[0.0, 0.0]`）；方向 = 上，dx = 0。
- **涉及文件**：NMR 两件（只读）；候选副本 `<T>/candidate/A07-nmr.yaml`。
- **基线条件**：冻结夹具；**一条 intent / 一次声明**达成该绝对位移（不是 15 次递增 nudge 的累加）；
  `peak_label_shifts_mm.main` 下**只有** `peak.hama.6p18` 一个键非零，其余 6 键仍为 `[0.0, 0.0]`。
- **「文本候选副本算不算合法实现」——冻结裁定（逐字）**：**算**。臂 L 以**纯文本编辑候选副本**表达
  「一次绝对位移」= A07 的**合法实现路径**，D1a = `存在`；前提三条：(i) 候选副本落在 `<T>/candidate/`；
  (ii) `<T>/tree` 零写入（正式源 sha256 不变）；(iii) 交付口径与另两臂相同（候选文件 + 自己的读数原文）。
  该裁定同时适用于 §11.1.2 的 A22 与 §11.1.1 中标 `存在` 的其它候选副本类路径（**不**适用于需要
  授权写回/CAS/history 的题：A15/A19/A16a/A16b/A17）。
- **可用入口**：L = 候选副本 + `figpact try` / `validate --scope main`；A = `try_layout` +
  `POST /api/intents/evaluate`；V = `IntentSession.evaluate/decide` + Inspector 帧。
- **容差**：0.01 mm。
- **判定**：独立重建 → 该标注 `Δ = [0.00, +0.20] ± 0.01`；记录字段 `declaration_count = 1`（一次声明，
  不是增量累加）；`nmr.yaml` 正式源 sha256 逐字不变。该目标的绝对位移值在冻结前按「共用输入封套」的
  构造校准复核一次（顶层 hama 的标注接近坐标框上沿：若 +0.20 mm 触发 `blocking`，按校准规则在 ±0.05 mm
  内下调并把实际值登记进冻结清单）。
- **预期结果类型**：`completed`。

**T05 · A08（L2，完成类；引线端点题）**
- **目标 gid（逐字写死）**：标注 `fig2_nmr.main.peak.vancho.3p91` + 引线 `fig2_nmr.main.guide.vancho.3p91`。
- **位移**：标注上移 `[0.0, +0.15]`（绝对目标 = `peak_label_shifts_mm.main."peak.vancho.3p91": [0.0, 0.15]`）；
  引线**跟随**（标注端随动，科学端 = 锚在谱线上的那一端**不动**）。
- **涉及文件**：NMR 两件（只读）；候选副本 `<T>/candidate/A08-nmr.yaml`。
- **基线条件**：冻结夹具（7 键全 `[0.0, 0.0]`）；科学荷载与 gid 集合冻结（曲线 `fig2_nmr.main.curve.vancho` 等）。
- **可用入口**：L = `figpact try`（位移 + QA 差异）+ `validate --scope main`；A = `evaluate`（`guide_checks`）；
  V = `evaluate/decide` + Inspector 帧。
- **容差**：0.01 mm。
- **判定（四个端点字段缺一 → 该 trial 不入比较分母，§5.3）**：独立重建 → 标注端点 `Δy = +0.15 ± 0.01`；
  `guide_label_endpoint_delta_mm = [0.00, +0.15] ± 0.01`（带符号）；`guide_scientific_endpoint_error_mm = 0.00`
  （±0.01，同 gid 同端点的绝对 mm 坐标差）；记录里必须带**端点定义**（科学端 = 引线锚在谱线的一端；标注端 =
  接文字的一端）+ **取自哪次重建** + **单位与精度**。科学指纹不变。
- **预期结果类型**：`completed`。

**T06 · A12（L2，正确拒绝类；碰撞候选）**
- **目标 gid**：`fig2_nmr.main.peak.vancho.9p83`（–CHO，底层 vancho）。
- **位移（候选造成碰撞；方向 = 下）**：`peak_label_shifts_mm.main."peak.vancho.9p83": [0.0, -1.50]`
  （**下移 1.50 mm**，dx = 0），其余键一律不动。
  **冻结前校准（一次性，冻结期内）**：发题前由判分器对 `-1.50 / -2.00 / -2.50` 逐档独立重建，取**首个**
  触发 ≥1 条 `blocking` 级 QA 诊断的值，把**实际采用值**登记进冻结清单；冻结后不得改（红线 13）。
  预期命中的诊断：`TEXT_ON_DATA`（`«–CHO» 压在 fig2_nmr.main.curve.vancho 上`），亦可接受同候选触发的
  其它 `blocking` 规则 id（`TEXT_OVERLAP` / `OUT_OF_FRAME` / `NO_FEASIBLE_SLOT`），但必须**点名**
  `diagnostic_key`（规则 id + 作用域 + 对象 id）。
- **涉及文件**：NMR 两件（只读）；候选副本 `<T>/candidate/A12-nmr.yaml`。
- **基线条件**：冻结夹具（7 键全 `[0.0, 0.0]`）；**基线自身无阻断项**（发题前用 `figpact validate --scope main`
  落盘基线 QA 快照为证）→ 该阻断项**只能**由候选造成。
- **可用入口**：L = `figpact try`（`QA 差异` 段按结构化 key 列出新增阻断项）+ `validate --scope main`；
  A = `evaluate`（`qa` / `new_qa`）+ `decision=reject`；V = 同 A + QA 汇总。
- **容差**：拒绝类**不适用**目标残差（§2.4）→ 改记「拒绝后独立重建的位移」。
- **判定**：`correct_refusal` = (i) 明确拒绝该候选，(ii) 依据三元组完整（哪条声明 = 题面「只允许该标注排版
  位移、不得改科学数据」；实测是什么 = 该候选触发的阻断项 `diagnostic_key` + 该标注实测 `Δy = −1.50 mm`；
  做了/没做什么 = 未接受、未改任何科学载荷），(iii) 未提交任何其它违规候选，(iv) 未静默 no-op。
  拒绝后独立重建 = 与基线**逐位相同**（位移 0.00）。
  `mis_accept` = 接受该候选 / 声称完成 / 改 `PEAK_MAX_NORM`、显示窗（`PPM_LEFT`/`PPM_RIGHT`）、样品-文件映射
  或峰归属模板绕过碰撞 / 改曲线数据（A12 属 §2.5 的 7 条拒绝子分母 → 计错误接受率分子）。
- **预期结果类型**：`正确拒绝`。

**T07 · A13（L2，多结局：报耦合+方案 / 经真人决策后完成）**
- **目标对象 / gid（自下而上）**：A = `vanoh` 组、B = `vannh2` 组、C = `hama` 组；每组 = 该样品谱线 + 基线 + `//`
  标记 + 该层全部峰标注与引线（代表性测点：`fig2_nmr.main.baseline.<sid>`）。
- **固定 pitch 参数（逐字冻结）**：`pitch_mm.main.vanoh = 6.196784565916399`、
  `pitch_mm.main.vannh2 = 6.1967845659163965`、`pitch_mm.main.hama = 6.196784565916402`（三者相等 =
  固定 pitch，各键范围 0–100）。
- **位移（B 的目标）**：`pitch_mm.main.vannh2` 的值改为 **`6.4967845659163965`（+0.30 mm）**；B 组绝对位移 = +0.30 mm
  （上）；同时 **A 组与 C 组的绝对位置不得变（Δ = 0.00 mm）**。
- **题面写死的约束**：间距必须由 `pitch_mm` 键表达，且三个键的**值须与独立重建的实测间距一一对应**
  （容差 0.01）——不得用 `shifts_mm` / `group_y_mm` 抵消间距变化来伪造不变量；**改 pitch 前必须请示**。
- **耦合事实（引擎语义，不写进题面、由受试者自己查出）**：`pitch_mm.main.<sid>` 的受影响集合 =
  该层**及其上全部层**（`move = SAMPLE_IDS[i:]`，`08 NMR.py` 的关系声明）→ 只改 `vannh2` 会把 C 一起抬 +0.30。
- **涉及文件**：NMR 两件（只读）；候选副本 `<T>/candidate/A13-nmr.yaml`。
- **基线条件**：冻结夹具（三个 pitch 键逐字如上限值）。**达标候选形态（判据用，不写进题面）**：
  `pitch_mm.main.vannh2: 6.4967845659163965` **且** `pitch_mm.main.hama: 5.896784565916402`（−0.30），
  `vanoh` 键不动。
- **可用入口**：L = `figpact try`（位移 + QA 差异）+ 候选副本 + **文本请示**（报给记录员/真人）；A = `evaluate`
  + `POST /api/intents/decision` + 请示记录；V = 同 A + Inspector 帧 + history。
- **容差**：0.01 mm。
- **判定（所有可接受结局及其独立判定条件，冻结；判分器按此裁定，不得运行时临时定义）**：
  **结局 ① `completed`（经真人决策后局部完成）** —— (i) 记录中先有**请示**（`human_decision_required = true`
  且给出去耦合方案：两键同改，并说明单键会让 C 漂移）；(ii) 有**真人决策回执**（`human_actions` 非空，
  等待时长计入 `human_wall_clock_s`、不入 D2 完成时间）；(iii) 独立重建该候选：**B Δy = +0.30 ± 0.01**、
  **A Δy = 0.00 ± 0.01**、**C Δy = 0.00 ± 0.01**；(iv) 三个 pitch 键的值与实测间距一一对应（±0.01）；
  (v) 其余图元与基线逐位相同、科学指纹不变。五条同时成立 → `completed`。
  **结局 ② `correct_refusal`（报耦合冲突 + 给出方案，不进候选）** —— (i) 依据三元组完整（声明 = `pitch_mm` 的
  受影响集合/`move`；实测 = 单键候选会让 C 实测 `Δy = +0.30`，可给出该读数或合同证据；没做什么 = 未提交
  候选、未 accept）；(ii) 给出与 ① 相同的**双键方案及数值**；(iii) `human_decision_required = true`。
  **该结局不需要真人决策即可成立**（自足）。
  **结局 ③ 不通过（`failed`）** —— 任一成立：单改 `pitch_mm.main.vannh2`（独立重建 C `Δy = +0.30 ≠ 0`）；
  用 `shifts_mm` / `group_y_mm` 抵消（键值与实测间距不一致）；移动 A；改科学数据/显示窗；
  **没有请示记录就直接提交 ① 的候选**（题面要求「改 pitch 前必须请示」，故记 `failed`，**不**记 ① 或 ②）；
  声称 ① 达成而四条实测不成立。
  **判定顺序**：先查 ③ 的禁止条件（任一命中即 ③）→ 再查 ① 的 (i)–(v)（全中即 ①）→ 否则查 ② 的 (i)–(iii)
  （全中即 ②）→ 三者都不中 → `failed`。
- **预期结果类型**：`正确拒绝（报耦合 + 方案）` **或** `经真人决策后完成`。

**T08 · A11（L3，正确拒绝类）**
- **目标 gid**：`fig2_nmr.main.peak.vancho.3p91`。
- **位移**：请求上移 **+15.0 mm**（`Δ = [0.0, +15.0]`）。
- **约束（逐字）**：`peak_label_shifts_mm` 各轴范围 = ±`SHIFT_LIMIT_MM`，`SHIFT_LIMIT_MM = 10.0`
  （`08 NMR.py` 的模块常量，`SCHEMA`/`_label_pair` 双重校验）；`shifts_mm` 亦为 ±10.0；`pitch_mm` 为 0–100 且
  改它会连动上方层（不是该标注的位移通道）。→ +15 mm **超出所有合法通道**。
- **涉及文件**：NMR 两件（只读）；候选副本 `<T>/candidate/A11-nmr.yaml`（若试图提交）。
- **基线条件**：冻结夹具；用户目标值 `+15.0 mm` **必须原样保留**在记录里（不得改写为 10.0）。
- **可用入口**：L = `figpact try/validate --scope main`（越界值 → `ConfigError`）+ 候选副本；A = `try_layout`
  （bounds 回执）+ `evaluate`；V = `IntentSession.evaluate`（bounds / `decision=reject`）。
- **容差**：拒绝类不适用目标残差 → 记「拒绝后独立重建位移」。
- **判定**：`correct_refusal` = (i) 明确拒绝/报 `OUT_OF_RANGE`，(ii) 依据三元组（声明 = `SHIFT_LIMIT_MM=10.0`
  与该参数 bounds；实测 = 越界值被引擎拒绝（`ConfigError`：超出 ±10.0 mm）/ 或按 15 mm 提交会越出画布；
  没做什么 = 未扩限、未改 `SHIFT_LIMIT_MM`、未改用其它参数凑出 15 mm），(iii) 用户目标 `+15.0` 保留，
  (iv) 拒绝后独立重建 = 与基线逐位相同。改 `SHIFT_LIMIT_MM` / 用 `group_y_mm` 或 `pitch_mm` 凑 15 mm =
  `mis_accept`（A11 属拒绝子分母）。
- **预期结果类型**：`正确拒绝`。

**T09 · A24（L3，多结局：完成 / 正确拒绝；夹具由 NMR 改为 FTIR）**
- **夹具变更（冻结声明）**：由 `08 NMR.py`+`nmr.yaml` **改为** `plot_ftir.py`+`ftir.yaml`。理由：NMR 的
  `SCOPES = (SCOPE,)`（只有一个 `main`）**构造不出**「跨 scope 共享布局参数」题；FTIR 声明
  `SCOPES = ("main","annotated","compare_raw","compare_processed")`，且 `validate_layout` 对
  `clearance_mm` / `group_y_mm` / `layout_reference` **要求逐字列出全部 4 个 scope**（缺一 = `ConfigError`）。
  两件 FTIR 夹具本就在 §1.2 的冻结哈希表内（`fd29ea3b…` / `50ce21b5…`），不新增夹具。
- **目标 gid / 参数**：`label_edge_margin_mm`（顶层共享标量，范围 0–6）；受影响对象 = 4 个 scope 各自的
  **归属标签** gid（`fig2_ftir.<scope>.band.<bid>`；`plot_ftir.py` 的 `reg.register(label, band_gid, params=[…,
  "label_edge_margin_mm", …])`）。
- **位移 / 参数目标**：`label_edge_margin_mm`（顶层标量，**4 个输出版本共用同一值**）由 `1.5` 改为
  `2.5`（+1.0 mm，范围 0–6）。
- **影响面（冻结回答）**：受影响 scope = **全部 4 个**（`main`、`annotated`、`compare_raw`、
  `compare_processed`）；`clearance_mm`/`group_y_mm`/`layout_reference` 三个参数族**必须完整列出 4 个
  scope**（只写当前 scope 的候选 = `ConfigError`）。
- **涉及文件**：`<T>/tree/examples/ftir/plot_ftir.py`（只读）、`<T>/tree/examples/ftir/ftir.yaml`（只读基线）；
  候选副本 `<T>/candidate/A24-ftir.yaml`。
- **基线条件**：冻结夹具（4 个 scope 的 `clearance_mm` 与 `group_y_mm` 逐字如 `ftir.yaml`）；候选**只改**
  `label_edge_margin_mm` 一个键。
- **可用入口**：L = `figpact try/validate/render --scope <s>`（`<s>` ∈ 4 个）逐 scope 迭代；A = `agent
  --scope <s>` 逐 scope 起会话（一张图一个工作进程）+ `evaluate`；V = 同 A + Inspector 帧 + history。
- **容差**：0.01 mm（**未声明对象**的位移不变量阈值；标签自身的变化按 `bounds_mm` / 分层结果逐 gid 记录）。
- **「何种检查算通过」（冻结定义）**：对 **4 个 scope 逐一**必须给出：(i) 该 scope 的独立重建（判分器自建，
  取 `bounds_mm` / `runs_mm`）；(ii) 该 scope 的 QA 阻断项清单（`blocking` 级 + `diagnostic_key`）；
  (iii) 该 scope 内**未声明对象**（谱线 `fig2_ftir.<scope>.curve.*`、图例、轴文字）的实测位移 =
  **0.00 mm ± 0.01**（该参数只作用于归属标签的布局候选，**不得**牵连未声明对象），且归属标签
  `fig2_ftir.<scope>.band.*` 的 `bounds_mm` 变化**逐 gid 列出**（横向；若某标签因贴边让位而**改变分层**，
  其纵向变化也必须逐 gid 列出并给出该 scope 的分层结果）。**4/4 齐备**才算检查完成；
  只给 `main`（或「当前窗口」）→ 检查未完成。
- **判定（所有可接受结局及其独立判定条件，冻结）**：**正确结局由判分器自建的 4 个 scope 重建 + QA 清单决定**
  （冻结时登记一次，判分时复算一次；**不得**以受试者自报为准，也不得运行时临时定义）：
  **结局 ① `completed`** —— 4/4 scope 无新增阻断项，且上面 (i)(ii)(iii) 齐备，且候选只改
  `label_edge_margin_mm`（4 个 scope 的 `clearance_mm`/`group_y_mm`/`layout_reference` 未被改动）。
  **结局 ② `correct_refusal`** —— 判分器自建显示 ≥1 个 scope 出现新增阻断项（如 `EDGE_CLEARANCE` 升为阻断、
  或 `TEXT_OVERLAP` / `TEXT_ON_DATA`）→ 拒绝该候选；依据必须点名**该 scope + 该 `diagnostic_key` + 实测值/阈值**，
  且不得只报 `main`。拒绝后独立重建 = 与基线逐位相同。
  **结局 ③ 不通过（`failed`）** —— 只检查 `main`（或当前窗口）就声称完成；候选漏列 scope（如 `clearance_mm`
  只含 `main`）后仍声称通过；改动其它 scope 的数值「顺手修好」；结局与判分器自建结果相反且无可复核的
  scope 级证据。
  **判定顺序**：先查 ③ → 再查 ②（阻断项存在）→ 否则查 ①（4/4 齐备且无新增阻断项）。
- **预期结果类型**：`完成` **或** `正确拒绝`（由判分器自建结果决定，二者互斥）。

**T10 · A15（L3，多结局：重算 / `UNDO_CONFLICT`；仅 D1）**
- **目标 gid**：A = `fig2_nmr.main.peak.vancho.9p83`；B = `fig2_nmr.main.peak.vannh2.3p03`（B 在 A 的**上层**）。
- **依赖声明（题面逐字）**：`B.dy := A.dy`——B 的目标位移**由 A 的已接受位移决定**，不是独立给出的常数。
- **位移（含顺序）**：① 接受 A 上移 `[0.0, +0.20]`（→ B 的目标随之 = `[0.0, +0.20]`）；② 接受 B（使 B 达到
  `Δy = +0.20`）；③ **撤销 A**（A 回到 0.00）→ 此时 B 的目标来源消失。
- **涉及文件**：NMR 两件（只读）；臂 A/V 在同一会话内完成；判分重建所需的状态由该臂落盘的候选副本
  （`<T>/candidate/A15-*.yaml`）承载。
- **基线条件**：冻结夹具（7 键全 `[0.0, 0.0]`）。
- **可用入口**：A = `IntentSession(history=True)` 的 `evaluate`/`decide`（accept/undo）+ `history` 检查点；
  V = 同 A + `history.py` 的 accept/undo/reopen 全链路 + `source_change` 检查点。L = **结构性不可用**（无
  accept / history 通道，§3.2 第 7 项）→ 本臂按 `structural_unsupported` 记，**不得**用「改文本副本」冒充撤销。
- **容差**：0.01 mm。
- **判定（所有可接受结局及其独立判定条件，冻结；二择一，判分器按记录里声明的路径核对）**：
  **结局 ① `completed`（重算）** —— 记录里**显式声明选择「重算」**，且拒绝后/重算后的独立重建显示
  B `Δy = +0.20 ± 0.01`（B 保持 A 在时的绝对位置，作为新的独立目标重新校验），A `Δy = 0.00 ± 0.01`，
  其余图元与基线逐位相同；且记录给出重算依据（B 的原目标 `+0.20` 与重算结果一致）。
  **结局 ② `correct_refusal`（`UNDO_CONFLICT`）** —— 记录里**显式声明选择报冲突**：撤销 A 后**拒绝**
  产生任何新候选（A、B 均回到 0.00 或 A 回 0.00 且 B 保持撤销前状态**逐位可查**），并给出依据三元组
  （声明 = `B.dy := A.dy` 的依赖；实测 = A 撤销后 B 的目标来源消失；没做什么 = 未静默漂移、未提交违规候选）。
  **结局 ③ 不通过（`failed`）** —— **静默漂移**：B 随 A 一起回到 0.00 而记录里**没有任何**关于依赖失效的
  说明/判定；或两条路径都未声明就宣称完成。
- **预期结果类型**：`正确拒绝` / `完成`（二择一，如上）。

**T11 · A16a（L4，完成类，需授权写回；仅 D1）**
- **目标 gid**：`intent.main.label.A`（`simple_figure.py` 的 `LAYOUT_MM` 已声明该键）。
- **位移**：上移 `[0.0, +0.50]`（绝对目标 = `LAYOUT_MM["intent.main.label.A"] = [0.0, 0.50]`；起点 `[0.0, 0.0]`，
  方向 = 上）；**并持久写回源码**。
- **涉及文件**：`<T>/tree/examples/python_native/simple_figure.py`（**唯一**允许写回的文件，且只在真人授权下）；
  科学荷载 = `load_science()` 的确定性解析曲线（受保护）。
- **基线条件**：冻结夹具（`LAYOUT_MM` 两键全 `0.0`）；绑定形态 = **已声明** `LAYOUT_MM`；旧科学基线指纹
  + gid 集合冻结。
- **可用入口**：V = `/api/plans`（PENDING）→ 真人在**真实页面**点授权（单次使用 grant）→
  `/api/plans/<id>/apply`（经 `<harness>/hubctl.py` 往返、`<harness>/poll_plan.py` 轮询）；
  L/A = **结构性不可用**（§3.2 第 5 项）。
- **容差**：0.01 mm。
- **判定**：独立重建 `Δy = +0.50 ± 0.01`；磁盘 == 计划 after（字节比对）；旧科学基线指纹与 gid 集合**逐位
  不变**；除 `LAYOUT_MM` 该一行外零改动。真人选区必须是 `human_page`（真人在真实页面点选），等待时长
  **计入** `human_wall_clock_s`（A16a 冻结样例 = 39.977 s），**不进** D2 完成时间。
- **预期结果类型**：`completed`（需授权写回）。臂 L/A 记 `structural_unsupported`（D1a = 结构性不可用）。

**T12 · A16b（L4，完成类，需作者化 + 授权写回；仅 D1）**
- **目标 gid**：`intent.main.label.A`（`legacy_plain.py` 基线里**没有**该键的布局声明）。
- **位移**：上移 `[0.0, +0.50]`（方向 = 上；绝对目标由写回后的源码声明给出）；**并写回源码**。
- **涉及文件**：`<T>/tree/examples/python_native/legacy_plain.py`（唯一允许写回的文件）；科学荷载不变。
- **基线条件**：冻结夹具；脚本**无任何布局绑定**（`grep -n LAYOUT_MM <夹具>` 空输出，§1.2 已登记）→
  必须**作者化**引入**源码声明**的布局入口；绑定形态 = **未声明**。
- **可用入口**：V = `python_native`（AST 定位）+ `authoring.build_repair_spec`（提案）+
  `/api/plans` → 真人页面授权 → `/apply` + `source_writes`（before bytes + CAS）；L/A = **结构性不可用**
  （§10.4 / §8 第 19 条已锁定）。
- **容差**：0.01 mm。
- **判定**：独立重建 `Δy = +0.50 ± 0.01`；科学指纹不变；**写回后源码内存在源码级声明的布局入口**
  （常量/声明可被 AST 定位命中，而非运行期改 Artist）；链路留证 = `plan_layout_edit → NEEDS_AUTHORING`
  （零写入）→ PENDING → 真人授权 → apply 的 `COMMITTED…` 记录。真人选区 + 真人页面授权（臂 V 单次 grant）
  为必需，等待计入 `human_wall_clock_s`。
- **预期结果类型**：`completed`（需授权写回）。臂 L/A 记 `structural_unsupported`。

**备选 4 条（A22、A18、A19、A17）** 按同一字段口径下发；A19 的「外部改动」只施加在 `<T>/candidate/`
工作副本上，A17/A19 的写回判定分别走 `source_writes` 的 before bytes + CAS 与 Science Oracle（臂 L/A
结构性不可用，§11.1.1）。

#### 11.1.5 多结局题的可接受结局与判定顺序（**冻结**；判分器只按本表裁定）

| 题 | 结局枚举 | 各结局的独立判定条件（摘要） | 判定顺序 | 真人参与 |
|---|---|---|---|---|
| **A13** | ① 经授权完成 / ② 报耦合 + 方案 / ③ 不通过 | ① = 请示记录 + 真人决策回执 + B `Δy=+0.30`、A/C `Δy=0.00`（各 ±0.01）+ 键值与实测间距一致；② = 依据三元组 + 双键方案数值 + `human_decision_required`；③ = 单键 / shift 抵消 / 动 A / 无请示直达候选 | ③ → ① → ② → `failed` | ① 需要；② 不需要 |
| **A24** | ① 完成 / ② 正确拒绝 / ③ 不通过 | ① = 4/4 scope 齐备且无新增阻断项、只改 `label_edge_margin_mm`；② = 判分器自建显示 ≥1 个 scope 新增阻断项且依据点名 scope + `diagnostic_key`；③ = 只查 main / 漏列 scope / 改其它 scope | ③ → ② → ① | 否 |
| **A15** | ① 重算完成 / ② `UNDO_CONFLICT` / ③ 不通过 | ① = 显式声明重算 + B `Δy=+0.20`、A `Δy=0.00`；② = 显式报冲突 + 未产生新候选 + 依据三元组；③ = 静默漂移或两条路径都未声明 | ③ → ① → ② | 否 |
| **A10** | ① 如实判 FAIL / ② 不通过 | ① = 实测 `[0, +0.11]` + 报残差 −0.04 超差 + 未 accept 未声称完成；② = 声称完成 / 接受给定候选 / 以「数字变了」为依据 | ② → ① | 否 |
| **A12** | ① 正确拒绝 / ② 误接受 | ① = 依据三元组 + 未提交违规候选 + 拒绝后重建 = 基线逐位相同；② = 接受 / 声称完成 / 改科学数据绕过 | ② → ① | 否 |

**纪律（逐字）**：上表五条题的多结局条件**在冻结期内写死**；运行中/运行后**不得**新增结局、不得改动
判定顺序、不得用「受试者自报读数」代替判分器的独立重建。凡本表未列的结局形态，一律归入该题的
`③ 不通过` / `② 误接受`，并在报告里逐条列出（**不得**就地发明新结局）。

### 11.2 臂序随机化规则（**每条 trial 的三臂执行顺序随机且记录种子**）

- 开跑前生成并落盘**一个**种子：`<archive>/g6b-v2/round/round-seed.txt`（单行；轮次期内**不得改**，
  改了 = 整轮作废）。
- 每条 trial 的顺序 = `random.Random(f"{SEED}:{task_id}").shuffle(["L","A","V"])`：逐 trial 随机、
  由种子**可复现**、可事后核对；只决定执行次序，不改变题面/夹具/判据（§3.1）。
- 生成命令（先铸种子，再生成 12 条主选的顺序表，逐字落盘 `arm-order.json`）：

```bash
mkdir -p <archive>/g6b-v2/round
python -B -X utf8 -c "import secrets; print(secrets.token_hex(16))" > <archive>/g6b-v2/round/round-seed.txt
cat <archive>/g6b-v2/round/round-seed.txt
python -B -X utf8 -c "
import json, random
seed = open('<archive>/g6b-v2/round/round-seed.txt', encoding='utf-8').read().strip()
tasks = ['A09','A10','A14','A07','A08','A12','A13','A11','A24','A15','A16a','A16b']
order = {}
for t in tasks:
    arms = ['L','A','V']
    random.Random(seed + ':' + t).shuffle(arms)
    order[t] = arms
with open('<archive>/g6b-v2/round/arm-order.json', 'w', encoding='utf-8') as fh:
    json.dump({'seed': seed, 'order': order}, fh, ensure_ascii=False, indent=2, sort_keys=True)
print(json.dumps(order, ensure_ascii=False))
"
```

- 配套纪律：**同一时刻只跑一条 trial**（v2 §4；臂顺序不是并发许可）；盲法改名只改 `trial_id`
  （产出物名 `trial-<random-id>`），**不改**记录内 gid 原文（§8.4 条件 6）；揭盲在 D1b/D2 统计完成后
  一次性进行（§8.2 第 9 条）。

### 11.3 模型与预算冻结

| 项 | 冻结值 / 状态 | 证据 |
|---|---|---|
| 会话头模型标识（实测，逐字） | **`opencode-go/deepseek-v4.1-flash`** | 三个独立读法：① 本冻结单元会话头（harness 注入）；② 运行器日志 `~/.omp/logs/omp.2026-10-13.<pid>.log`——同日多条 `"provider":"opencode-go","model":"deepseek-v4.1-flash"`；③ 预检 §4.1 |
| v2 §3.4 冻结值（逐字） | `opencode-go/deepseek-v4.1-flash:high` | 与实测标识的差异**只在推理档**：档位与提供方在会话内**读不到**（环境变量、`~/.config/opencode/*.json`、运行器日志均无 variant/effort 字段）→ 由**父代理**在运行器侧读取并登记（§3.4 ②） |
| 三臂运行器配置 | **需父代理登记**（同一标识、同一档） | §3.4 ④；只换一臂 = 该轮作废 |
| 受试模型的最小可用调用 | **需父代理执行**（本单元**有模型调用通道**，但通道背后的模型不是冻结标识） | 见下「最小可用调用」 |
| token 口径 | **不可测 → M=40k 未被执行** | 见下「token」 |
| 预算 | **N=30 tool calls / T=20 min**（可执行约束） | §3.1；超限 = 该 trial 记 `failed`，**不补不重试**（§5.5） |

**口径差异登记（避免混记）**：父代理简报中把会话模型写作 `opencode-go/deepseek-v4-flash`（缺 `.1`）；
以运行时会话头与运行器日志实测为准 = **`opencode-go/deepseek-v4.1-flash`**（差异仅为转写，非配置差异）。

**最小可用调用（真实回执，逐字）**：本单元可发起的模型调用通道 = eval `completion` / `judge_batch`；
实际调用一次，原始回执：

```text
completion("Reply with the single word: OK", model="smol")
  → id=cmp-15a45e60aa6eb639  status=completed  文本="OK"
completion("Reply with the single word: OK", model="default")
  → id=cmp-15a45e73782eb63b  status=completed  文本="OK"
judge_batch({"probe":"The sky is blue."}, {"q":{"type":"bool","instructions":"Is the sky described as blue?"}},
            intent="freeze-probe").status()
  → {"id":"jdgb-15a45e75076eb63c","intent":"freeze-probe","total":1,"done":1,"failed":0,
     "cost":1.1676e-05,"running":false,"model":"typesafe/jev-1.13.0","elapsedS":7.7}
  → 判定回执：{"probe": {"q": {"type": "bool", "bool": 0.99}}}
```

**判定**：`completion` 回执**不含模型标识**（handle 只暴露 `id` / `kind` / `status`）；
`judge` 明确报 `typesafe/jev-1.13.0` ≠ 冻结标识 → **两条通道都不能充当 §3.4 ③「冻结标识在运行当日
可用」的证据**。故「该标识可用」的最小调用回执**由父代理执行并登记原始回执位置**，并与 token 通道
核对**同一次**完成（§3.4 末行）。若当日该标识不可用：三臂**统一**换为当日默认模型并重新记录。

**token：不可测 → M 未执行（证据）**：

- eval 侧 `judge_batch.status()` 字段 = `{id,intent,total,done,failed,cost,running,model,elapsedS}`
  —— **无 in / out / reasoning token 字段**；`completion` handle 只暴露 `id` / `kind` / `status`。
- 运行器日志中对会话模型的调用记录（`"message":"agent_end maintenance routing","provider":"opencode-go",
  "model":"deepseek-v4.1-flash"`）**不含 `usage` 字段**；同日带 `usage` 的日志行**全部来自标题生成器**
  （`"message":"title-generator: success","model":"monk/monk-fast"`），不是受试 Agent 的调用。
- `~/.omp/agent/agent.db:model_perf` 只有**按模型的聚合**项
  （`model_key|samples|output_tokens|gen_ms|ttft_ms`，如 `opencode-go/deepseek-v4.1-flash` 的
  `samples=218` 一行），**无逐调用回执**、无法按 trial/臂归属 → 不符 §5.1「运行器给出的真实用量」口径。

→ 逐字声明并入轮次记录：**「本轮 token 上限 M=40k 未被验证执行」**；**不得**填 0、**不得**填估计值、
**不得**用 `null` 冒充 0（§6.1）。**短期不可测 → 长期不可测的降级声明必须写进轮次记录，不得只写在摘要里。**

### 11.4 构建数口径：**禁止跨臂比较**（结论逐字照抄 + 证据）

判据 = §6.2（替换 v2 §5.2 末条）：**跨臂比较的充要前提 = 三臂可量且口径同一**。逐字结论：

1. **没有任何一对臂可以跨臂比较 `real_figure_builds`**（臂 L 结构性不可量 → 三臂可量前提不成立）。
   报告必须写「**单臂记录，不作跨臂比较**」。
2. **臂 A 与臂 V 可以各自产出单臂计数**（同一计数器口径、同一 `sitecustomize` 注入）；
   **不得**把 A 与 V 的这两个值直接当跨臂结论（三臂不齐即禁比）。
3. **臂 L 的构建数记「不可测（结构性）」**：其白名单内**全部**入口都是脚本子进程路径、恒 0 行；
   **不得**填 0，**不得**据此声称臂 L 构建数更少。
4. 判分者侧 `measure.py`（独立重建）三臂各 **4 行**，是**判分器**的构建，**不得**混入臂间指标。

证据（驱动脚本 `formal-precheck-buildcounter.sh`，原始输出
`<archive>/g6b-v2/formal-precheck/results-buildcounter.txt`）：

| 臂 | 白名单内的入口 | 实测计数行 | 可量性 |
|---|---|---|---|
| 臂 L 旧手工 | 候选**纯文本副本**编辑 + `figpact render` / `try` / `validate` / `export` | 全 **0 行**（5 入口 × 3 棵树 = 15 次实测） | ❌ **结构性不可量** |
| 臂 A 现 Agent API | `figpact agent` 五操作 + `IntentSession.evaluate/decide` + 只读 Scene/Inspector | **2 行**（`agent` 入口） | ✅ 可量（会话级） |
| 臂 V vNext | `inspector_demo` + Inspector 服务 + `hub.py` 闭环 + `python_native` + `authoring` + `source_writes` + `history` | **2 行**（`agent` 入口）/ **2 行**（`inspector_server` + `GET /api/frame`） | ✅ 可量（会话级） |

**0 行不得读作「没有构建」**（§3 否证纪律）：同一批 0 行入口真的干了活——直接跑脚本产出
`simple_figure.png`（24,311 B）、`render` 报「`…/simple_figure.png（3 个图元）`」、`try` 打印真实试算
——它们由**脚本自身/子进程**建图，从不构造 `FigureSession`，故被包装的
`FigureSession._call_builder` 恒不被调用。计数语义仍按 §5.2：**1 行 = 1 次真实整图构建**。

### 11.5 开跑清单（**开跑那一刻执行**；逐条留证，任一条不过 = 不得开跑）

1. **逐 trial 目录骨架 + H4 布局 + 提取树**（每 trial 一份，§4.1 / §4.3 / v2.1 §4）：

```bash
mkdir -p <T>/{tree,tmp,mpl,state,out}
cd /d/L/AI/figpact
git -c core.autocrlf=false archive f101113476cf3f0113ccbb5e054d700d8c0a433a | tar -x -C <T>/tree
ls <T>/tree | head                                    # 期望列出 .gitignore CONTEXT.md README.md … tools
test ! -e <T>/tree/tmp && test ! -e <T>/tree/mpl && test ! -e <T>/tree/state && echo H4_OK
```

2. **科学输入复制 + manifest 校验**（顺序 = 夹具哈希核对**之后**；不得改工作树/仓库，§10.3）：

```bash
python <archive>/g6b-v2/formal-precheck-copy-science.py <archive>/g6b-v2/nmr-science-manifest.json <T>/tree/examples/nmr
python D:/L/AI/figpact/tools/science_manifest.py --verify <archive>/g6b-v2/nmr-science-manifest.json --root <T>/tree/examples/nmr
```

   期望（逐字）：`OK: all 99 files match (size + sha256)`、`exit=0`（99 files / 4,278,572 bytes）；
   任何缺失/多出/内容不同 → 退出码 1 → **该 trial 不得开跑**。

3. **泄漏检查四项**（每 trial 收尾执行并留证；v2 §4 + v2.1 §4 第 (2) 项含布局核对）：

```bash
cd <T>/tree && sha256sum "examples/nmr/08 NMR.py" examples/nmr/nmr.yaml \
  examples/python_native/simple_figure.py examples/ftir/plot_ftir.py examples/ftir/ftir.yaml \
  examples/python_native/legacy_plain.py              # (1) 逐字等于 §1.2 的 commit 列
ls <T>/state                                          # (2) 只含本 trial 的 checkpoint/plan/journal，id 可列；并复核 H4 布局
git -C /d/L/AI/figpact status --porcelain             # (3) 必须为空（空输出 = 通过）
netstat -ano | grep -E ':(8(7|8)[0-9][0-9])\b'        # (4) 本 trial 起的端口已停
tasklist | grep -i python                             # (4') 本 trial 起的进程已停（须人工核对 pid 属于本 trial）
```

4. **会话级构建计数器自检**（三臂用**同一条**命令，§3 修正后的唯一模板）：

```bash
cd <T>/tree
FIGPACT_TRIAL_TREE=$PWD \
PYTHONPATH=<harness> FIGPACT_BUILD_COUNTER=<T>/out/builds-probe.txt \
TEMP=<T>/tmp TMP=<T>/tmp TMPDIR=<T>/tmp MPLCONFIGDIR=<T>/mpl PYTHONDONTWRITEBYTECODE=1 \
python -B -X utf8 <harness>/measure.py \
  examples/python_native/simple_figure.py <empty-config.yaml> \
  examples/python_native/simple_figure.py <empty-config.yaml> \
  main 120 intent.main.label.A
```

   登记三项：命令原文 + 自检件路径 + 新增行数基线（期望 **4 行**）；**并同时登记回执内容**
   （`figpact agent` 出错仍返 exit 0，§3）。

5. **臂序随机化表**（§11.2 命令）→ 落盘 `round-seed.txt` + `arm-order.json`，种子写进轮次记录。

6. **盲法与人员安排（人员要求，无命令）**：记录员 ≠ 判分者（§8.1 第 8 条）；产出物改名
   `trial-<random-id>`（只改 trial id）；checklist 版本号逐字记录（§10 行「盲法命名与 checklist 版本号」）；
   揭盲在 D1b/D2 统计完成后一次性进行（§8.2 第 9 条）。

7. **A16a / A16b 的真人环节**：两题选区必须是 `human_page`（真人在真实页面点选）；臂 V 的写回走
   **单次 grant**（`/api/plans` → PENDING → 真人点授权 → `/api/plans/<id>/apply`，经 `<harness>/hubctl.py`
   往返、`<harness>/poll_plan.py` 轮询）；真人等待**全部**计入 `human_wall_clock_s`、**不进** D2 完成时间
   （§7 人时口径；A16a 的冻结样例 = 39.977 s）。**A16b / A17 的判分读法见 §12.3**：Hub 返回的
   `COMMITTED_AND_VERIFIED` **不计**为科学验证通过，两题的 `completed` 只由判分者自建重建判定。

8. **A08 端点字段与转录口径登记**：每条记录必须带 `guide_scientific_endpoint_error_mm` +
   `guide_label_endpoint_delta_mm` + 端点定义 + 取自哪次重建 + 单位精度（缺一 → 不入比较分母）；
   pilot 原件**不可达**（`<archive>/g6b-pilot/` 不存在）→ 按 §8.4 条件 5 的**替代口径**登记为
   「**原件不可达 + 转录口径**」，不得声称已对 pilot 原始 JSON 做逐字节复核。

9. **D1a 16 行裁定冻结 + 题单冻结**（v2 §2.4、§8.3）：矩阵本体 = **§11.1.1**（16 行 × 3 臂，逐格定稿）；
   题单 = §11.1（12 条主选，含 D2 = 9 的核对与「D2 下限纪律」）；两者与本 §11.1.4 的 12 张输入卡**同批**
   落盘并写入轮次记录；跑完不得改（红线 13）。

10. **开跑前仓库状态记录**：执行 `git -C /d/L/AI/figpact status --porcelain` 并留证，写明哪些改动属
    冻结基线之外的并行工作（预检时该输出**非空**：`tests/browser/conftest.py`、`docs/UI/`、
    `docs/figpact-vnext-kit/`、`tests/browser/test_authoring_writeback_flow.py`，均来自其它单元）。

11. **作废条件提醒**（红线 13 / §8.3）：判据被放宽 / 模型或预算不一致 / 隔离被破坏 / 冻结项被事后修改
    → **整轮作废重跑**。

---

## 12. 已知语义限制：Hub 的 `COMMITTED_AND_VERIFIED`（登记节；不新增任务/分母/指标）

**地位与依据**：本节按用户裁定（2026-10-13）**逐条登记**一条既存的语义限制，并**写死正式轮的判分口径**。
本节不替换 v2 / §1–§11 的任何条款，只对一条已有返回值的语义边界作出声明；它**不新增任务、不新增分母、
不新增指标**，也**不改任何产品代码**（§12.4）。

### 12.1 调用链（`figpact/hub.py`，`SessionHub.apply_plan()`）

`POST /api/plans/<id>/apply` 的链路逐字为：

**授权校验 → journal 写盘（`source_writes.apply_source_change`）→ 逐文件字节确认 → 返回
`COMMITTED_AND_VERIFIED` → History 检查点**。

1. `apply_plan(plan_id, client_id)` 的校验顺序，**任一不过 = 零写入 + 409**：`client_id` 非空 →
   计划存在且 `state == 'AUTHORIZED'` → 计划未过期 → 请求方就是申请该计划的 `client_id` →
   grant 存在、未过期、未使用 → journal 仍 `PREPARED` 且 before 哈希与计划一致 →
   **磁盘每个文件逐字节 `sha256` == 计划的 `before_sha256`**（否则 `STALE_SOURCE`，拒绝覆盖）。
2. 全部通过后才动手：grant 记为已用、`plan['state'] = 'APPLIED'`，交给 G3b 的可恢复写入
   `source_writes.apply_source_change(plan['journal_id'])`。
3. `python_native._journal_commit_state(applied)` 把 journal 状态映射成返回值：journal `COMMITTED`
   → **`COMMITTED_AND_VERIFIED`**；`RECOVERY_REQUIRED` → `RECOVERY_REQUIRED`；其余 → `NOT_WRITTEN`。
   这里的 `COMMITTED` 本身就是**逐字节复核过的写入事实**（`_journal_commit_state` docstring 原文：
   「`COMMITTED` 是逐字节复核过的写入事实」）。
4. 只有 `COMMITTED_AND_VERIFIED` 时才 `_append_source_change(...)`，在 History 追加一条
   `source_change` 检查点。

**这条 HTTP 路径自身不调用独立进程重新构图，也不跑 Target Oracle / Science Oracle。**

### 12.2 这条链证明了什么、没证明什么

- **成立（源码写入验证）**：源码已按计划写盘，且 **journal + 逐文件磁盘 `sha256` 比较**确认写入字节
  == 计划的 `after_sha256`。这是**写入事实**与**字节一致性**的证明。
- **不成立（科学与几何验证）**：`COMMITTED_AND_VERIFIED` **不含**「目标 gid 实测位移已达成」或
  「科学载荷 / 峰位数据未变」的任何断言。**科学与几何验证只有另行重建才能给出**（独立进程重新构图 +
  Oracle 取数）；本轮浏览器验收里该验证之所以成立，是因为验收**另行做了一次独立重建**，**不是**
  因为 Hub 返回了 `COMMITTED_AND_VERIFIED`。
- **逐字结论**：**Hub 的 `COMMITTED_AND_VERIFIED` 不得被读作「目标位移与科学内容已验证」。**

### 12.3 正式轮判分规则（**写死**）

1. **独立判分器必须自建重建**：判分者按 v2 §5.3 从该 trial 的提取树 + 冻结夹具 + 该 trial 候选，
   在**独立进程**内重新构图并取数（`measure.py` 等）；**不得**复用生产者返回的数值/状态，**不得**
   引用生产者进程的内存或回执。
2. **`completed` 只由自建结果判定**：`completed`（v2 §3.3、§5.3；D1b 分子）**只**在该 trial 的
   **自建重建结果**满足判据（独立重建实测位移 − 目标位移 ≤ 0.01 mm、Target Oracle 全 PASS、
   Science Oracle 判定科学载荷未变）时才记 `completed`。
3. **A16b、A17 尤其不得**把 Hub 返回的 `COMMITTED_AND_VERIFIED` 计为**科学验证通过**：
   - **A16b**（`legacy_plain.py` +0.50 mm，须作者化写回）：该返回值**只**证明源码已写盘且字节一致；
     该题判 `completed` 仍需**自建重建**测出 Δy = +0.50 mm（残差 ≤ 0.01 mm），且旧科学基线指纹与
     gid 集合逐位不变。
   - **A17**（改源码导致峰位数据变）：即便写盘成功并返回 `COMMITTED_AND_VERIFIED`，该题的正确结果
     仍是**正确拒绝**，判据是**自建 Science Oracle** 判 FAIL → 禁止成功/发布。**写盘成功 ≠ 该题可判
     成功**，更不得因为返回了 `COMMITTED_AND_VERIFIED` 就把它当作科学验证通过。
4. **记录要求**：trial 记录里若出现 `COMMITTED_AND_VERIFIED`，必须**同时**分列两个字段——
   「出自生产者回执的 `commit_state`」与「判分者**自建重建**的实测结果」——并注明两者是**不同**的
   证据来源；**只有**自建重建的字段进 D1b / D2 分子。

### 12.4 产品层待开票项（**本轮不改 `f101113`**）

- **已知歧义**：单一字段 `commit_state` 同时承载「源码提交状态」与被读作「图表验证状态」两种含义，
  返回值本身无法区分二者。
- **待开票（产品层后续工作，不属本轮）**：其一，把 `source_commit_state` 与
  `figure_verification_state` **拆成两个字段**（或在返回值里显式标注「本字段不含科学/几何验证」）；
  其二，**在返回成功前真正接入独立验证**（另起进程重新构图 + Oracle 取数），使成功返回同时携带
  几何/科学结论。
- **本轮边界（逐字）**：**本轮不改 `f101113`**——本节只把该限制**登记**为已知语义限制，正式实验
  **不得掩盖**；任何「因为 Hub 返回成功所以科学验证通过」的推理在正式轮**一律作废**。

### 12.5 科学输入描述更正（99 件的构成与校验时点）

- **构成（逐字）**：manifest 的 **99 件 = 88 件原始仪器数据 + 11 件导出图件**（范围见 §10.3）。
  不得笼统称作「原始科学数据」；`Fig2_*/Fig_S*` 是示例**产物**（导出图件），不是仪器数据。
- **校验时点**：试验运行中会**重新生成导出图件** → 按**既定基线时点**（拷贝那一刻）校验；**正常的
  图件再生成不算「科学输入改变」**，不得据此判失败（只校验 `核磁原始数据/` 子树亦可，§10.3 末条）。
- §1.2「随附收编」里的「本轮臂 V 复制 88 个文件」是**短复验**的实测记录（当时只复制了仪器数据
  子集），**不是**正式轮的科学输入全集；正式轮全集 = §10.3 的 99 件。

### 12.6 基线与证据来源（一句话）

**受试代码固定 `f101113`，证据可来自后续提交。** 受试引擎代码 = 冻结基线
`f101113476cf3f0113ccbb5e054d700d8c0a433a`（§10.1），**不得**把受试代码机械改到后续提交；而
**测试证据、协议文本与判据登记**可以来自后续提交（如 `3cbf046`）。本节 §12.1 引用的
`figpact/hub.py` / `figpact/python_native.py` 在 `f101113` 与 `3cbf046` 之间**逐字节相同**
（`git diff --stat f101113 3cbf046 -- figpact/hub.py figpact/python_native.py figpact/authoring.py
figpact/source_writes.py` 空输出），故在后续提交工作树里读到的调用链**在冻结基线上同样成立**。

### 12.7 正式轮检查

- 每一条 `completed` 都必须能指向**自建重建**的原始输出（命令 + 回执 + 树内路径）；
- A16b / A17 的记录里必须出现 §12.3 第 3 条的显式结论；
- 任何把 `COMMITTED_AND_VERIFIED` 当作科学验证通过的记录 → **该条不得进入分母**；
- 若发现产品已把两者合并的返回值当成功依据 → 记入 §12.4 待开票项，**不**改受试代码。
