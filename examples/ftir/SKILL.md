# Fig2 FTIR 面板 —— 改图规则

**唯一可改的文件是 `ftir.yaml`。** `plot_ftir.py` 只在「要新增一个参数」时才动；
数据、峰位、归一化、基线校正永远不在配置里，也不该进来。

```bash
python plot_ftir.py                  # 预览：出图，阻断项只打印（退出码 0）
python plot_ftir.py --strict         # 验收：有阻断项则退出码 1，且**不覆盖**正式输出
python plot_ftir.py --config b.yaml  # 换一份配置做对比
```

命令行是**严格解析**的：`--strcit` 这类拼错会当场报错退出（退出码 2），不会被当成预览模式跑过去。
出图先写临时目录，最后一步才发布到本目录——所以 `--strict` 拒绝时，磁盘上原有的
`Fig2_FTIR_*` 一个字节都不动。

## 参数（schema_version: 2；以 `--list-params` 查看当前值和范围）

| key | 含义 | 允许范围 | 动它会怎样 |
|---|---|---|---|
| `canvas_w_mm` / `canvas_h_mm` | 拼版里的实际占位尺寸 | 20–200 | 画布物理尺寸；字号**不**跟着缩放 |
| `label_font_pt` | 官能团归属标签字号 | 3.0–12.0 | 标签块高度与层数变化；谱线显示标尺固定，空间不足报超限 |
| `legend_font_pt` | 图例字号 | 3.0–12.0 | 图例框高度变化；不会自动缩小谱线 |
| `axis_font_pt` | 轴标题字号（粗体） | 3.0–12.0 | 太大时刻度数字会撞上轴标题（阻断项会报） |
| `tick_font_pt` | 刻度数字字号 | 3.0–12.0 | 只影响刻度行高 |
| `note_font_pt` | 对照版左上角小注 | 3.0–12.0 | 只出现在 raw/processed 那张 |
| `line_width` | 谱线线宽（pt） | 0.2–3.0 | 只影响观感，不参与布局 |
| `legend_cols` | 图例列数 | 整数 1–3 | 改图例框宽高，不改变谱线幅度 |
| `legend_anchor_x` | 图例水平锚点（0 左 1 右） | 0.0–1.0 | 太靠左会压住轴标题（阻断项会报）。**纵向固定在顶部**：预留量按"图例占顶部"算，见下 |
| `label_edge_margin_mm` | 归属标签距左右框净空 | 0–6 | 挤在框上的 Zn–O 往内让；可能改变分层 |
| `label_gap_top_mm` | 图例底 → 标签块顶 | 0–8 | 上面就是图例，只能小幅动 |
| `curve_gap_mm` | 标签布局候选净空（mm） | 0.5–8 | 改标签候选位置；以实测 QA 为准，不缩小谱线 |
| `clearance_mm.<scope>.<上方曲线id>` | 相邻曲线包络净距（mm） | 0–100 | 向上平移该曲线及其上方曲线，保持其他相邻净距与信号形状 |
| `group_y_mm.<scope>` | 曲线和归属标签整组竖向位置（mm） | ±100 | 整组平移，内部距离不变；空间不足报超限 |
| `layout_reference` | 旧图实测原点与显示标尺 | 只读 | 显式迁移生成，GUI 不可调；保持原曲线幅度 |
| `shifts_mm`（可选） | 逐曲线纯显示位移（mm，正数向上） | ±10 | 只动那一条，不动数据、不重算坐标范围 |

未知 key、缺 key、非数字、NaN/Inf、超范围 → 直接报错退出，不会静默兜底。

旧 YAML 仅通过 `python plot_ftir.py --config <旧.yaml> --migrate-config <新.yaml>` 迁移。
迁移按旧图实测毫米距离及原点生成新文件，不发布、不覆盖输入；科学数据与归属保持不变。
独立 `shifts_mm` 在相邻净距调整之后叠加，界面显示叠加后的实际距离。

## 两套检查，别混为一谈

