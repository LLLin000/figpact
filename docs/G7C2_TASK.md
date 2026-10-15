# G7-C2 任务书：Final-size 最小受控修改（第一版只统一三个角色）

**基线**：`D:/L/AI/figpact` @ `master`。本文件是 `docs/G7_PLAN.md` §5.2 / §5.5（阶段 C2）的实施规格。
**前提**：C1 只读审计已存在（`figpact/final_size.py`，`figpact final-size` 子命令）。C2 在它之上加**受控修改**。

## 目标文件（只改这些）
- 扩 `figpact/final_size.py`
- `figpact/cli.py`：**新增**子命令（**不改**现有命令语义）
- **新建** `tests/test_final_size_apply.py`
- **禁止**改 `figpact/intents.py`、`figpact/source_writes.py`、`tools/inspector/*`、`examples/*`（含任何输出文件）

## 第一版只统一三个角色
| 角色 | NMR 当前 | FTIR 当前 | 目标 |
|---|---|---|---|
| `axis.title` | 8.5 pt | 8.5 pt | 8 pt |
| `axis.tick` | 8.0 pt | 8.0 pt | 7 pt |
| `curve.linewidth` | 0.75 pt | 0.85 pt | 0.8 pt |

这些参数**已在真实配置中存在**（`examples/nmr/nmr.yaml` 的 `axis_font_pt` / `tick_font_pt` / `line_width`，`examples/ftir/ftir.yaml` 同名键）。

**只报告、不修改**的角色：FTIR 官能团标注（4.7 pt）、NMR 峰标注（6.0 pt）、图例、备注。它们虽同名 annotation，信息密度不同，强行统一可能让 FTIR 放不下。
**期刊规则不得写成全局常数**：若用户指定某刊风格，就按该刊规范检查；不得把 Nature 的下限当成对所有期刊强制生效。

## 两种缩放模式不可叠加（硬要求）
- **模式 B（实现）**：按**最终物理尺寸**重渲染 —— 目标轴标题 8 pt 就把"按最终尺寸重绘"的图设为 8 pt（即把画布宽设为最终宽度，`k ≡ 1`）。
- **模式 A（诊断）**：`f_final = f_source × W_target / W_export`，仅用于诊断外部缩放的后果。
- **不得**在模式 B 的基础上再乘旧宽度比，**不得**用原 48 mm 画布的比例补偿一次。**禁止叠加**。

## 写入必须走既有路径（不得新建写入器）
- 复用既有 **YAML 精确补丁 + 漂移检查 + 原子替换** 链路（`figpact/patch.py` / `figpact/source_writes.py`），并回传**双状态**（`source_commit_state` / `figure_verification_state`）。
- 写后**重新审计**（复用 C1 度量），回执里的 "PASS" 必须来自真实测量。
- **不新建**第二套样式真值、**不引入** `plate.yaml`、**不新建** `source_writer_v2`。

## 必须有的拒绝与不可行报告
1. **无安全修改入口** → 拒绝并点名角色与原因（来自既有绑定/契约，**不得自己猜**）。
2. **空间不足** → 输出**明确的不可行报告**：冲突对象 **GID**、实际位置与**实测超限量**、以及可选取舍（增加图宽 / 调整标注位置 / **显式**重新指定局部字号）。**不得**自动改科学视口、自动缩字或裁掉谱线；"明确告诉用户放不下"是**一次正确的系统结果**。

## 交付证据（缺一不可）
在 **TEMP 下的副本**上跑（不得改 `examples/`）：
1. **NMR 目标 42 mm**、**FTIR 目标 38 mm** 各一次受控修改：before/after 对照（配置键变更、画布宽、**实测导出宽**、`k`、三角色的**实测 effective pt**、线宽）。
2. **不可行报告原文**（FTIR label/legend 与 NMR note 低于地板；FTIR 引线超出画布顶部）。
3. `examples/` 的 **sha256 前后一致**证明 + `git status` 干净。
4. 测试：`tests/test_final_size_apply.py` 覆盖 ①三角色写入后实测达到目标（k≡1）②只报告角色**未被改动**③无安全入口时拒绝并给原因④空间不足时报告**含 GID 与超限量**⑤**模式 A/B 不叠加**（构造一个"若叠加会明显偏小"的用例并断言未叠加）。
5. 跑 `tests/test_final_size_audit.py` 与新建文件，给 pytest 尾部。

## 禁止
写桩或 mock 掉真实测量；改既有命令语义；任何 git 写操作；触碰 `examples/` 的任何文件。
