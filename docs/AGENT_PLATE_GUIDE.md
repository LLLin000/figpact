# Agent 指南：plate（跨图件实测比较与源码级统一）

## 1. 这个工具是干什么的

让**各自独立的图件**在**最终物理尺寸**下**可比较**、按**源码**可统一，
并给出**可复算的证据回执**。三步闭环：`audit`（实测）→ `unify`（规划→
`--apply` 写源码→重渲染复测）→ `receipt`（JSON 回执，`content_hash`
逐字节可复算，`generated_at` 除外）。不做整版 GUI、不做审美排版、
不造第二套期刊规格词表。

## 2. 什么时候该用

- 多张**代码图**（脚本+YAML/契约）要统一最终尺寸下的轴标题/刻度/线宽；
- 多张**矢量图**要核对页面尺寸与文字字号；
- 需要向外部证明“统一前后都实测过”（回执 `before/after` + 双状态）。

## 3. 什么时候不该用

- 以**位图**为主：只能摆放，不能规格归一（字号/线宽不可恢复）；
- 需要整版 GUI 拖拽、自动审美排版；
- 需要改科学数据（谱线、窗口、归属）才能腾空间——工具拒绝，需人决策。

## 4. 输入/输出与错误码

- 输入：一组 `--figure script.py[,config.yaml][,scope][,label][:width]`，
  另给默认 `--width-mm`。自动按后缀判定 `code/vector/bitmap`。
- `plate audit [--json] [--out]`：人类可读表（正在做什么→表格→
  测不到什么→下一步）或 JSON。exit 0；输入缺失/路径错 exit 2（拒绝三段式）。
- `plate unify --axis-pt --tick-pt --line-pt [--target-width-mm]`：默认只
  给计划；`--apply` 才写。`feasible→0`，`infeasible→1`（含 gid 与超限量）。
- `plate receipt [--out]`：JSON 回执，字段见
  `docs/schema/plate_receipt.schema.json`。exit 0 / 2。
- 双状态：`dual_state.source_commit_state`（源码是否写入）与
  `figure_verification_state`（复测 PASS/FAIL/NOT_RUN）分开报告。

## 5. 最小示例

```bash
figpact plate audit --figure nmr.py,nmr.yaml --figure ftir.py,ftir.yaml --width-mm 42
figpact plate unify --figure nmr.py,nmr.yaml --figure ftir.py,ftir.yaml --width-mm 42 \
  --axis-pt 8 --tick-pt 7 --line-pt 0.8
figpact plate unify ... --apply   # 写入源码 + 重审计 + 回执
figpact plate receipt --figure nmr.py,nmr.yaml --width-mm 42 --out receipt.json
```
