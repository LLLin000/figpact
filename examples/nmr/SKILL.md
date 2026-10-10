# Fig.2 NMR 叠谱 —— 改图规则

**唯一可改的文件是 `nmr.yaml`。** `08 NMR.py` 只在「要新增一个参数」时才动。
数据、定标、归一化、峰归属、显示窗永远不在配置里，也不该进来。

本图只有一个输出作用域 **`main`**（`SCOPES = ("main",)`），gid 前缀 `fig2_nmr.main.`。
图上对象身份（`inspect` / 契约 / YAML 路径都用它）：

| 对象 | gid |
|---|---|
| panel（唯一 Axes） | `fig2_nmr.main.panel` |
| 谱线 / 基线虚线 / `//` 截顶标记 | `fig2_nmr.main.{curve,baseline,break}.<样品id>` |
| 峰标注文字 / 引线 | `fig2_nmr.main.{peak,guide}.<样品id>.<tag>` |
| 轴标题 / 图例 / 图例文字 | `fig2_nmr.main.{xlabel,ylabel}` · `fig2_nmr.main.legend` · `fig2_nmr.main.legend.text.<样品id>` |

- 四层样品 id（自下而上）：`vancho`(Van–CHO)、`vanoh`(Van–OH)、`vannh2`(Van–NH₂)、`hama`(HAMA 终产物)。
- 峰标注 tag 由目标 ppm 生成，末段**不带点**：`9p83 3p91 3p68`(vancho) · `4p62`(vanoh) · `3p03`(vannh2) · `6p18 2p02`(hama)。
  例：`fig2_nmr.main.peak.vancho.3p91`、`fig2_nmr.main.guide.vancho.3p91`。
- **两个名字别混**：`fig2_nmr.main.peak.vancho.3p91` 是**图元 gid**（`inspect` / 契约
  `objects` / `movements` 用）；`peak.vancho.3p91` 是它在 `nmr.yaml`、JSON `path` 第三段、
  GUI 参数目录里的**键**（作用域在上一段 `main`，两个名字都点号不拆）。

## 0. 启动会话（Windows；脚本名带空格，必须加引号）

```bat
python -X utf8 -m figpact agent --script "examples/nmr/08 NMR.py" --config "examples/nmr/nmr.yaml" --scope main
```

在仓库根运行。`--scope main` 必填（一张图一个工作进程）；`--output-dir` 可选，
默认发布到脚本同目录 `examples/nmr/`。进程在 stdin 上**一行一个 JSON**，stdout 只回协议
（人读的输出与 `[QA]` 行走 stderr）。关掉 stdin（EOF）即结束会话。

## 1. 五个方法：请求信封

五个方法 `snapshot / inspect / try_layout / render_preview / commit` 的**通用语义、状态词表、
验证等级、不支持/歧义口径**统一写在根 `SKILL.md` §2–§6，**本文件不重复协议**；这里只写 NMR
的精确实参。`operation` 判别键只能是 **`operation`**（写 `op`/`kind`/`type` 会得到
`INVALID_VALUE: 未知操作`）。默认 `detail:"summary"` 会省略折线采样；要全量几何加 `"detail":"full"`。

```jsonc
// 1) 量当前场景：返回 revision / nodes / relations / parameter_index / measurement
{"jsonrpc":"2.0","id":1,"method":"snapshot","params":{}}

// 2) 按 gid 查：实测 pitch 关系、精确峰 id、受影响参数（path 是数组）
{"jsonrpc":"2.0","id":2,"method":"inspect","params":{"ids":["fig2_nmr.main.baseline.vanoh"],"scope":"main"}}
{"jsonrpc":"2.0","id":3,"method":"inspect","params":{"ids":["fig2_nmr.main.peak.vancho.3p91"]}}

// 3) 一批绝对目标（原子：失败不改状态）。path 逐段是 YAML 真实 key。
{"jsonrpc":"2.0","id":4,"method":"try_layout","params":{"operations":[
  {"operation":"set_relation","relation_id":"main.pitch.hama","target_mm":7.0}]}}
{"jsonrpc":"2.0","id":5,"method":"try_layout","params":{"operations":[
  {"operation":"set_parameter","path":["pitch_mm","main","hama"],"value":7.0}]}}

// 4) 出候选预览 PNG（base64）+ space + qa；同一 revision 命中缓存
{"jsonrpc":"2.0","id":6,"method":"render_preview","params":{"revision":"<上一步返回的 revision>"}}

// 5) 存草稿（T4 门，不过独立 strict）
{"jsonrpc":"2.0","id":7,"method":"commit","params":{"kind":"draft","revision":"<revision>"}}
// 5b) 发布：独立严格门 + 全量产物；必须显式 confirm
{"jsonrpc":"2.0","id":8,"method":"commit","params":{"kind":"publication","confirm":true}}
```

