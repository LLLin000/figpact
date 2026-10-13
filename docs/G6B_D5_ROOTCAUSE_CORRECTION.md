# D-5 根因更正（P0b 实施后留痕）

**本文件更正** `docs/G6B_ROUND_DEVIATIONS.md` §D-5 与 `docs/G6B_FINAL_ADJUDICATIONS.md` §七 P0b 中对 FTIR 同进程双建伪影**机制**的描述。原描述把根因归给 `_CFG` 回写，**该分支在出厂 `ftir.yaml` 上从不触发**，因此不准确；以下为逐层插桩实测后的正确机制。原文保留不删，本文件为其权威更正。

## 原（不准确）描述

> `plot_ftir.py` 的 `draw_panel()` 会就地把实测净距写回模块级 `_CFG`，于是同进程第 1 次构建 ≠ 第 2 次。

## 更正后的真实机制（两条独立缺陷，均已修）

1. **样式只在模块导入时 apply 一次**（**这是 18 个伪位移的真正来源**）
   `IntentSession` 在 `matplotlib.rc_context()` 里装载绘图脚本，退出时把 rcParams 还原成**导入前**的值；而脚本的样式（`fs.apply()`：字体、mathtext、`figure.dpi`）只在 import 时设置过一次 → 同进程的**第二次会话**（即第 3 次构图起）掉回 matplotlib 默认（`figure.dpi=100`、DejaVu），几何整体改变。
   修法：`_build()` **每次构图**都 `fs.apply()`。
2. **可达共享状态**：`_apply_config()` 曾直接 `_CFG = cfg`（与调用方字典同一引用），且 `draw_panel()` 把实测冻结视口/净距写回 `_CFG`。
   修法：装 `copy.deepcopy(cfg)`；派生量移入模块级 `_DERIVED`（每次构图清空）；`--migrate-config` 通过显式 `_adopt_measured_layout()` 取用派生量。

## 修前/修后实测（与 G6b 记录逐位一致）

- 修前：第 1 次构图 `band.oh` y0 = `29.5112934236111`，第 2 次起 `29.552483049514038` → **Δy = +0.3586896259029402、Δx = −0.06614583333333002**，与 `formal/ftir-measure-artifact.md` 逐位相同；修后连续三次全等。
- 出版图：修前/修后 PNG、TIFF **逐字节相同**；PDF 仅差 `CreationDate`/`ModDate`（剥离后相同）；SVG 仅差时间戳与运行期随机元素 id（归一化后相同）；QA 同为「无阻断项 ✓」。**未解释变化 = 0**。
- 永久回归：`tests/test_ftir_composition_determinism.py`（10 项，含 D-5 原样例：4 scope × 同进程双建无伪位移、A→B→A 对独立新进程、跨 scope 不互污、输入配置深度不变、出版科学指纹与 QA 不变、迁移仍冻结实测视口）。

## 对 G7 的影响

P0b 的验收目标不变（**A→B→A 与独立 A 一致；同进程连续构图不改变输入**），但需补一条：**任何"只在导入时做一次"的全局初始化，都必须在每次构图时重放**——这类缺陷已在 NMR（P0 缺陷 `8af3b25`）与 FTIR（本项）各出现一次，属同一模式。建议 G7 后续把"每次构图重放样式/全局初始化"写进新脚本接入清单。
