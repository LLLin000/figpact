# figpact 技能与规范 (SKILL.md)

## 1. 新图接入流程
数据处理与业务逻辑保持不动，只抽取排版与几何参数：
- 画布 (canvas)
- 坐标轴与范围 (axes)
- 刻度 (ticks)
- 轴标题 (labels)
- 图例 (legend)
- 系列/谱线 (series/curves)
- 标注/标签 (annotations/bands)
- 色带与辅助线 (bands/guides)
- 作用域 (scope)

## 2. 参数契约字段
- `key`: 参数名
- `meaning`: 物理/排版含义
- `unit`: 计量单位 (mm, pt, a.u., 无)
- `range`: 合法数值范围
- `policy`: 变动策略 (`locked` / `edit` / `conditional` / `derived`)
- `affects`: 影响的视觉对象与图元

## 3. 自然语言需求 → 改动参数映射
自然语言需求对应到参数契约修改，并附真实微调范例。

## 4. 禁止项与如实报告规则
- 禁止静默放行任何阻断几何问题。
- 禁止为规避 QA 私自缩放文字或篡改实验数据。
- 空间无解时必须如实报告 `NO_FEASIBLE_SLOT` 或阻断信息。
