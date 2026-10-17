# G14 Apply 证据：`plate_g11.yaml` 四图（隔离副本实测，本轮重跑）

清单 `examples/plate/plate_g11.yaml`：demo（verified contract）+ ftir + SVG + PNG，统一 80 mm；
目标 token：`axis_title_pt=8` / `axis_tick_pt=8` / `curve_linewidth_pt=0.8`（容差 0.25 pt）。
`panel_label_pt=9` 仅比较目标，unify 永不强制。

本轮为 `plate.unify` 多 token 联合允许集（`change_audit.verify_apply`）落地后的当前工作树重跑
（上一版文档在旧代码上为 `AUDIT_BLOCKED`，已作废，被本文件覆盖）。
退出码：`plate compare`（before）0 → `plate unify`（plan）1=`partially_feasible`
→ `plate unify --apply` 1 → `plate compare`（after）0 → `plate receipt` 0。
（注意：apply 的 exit 1 来自 ftir `figure_verification_state=FAIL`，顶层 `status` 仍为 `OK`，见 §6。）

## 0. 方法与隔离（实跑命令）

- 隔离副本两份（`figpact` 以 junction 指回仓库，仅读）：
  `C:\Users\Lin\AppData\Local\Temp\g14ev_before\`（before 实测 + plan 用，apply 后未再动）与
  `C:\Users\Lin\AppData\Local\Temp\g14ev\`（apply + after + receipt 用），
  各复制 `examples/plate`、`examples/demo`（含 `demo.contract.yaml`）、`examples/ftir`，保持相对布局。
- 契约绑定改写仅在副本内：两份副本 `demo.contract.yaml` 第 2–3 行 `script`/`config`
  绝对路径指向各副本（否则 plate 会因"contract 指向不同脚本/作用域"正确拒绝）。仓库内契约文件本轮未动。
- 顺序（环境 `PYTHONPATH=D:/L/AI/figpact`，`MPLBACKEND=Agg`，`PYTHONDONTWRITEBYTECODE=1`，
  Python `D:/programs/Python/python.exe -B -X utf8`）：
  before 副本 `plate compare --json --out before.json`（exit 0）→
  `plate unify`（plan, exit 1）→
  apply 副本 `plate unify --apply > apply.json`（exit 1，顶层 status=OK）→
  `plate compare --json --out after.json`（exit 0）→
  `plate receipt --out receipt.json`（exit 0）。
- 本轮未写入仓库任何文件：仓库 `examples/demo/demo.yaml`（`4f4dc35be395ad87…`）与
  `examples/ftir/ftir.yaml`（`d6946d9286ffc3f9…`）sha256 与副本统一前逐字节一致；
  `git status --porcelain -- examples/` 仅见 `M examples/demo/demo.contract.yaml`，
  该修改相对 HEAD 有 131 行（119+/12-），来自本轮之前的并发任务，非本轮产生（本轮命令只读仓库 examples）。
  仓库 `.py` 源文件本轮未动（见 §8）。

## 1. 统一前（before，compare 实测，`g14ev_before`）

| role | demo (code) | ftir (code) | synth_vector (vector) | micro_bitmap (bitmap) |
|---|---|---|---|---|
| axis.title | 7.11 pt [C✓ E✓ F✗]（verified-contract；k=0.889301，画布 90×60 mm） | 14.18 pt [C✓ E✓ F✗]（k=1.667929，画布 48×48 mm） | spans[10.5,13.5] n=2 [C✗ E✗ F–]（无缩放上下文，角色不可归因） | — [C✗ E✗ F–]（物理 81.28×60.96 mm @300 dpi；字号/线宽不可恢复） |
| axis.tick | 6.22 pt [C✓ E✓ F✗]（verified-contract） | 13.34 pt [C✓ **E✗** F✗]（tick 无可编辑绑定；只报告） | 同上 [C✗ E✗ F–] | 同上 [C✗ E✗ F–] |
| curve.linewidth | 0.80 pt [C✓ E✓ F✓]（verified-contract；cell 值 0.8 已在容差内） | 1.42 pt [C✓ E✓ F✗] | 同上 [C✗ E✗ F–] | 同上 [C✗ E✗ F–] |
| panel.label | 6.22 pt [C✓ E✗ F–]（compare-only） | — [C✗ E✗ F–]（本图无该角色图元） | 同上 [C✗ E✗ F–] | 同上 [C✗ E✗ F–] |
| legend | 6.22 pt [C✓ E✓ F–]（verified-contract；compare-only） | 7.84 pt [C✓ E✓ F–]（compare-only） | 同上 [C✗ E✗ F–] | 同上 [C✗ E✗ F–] |
| scalebar | — [C✗ E✗ F–]（plot 图无 scalebar 角色） | — [C✗ E✗ F–] | 同上 [C✗ E✗ F–] | 同上 [C✗ E✗ F–] |

跨图实测极差（仅实测值）：title min 7.114 / max 14.177 / spread **7.063**；
tick min 6.225 / max 13.343 / spread **7.118**；linewidth min 0.8 / max 1.418 / spread **0.618** → 均未达标。

## 2. 统一计划（plan，`partially_feasible`）

- demo：`axis_font_pt` 8.0→8.0（名义值不动，靠画布 k 修正）、`tick_font_pt` 7.0→8.0、`line_width` 0.9→0.8。
- ftir：`axis_font_pt` 8.5→8.0、`line_width` 0.85→0.8；`tick_font_pt` 不可行动。
- infeasible（3 项，只比较不强制）：ftir `tick_font_pt`（layout_contract 非 EDITABLE；
  替代建议：逐图显式值或保持 compare-only）、vector 与 bitmap（无 YAML 源参数；重建或仅比较）。
- `manifest_hash = bb73573b43dedf361517acd21030803b3b5625bc3a38208cfcf827672e3db244`。

## 3. 统一后（after，compare 实测，`g14ev`）

| role | demo (code) | ftir (code) | synth_vector | micro_bitmap |
|---|---|---|---|---|
| axis.title | **8.00** pt [C✓ E✓ F✓] | **8.00** pt [C✓ E✓ F✓] | 不变 [C✗ E✗ F–] | 不变 [C✗ E✗ F–] |
| axis.tick | **8.00** pt [C✓ E✓ F✓] | **8.00** pt [C✓ **E✗** F✓]（只报告，不可控） | 不变 [C✗ E✗ F–] | 不变 [C✗ E✗ F–] |
| curve.linewidth | **0.80** pt [C✓ E✓ F✓] | **0.80** pt [C✓ E✓ F✓] | 不变 [C✗ E✗ F–] | 不变 [C✗ E✗ F–] |
| panel.label | 7.00 pt [C✓ E✗ F–]（compare-only；随 k 派生） | — [C✗ E✗ F–] | 不变 | 不变 |
| legend | 7.00 pt [C✓ E✓ F–]（compare-only） | 4.70 pt [C✓ E✓ F–]（compare-only；触发 verification FAIL，见 §6-2） | 不变 | 不变 |
| scalebar | — [C✗ E✗ F–] | — [C✗ E✗ F–] | 不变 | 不变 |

跨图实测极差：三角色 spread 均为 **0.0**（8.003/8.003/0.8，容差 0.25 pt）→ 达标。
SVG/PNG 在 before/after 间逐格一致（sha256 见 §8），保持 C✗E✗（边界未被动过）。

## 4. 各角色数值变化的来源分类

| 图 | 角色 | 名义值变化 | effective 变化 | 来源分类 |
|---|---|---|---|---|
| demo | axis.title | 8.0→8.0（未动；journal diff 无此行） | 7.114→8.003 | **缩放派生**（k 0.889301→1.000404；画布 90×60→80×53.333 mm） |
| demo | axis.tick | 7.0→**8.0** | 6.225→8.003 | **自身参数**（+ 缩放派生叠加） |
| demo | curve.linewidth | 0.9→**0.8** | cell 值 0.8→0.8（diff 0.1→0.0） | **自身参数** |
| ftir | axis.title | 8.5→**8.0** | 14.177→8.003 | **自身参数**（+ 缩放派生叠加；k 1.667929→1.000404，画布 48×48→80×80 mm） |
| ftir | axis.tick | 8.0→8.0（**未动**；YAML 仍为 8.0，`refused_roles = ["tick_font_pt"]`） | 13.343→8.003 | **缩放派生**（8.0×1.667929=13.343；8.0×1.000404=8.003，完全由 k 解释） |
| ftir | curve.linewidth | 0.85→**0.8** | 1.418→0.8 | **自身参数** |
| demo/ftir | panel.label、legend | 名义值均未动 | 随 k 派生（如 demo 6.225→7.003；ftir legend 7.839→4.702） | **缩放派生**（compare-only，从未强制） |

- FTIR tick 保持 **E✗**（layout_contract 非 EDITABLE 且无已验证 contract），其 F✓ 为**碰巧达标 ≠ 受控达标**，
  不得升 E✓。apply 记录中 ftir `changes.tick_font_pt = [8.0, 7.0]` 的 7.0 是缺省目标口径，
  实际未写入（YAML 第 96 行仍为 `tick_font_pt: 8.0`，`refused_roles = ["tick_font_pt"]`），特此澄清以免误读。
- **无"间接"与"越权"来源**：全部 effective 变化均可由"名义值写入 / k 变化"二者解释；
  越权项见 §5（对象级审计口径，非数值来源；本轮为 0 项）。

## 5. 科学指纹与 unauthorized 结果（apply 内嵌 change_audit，多 token 联合允许集）

- 本轮审计为联合允许集形状：每图一条（不再是每 param 一条）。
  全部 2 条审计 `status = EFFECT_OK`，`science_unchanged = true`，`science_notes = []`，
  `unauthorized = []`（0 项），`within_allowed = true`。
- demo 联合（`param = "tick_font_pt+line_width"`，
  `roles = {tick_font_pt: axis.tick, line_width: curve.linewidth}`）：
  **EFFECT_OK**，`unauthorized` 0 项，`derived_geometry` 2 项
  （`0:xlabel_envelope:0` dy +0.254 mm、`0:ylabel_envelope:0` dx +0.1905 mm，
  size_stable=true，属派生几何）；`within_allowed = true`。
  扰动快照：`tick_font_pt 8.0→7.0`、`line_width 0.8→0.3`（均为 nonzero）；
  `required_targets_effectively_changed` 含 13 个 tick fontsize 与 3 条 curve linewidth。
- ftir 联合（`param = "axis_font_pt+line_width"`，
  `roles = {axis_font_pt: axis.title, line_width: curve.linewidth}`）：
  **EFFECT_OK**，`unauthorized` 0 项，`derived_geometry` 2 项
  （`fig2_ftir.main.xlabel` / `fig2_ftir.main.ylabel` envelope 位移，
  size_stable=false，tol 0.3387 mm 内记为派生几何）；`within_allowed = true`。
- 相对上一版：demo tick 原 17 项 unauthorized
  （`unregistered.Line2D.*`、`unregistered.tick.y.*`、2 个 ytick envelope structure-removed）的
  EFFECT_MISMATCH 已消除——联合口径下 tick+line 联合扰动的副作用落在声明对象并集之内，
  不再判越权。顶层相应翻转：`status = OK`（见 §6）。

## 6. 回执关键字段

apply 输出顶层：`status = OK`（进程退出码仍为 1，来自 ftir verification FAIL，见下）；
`unify.status = OK`；
`compare.roles = [axis.title, axis.tick, curve.linewidth, panel.label, legend, scalebar]`，
`targets_pt = {axis.title: 8.0, axis.tick: 8.0, curve.linewidth: 0.8, panel.label: 9.0}`；
plan `manifest_hash` 同 §2；内嵌 receipt
`content_hash = 48b8894f0558942311379295f18b0fd9665a43c06837ce779eb5240e795e75e9`，
`generated_at = 2026-10-17T16:59:28.612090+00:00`，
`dual_state = {source_commit_state: OK, figure_verification_state: FAIL}`。

- demo：`status OK` / `source_commit_state COMMITTED` / `figure_verification_state PASS`
  （"保存完成并通过验证（重新运行确认）"）；journal 1 文件 `demo.yaml` APPLIED
  （before `4f4dc35b…` → after `415c3652…`，diff：canvas_w/h、line_width、tick_font_pt 共 5 行）。
- ftir：`status OK` / `source_commit_state COMMITTED` / `figure_verification_state FAIL`；
  journal 1 文件 `ftir.yaml` APPLIED（before `d6946d92…` → after `2a536cf5…`；
  实质变更仅 canvas 48→80、axis 8.5→8.0、line 0.85→0.8，其余为重排版全文件重写）；
  `infeasible_report = "label_font_pt effective 4.702pt < 5pt; legend_font_pt effective 4.702pt < 5pt"`，
  另有 spatial_risk（Line2D top 溢出 4.023，两项，仅报告）。
- 独立 `plate receipt`（统一后复测）：`content_hash = 921fa73a2264526f95917a4b6b7879bc0fac19826fee4f85cefd880ffc91f741`，
  `generated_at = 2026-10-17T16:59:57.089493+00:00`，
  `role_spread_pt` 三角色 `within_tolerance: true`（8.003/8.003/0.8），
  `dual_state = NOT_WRITTEN/NOT_RUN`（receipt 本身不写源）。
  `schema_version = plate-receipt/1`，note：除 `generated_at` 外逐字节可复算。

## 7. 未达预期（2 项，如实记录）

1. **ftir verification FAIL**：`label_font_pt` / `legend_font_pt` effective **4.702 pt < 5 pt** 下限。
   名义值 4.7 从未被统一目标覆盖；统一前 k=1.668 将其放大为 7.839 而掩盖，k 归一后暴露。
   非目标角色，但 verification 状态为 FAIL，故内嵌 receipt `figure_verification_state = FAIL`，
   且 `plate unify --apply` 进程退出码为 1（顶层 `status = OK` 不受此影响——audit 口径与 verification 口径分离）。
2. **口径差异两处**：① 内嵌 receipt 的 `role_spread_pt` 仍为统一前极差
   （7.063/7.118/0.618，`within_tolerance: false`），与其同文件的 compare cells（8.003，F✓）不在同一口径，
   仅记录未深究；② ftir `changes.tick_font_pt = [8.0, 7.0]` 易误读为"被写成 7.0"，实际 YAML 仍为 8.0（见 §4）。
   本轮 apply/after 的 stderr 无非阻断警告（`RuntimeWarning: More than 20 figures` 本轮未出现）。

## 8. 副本内源文件写入状态与关键文件哈希（sha256）

- 副本内实际写入：仅 `examples/demo/demo.yaml` 与 `examples/ftir/ftir.yaml`（各 1 文件，APPLIED）；
  `demo_figure.py`、`plot_ftir.py`、数据目录、`synth_vector.svg`、`micro_bitmap.png`、
  副本契约文件均未被写入。
- 仓库 examples 本轮未写（`git status --porcelain -- examples/` 仅见本轮前已有的
  `M examples/demo/demo.contract.yaml`；仓库 `demo.yaml`/`ftir.yaml` sha 与副本统一前一致）：
- `f534ade18490e93…` `examples/plate/plate_g11.yaml`（与仓库一致，未动）
- `415c3652ebe9fb40…` 副本 `examples/demo/demo.yaml`（统一后；统一前 `4f4dc35be395ad87…` = 仓库/HEAD）
- `dbe6890e48692d9b…` 副本 `examples/demo/demo_figure.py`（= 仓库 worktree，本轮未写）
- `5de49d6f8a9ac8f1…` 仓库 `examples/demo/demo.contract.yaml`（worktree 当前值；副本 = 该值 + 仅改 2 行 script/config 路径）
- `2a536cf5a78e012b…` 副本 `examples/ftir/ftir.yaml`（统一后；统一前 `d6946d9286ffc3f9…` = 复制时仓库值）
- `32f8df6ffb592eb1…` 副本 `examples/ftir/plot_ftir.py`（= 仓库 worktree，本轮未写）
- `5337cbb99d74f67a…` `examples/plate/synth_vector.svg`；`b17874bb491c98f5…` `examples/plate/micro_bitmap.png`
  （仓库与副本逐字节一致，before/after 未动）
