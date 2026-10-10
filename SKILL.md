# figpact 技能与工程规范 (SKILL.md)

`figpact`（Figure + Pact，参数契约）是面向顶级学术出版图表的参数化治理与自动化质量保障（QA）引擎。
核心设计理念：**排版参数在 YAML 集中管理，绘图与科学计算在 Python 脚本实现，二者以严格的参数契约隔离。**

---

## 1. 新图接入流程

接入新图表时，遵循**「数据处理不动，只抽排版几何」**的原则。原始数据读取、谱线定标、峰位极大值搜索、归一化标尺等属于科研真实性与科学逻辑，严禁移入 YAML。

接入分为以下对象类别逐类声明参数与提取契约：
1. **画布 (Canvas)**：声明实际物理打印尺寸 `canvas_w_mm`、`canvas_h_mm`（直接决定排版比例，字号不随之缩放）。
2. **坐标轴与物理关系 (Axes & Relations)**：锁定科学范围，明确包络净距 `clearance_mm` 与基线间距 `pitch_mm` 的不同定义。
3. **刻度 (Ticks)**：声明刻度字号 `tick_font_pt`、刻度长度与朝向规范。
4. **轴标题 (Labels)**：声明轴标题字号 `axis_font_pt`。
5. **图例 (Legend)**：声明图例字号 `legend_font_pt`、列数 `legend_cols`、水平锚点 `legend_anchor_x`。
6. **系列/谱线 (Series/Curves)**：声明线宽 `line_width` 以及各系列纯显示位移 `shifts_mm.<scope>.<sid>`。
7. **标注 (Annotations/Labels)**：声明峰标注字号 `peak_font_pt` / 归属字号 `label_font_pt`、避让参数（`label_min_gap_mm`、`label_max_dx_mm`、`label_lanes`、`label_lift_mm`）。
8. **色带与辅助线 (Bands/Guides)**：声明归属阴影带边界与文字标签。
9. **作用域 (Scope)**：声明图元输出版本作用域（如 `main` 主图、`annotated` 标注版、`compare_raw` 对照版），确保同名图元在多子图与多版面导出时 ID 唯一且位移隔离。

---

## 2. 参数契约字段规范

每个配置参数必须在代码中声明严格的元数据与验证规则：

| 字段 | 说明 | 示例 |
|---|---|---|
| `key` | 参数唯一标识名 | `canvas_w_mm`、`label_font_pt`、`shifts_mm` |
| `meaning` | 明确的物理排版含义 | 拼版物理宽度、诊断峰标注字号、逐层纯显示位移 |
| `unit` | 明确物理单位 | `mm`（毫米）、`pt`（磅值）、`a.u.`（数据单位）、无 |
| `range` | 闭区间合法边界 | `[20.0, 200.0]`、`[3.0, 12.0]`、`[-10.0, 10.0]` |
| `policy` | 变动策略分类 | `locked`（锁定）、`edit`（常调）、`conditional`（条件）、`derived`（派生） |
| `affects` | 关联视觉对象与图元 | 坐标轴框高、图例尺寸、特定 Curve/Text |

### 策略分类说明：
- **`locked`**：严禁随意变动（如 `schema_version`、科学常数）。
- **`edit`**：用户与模型直接微调的排版旋钮（如 `canvas_w_mm`、`curve_gap_mm`、`legend_cols`）。
- **`conditional`**：仅在对应 scope 生效（如 `clearance_mm.annotated`、`group_y_mm.annotated`）。
- **`derived`**：布局求解过程中根据其它参数推导出的几何量。

---

## 3. 自然语言需求 → 参数映射指南、口语同义词与拒绝判据

### 自然语言需求映射法则
- **动整幅垂直空间**：
  - FTIR：调 `clearance_mm.<scope>.<上方曲线id>` 控制相邻包络净距；`group_y_mm.<scope>` 移动整组曲线与归属标签。
  - NMR：调 `pitch_mm.main.<上方样品id>` 控制基线间距；`group_y_mm.main` 移动所有样品与其标注。空间不足报告超限 mm，保持原信号显示标尺。
- **动某单一谱线**：找 `shifts_mm.<scope>.<sid>` 纯显示位移（整组/单线联动；必须带明确 scope 如 `main` 或 `annotated`，漏 scope 静默失效）。
- **动局部文字重叠/粘连**：
  - 先调字号（`label_font_pt` / `peak_font_pt`）或避让参数（`label_min_gap_mm` / `label_max_dx_mm` / `label_lanes`）。
  - 极度拥挤处使用逐标注微调（NMR 的 `peak_label_shifts_mm`）。
  - 注意模糊指称：「顶层」需对应真实图层（如 NMR 顶层为 HAMA，而非底层 Van-CHO）。