`status`（`has_candidate` / `worker.alive` / `revision` / `candidate_paths`）与 `close` 是辅助方法。
`commit` 前须有一次成功的 `try_layout`，否则 `NO_CANDIDATE`；`revision` 与当前候选不符一律
`STALE_REVISION`（先重新 `snapshot`）。**草稿写完 YAML 会变字节 → revision 变**，再改要重新
`snapshot`/`try_layout` 拿新 revision，不要拿旧 revision 硬提。

## 2. 先量再改：实测 pitch、剩余空间、精确峰 id

**声明的是目标，实测的是事实。** 参数值（间距/位移）是你**声明**的毫米目标；`snapshot` /
`inspect` / `render_preview` 给出重建后的**实际**几何。纯显示位移 `shifts_mm` 叠加在间距调整
**之后**，所以声明的毫米数与实测毫米数一般不相等——**报告以实测为准**，不要把声明值当测量结果。

- **相邻基线间距（pitch）**：`inspect` 某条 `…baseline.<sid>`，返回里关系
  `id` 形如 `main.pitch.<sid>`（`kind:"gap"`、`axis:"y"`、`method:"baseline"`），带
  `value_mm`（实测）、`target_mm`、`delta_mm`。
- **剩余空间**：只有 `render_preview` 的返回带 `space`（每个 Axes 的 `bottom_mm` / `top_mm` /
  `overflow_mm`；负值表示压框）。`snapshot` **不含** `space`。
- **精确峰 id / 峰位**：`inspect` 某条 `…peak.<sid>.<tag>`；峰位由 `_detect_peak` 在定标后的真实
  谱线上取极大，`science_manifest` 的锚点用的是**同一个**函数——引线指的就是声明的。
  同一份返回里带**该标注的逐标注微调绑定**，路径就写在 `parameter_index` / 受影响参数里：

  ```jsonc
  {"jsonrpc":"2.0","id":3,"method":"inspect","params":{"ids":["fig2_nmr.main.peak.vancho.3p91"]}}
  // → 该标注的绑定：path ["peak_label_shifts_mm","main","peak.vancho.3p91"]，值形 [dx, dy]，
  //   当前 [0.0, 0.0]（`nmr.yaml` 是 {}，这是规范化补出来的零基线），min/max = ±10 mm
  ```

  想动它就原样发回同一段 path（见 §3 的 `[dx, dy]` 规则），不用先手改 YAML。
- **验证等级**：`try_layout` 返回 `verification` = `GEOMETRY_CHECKED` 或 `RENDER_CHECKED`，
  别拿几何检查冒充渲染检查。

## 3. NMR 参数：路径 / 单位 / 值形 / 是否走 JSON 操作面

`--list-params`（或 `python "08 NMR.py" --list-params`）看当前值与范围；下表是 JSON 操作面的口径。