| | 谁管 | 结果 |
|---|---|---|
| **配置合法性** | `load_config()` | 不合法 → 抛异常、退出码 1，**根本不画图** |
| **出版下限** | `qa_report` / `audit_pdf` | 只报 ✗。含上下标的文字母体需 ≥ 7.143 pt（否则字形 < 5 pt）；贴边红线 1.0 mm。**这是取舍，不是非法值** |
| **阻断项** | `blocking_problems()` | 曲线/图例越出坐标框、**相邻谱线最近处 < 0.5 mm**、文字重叠、文字压线。预览只打印，`--strict` 下拒绝发布 |

**`--strict` 通过 ≠ 可以投稿。** 这是刻意的分工：阻断项只覆盖**排版几何**——它们是改
YAML 能直接造成的坏图（曲线被裁、两条线糊在一起、文字压线）。而「字形 < 5 pt」和
「贴边 < 1 mm」**只警告、不阻断**，因为它们描述的是**这张图当前的出版取舍**（4.7 pt
母体 + 上下标 = 3.29 pt；图例距上框 0.52 mm），不是某次参数改动引入的回归。
把它们设成阻断，等于让这套参数化永远过不了门——而它们该由人决定：要么接受，
要么按 §结论 3 的代价换合规。**判断「能不能投稿」要看字形审计那一行，不是看退出码。**

所以 `label_font_pt: 4.7` 是**合法**的（在 3.0–12.0 内），但它会让 `Cu$^{2+}$` 这类
上标落到 3.29 pt，低于 5 pt 出版下限——那是**已知存量问题**，见文末。

## 作用域与对象身份

四个输出版本各有作用域，gid 里带这一段，**跨图不重名**：

| 作用域 | 输出 | gid 前缀 |
|---|---|---|
| `main` | 干净版 | `fig2_ftir.main.*` |
| `annotated` | 归属标注版（论文主图） | `fig2_ftir.annotated.*` |
| `compare_raw` | 原始/处理对照版上格（SI） | `fig2_ftir.compare_raw.*` |
| `compare_processed` | 同下格 | `fig2_ftir.compare_processed.*` |

完整清单：`<前缀>.curve.{ha, zno, hama, hama_cu_zno, gel}`、`<前缀>.band.{oh, coo_cc, coo, coc, zn_o}`、`<前缀>.legend`。

`shifts_mm` 也按作用域分档，**改论文主图不会顺手改掉 SI 对照图**：

```yaml
shifts_mm:
  annotated:
    hama: 2.0     # 只抬归属版里的 HAMA；main / compare_* 一动不动
```

## 用 Agent 会话改这张图（五个操作）

协议的精确形状、错误码与提交语义见根 `SKILL.md` §2.1；这里只给**本图真实**的命令与 id。

```bash
# 仓库根目录起会话；一个会话只服务一个作用域
python -m figpact agent --script examples/ftir/plot_ftir.py \
    --config examples/ftir/ftir.yaml --scope annotated
```

要动 `main` / `compare_raw` / `compare_processed` 就换 `--scope` 另开会话；用 `annotated`
的路径去动别的格会被拒（`NOT_IN_SCOPE`），对照图上下两格是**两个独立作用域**、共享一个产物。

`annotated` 作用域里的真实 id（与 `clearance_mm.annotated` 的键一一对应；关系 id 用该对的
**上方曲线 id**，与 `controlled_by` 指向的参数路径同段）：

| 用途 | 关系 id | 映射到的参数路径 |
|---|---|---|
| hama 与其下方相邻曲线的包络净距 | `annotated.clearance.hama` | `["clearance_mm","annotated","hama"]` |
| HAMA 这一条谱线的纯显示位移 | ——（无关系，只有参数） | `["shifts_mm","annotated","hama"]` |
| 曲线+归属标签整组竖向平移 | —— | `["group_y_mm","annotated"]` |

同类还有 `annotated.clearance.zno` / `.hama_cu_zno` / `.gel`——**底层 `ha` 没有净距关系**
（契约里净距只登记 `CURVE_IDS[1:]`）。`main` / `compare_*` 各有自己的同名关系（带各自作用域前缀）。
**这些 id 不要照抄去别的图**——先 `snapshot` 查
`relations[].id` 与 `parameter_index[].path`，`min`/`max`/`operation` 用
`python plot_ftir.py --list-params` 或
`python -m figpact export-params --script examples/ftir/plot_ftir.py --config examples/ftir/ftir.yaml --json` 查。

一次完整往返（每行一个 JSON，`<…>` 全部来自上一条响应，**不要自己编**）：

