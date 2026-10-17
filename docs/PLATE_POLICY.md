# PLATE 统一策略：可统一 / 不可统一

`unify` 只改 YAML 源码参数（经 `figpact.final_size.apply_final_size` +
`source_writes` 日志链路），写后重渲染复测。目标由用户给定或外部 profile，
工具不自创规格。

## 默认可统一（代码与矢量来源的对应参数）

| 角色 | YAML 键 | 理由 |
|---|---|---|
| `axis.title` | `axis_font_pt` | 跨图横向比较的主标识，统一收益最大 |
| `axis.tick` | `tick_font_pt` | 同上；FTIR 等契约未声明该键时按“不可统一”拒绝（见下） |
| `curve.linewidth` | `line_width` | 只影响观感，不改布局 |

达标线：统一后各图同角色实测极差 ≤ 0.25 pt（`UNIFY_TOLERANCE_PT`，
见回执 `role_spread_pt[].within_tolerance`）。

## 只比较、默认不强制统一

峰/官能团**标注**（`peak_font_pt`/`label_font_pt`）、**图例**
（`legend_font_pt`）、备注（`note_font_pt`）：信息密度逐图不同，
强行统一会放不下。`plan_unify` 不把它们列入 `steps`；
审计表照常给出实测值供人判读。

## 不可统一

- **位图的任何字号/线宽**：不可恢复，只能比较摆放尺寸。
- 矢量已转曲文字的字号：无内嵌文字，并列入 `unmeasurable_specs`。
- 需要改科学内容才能腾出空间的项（谱线位置、积分窗口、归属文本）。
- 契约中非 EDITABLE 的键（如 FTIR 的 `tick_font_pt` 未声明）：拒绝，
  给替代方案（显式指定局部值 / 保持比较-only）。

## 拒绝三段式（`plan.status == "infeasible"` 逐条含）

1. 为什么不行（含 gid 与实测超限量，如 `overflow: [["left", 5.058]]`）；
2. 需要什么才能行（加宽目标宽度 / 移动图元 / 显式局部值）；
3. 一条建议命令（`figpact plate unify ... --apply` 的具体参数）。

**禁止自动缩字**：放不下 → `infeasible`，绝不悄悄改小字号。
`k>1`（目标宽大于实测导出宽、会被放大）同样报 `infeasible`。
