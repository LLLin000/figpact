# G13：用通用机制扩展 `legend` / `panel.label` 的角色覆盖

**前置（已冻结）**：`figpact/roles.py`（角色注册表，唯一语义来源）+ `figpact/change_audit.py`（对象级审计，两条件）+ `init_contract`（发现/确认/扰动）。
**唯一范围**：把 `legend` 与 `panel.label` 纳入通用机制。**不新增图种、不扩 GUI、不给具体 Artist 写专用分支**；必须通过**注册表条目 + 绑定规则 + 扰动验证**实现。

## 要做的事

1. **注册表条目**（`roles.py`）
   - `legend`：`artist_kinds` 含 `Legend`；`properties` 至少含 `fontsize`（若可绑定）；`measurement` 复用既有实测口径（`nominal × k`，字形仅作一致性证据）；`capability` 按实际能力标注；`aliases` 兼容历史名。
   - `panel.label`：`artist_kinds` 含 `Text`（**仅限被识别为面板标签的文本**——定义必须可判定：如位置在轴外/角、或由契约显式声明；**不得**把任意 Text 当 panel label）；`properties` 含 `fontsize`。
   - 若某角色在当前夹具上**无法可靠判定**归属 → 保持 `unresolved` 并写明判定缺口，**不得强行归属**。
2. **绑定与可编辑性**：沿用 G11/G12 —— 只有"人工确认 + 非零扰动 + 身份一致 + 无越权"才 `E✓`；否则 `E✗`/`unresolved`。
3. **策略不变**：`legend` 与 `panel.label` **只比较、不强制统一**（`F–` 或按 profile 显式指定）；**不得**因新增覆盖而自动统一。
4. **审计**：这两个角色的扰动同样走 `change_audit`（`Actual ⊆ Allowed` ∧ 目标确实变化），不得绕开。

## 验收

1. `figpact plate compare` 的 4 图表中，`legend` / `panel.label` 的 `C/E/F` 标注与**实际能力一致**（能测则 `C✓`；有已验证绑定则 `E✓`；否则 `E✗` 或 `unresolved`）。
2. 覆盖率报告更新（分母恒 6）：给出 `verified_editable / candidate / unresolved / unsupported` 的新计数与理由。
3. 两条**反例**：①把任意 `Text` 当 panel label → 必须拒绝或标 `unresolved`；②对 `legend` 做**无效扰动** → 不得升 `E✓`。
4. 端到端复归：demo/FTIR/SVG/PNG 行为与科学边界不变；既有 **32** 项测试保持通过。
5. 报告：每个新角色的"是什么 / 由谁控制 / 允许改什么 / 改后是否生效 / 是否误伤"，各给一条实测证据。

## 环境
`TEMP/TMP/TMPDIR/MPLCONFIGDIR` 指向 `D:/L/AI/figpact-archive/g6b-v2/tmp*`；`MPLBACKEND=Agg`；`PYTHONDONTWRITEBYTECODE=1`；`D:/programs/Python/python.exe -B -X utf8`；无 git 写操作。
