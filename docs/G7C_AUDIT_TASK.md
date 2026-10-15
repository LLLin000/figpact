# G7-C1 任务书：Final-size 只读审计

**基线**：`D:/L/AI/figpact` @ `master`。本文件是 `docs/G7_PLAN.md` §5.1（阶段 C1）的实施规格。
**产品红线**：本阶段**完全只读**——不新增任何源码修改能力，不写用户图件目录与 `examples/`。

## 目标文件（只改这些）
- **新建** `figpact/final_size.py`
- `figpact/cli.py`：**新增**只读子命令（**不改**现有命令语义）
- **新建** `tests/test_final_size_audit.py`
- **禁止**改 `figpact/hub.py`、`inspector_server.py`、`tools/inspector/*`、`examples/*`（有兄弟单元正在改前端）

## 输入
图件（脚本 + 可选 yaml）+ 目标最终宽度（mm）+ 共同目标（轴标题 pt / 刻度 pt / 线宽 pt，可选）。

## 输出：必须能回答这七项
1. **源文件画布宽度**（声明值）
2. **真实导出宽度**（实测页面尺寸——不是声明值）
3. **缩放因子** `k = 目标宽 / 实测导出宽`
4. **字体角色表**：轴标题 / 刻度 / 图例 / 标注 各多少 pt；**名义值**与**实测字形占用**必须**分开报告**，并注明两者不可直接比较（同 8 pt 不同字体字高/字宽不同，上下标与数学字体也不例外）
5. **线宽**实际值与目标差
6. **空间约束**：目标尺寸下有无裁剪 / 文字重叠风险（有则点名对象）
7. **编辑能力**：哪些字段存在**安全修改入口**（来自既有绑定/契约声明，**不得自己猜**）

## 测量红线（必须遵守；`docs/research/R2_restyle_implementations.md` 有实测陷阱）
- **禁用** `get_window_extent(dpi=...)`（混单位）。
- `Artist.get_window_extent` 的单位**跟随当前缓存 renderer**：同一 text 在 `savefig(dpi=600)` 之后会变成 600 dpi 像素；**必须**在受控 renderer / 显式 draw 之后测量，或测量前重设回基线 dpi。
- `Figure.get_tightbbox` 返回 **inches**，其它 artist 返回 **px**。
- **`bbox_inches='tight'` 会让页面尺寸随内容变化** → 必须**实测导出尺寸**（导出到 TEMP 下的临时目录），**不得**把声明尺寸当出版尺寸。
- 临时渲染只写 TEMP；不得在 `examples/` 或用户图件目录产生任何文件。

## 形态
- 人读表格 + **机器可读 JSON** 两种输出。
- API 建议：一个主函数（如 `audit_figure(...)`）返回结构化结果 + 一个 CLI 子命令渲染它。

## 验收（必须真实跑通并给原文输出）
1. 对 `examples/nmr/08 NMR.py` + `nmr.yaml` 与 `examples/ftir/plot_ftir.py` + `ftir.yaml` **各跑一次**，给出真实数字：
   - 目标 **42 mm**（NMR）与 **38 mm**（FTIR）下的 `k`、各角色 effective pt、线宽差、空间风险、**不可行项**。
2. **只读证明**：跑完后两个脚本、两个 yaml 以及 `examples/` 下相关目录的 sha256 **不变**（给前后对比）。
3. 测试覆盖：单位陷阱（同一 text 在不同 renderer/dpi 下取值正确）、tight bbox 导致**声明 ≠ 实测**、无越界时不误报、有越界时报告**含对象名**。

## 禁止
任何写入源文件的路径；修改既有命令语义；git 写操作。