| YAML 路径（数组逐段） | 单位 | 值形 | `set_parameter` 结果 |
|---|---|---|---|
| `["canvas_w_mm"]` / `["canvas_h_mm"]` | mm | 标量 20–200 | OK（`operation:"resize"`） |
| `["pitch_mm","main",<sid>]`（sid=vanoh/vannh2/hama） | mm | 标量 0–100 | OK（平移该样品**及其上方所有层**） |
| `["group_y_mm","main"]` | mm | 标量 ±100 | OK |
| `["shifts_mm","main",<sid>]`（sid 四选一） | mm | 标量 ±10 | OK（整层：谱线+基线+`//`+该层标注+引线） |
| `["label_lift_mm"]` | mm | 标量 0–15 | OK |
| `["label_min_gap_mm"]` | mm | 标量 0–15 | OK |
| `["label_max_dx_mm"]` | mm | 标量 0–25 | OK |
| `["label_lanes"]` | 层 | 整数 1–5 | OK |
| `["peak_font_pt"]` / `["legend_font_pt"]` / `["note_font_pt"]` / `["axis_font_pt"]` | pt | 标量 3–12 | OK |
| `["line_width"]` | pt | 标量 0.2–3.0 | OK |
| `["legend_cols"]` / `["legend_anchor_x"]` | 列 / 比例 | 整数 1–3 / 0–1 | OK |
| `["peak_label_shifts_mm","main","peak.<sid>.<tag>"]` | mm | **`[dx, dy]` 两个数字**（各 ±10） | OK：`operation:"rebuild"`、`type:"[dx,dy]"`，结论 `RENDER_CHECKED`（见下） |
| `["show_ppm"]` | bool | true/false | `LOCKED`（画出来的化学位移文字是受保护科学内容） |
| `["tick_font_pt"]` | pt | 标量 3–12 | `UNSUPPORTED_PATH`（合法 YAML 键，但契约未声明可编辑绑定） |
| `["schema_version"]` / `["layout_reference",…]` | — | — | `FIXED_STYLE` / `DERIVED`，不可编辑 |

`pitch_mm` / `shifts_mm` 的 `<sid>` 段是**样品 id**；`peak_label_shifts_mm` 的第三段是
**整串标注 key**（`peak.<sid>.<tag>`），不是把 id 单列出来。

旧 YAML 迁移只用 `python "08 NMR.py" --config <旧.yaml> --migrate-config <新.yaml>`：按旧图实测
毫米几何生成新文件，保留原点、显示标尺、峰位与归属；只写新文件，不发布、不覆盖输入。

### 逐标注微调 `peak_label_shifts_mm`（值形 `[dx, dy]`，两个坑）

1. **标注 key 是 `peak.<sid>.<tag>` 这一整串，是一个键段，不能按点拆开。**
   路径 `["peak_label_shifts_mm","main","peak.vancho.3p91"]` 的第三段就是
   `peak.vancho.3p91`；写成 `["…","main","peak","vancho","3p91"]` 会 `UNSUPPORTED_PATH`。
   这个拼法和 `nmr.yaml` 里的键、GUI 参数目录里的路径**逐字相同**。（图元 gid 多一层
   `fig2_nmr.main.` 前缀，是给 `inspect` 用的另一个名字，别混。）
2. **值是 `[dx, dy]` 两个有限数字**（dx 向右、dy 向上，**每个分量各 ±10 mm**），
   `type: "[dx,dy]"`、`operation: "rebuild"`（重画引线，不是单轴纯平移）：
   目标是**长度 2 的数组**，`[0.8]` / `0.8` / 嵌套 / NaN / Inf / bool 一律 `INVALID_VALUE`；
   某个分量越界是 `OUT_OF_RANGE`，整批原子回滚、`revision` 不变。合法的一个请求：

   ```jsonc
   {"jsonrpc":"2.0","id":9,"method":"try_layout","params":{"operations":[
     {"operation":"set_parameter",
      "path":["peak_label_shifts_mm","main","peak.vancho.3p91"],
      "value":[0.8, 0.0]}]}}
   ```

   结论等级是 **`RENDER_CHECKED`**（真实重建与 renderer 测量）；文字按 `[dx,dy]` 移动，
   引线的科学锚点固定，文字端重新连接，不能把引线当成整体刚性平移。
3. **`nmr.yaml` 写 `peak_label_shifts_mm: {}` 也能设**：`prepare_config` 为诊断峰模板补零基线，
   `layout_contract` 只给实际画出的峰声明绑定。规范形态与 YAML 同形：`main` → 短 key →
   `[dx,dy]`；再次归一化保持结构和数值不变。
   零值 = 不动：补出来的零和 `[0, 0]` 都不改变排布（基线图与「不写」逐字节同图）。
   不过**显式发一个 `[0, 0]` 仍会被记成"一个目标"**：结论是 OK / `RENDER_CHECKED` 且没有
   需要观测的变化，但 `candidate_patch` 会多出这一条、候选 revision 与基线不同。想要
   「等于没写」就别发这一条，而不是发个零。
   没有画出的峰（搜索窗口无峰或没有可行避让位置）不声明绑定，改它得到 `UNSUPPORTED_PATH`。
