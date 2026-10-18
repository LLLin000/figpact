# G16 Verified Style Overlay / R2

## 结论

三个预登记的陌生 Matplotlib 图目标均完成了 **真实接受 → 原子保存 Overlay → 全新进程重建/审计/渲染 → 重复 Apply**。
这是无需预先将科学绘图脚本全面 YAML 参数化的声明式样式覆盖，不是原始 Python 自动改写，仍要求可信、可复现的 Figure 建图入口。
Native Parameter Binding 不变；G15 的 R0/R1 与本轮 R2 分开记账，没有回填旧分数。

范围与目标在实现前固定，见 [G16_PROTOCOL.md](G16_PROTOCOL.md)。
G15 的 44 份冻结文件（原文、声明、指标、报告）逐文件 SHA-256 复核，**0 个变化**。

## 1. 三个真实成功编辑

| 样本 / 操作 | 首次有效变化 | 保存 | 新进程重建 | 重复 Apply | 整图 QA |
|---|---|---|---|---|---|
| barchart，ylabel “Length (mm)” | 10 → 8 pt | COMMITTED | 局部审计 PASS、science unchanged | Overlay 字节相同 | PASS |
| 共享轴双面板，上方 y 主刻度 | 10 → 8 pt | COMMITTED | 局部审计 PASS、science unchanged | Overlay 字节相同 | PASS |
| 误差棒图，上方连接数据 Line2D | 1.5 → 0.8 pt | COMMITTED | 局部审计 PASS、science unchanged | Overlay 字节相同 | PASS |

实际通过公开 CLI，inventory、apply、render/restart、repeat 各为不同 Python 进程。
本轮三目标全部得到 `local_edit_state=PASS`、`figure_verification_state=PASS`、`source_commit_state=COMMITTED`；
所有原始 wrapper 与科学源码字节不变。这里的 COMMITTED 明确指 Overlay 文件，不是第三方 Python 修改。

额外独立检查：

- 共享轴图上方 y 字号 8 pt，下方 y 仍为 10 pt；共享 x 关系保留。
- 误差棒图上方曲线 0.8 pt，下方数据线 1.5 pt；所有 LineCollection 线宽与误差线段逐值不变。
- marker、xlim/ylim、线性/log 标度不变。
- 实际 after PNG 已查看，未以仅单元测试替代图形输出。

## 2. 新增接口与控制权

`figpact/style_identity.py`：

- 从实际 Figure 清点三类目标；返回只读身份与当前实测属性。
- Axes 使用真实 GID（有且唯一时）、GridSpec/subplot 结构、数据/视图/文本指纹；add_axes 使用结构矩形。
- 曲线使用精确数据摘要、label/GID、连接方式、marker/transform 等结构，不靠遍历顺序。
- 主刻度目标是指定 Axes 的 x/y 可见、非空主刻度标签集合；共享轴隐藏标签不暴露为目标。
- 重复 GID、同结构 Axes/曲线歧义、对象缺失或结构漂移即拒绝，不自动选择相近对象。

`figpact/style_overlay.py`：

- `inventory(script, config=None, scope=None)`：可信入口重建与身份清单。
- `apply(..., edits=[{target_id,value}], overlay=..., expected_before_sha256=None, allow_draft=False)`：
  白名单绝对值控制、独立重建验证、条件持久化。
- `load(overlay_path)`：源依赖先验校验、独立重建与应用；返回已验证 Figure 和回执。
- `render(overlay_path, output)`：验证后渲染，拒绝覆盖 Overlay 或任何受保护源/科学依赖。

请求只含 `target_id` 与有限数值，不能指定 Python 方法、任意属性或伪造 Artist 类型。
三个 setter 固定在引擎内；无 Collection/caps/marker-only/legend/bar/scatter 编辑入口。
数值范围 fontsize 0.5–100 pt、linewidth 0.05–20 pt；可解析的范围不等于出版 QA 通过，
例如 4 pt 字号可作明确失败草稿，但不会冒充整图 PASS。

## 3. 验证复用与隔离

对象差异由现有 `change_audit.audit_pair` 判定，科学内容由 `science.capture_science/compare_science` 保护，
视图由现有 snapshot 保护。新增的是授权对象清单与样式绑定，不是第二套科学验证器。
现有窄语义样式快照只记录字号/线宽/文本，新路径补充颜色、alpha、marker、linestyle、visible、Collection 线宽等观测，
避免把“科学指纹不变”误当“非授权语义属性不变”。