```json
{"jsonrpc":"2.0","id":1,"method":"snapshot","params":{}}
{"jsonrpc":"2.0","id":2,"method":"try_layout","params":{"revision":"<id1 的 revision>","operations":[{"operation":"set_relation","relation_id":"annotated.clearance.hama","target_mm":2.5}]}}
{"jsonrpc":"2.0","id":3,"method":"render_preview","params":{"revision":"<id2 的 revision>"}}
{"jsonrpc":"2.0","id":4,"method":"commit","params":{"kind":"draft","revision":"<id2 的 revision>"}}
{"jsonrpc":"2.0","id":5,"method":"snapshot","params":{}}
```

`render_preview` 不改 revision；`draft` 写入 `ftir.yaml` 后会话按新文件**重新基线**——候选被
清空、revision 变新，要接着改就先做第 5 步 `snapshot` 拿新 revision 再 `try_layout`
（直接再 commit 会 `NO_CANDIDATE`）。**同一会话不需要重启**：接着可以继续
`try_layout` → `render_preview` → `commit`，要正式出图就把最后一步换成
`{"kind":"publication","confirm":true,…}`。`<…>` 全部来自上一条响应，不要自己编。

等价写法也可以直接给参数路径：
`{"operation":"set_parameter","path":["clearance_mm","annotated","hama"],"value":2.5}`。
判别键恒为 **`operation`**；`set_relation` 只认关系 id（`relation_id`）。

- **声明的 2.5 mm 不是结果**：实测净距看 `snapshot` / `render_preview` 的 `relations[]` 里
  `id == "annotated.clearance.hama"` 那条的 `value_mm`（并看 `status` `precision`
  `calibrated` `uncertainty_mm`）。净距调整之后还会叠加 `shifts_mm` 的额外抬升，所以声明值
  一般 ≠ 实测值——报**实测**毫米数，不要说「落在 2.5 mm 容差内」。
- `try_layout` 返回 `status` 非 `OK` 就是**没做到**，别把目标值当结果报出去：例如净距要
  1.5 mm 时 `GEOMETRY_REJECTED`（实测碰撞/越界，`message` 带**实测**超限毫米数）、
  `UNSUPPORTED_RELATION`（关系没有单一 `controlled_by` 或依赖非 `translate` 参数）、
  `QA_BLOCKED`（渲染路径被阻断项拦下）。先看 `checks[]` / `diagnostics[]`，再决定改字号、
  改别的参数，还是报告实测放不下。
- 提交：`kind:"draft"` 只写草稿（`verification:"DRAFT_SAVED"`，**未过**严格校验）；
  `kind:"publication"` 必须带 `confirm:true`，在独立沙箱跑**整张图**的全量 strict，通过后
  事务性安装本图声明的全部产物（四个作用域的并集去重：`Fig2_FTIR_transmittance_stacked[_annotated]`
  与 `Fig2_FTIR_transmittance_raw_processed` 的 png/pdf/svg/tiff）并保存 `ftir.yaml`，
  失败则产物与 YAML 都不动。它不依赖草稿的正确性，是独立第二次校验。
- **试算用沙箱副本**：把 `ftir.yaml` 拷到临时目录当 `--config`、产物落 `--output-dir` 沙箱，
  真件零改动；人工/CI 复核后才用真实路径开新会话、带 `confirm:true` 正式发布（发布写的是
  **你传进去的那份配置**）。

会话只是既有能力的一种入口：文首的 `python plot_ftir.py [--strict]` 闭环与本仓库 GUI 照旧
可用，本图没有新增功能。

## 关系型要求怎么落到参数上与口语同义词映射

