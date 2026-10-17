# G9 任务书：跨图件元素的"可测量 / 可统一"能力（最小可演示版）

**定位（一句话）**：让**各自独立的图件**在**最终物理尺寸**下**可比较**、按**源码**可统一，并给出**可复算的证据**。不做整版 GUI、不做 AI 审美排版、不造第二套期刊规格词表。

## 交付物（只改这些）
1. **新建** `figpact/plate.py`：`audit(figures, widths)` / `unify(plan)` / `receipt(...)`。
2. `figpact/cli.py`：**新增** `figpact plate audit|unify|receipt` 子命令（全部支持 `--json`；**不改**既有命令语义）。
3. **新建** `docs/PLATE_CAPABILITIES.md`：**输入类型 × 可测项矩阵**。
4. **新建** `docs/PLATE_POLICY.md`：**可统一 / 不可统一**清单与理由。
5. **新建** `docs/AGENT_PLATE_GUIDE.md` + **新建** `docs/schema/plate_receipt.schema.json`。
6. **新建** `tests/test_plate_audit.py`（含混合输入）。
7. **禁止**改 `examples/nmr/*`、`examples/ftir/*`、`tools/inspector/*`、`figpact/intents.py`、`figpact/source_writes.py` 的既有语义；无 git 写操作。

## 一、实测口径（不可妥协）
- **eff_pt**：先 `fig.canvas.draw()`，再 `Text.get_window_extent(renderer)` → 换算到**最终物理尺寸**下的 pt；**不得**用"声明值 × 缩放比"。
- **线宽**：取渲染后的实际值（pt）。
- **k**：用**实测导出尺寸**（临时目录导出，`bbox_inches` 的影响必须计入）与目标宽之比；`k>1`（会被放大）报 `infeasible`。
- **越界/重叠**：文本 bbox 与曲线**折线**判定；结果逐项给 gid。

## 二、按输入类型记录"能测/不能测"（写进 `PLATE_CAPABILITIES.md`，并在回执里体现）
必须覆盖三类，每格写**测什么、依据/精度、不能测什么**：
| 输入 | 能测 | 不能测 |
|---|---|---|
| **代码**（脚本+YAML/契约） | 画布 mm、各角色 pt、线宽、k、bbox、越界 | —（唯一能承诺 `k≡1` 的来源） |
| **矢量**（PDF/SVG） | 页面物理尺寸、文本位置/字号（若文字仍为文字）、路径 bbox | 已转曲/字体缺失时的字号与字形 |
| **位图** | 像素尺寸 × DPI → 物理尺寸、摆放位置 | **字号/线宽不可恢复**（只能估算），**不得**报规格达标 |
回执字段：`measurable_specs` / `unmeasurable_specs` / `measurement_basis`（方法+renderer+dpi）。

## 三、可统一 / 不可统一（写进 `PLATE_POLICY.md`）
- **默认可统一**（代码与矢量）：`axis.title`、`axis.tick`、`curve.linewidth` —— 目标由用户给定或外部 profile。
- **只比较、默认不强制统一**：峰/官能团**标注**、**图例**、备注（信息密度不同，强行统一会放不下）。
- **不可统一**：**位图的任何字号/线宽**、需要改科学内容才能腾出空间的项。
- 每条给**理由**与**拒绝时的替代方案**（加宽/移动/显式指定局部值）。
- **禁止自动缩字**；`unify` 放不下 → `infeasible`（含 gid、实测超限量）。

## 四、命令行为（用户可见）
- `plate audit`：先打印"**正在做什么**"（读了哪些图、按什么宽度、用什么方法），再表格，再"**测不到什么**"，最后"**下一步能做什么**"。
- `plate unify`：**先给计划**（每张图将改哪些键、旧→新），`--apply` 才写；写后**重新审计**并给回执。
- `plate receipt`：输出 JSON 回执（规格/实测/偏差/双状态/哈希/输入清单/时间戳）。
- 所有**拒绝**用三段式：**为什么不行 / 需要什么才能行 / 一条建议命令**。

## 五、Agent 面（`AGENT_PLATE_GUIDE.md`）
必须写清：
1. **这个工具是干什么的**（跨独立图件的实测比较与源码级统一 + 证据回执）；
2. **什么时候该用**（多张代码/矢量图的最终尺寸规格统一、需要可复算证据时）；
3. **什么时候不该用**（位图为主；需要整版 GUI 拖拽；需要自动审美排版；需要改科学数据）；
4. 输入/输出 schema、错误码、最小示例（读→规划→应用→拿回执）。

## 六、验收（父代理会执行）
1. 两张代码图 `plate audit --json`：输出**可横向比较**的实测表（含 k、eff_pt、线宽、越界），且逐项标注测量方法。
2. 混入**一张矢量 + 一张位图占位**：回执如实标 `unmeasurable_specs`，**不谎报**。
3. `plate unify --apply`：轴标题/刻度/线宽统一到目标后复测达标（各图极差 ≤0.25 pt），放不下时报 `infeasible`（含 gid 与超限量）。
4. 同输入重构两次：**回执逐字节一致**（时间戳字段除外，需在 schema 里说明）。
5. 三份文档与实现一致（字段名对得上）。

## 环境
`TEMP/TMP/TMPDIR/MPLCONFIGDIR` 指向 `D:/L/AI/figpact-archive/g6b-v2/tmp*`；`MPLBACKEND=Agg`；`PYTHONDONTWRITEBYTECODE=1`；`D:/programs/Python/python.exe -B -X utf8`。