- **动图例**：调整列数 `legend_cols` 或水平锚点 `legend_anchor_x`；纵向位置两图均固定在顶部，要求「图例挪到底部」应直接**拒绝/无解**。

### 口语同义词词典与参数映射表：
| 口语描述（贴太近/挤/挡/看不清/整体往上等） | 适用图表 | 对应参数 | 关键操作与效果 |
|---|---|---|---|
| 「线和标注贴太近」、「谱线和上面的标签太挤/留白不够」 | FTIR | `curve_gap_mm`、`label_gap_top_mm` | 调整标签布局候选位置，查看实际 QA；不会自动缩小谱线 |
| 「五条线拉开一点距离」、「曲线之间太挤」 | FTIR | `clearance_mm.<scope>.<上方曲线id>` | 输入毫米净距；GUI 可把本组全部相邻净距设为同一值 |
| 「右边 Zn–O 标签贴边了/离边框太近/快撞墙了」 | FTIR | `label_edge_margin_mm` | 增大内缩边距 |
| 「图例压住 O–H 带 / 离顶部标签太近」 | FTIR | `label_gap_top_mm` | 增大数值，标签块整体下移让开图例 |
| 「标注版整幅谱线整体往上挪一点/别贴底」 | FTIR | `group_y_mm.annotated` | 曲线与归属标签整组平移，内部净距不变 |
| 「四层谱线之间拉开/太挤了」 | NMR | `pitch_mm.main.<上方样品id>` | 输入毫米基线间距；其他相邻距离不变 |
| 「顶部留白不够/最上方图例和谱图太挤」 | NMR | `group_y_mm.main` 或相邻 `pitch_mm` | 下移整组或减小指定间距；保留谱线幅度，查看剩余空间和 QA |
| 「两个相邻诊断峰标注叠在一起/重叠/打架」 | NMR | `peak_font_pt` 或 `label_min_gap_mm` / `peak_label_shifts_mm` | 调小字号 / 调大最小间距 / 逐标注位移 |
| 「标注文字整体抬高离峰尖远一点/引线拉长」 | NMR | `label_lift_mm` | 用毫米控制标注基础抬升 |
| 「图例由两列改成单列/太宽了」 | FTIR / NMR | `legend_cols: 1` | 设为 1 列 |
| 「图例整体往左靠一点/别贴着右边框」 | FTIR / NMR | `legend_anchor_x` | 调小锚点比率（如 0.98 → 0.94） |

### 该拒绝 / 无解判据：
1. **图例纵向自由移动（如挪到底部、居中）**：拒绝。两张图顶部预留模型均绑定图例置顶，无纵向坐标旋钮。
2. **请求超出可用空间**：报告实测超限 mm；用户明确选择调整间距、位置或画布，保持信号幅度与科学量不变。
3. **修改原始科研数据/改变峰高比例**：拒绝。严禁改动透过率、Bruker 数据点、溶剂定标与归一化标尺。
4. **FTIR `curve_gap_mm` < 0.5 mm**：拒绝。硬断言限制，小于 0.5 标签必压线。
---

## 4. 参数扰动生效检查机制 (`--check-effect`)

为了防止配置参数「写了但没连到底层视觉元素（假绑定）」或「代码重构后参数通道被静默架空」，`figpact inventory` 提供了 `--check-effect`（默认关闭）自动化探测机制。

### 1. 扰动幅度 (Perturbation Magnitude)
检查器在内存中对图元施加极小、可逆且立即回滚的探针扰动：
- **字号类参数 (`font`)**：
  - 常规单文本图元：`art.set_fontsize(orig + 1.0 pt)`
  - 图例多文本组合：`t.set_fontsize(orig + 1.5 pt)`
- **线宽类参数 (`line_width`)**：
  - 曲线与边框：`art.set_linewidth(orig + 0.5 pt)`
- **几何与位移类参数 (`shift`, `gap`, `lift`, `margin`, `headroom`, `dx`)**：
  - 通过注册表的微调位移通道施加 `dx_mm = +0.2 mm, dy_mm = +0.2 mm`
- **容器/结构类参数 (`legend_cols`, `legend_anchor_x` 等)**：
  - 结构属性关联验证：验证图元已正确装配进 Matplotlib 容器并建立了排版上下文，不破坏容器几何拓扑。