每次 apply/load 比较两组从干净源码独立重建的 baseline/candidate。非零目标效果、允许属性集合、
科学指纹、受保护视图必须成立；两次候选结果必须一致。用于 render 的下一次实际 Figure 还核对完整样式/几何/视图/science/QA 指纹，
不是只检查目标数字。未知几何变化不因为重建完成就自动豁免。

字体可触发布局管理器重排：字形盒及纯布局 envelope 的派生变化逐项记录；
柱形 patch 的显示重排仅在科学数据/视图不变、非目标样式不变且独立重建重复出现时记作派生。
polyline/Collection/image 几何不被一概豁免。没有为了使样本成功修改 G14 原规则或降低 QA。

整图 QA 使用现有 blocking checks 与数学字形下限，新路径补足可见普通文本的 5 pt 下限；
不修改旧 QA 行为。局部通过不代表整图通过。

## 4. 持久化与漂移

Overlay 是版本化 JSON，含目标身份、绝对属性值、来源、scope、精确依赖文件引用及 SHA-256。
依赖覆盖 wrapper、config、RAW 与声明的 science inputs；不猜 `raw/*.py`，不对整个目录含缓存/产物做模糊扫描。
加载前先按存储路径校验字节，再执行可信模块；执行后校验实际依赖集合与哈希，写入前再核对。

首次保存复用 `source_writes._write_json` 先写完整同目录临时文件，再以 hardlink 原子排他安装：
若另一个创建者已占用目标则拒绝，绝不替换它；不支持该安装方式时明确失败。
更新复用现有原子替换并校验 expected hash，沿用**单写者约束，不宣称跨进程 CAS**。
相同声明重复应用保持既有文件字节不变。跨盘路径可存绝对引用并标记不可移植，不能假装可相对迁移。

失败拒绝保持已有 Overlay 字节不变；源程序和 config 始终不写。
`allow_draft` 仅允许局部审计通过且整图 QA 未通过时保存 `COMMITTED_DRAFT / FAIL`；
退出码 1，失败草稿不渲染为已验证产物。

## 5. 已验证的失败边界

永久回归覆盖：

- constrained_layout 重复 draw 后身份不漂移；编辑属性不参与身份选择。
- 共享轴隐藏刻度不暴露，上下 Axes 目标集合分开。
- 重复曲线歧义、对象消失、未知属性/字段拒绝。
- bool、NaN、Inf、负数、超范围值不创建 Overlay。
- 4 pt 普通标签默认不保存；显式草稿保存并在重载后维持整图 FAIL。
- stale expected hash 更新不覆盖已有字节。
- 修改源脚本后，重载在执行变更代码前拒绝（用模块顶层 marker 副作用证实）。
- render 不允许覆盖 Overlay/源依赖。
- 新进程重载误差棒图，只改 Line2D，Collection 线宽和科学视图保留。

过程中修复了真实实现缺陷：constrained_layout 多次 draw 微迭代导致身份漂移、跨盘相对路径拒绝、
普通小字被旧数学字形检查漏过、stale 回执重复关键字异常、依赖路径猜测和渲染下一次重建未核对全部指纹。
这些是 G16 新路径的修复，G15 证据未变。

## 6. 证据与复跑

```bash
python tools/g16/run_acceptance.py --output-dir <fresh-output-directory>
python -m pytest tests/test_style_identity.py tests/test_style_overlay.py tests/test_style_overlay_failures.py tests/test_style_overlay_drift.py -q
```

真实 CLI 回执、Overlay、after PNG 和新进程日志：
`D:/L/AI/figpact-archive/g16/r2-release/`。
独立非目标核对：该目录的 `independent-invariants.json`。
G15 冻结哈希：`D:/L/AI/figpact-archive/g16/g15-frozen-hashes.json`。
可复跑入口与紧凑 R2 结果保留在 `tools/g16/`。

已执行相关组合：**27 passed**（新身份/Overlay/草稿/漂移、统计图状态、plate、事务回归）。
最终全量非浏览器实际执行：**567 passed / 7 skipped / 1 warning / 87 subtests passed**，耗时 849.38 秒。
浏览器本轮尚未复跑；未改 GUI，也不以此宣称浏览器验证。

## 7. 能力上限

本轮证明的是三操作、可信重建入口、稳定唯一身份下的声明式覆盖闭环，不是任意 Python 自动改写、任意图元编辑或自动科研语义理解。
不增加 G17 源码重构、GUI、自然语言编辑、误差棒样式或更复杂 Artist 能力。
原始科学程序不必全面 YAML 参数化，但仍须能被确定性重建，依赖来源必须可信。
