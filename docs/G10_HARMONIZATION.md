# G10：Cross-Figure Design Harmonization（跨科研图视觉设计协调）

**产品重心（定稿）**：让**来源不同、类型不同**的科研图，在**最终稿件尺寸**下形成**统一、可控的视觉设计语言**。
**规格审计是底层保障，不是产品**。"让每张图都漂亮"不是目标；**统一的是整篇论文的设计语言，不是每张图的全部参数**。

---

## 1. 三个边界（不可混为一谈）

| 边界 | 含义 | 不可越界的例子 |
|---|---|---|
| **Comparable** | 可测量、可比较 | SVG 能测字号，但未必能可靠写回 Python |
| **Editable** | 能安全修改并回写 | 有绑定才可改；无绑定 → 只比较 |
| **Conformant** | 改后符合目标规格 | 位图**估计**的字号**不得**当作可验证字号 |

回执对每个角色逐项标注三者，**缺一不可**，且**估计值永不冒充实测值**。

## 2. 角色，而不是图片

比较与统一都以**视觉语义角色**为单位：`axis.title` / `axis.tick` / `curve.linewidth` / `panel.label` / `legend` / `scalebar`（显微图；可测但**需保护标定**）。
**角色相同 ≠ 所有属性必须相同**：Panel label 可以统一 Arial Bold 9 pt；但 FTIR 的峰标注与 CCK-8 的显著性标注**不要求**同一布局。

## 3. 三层样式 + 局部例外

```
Global tokens   字体家族、panel label、基础色、轴标题/刻度样式
Plot profile    曲线、坐标轴、图例、误差线、统计标记
Image profile   panel label、比例尺、间距、图像边界
Local overrides 允许特例，但必须**声明例外理由**；科学内容相关属性**锁定**
```

## 4. Final Layout Space 是一等公民

比较基准**不是原图空间**，而是"放到最终宽度后实际呈现"：

```
最终有效字号 = 源字号 × 放置宽度 / 源宽度      （等比例缩放、不重排时）
```

figpact 的做法是**按最终尺寸重渲染**（`k≡1`），并把 **实测** `k`、`eff_pt`、线宽写进回执——因此"统一"不依赖缩放换算，而是由构造保证 + 实测证明。
区分两个概念：**Figure**（单图内容与设计） vs **Plate/Manuscript Layout**（最终摆放与视觉关系），共享 token，约束不同。

## 5. 最小配置（示例）

```yaml
plate:
  layout: manuscript
  figures:
    - id: ftir
      source: Fig1
      target_width_mm: 80
    - id: xrd
      source: Fig2
      target_width_mm: 80
design:
  global:
    font_family: Arial
    axis_title_pt: 8
    axis_tick_pt: 7
    panel_label_pt: 9
  plot:
    curve_linewidth_pt: 0.8
policy:
  science_content: locked
  unsupported: report
  unmeasurable: not_verified
```
`source` 实际还需：输入类型、元素身份、可编辑能力、内容哈希。

## 6. 命令（比较 → 统一 → 复核）

```
figpact plate compare <plate.yaml>   # 跨图角色表：每格给 实测值 + Comparable/Editable/Conformant
figpact plate unify <plate.yaml>     # 由共享 token 生成计划；--apply 才写（既有漂移检查+原子写+写后复验）
figpact plate receipt <plate.yaml>   # JSON：规格/实测/偏差/三边界/双状态/哈希
```

## 7. 下一轮最小验证（4 张不同类型的真实图）

在**统一最终宽度**下执行：①比较每张图**所有可测量角色**；②应用共同 Global Design；③保留类型特有问题与局部例外；④重新生成最终图，出具**统一前后可计算差异**与合规回执；⑤**人工审阅**是否更协调。
**明确不做**：自动审美评分。若数值全达标但肉眼仍不协调，结论是**需要新的可比较属性**，而不是让 agent 乱改。

## 8. 不做清单

整版 GUI 拖拽；新排版算法；AI 自动美化；第二套期刊规格词表（接外部 profile 语义）；把估计值当实测值。