4. 缓解拥挤优先调 `label_min_gap_mm` / `label_max_dx_mm` / `label_lanes`，再定向毫米微移。
   只有作者明确授权才改字号；逐标注微移仍须通过碰撞检查。

NMR 的基线虚线、峰标注引线由构建路径登记为 `LAYOUT`（纯布局几何，不进科学指纹）；谱线、
峰/归属文字、轴文字、图例文字是 `LOCKED_SCIENCE`。改这些受保护内容 = 改「这张图回答什么」，拒绝。

## 4. 关系型要求怎么落到参数上与口语同义词映射

| 要求与口语表述 | 改什么 | 机制说明与不该做的事 |
|---|---|---|
| 「四层谱线之间拉开/太挤了」 | `pitch_mm.main.<上方样品id>`，或 `set_relation relation_id="main.pitch.<sid>"` | 给出目标基线间距，会话按当前候选反解；其他相邻间距与信号幅度不变 |
| 「顶部留白不够/图例和谱图太挤」 | `group_y_mm.main` 或相邻 `pitch_mm` | 下移整组或减小指定间距；看剩余空间与 QA，不缩小信号 |
| 「某一层（如 Van-NH₂ / HAMA）整体上移/下挪」 | `shifts_mm.main.<样品id>` | 整组位移：谱线+基线+`//`+该层标注+引线全联动 |
| 「两个相邻诊断峰标注叠在一起/看不清」 | 调间距、避让窗口/层数，必要时定向 `peak_label_shifts_mm` | 不合并标注；未经明确授权不改字号 |
| 「标注整体抬高/引线拉长」 | `label_lift_mm` | 标注基础抬升（mm），不改真实峰位 |
| 「标签横向太挤/防粘连」 | `label_min_gap_mm`（增大） | 最小横向净空 |
| 「允许标签向左右挪更开找空位」 | `label_max_dx_mm`（增大） | 自动避让搜索横向窗口 |
| 「启用更多层阶梯避让」 | `label_lanes`（增大，如 3→4） | 避让最大允许层数 |
| 「去掉 ppm 只留官能团」 | `show_ppm: false` | YAML 布尔（JSON 面是 `LOCKED`）；只改显示格式，标签窄约 40% |
| 「图例改单列/太宽」 | `legend_cols: 1` | 图例列数 |
| 「图例向左挪/别贴右」 | `legend_anchor_x`（调小） | 水平锚点（0 左 1 右）；**纵向固定顶部，无纵向旋钮** |
| 「轴标题和刻度数字挤」 | `axis_font_pt`（缩小） | 刻度字号 `tick_font_pt` 只能改 YAML（见 §3） |

### NMR 「该拒绝 / 无解」判据

1. **请求超出可用空间** → 报**实测**超限毫米数（`NO_FEASIBLE_SLOT` / 几何拒绝）；由用户明确选择
   调位置、间距或画布，**不缩信号**。
2. **要求图例纵向自由移动** → 拒绝/无解：图例纵向固定在顶部（y=0.98），没有这个自由度的编辑绑定。
3. **要求改 Bruker 原始数据、溶剂定标峰、归一化标尺 `PEAK_MAX_NORM`、显示窗、峰归属** → 拒绝：
   硬科研边界。
4. **限定的可编辑范围内找不到安全位置** → 报告实测碰撞或超限；
   不凭历史图的缺陷推断当前候选，也不加豁免放行。

**拒绝 = 状态不变，不是变通放行。** `try_layout` 的失败批次是**原子**的：整批回滚，`goals`/候选
不变，`snapshot.revision` 与磁盘 YAML 一个字节都不动（实测例：把 `pitch_mm.main.<sid>` 压到
1.5 mm 会造出新的谱线/引线相交 → 返回 `GEOMETRY_REJECTED` 之类的非 OK 状态）。正确反应是
**把实测的碰撞/超限对象与毫米数报出来**，让用户选可行值——不是偷偷缩字号、裁数据或加人工豁免
把门糊过去。

## 5. 验证：预览 → 草稿 → 独立严格发布

