# G16：Verified Style Overlay（R2）

## 产品语义

Native Parameter Binding 与 Verified Style Overlay 为两条明确分开的控制路径。
R2 持久化的是声明式样式文件，不是第三方 Python 源码修改；仍要求可信 Figure 重建入口。
只允许 xlabel/ylabel fontsize、主刻度标签 fontsize、确定身份且连接的数据 Line2D linewidth。
不提供任意方法调用、Collection/误差棒/柱形/散点/图例编辑或 Python AST 自动改写。

G15 的原文、声明、R0/R1 分数与报告保持不变。R2 在独立目录运行；不倒填为 R0 能力。
来源固定为 tools/g15/inputs.json 中上游 commit 4aeb773422464799998d900198b35cb80e94b3e1。

## 实现前固定的三个样本与目标

| G15 样本 | 现有重建入口 / scope | R2 目标 | 必须不变 |
|---|---|---|---|
| B/barchart.py | tools/g15/B/g15b_barchart_decl.py / main | ylabel “Length (mm)” fontsize 8 pt | 柱高、柱位置、柱标签、图例、轴标题文本、数据视图 |
| A/subplots_demo.py | tools/g15/A/wrap_subplots_demo_r1.py / fig07（共享 x 双 Axes） | 上方面板 y 主刻度字号 8 pt | 下面板刻度字号、两条曲线、共享轴关系和视图 |
| B/errorbar_features.py | tools/g15/B/g15b_errorbar_decl.py / ax0 | 上方面板连接的均值 Line2D linewidth 0.8 pt | 下方面板数据线、所有误差棒 LineCollection 的线宽/segments、marker、科学视图 |

这里 Figure/Axes 路径用于人工预选目标；持久化后不能仅靠遍历序号重定位。
目标以 inventory 的结构指纹、唯一身份与源文件/依赖哈希锁定；有歧义则拒绝，不能选一个相近对象。
如果某样本原有空间 QA 失败，保留整图 FAIL，可明确请求保存本地审计通过的工作草稿；
不能把局部编辑有效性冒充整图 PASS，也不降低 QA 使其变绿。

## 验收

1. 首次编辑目标实测变化，非授权属性与科学数据/视图不变；共享参数不导致误差棒连带修改。
2. 原始脚本和 config 字节不变；Overlay 经现有原子/可恢复写入机制保存。
3. 全新进程仅加载原始可信重建入口 + Overlay，确定性应用、审计并生成实际图。
4. 第二次 Apply 使用绝对样式值、不累积；保存文件字节一致或明确无操作，不以无效目标伪装首次成功。
5. 多 Axes 同类对象隔离；对象消失、重复/歧义、源文件或依赖漂移均 fail-closed。
6. 属性白名单与数值验证覆盖 bool、NaN/Inf、非法字段/方法/类；拒绝时 Overlay 与原图源字节不变。
7. 独立报告 local_edit_state、source_commit_state（明确指 Overlay）、figure_verification_state 与 QA 明细。
8. 至少一个真实获接受、持久化、重启重建后审计通过的编辑，否则 G16 不完成。

保留回归测试、可复跑 R2 检查、机器回执、实际前后图；不修改 G15 旧证据。
