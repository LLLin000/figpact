# PLATE 证据：4 张图的统一前 / 统一后（实测）

**清单**：4 张不同类输入，统一最终宽度 **80 mm**；共享目标 `axis.title 8 pt`、`axis.tick 7 pt`、`curve.linewidth 0.8 pt`。
**输入**：`ftir`（代码，48 mm 源）、`demo`（代码，96 mm 源，全合成）、`synth_vector`（SVG）、`micro_bitmap`（PNG 960×720 @300 dpi）。
**方法**：`figpact plate compare → unify --apply → compare`；有效字号 = **`nominal_pt × 实测 k`**（精确）；字形高度仅作渲染一致性证据。执行在 TEMP 副本上，仓库源文件未被修改。

## 统一前

| 图 | axis.title | axis.tick | curve.linewidth | 说明 |
|---|---|---|---|---|
| ftir（code） | **14.18 pt** [C✓ E✓ F✗] | 13.34 [C✓ E✗ F✗] | 1.42 [C✓ E✓ F✗] | 48 mm 被放大到 80 mm，k=1.667 |
| demo（code） | 7.11 [C✓ E✗ F✗] | 6.22 [C✓ E✗ F✗] | 0.80 [C✓ E✗ F✓] | 96 mm 缩到 80 mm；三角色在契约中不可编辑 |
| vector（SVG） | spans 10.5/13.5 pt，**无法归属角色** [C✗ E✗] | 同左 | 同左 | viewBox 单位，无缩放上下文 |
| bitmap（PNG） | 物理 81.28×60.96 mm；**字号/线宽不可恢复** [C✗ E✗] | 同左 | 同左 | 明确禁止报"达标" |

## 统一后

| 图 | axis.title | axis.tick | curve.linewidth |
|---|---|---|---|
| ftir（code） | **8.00 pt [C✓ E✓ F✓]** | 8.00 [C✓ **E✗** F✗] | **0.80 [C✓ E✓ F✓]** |
| demo（code） | 7.11 [C✓ **E✗** F✗] | 6.22 [C✓ E✗ F✗] | 0.80 [C✓ E✗ F✓] |
| vector / bitmap | 不变（不可编辑，只可摆放） | — | — |

## 结论（如实）

1. **可编辑的角色确实被统一到目标**：FTIR 的轴标题 14.18 → **8.00**、线宽 1.42 → **0.80**，两者 `F✓`。
2. **不可编辑的角色如实拒绝**：FTIR 的 `tick_font_pt` 与 demo 的 `axis_font_pt` / `tick_font_pt` / `line_width` 在各自契约中未声明 → 保持原值并标 `E✗`，**没有被算作"已统一"**。
3. **矢量和位图只能摆放**：矢量给出可测的 span 字号但**无法归属角色**；位图只给出物理尺寸，字号/线宽不可恢复——回执明确标注，不谎报。
4. **"为什么必须在最终尺寸下比较"**：同一张 48 mm、8.5 pt 的图，放到 80 mm 后**有效字号是 14.18 pt**。只看源文件会得出完全错误的结论。

## 由这张表暴露的产品缺口（下一步）

**契约覆盖率就是统一能力的上限。** demo 图无法统一，不是因为不能渲染，而是因为脚本没有暴露 `axis/tick/linewidth` 这些角色 → 需要 `figpact init-contract`（生成最小可编辑声明草稿，人审后生效）。
在此之前，"跨图统一"只能覆盖**已经暴露角色**的图件；这是能力边界，不是缺陷。

---

## 补记：`init-contract` v0.1 之后的复测（收口证据）

**demo 的契约**（`examples/demo/demo.contract.yaml`）中三条绑定经**人工确认 + 非零扰动**验证为 `verified`；比较表现在读契约：

| 图 | axis.title | axis.tick | curve.linewidth |
|---|---|---|---|
| **demo**（代码） | 7.11 [C✓ **E✓** F✗] *经由 verified-contract* | 6.22 [C✓ **E✓** F✗] *经由 verified-contract* | 0.80 [C✓ **E✓** **F✓**] |
| **ftir**（代码） | 14.18 [C✓ E✓ F✗] | 13.34 [C✓ **E✗** F✗]（`tick_font_pt` 无可编辑绑定） | 1.42 [C✓ E✓ F✗] |
| 矢量 / 位图 | 仍 `C✗ E✗`（**边界未变**，未因新增能力而被宣称可编辑） | — | — |

- **`E✓` 的含义是可证明的**：demo 三角色由"人工确认 + 扰动生效 + 对象身份一致 + 无副作用"四项齐备后升级；FTIR 的 tick 在同一张表里仍是 `E✗`——说明这不是"一律放行"。
- **`F✗` 是真实差距**：demo 的 title/tick 实测 7.11 / 6.22，而目标是 8.0——需要执行统一（`unify --apply`）才会变成 8.00 `F✓`（FTIR 的 title 已验证可达 8.00 `F✓`）。
- **覆盖率（分母恒为 6 个角色，含未发现）**：`verified_editable = [axis.title, axis.tick, curve.linewidth]`、`candidate = []`、`unresolved = [legend, panel.label]`、`unsupported = [scalebar]`。**没有把未发现角色从分母里剔除**。

**三项收口条件对照**：demo 三角色 `E✗ → E✓` ✓；SVG/PNG 能力边界不变 ✓；FTIR `tick` 保持 `E✗` ✓。科学数据与非目标不变作为每条绑定的证据之一随扰动一并校验。
