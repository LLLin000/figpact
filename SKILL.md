# figpact 技能与工程规范 (SKILL.md)

`figpact`（Figure + Pact，参数契约）是面向顶级学术出版图表的参数化治理与自动化质量保障（QA）引擎。
核心设计理念：**排版参数在 YAML 集中管理，绘图与科学计算在 Python 脚本实现，二者以严格的参数契约隔离。**

---

## 1. 新图接入流程

接入新图表时，遵循**「数据处理不动，只抽排版几何」**的原则。原始数据读取、谱线定标、峰位极大值搜索、归一化标尺等属于科研真实性与科学逻辑，严禁移入 YAML。

接入分为以下对象类别逐类声明参数与提取契约：
1. **画布 (Canvas)**：声明实际物理打印尺寸 `canvas_w_mm`、`canvas_h_mm`（直接决定排版比例，字号不随之缩放）。
2. **坐标轴与范围 (Axes)**：声明轴范围与纵向/横向层间距（如 `stack_gap`、`layer_gap`、`top_headroom`）。
3. **刻度 (Ticks)**：声明刻度字号 `tick_font_pt`、刻度长度与朝向规范。
4. **轴标题 (Labels)**：声明轴标题字号 `axis_font_pt`。
5. **图例 (Legend)**：声明图例字号 `legend_font_pt`、列数 `legend_cols`、水平锚点 `legend_anchor_x`。
6. **系列/谱线 (Series/Curves)**：声明线宽 `line_width` 以及各系列纯显示位移 `shifts_mm.<scope>.<sid>`。
7. **标注 (Annotations/Labels)**：声明峰标注字号 `peak_font_pt` / 归属字号 `label_font_pt`、避让参数（`label_min_gap_mm`、`label_max_dx_mm`、`label_lanes`、`label_lift`）。
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
- **`conditional`**：仅在特定标注版生效（如 `stack_gap_annotated`、`stack_lift_annotated_mm`）。
- **`derived`**：布局求解过程中根据其它参数推导出的几何量。

---

## 3. 自然语言需求 → 参数映射指南、口语同义词与拒绝判据

### 自然语言需求映射法则
- **动整幅垂直空间**：
  - FTIR: 找总闸参数 `curve_gap_mm`（调小曲线长高上移，调大拉开标签净空）；标注版整幅上移用 `stack_lift_annotated_mm`。
  - NMR: 顶部预留找 `top_headroom`；**注意 NMR 无底部边距旋钮**，要求「NMR 主图整体往上提留底边」应明确判定为**无解/拒绝**。
- **动某单一谱线**：找 `shifts_mm.<scope>.<sid>` 纯显示位移（整组/单线联动；必须带明确 scope 如 `main` 或 `annotated`，漏 scope 静默失效）。
- **动局部文字重叠/粘连**：
  - 先调字号（`label_font_pt` / `peak_font_pt`）或避让参数（`label_min_gap_mm` / `label_max_dx_mm` / `label_lanes`）。
  - 极度拥挤处使用逐标注微调（NMR 的 `peak_label_shifts_mm`）。
  - 注意模糊指称：「顶层」需对应真实图层（如 NMR 顶层为 HAMA，而非底层 Van-CHO）。
- **动图例**：调整列数 `legend_cols` 或水平锚点 `legend_anchor_x`；纵向位置两图均固定在顶部，要求「图例挪到底部」应直接**拒绝/无解**。

### 口语同义词词典与参数映射表：
| 口语描述（贴太近/挤/挡/看不清/整体往上等） | 适用图表 | 对应参数 | 关键操作与效果 |
|---|---|---|---|
| 「线和标注贴太近」、「谱线和上面的标签太挤/留白不够」 | FTIR | `curve_gap_mm` | 增大数值，拉开标签块底与曲线顶的垂直净空 |
| 「五条线拉开一点距离」、「曲线之间太挤」 | FTIR | `stack_gap` / `stack_gap_annotated` | 增大基线间距 |
| 「右边 Zn–O 标签贴边了/离边框太近/快撞墙了」 | FTIR | `label_edge_margin_mm` | 增大内缩边距 |
| 「图例压住 O–H 带 / 离顶部标签太近」 | FTIR | `label_gap_top_mm` | 增大数值，标签块整体下移让开图例 |
| 「标注版整幅谱线整体往上挪一点/别贴底」 | FTIR | `stack_lift_annotated_mm` | 增大数值（曲线与标签整幅上移） |
| 「四层谱线之间拉开/太挤了」 | NMR | `layer_gap` | 增大数值，拉开基线距离 |
| 「顶部留白不够/最上方图例和谱图太挤」 | NMR | `top_headroom` | 增大数值，顶部常数预留量增加 |
| 「两个相邻诊断峰标注叠在一起/重叠/打架」 | NMR | `peak_font_pt` 或 `label_min_gap_mm` / `peak_label_shifts_mm` | 调小字号 / 调大最小间距 / 逐标注位移 |
| 「标注文字整体抬高离峰尖远一点/引线拉长」 | NMR | `label_lift` | 增大数值，抬高标注与引线 |
| 「图例由两列改成单列/太宽了」 | FTIR / NMR | `legend_cols: 1` | 设为 1 列 |
| 「图例整体往左靠一点/别贴着右边框」 | FTIR / NMR | `legend_anchor_x` | 调小锚点比率（如 0.98 → 0.94） |

### 该拒绝 / 无解判据：
1. **图例纵向自由移动（如挪到底部、居中）**：拒绝。两张图顶部预留模型均绑定图例置顶，无纵向坐标旋钮。
2. **NMR 主图整体上移/增加底部留白**：拒绝。NMR 由 `layer_gap` + `top_headroom` 静态决定，无底层抬升机制。
3. **修改原始科研数据/改变峰高比例**：拒绝。严禁改动透过率、Bruker 数据点、溶剂定标与归一化标尺。
4. **FTIR `curve_gap_mm` < 0.5 mm**：拒绝。硬断言限制，小于 0.5 标签必压线。
## 4. 禁止项与如实报告规则

1. **严禁静默放行任何阻断项**：
   - 曲线超出坐标轴裁切、文字间互相重叠（交叠面积 > 4 px²）、文字压在数据曲线上、谱线相对顺序倒错或净空 < 0.5 mm 均属致命几何阻断。
   - `--strict` 模式下一旦存在未豁免阻断项，退出码必须为 1，且**绝对不覆盖/发布正式文件**。
2. **严禁暗中篡改与硬塞**：
   - 严禁为了通过 QA 检查而私自缩放轴标题、刻度字号至出版下限以下。
   - 严禁私自裁剪、平滑、缩放原始科研数据。
3. **空间无解如实报告**：
   - 当在约束步长与层数内无法找到可行避让位置时，必须立即报告 `NO_FEASIBLE_SLOT`（如 NMR 极端近峰样例），将排版局限性真实暴露给作者与审稿人。
   - 遇已知排版妥协，必须通过 `Exemptions` 登记显式理由（`reason` 不能为空），绝不使用伪代码静默消除。
