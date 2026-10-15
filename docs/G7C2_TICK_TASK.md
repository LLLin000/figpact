# G7-C2b 任务书：让 NMR 的刻度字号成为**可安全修改**的角色

**基线**：`D:/L/AI/figpact` @ `master`。C2 已实现三角色受控修改，但 NMR 的 `tick_font_pt` 被判"无安全修改入口"而**拒绝修改**（仍 8.0 pt，目标 7 pt）。本任务只解决这一件事。

## 问题
- `examples/nmr/nmr.yaml` 里**存在** `tick_font_pt: 8.0`。
- 但保存/修改路径判定该角色**没有安全修改入口**，因此拒绝。**不能**因为"键恰好存在"就允许编辑。
- 必须先查清**真实原因**，二选一：
  - **(a) 缺绑定声明**：脚本/样式模块没有把该键声明为受支持的参数 → 补上**可验证**的绑定。
  - **(b) 死键**：脚本根本没读这个键（改了也不影响图）→ **如实报告为不支持**，给出证据（例如改键后实测字体不变），**不得**假装支持。

## 目标文件
- 允许：`examples/nmr/8 NMR.py`（注意实际文件名含空格：`examples/nmr/08 NMR.py`）、`examples/nmr/figure_style.py`（**仅**绑定/参数声明部分）、必要时 `figpact/final_size.py`（仅当缺口在引擎的角色映射）、**新建** `tests/test_nmr_tick_role.py`
- **禁止**：改 `examples/ftir/*`、改任何 TIFF/PDF/PNG/SVG 输出、改 `figpact/intents.py`、`figpact/source_writes.py`、`tools/inspector/*`
- 无 git 写操作。

## 硬约束
1. **不得改变任何既有输出**：在**配置值不变**的前提下，NMR 图的科学指纹、实测几何、导出尺寸必须与修改前**一致**（给前后实测对照）。绑定声明是"让能力可见"，不是"改变默认渲染"。
2. **不得放宽安全判定**：只补**真实存在**的绑定；绑定必须真的驱动图上的刻度字号。
3. **不得写桩**：不接受 `assert True`、不接受 mock 掉测量。

## 验收（必须真实跑通并给原文数字）
1. **tick 角色可改且可验证**：在 **TEMP 副本**上把 NMR 目标设为 **42 mm**、tick 目标 **7 pt** → 修改后**实测 effective pt ≈ 7**（给出实测值与容差），且 **k ≈ 1**。
2. **（b）情形的诚实出口**：若查明是死键、无法在不改科学内容的前提下支撑目标 → 输出明确不可行报告（点名角色与原因），并在本文档同目录留下结论；**不得**为凑绿而硬接一个不改图的键。
3. **无副作用证明**：配置不变时，NMR 的 `figure_verification_state` 走既有验证路径得到 **PASS**，且科学指纹与几何**前后一致**（给对照）。
4. 测试 `tests/test_nmr_tick_role.py`：①绑定存在时 tick 可改并实测生效；②配置不变时渲染与科学指纹一致；③若角色仍不可改，测试必须断言"拒绝并给出原因"而不是通过。
5. 跑并报：新建测试 + `tests/test_final_size_audit.py` + `tests/test_final_size_apply.py` + `tests/test_python_native_edit_flow.py` 的 pytest 尾部。

## 环境
`TEMP/TMP/TMPDIR/MPLCONFIGDIR` 指向 `D:/L/AI/figpact-archive/g6b-v2/tmp*`；`MPLBACKEND=Agg`；`PYTHONDONTWRITEBYTECODE=1`；`D:/programs/Python/python.exe -B -X utf8`。