- `try_layout` + `render_preview` 只出候选，**不发布**。
- `commit kind="draft"` 把候选写回 `nmr.yaml`（保留注释），验证等级是 `DRAFT_SAVED`——**草稿没过严格门**。
- `commit kind="publication" confirm=true` 走**独立严格门**：子进程跑脚本 `--strict --probe <一次性沙箱>`，
  要求四份产物齐全、科学载荷与基线逐项一致、无未豁免阻断项，然后一次性事务化安装，最后才写配置；
  失败则正式产物与配置**都不动**。

产物名（四个格式，缺一即发布被拒）：

```
Fig2_NMR_pure_stacked.png   Fig2_NMR_pure_stacked.pdf
Fig2_NMR_pure_stacked.svg   Fig2_NMR_pure_stacked.tiff
```

**发布能不能过，只看那一次实测候选的 QA。** 严格门用的是一次性全新沙箱（`qa_exemptions.json`
在那里不存在），所以沙箱里的阻断项一律算「未豁免」、**不继承仓库里的存量豁免**；是否放行由
**该候选在沙箱里测得的结果**决定，与「基线图有没有历史缺陷」不是同一件事，也别互相推断：
`--strict --probe` 在同一份原始数据上的实测既有 PASS 的记录，也有因候选本身造出阻断项而拒绝
的记录（实测例：把某一层标注横向挪 0.5 mm，候选里 `3p68` 变成无可行避让位置 → 拒绝）。
有阻断项时 `commit kind="publication"` **拒绝**并把 QA 行回传，这类合法但未过 QA 的改动
**只能保留为草稿**，不得把候选图当正式通过的图。想让发布落地，候选必须在该沙箱里**零阻断项**。

## 6. 禁止

- 改 Bruker 原始数据、溶剂定标、归一化标尺 `PEAK_MAX_NORM`、峰归属模板、显示窗。
- 把 `PEAK_MAX_NORM` 加进 YAML——它是科学量，同时决定峰的相对幅度与截顶阈值。
- 越界时偷偷缩字号或裁数据——**报出来**。
- 拿一个作用域的路径动另一作用域：本图只有 `main`，别把 `fig2_nmr.main.*` 套到别处。
- 直接改 Artist 让 YAML「看起来生效」（`set_position` / `set_fontsize` / 手写 `_figpact_*`）。

## 7. 验收

1. `commit kind="publication"` 返回 `STRICT_VERIFIED`，四份产物齐全（否则保留草稿并回报 QA）；
2. 旧路径 `python "08 NMR.py" --strict` 退出码 0（`git diff` 里只有 `nmr.yaml`）；
3. 绝对毫米数一律**量导出件**（PDF/PNG）或 `snapshot`/`render_preview` 的实测，不要量交互环境
   （不同 matplotlib 版本文字度量会差几毫米）；
4. 不合并标注、不改变科学量、不新增人工豁免。合法但未过 QA 的改动只能保留为草稿。
5. **零基线不许改图**：`nmr.yaml` 仍是 `peak_label_shifts_mm: {}` 时，逐标注微调补出来的
   7 个 `[0.0, 0.0]` 必须与「什么都不写」逐字节同图（bbox 差 ≤ 0.05 mm、科学指纹一致）；
6. **逐标注微调走真重建**：把某个 `["peak_label_shifts_mm","main","peak.<sid>.<tag>"]` 设成
   非零 `[dx,dy]`，结论是 `RENDER_CHECKED`；从实际 bbox 量文字位移，并核对引线科学端固定、
   文字端重连，其余图元不动。GUI 的小位移计数有过滤阈值，不能拿计数 0 当作参数未生效。

**历史旧图存在近峰文字重叠与压线；仓库里的 `qa_exemptions.json`（若存在）不是当前 strict 的
自动豁免。** 存量豁免由 `python "08 NMR.py" --exempt-current --reason "<理由>"` 写入
`qa_exemptions.json`（规范：只该接出版取舍类；阻断项不许靠豁免糊过去）。以当前 scope 的预览
QA 和正式全图 strict 为准。

**图注待补（科研表述）**：四层谱图做过**逐谱独立定标 + 去溶剂后归一化 + 垂直堆叠**，
纵向位置与幅度不可跨样品比较绝对强度。正式图注必须写明这一点。