| 要求与口语表述 | 改什么 | 机制说明与不该做的事 |
|---|---|---|
| 「五条线拉宽/拉开一点」、「谱线挤在一起」 | `clearance_mm.<scope>.<上方曲线id>` | 输入毫米包络净距；GUI“全部相邻间距”同时设置本组真实参数 |
| 「谱线和上面的官能团标签贴太近」 | `curve_gap_mm`、`label_gap_top_mm` | 调整标签候选布局，查看实际 QA；谱线不会自动缩小 |
| 「图例别压住 O–H」、「图例离顶部标签太挤」、「标签往下挪一点避开图例」 | `label_gap_top_mm`（增大） | 调整图例底到标签块顶距离；不够再微缩 `legend_font_pt`；**不要动 curve_gap_mm** |
| 「右边 Zn–O 标签贴边了/离边框太近/快撞墙了」 | `label_edge_margin_mm`（增大） | 增大右侧标签向内缩进距离 |
| 「标注版整幅内容往上提一点/别贴底」 | `group_y_mm.annotated` | 曲线与归属标签整组平移；不是单条曲线位移 |
| 「某一条特定谱线微调高低（如 HAMA 往上抬 1mm）」 | `shifts_mm.<作用域>.<曲线id>` | 纯显示位移；必须写明作用域（`main`/`annotated` 等），否则静默不生效 |
| 「图例由两列改成单列」、「图例太宽挡字改成一列」 | `legend_cols: 1` | 调整列数；不要在文本里手工加换行 |
| 「图例整体往左挪一些/居中一点」 | `legend_anchor_x`（调小） | 水平锚点（0 左 1 右）；注意纵向固定在顶部无法改纵向锚点 |
| 「轴标题和刻度数字挤在一起/打架」 | `axis_font_pt`（适当缩小） | 轴标题字号 |

### FTIR 「该拒绝 / 无解」判据：
1. **图例挪到底部/自由定位纵向 y 坐标** → **拒绝/无解**：FTIR 纵向预留高度模型严格绑定「图例占顶部预留」，未提供纵向坐标旋钮。
2. **要求单条曲线透过率数据拉高/改峰值幅度** → **拒绝**：科研真实性硬边界，严禁修改归一化与原始透过率数据。
3. **要求 curve_gap_mm 设为 < 0.5 mm** → **拒绝**：硬契约保护，小于 0.5 mm 标签必压曲线。
4. **跨图修改未指定作用域** → 警告并默认要求指定 `main` 或 `annotated`，杜绝全局污染。
## 禁止

- 改 CSV、归一化、峰位归属判定，或把位移写回 y 数据。
- 越界时偷偷缩字号或裁数据——**报出来**。
- 把同一个 gid 用在两个 Axes 上（对照图上下格必须用各自的 scope）。

## 验收

1. 常见微调里 ≥ 8/10 只改 `ftir.yaml`；
2. `git diff` 里只有 `ftir.yaml`（**从本次改造完成起算**——第一次抽参数当然改了 Python）；
3. `python plot_ftir.py --strict` 退出码 0；
4. 绝对毫米数一律**量导出件**（PDF/PNG），不要量交互环境——不同 matplotlib 版本
   文字度量不同，会给出差几毫米的幻影。

**当前已知 ✗（存量，尚未处理，别当成新引入的）**：含上下标的文字母体 4.7 pt → 字形
3.29 pt（PDF 审计：主图 7 处、标注版 13 处）；`check_edge_clearance` 报 3 处贴边
（图例距上框 0.52 mm 等）。两者都不阻断 `--strict`。

**10 条真实指令验收已跑过一遍（2026-10-09）**，10/10 只改 YAML、10/10 `--strict` 通过。三条实测结论：

1. **`curve_gap_mm` 的"给曲线腾空间"已经接近用尽**：它只剩 0.4 mm 余量（0.9 → 下限 0.5），
   所以「让峰形看起来更高」这类要求最多换来 **+3%** 幅度。再要更高只能动图例/标签字号。
2. **`label_gap_top_mm` 加大会把曲线一起推下去**：+1 mm 的图例净空 = 预留带净增 1 mm，
   曲线跟着下移 0.6 mm（用 `curve_gap_mm` 顶到下限也只能补回 0.4）。要曲线**完全不动**，
   得同时缩小图例或标签字号。
3. **「含上下标字形 ≥ 5 pt」在 48 mm 上是能做的，但代价明确**：母体 7.15 pt 时
   `--strict` 通过、字形审计**全达标**，代价是谱线幅度从 1.98 mm 掉到 **0.92 mm**（−54%）。
   所以这不是"放不下"，是"要合规就得接受谱线变扁"——**取舍，不是故障**。

**图注待补（科研表述）**：五条谱线做过**逐条等高归一化 + 垂直堆叠**，纵向位置与幅度
不可跨样品比较绝对透过率。正式图注必须写明这一点。