### 2. "渲染变化"判定方法 (Change Detection)
- **比较对象与特征快照 (`_snapshot_artist`)**：
  - **包围盒 (`bbox`)**：通过 `art.get_window_extent(renderer)` 捕获屏幕像素坐标包围盒 `(x0, y0, x1, y1)`，舍入到 0.01 像素。
  - **物理字号 (`fontsize`)** 与 **线宽 (`linewidth`)**：探测真实属性浮点值。
  - **定位坐标 (`position`)**：文本锚点 `(x, y)` 坐标（4 位小数）。
  - **曲线采样点 (`y_mean`)**：对 `get_ydata()` 的前 10 个数据点取均值（4 位小数）。
- **判定标准**：
  - 比较扰动前快照 $S_0$ 与扰动后快照 $S_1$。
  - 若 $S_1 \neq S_0$（包围盒变动、坐标变动或线宽/字号变动），判定该参数与图元间的连接通道 **有效生效 (`VERIFIED`)**。
  - 扰动完成后**立即强制回滚至原始状态**并重绘，确保清点过程对最终渲染产物零污染。

### 3. 假阳性边界与免检标注 (False Positive Boundaries)
以下参数在物理/逻辑上天生**不会改变被检查的单一图元自身快照**，属于假阳性边界，应正确标注而非误报为 `NO_EFFECT`：
1. **只影响图例内部容器排布的参数**：例如 `legend_cols`（列数改动影响子条目的相对网格，若只探测图例大框的外层单个文字，可能短时间内未触发大框重算；系统应将整体 Legend 对象作为响应宿主）。
2. **跨作用域/多输出图隔离参数**：例如 `clearance_mm.annotated` 只影响 `annotated` 版；`shifts_mm.compare_raw` 只影响对应对照面板。非当前 scope 参数应标为 `OUT_OF_SCOPE`，严禁误报为故障。
3. **布局算法边界限制参数**：例如 `label_max_dx_mm`（避让窗口上限）或 `label_min_gap_mm`。当当前图表面板内峰位天然稀疏、未触发拥挤冲突时，增大搜索窗口不会引起实际标签位移。此类算法阈值参数应归类为条件生效 (`CONDITIONAL`)。

## 5. 禁止项与如实报告规则

1. **严禁静默放行任何阻断项**：
   - 曲线超出坐标轴裁切、文字间互相重叠（交叠面积 > 4 px²）、文字压在数据曲线上、谱线相对顺序倒错或净空 < 0.5 mm 均属致命几何阻断。
   - `--strict` 模式下一旦存在未豁免阻断项，退出码必须为 1，且**绝对不覆盖/发布正式文件**。
2. **严禁暗中篡改与硬塞**：
   - 严禁为了通过 QA 检查而私自缩放轴标题、刻度字号至出版下限以下。
   - 严禁私自裁剪、平滑、缩放原始科研数据。
3. **空间无解如实报告**：
   - 当在约束步长与层数内无法找到可行避让位置时，必须立即报告 `NO_FEASIBLE_SLOT`（如 NMR 极端近峰样例），将排版局限性真实暴露给作者与审稿人。
   - 遇已知排版妥协，必须通过 `Exemptions` 登记显式理由（`reason` 不能为空），绝不使用伪代码静默消除。

---

## 6. 参数修改试算流程 (`try` → 写 YAML → `--strict`)

在正式修改配置文件前，严禁直接手改 YAML 试错。必须遵循标准化安全闭环：

```text
figpact try (试探与测量) ──> 审阅位移与区间 ──> 明确写入 YAML ──> figpact render --strict (正式发布)
```

1. **先 `figpact try` 试探**：
   - 使用 `figpact try --script <py> --config <yaml> --patch <patch.yaml>` 或 `--set k=v`。
   - `figpact try` 仅在**内存中**合并参数并渲染到临时暂存目录，**绝对不修改正式 YAML、绝对不覆盖正式输出图件**。
   - 引擎返回三项量化依据：
     1. **对象位移 (mm)**：按图元 `gid` 实测列出相对基线的移动毫米数；
     2. **QA 差异**：按稳定签名列出新增的阻断/警告项以及被消除的缺陷；
     3. **参数可行区间**：通过实际二分试算（Bisection）得到保证 `--strict` 通过的合法闭区间 `[min, max]` 与迭代收敛次数。
2. **再写 YAML 文件**：
   - 根据 `figpact try` 给出的可行区间与 QA 差异，由人类作者/Agent 做出审慎权衡，决定最终数值并写入正式配置。
3. **再跑 `--strict` 验收**：
   - 执行 `python script.py --strict` 验证退出码为 0，完成正式原子发布。
