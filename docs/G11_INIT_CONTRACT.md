# G11：`figpact init-contract` v0.1（严格最小闭环）

**只做这四步**：自动发现可编辑入口 → 人工确认绑定 → 扰动验证 → 四图复测。
**明确不做**：任意 Python 脚本的自动改写；不把"找到参数"当成"找到控制权"；不承诺任意图都能自动统一。

## 三个概念必须分开（继承 `b5bbafa` 的证据）

- **Measurable**：能否在最终版面测出实际值。
- **Editable**：是否存在**确定的源码参数** + 契约 + 经扰动证明的控制权。
- **Compliant**：最终测量值是否满足统一规范。
**碰巧达标 ≠ 受控达标**（demo 线宽 0.80 但 `E✗` 就是例子）。

## `E✓` 的判定（四项全满足）

```
源码绑定存在  ∧  实际扰动生效  ∧  对象身份一致  ∧  无意外副作用
```
扰动必须是**非零变化**（数值相同的角色也要扰动验证，不得凭相等升级）。

## 输入与产物

- 输入：**只读**脚本（+ 可选 YAML）。**绝不改写脚本**。
- 产物：**独立的 Contract Draft 文件**（如 `examples/demo/demo.contract.yaml`），由引擎直接加载；**人工确认后**其中的条目才生效。
- Draft 必须包含：`candidates[]`（role、参数键、源码位置 file/line/call、对应 artist GID、confidence）、`unresolved[]`（不得猜测）、`unsupported[]`、`coverage{}`。

## 发现范围（v0.1 只需覆盖这些常见入口）

`set_title`、`set_xlabel`、`tick_params`、`plot(linewidth=...)`；以及**配置键驱动**的常见写法（`cfg["axis_font_pt"]` 等）。
每项给出：**文件、行号、具体调用、对应 Artist（GID）**。
无法确定作用对象 → `unresolved`，**不得**猜。

## 验收边界（用户给定）

| 项目 | v0.1 要求 |
|---|---|
| 自动识别 | 上述常见入口 |
| 参数定位 | 文件 + 行号 + 调用 + Artist |
| 歧义处理 | 无法确定则 `unresolved` |
| 契约生效 | 必须人工确认后才允许修改 |
| E✓ 判定 | 必须通过实际扰动 |
| 安全约束 | **不得**改科学数据、坐标窗口、曲线数值、峰位 |
| 非代码图 | SVG/PNG 维持原边界，**不得**伪造编辑能力 |

## 覆盖率报告（必须避免虚假 100%）

```
verified_editable / candidate / unresolved / unsupported
```
**分母必须包含未知/未覆盖角色**（按既有 6 个角色计：axis.title、axis.tick、curve.linewidth、panel.label、legend、scalebar），不能把"没发现"从分母里剔除。

## 四图复测的明确目标（demo）

| 角色 | 当前 | 目标 |
|---|---|---|
| axis.title | 7.11，E✗ | **8.00，E✓ F✓** |
| axis.tick | 6.22，E✗ | **8.00，E✓ F✓** |
| curve.linewidth | 0.80，E✗ | **0.80，E✓ F✓（须非零扰动验证）** |

- FTIR 既有证据保留；其 `axis.tick` 的 `E✗` **保持不变**（除非本次为它建立了经过验证的绑定）。
- SVG / PNG **不得**因新增能力而被宣称可编辑。
- 额外交付：**契约覆盖率报告**（四类计数 + 分母说明）。

## 复用（不得另建对象识别系统）

复用既有 `inventory`、GID、`final_size` 实测、`apply_final_size`、`source_writes`、扰动/QA 路径；**不新建**第二套对象模型或测量。

## 交付证据

1. `init-contract` 在 `examples/demo` 上的 Draft 原文（candidates / unresolved / unsupported / coverage）。
2. 每条 `verified` 的**扰动证据**：改了什么、目标角色前后实测、非目标角色未变、科学指纹未变。
3. 四图 compare 的**统一前/后**表（demo 三个角色转为 `E✓ F✓`；SVG/PNG 不变；FTIR tick 仍 `E✗`）。
4. 覆盖率报告。
5. 测试结果（含"未确认不得生效""歧义不得猜""扰动失败不得升 E✓"三条反例）。

## 环境
`TEMP/TMP/TMPDIR/MPLCONFIGDIR` 指向 `D:/L/AI/figpact-archive/g6b-v2/tmp*`；`MPLBACKEND=Agg`；`PYTHONDONTWRITEBYTECODE=1`；`D:/programs/Python/python.exe -B -X utf8`。无 git 写操作。
