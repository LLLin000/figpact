# G15 冻结引擎陌生图检查

## 结论

**本轮没有证明“陌生科研图可通用编辑”。** 8 个预先选定的第三方源码、29 张原始 Figure，
在两种接入条件下均没有产生可验证的编辑绑定，15 个合法视觉修改意图均未成功写入并通过验证。
这是能力边界，不是为了变绿而排除的失败。

引擎冻结 SHA：`793aaa89b39af49d2421e2a2840751cf757ba959`。
冻结后没有修改引擎、角色注册表、发现规则或 QA 标准。38 个产品文件的字节摘要前后一致：
`61e9c0da6a478eb288d00adeab2c0d1a79080454d6d2ed8002b22df1c9208f6c`。
冻结算法与环境见 `tools/g15/freeze.json`，原始输入与 SHA-256 见 `tools/g15/inputs.json`，
整数汇总见 `tools/g15/summary.json`，计分预登记见 [G15_PROTOCOL.md](G15_PROTOCOL.md)。

这是冻结软件后的陌生开源输入检查：不声称随机抽样、独立第三方双盲或总体准确率。
所有样本均来自 [Matplotlib v3.10.7](https://github.com/matplotlib/matplotlib/tree/4aeb773422464799998d900198b35cb80e94b3e1/galleries/examples)，
并非 figpact 开发者为适配引擎编写的新图。实际执行环境为 Python 3.14.0 / Matplotlib 3.10.8 /
NumPy 2.3.3 / Agg，第三方源码版本与宿主库版本分开记录。许可和署名保留在 `tools/g15/`。

## 1. 固定样本及两种接入条件

- A：`subplots_demo.py`、`label_subplots.py`、`figlegend_demo.py`。
  组合覆盖共享轴、多 Axes、真面板字母、Figure 级图例，合计 17 张 Figure；不冒充单图全覆盖。
- B：`barchart.py`、`errorbar_features.py`、`scatter_with_legend.py`。
  覆盖柱形/柱标签、误差棒、连接曲线、散点与多图例，合计 5 张 Figure。
  `errorbar(fmt='-o')` 中的数据曲线计入 curve.linewidth；marker-only 数据线不冒充连接曲线。
- C：`eventcollection_demo.py`、`annotation_demo.py`。
  覆盖曲线、EventCollection、普通 Annotation、箭头、Ellipse、极坐标和混合变换，合计 7 张 Figure。

第三方源文使用完整文件，不按运行结果换样本或挑面板。每文件的角色真值是所有原文 Figure 的并集，
六角色中实际存在者才进入召回分母；默认刻度也算实际存在。`axis.title` 仅指 xlabel/ylabel，
不是 Axes title。普通解释性 Annotation 不算面板字母。

**R0 原始脚本**：源文件字节不变，CLI 必填配置为外置空 YAML，不假装已有绑定。

**R1 仅协议声明**：包装器完整执行原文后选择对应 Figure，提供现有 build/load/contract/对象身份声明；
没有补 cfg 接线，没有新增可编辑参数，没有绘图后字体/线宽 setter，没有专用图种适配。
声明中的空参数集合忠实反映原脚本缺少已授权绑定，不代表编辑成功。
每个返回 Figure 的 registry 只枚举该 Figure 真实 Artist，contract 节点来自真实 registry。
B 的误差棒图有两个检查 scope 指向同一个原始 Figure，因此总计 **30 个 R1 scope，不是 30 张不同 Figure**。

**R1 方法限制**：本轮选择 wrapper 声明形式，Discover 只解析 wrapper AST，不追踪 runpy/exec 内的原文。
因此 R1 的源文角色提示会消失。这是声明形式与发现器的可见性边界，不能推论所有“只加协议”形式都必然如此，
也不能把 R0 的源文提示和 R1 的开发者声明混成引擎自动识别能力。

## 2. 实际指标

角色召回仅计有正确源文位置与语义的提示（含 unresolved），不是 editable 候选通过率。
字面量/默认样式没有 YAML 绑定，但正确角色提示仍可计入召回。按源文件角色种类去重，不随 scope 数膨胀。

| 指标 | R0 原始脚本 | R1 仅协议 wrapper |
|---|---|---|
| Role discovery recall（源文角色提示） | **9/19** | **0/19**，受上述 AST 可见性限制 |
| Binding precision | **N/A，0 个候选** | **N/A，0 个候选** |
| Edit success rate | **0/15** | **0/15** |
| Capability rejection | **15/15**，缺原生建图入口/参数绑定 | **15/15**，可测量但缺可授权写回绑定 |
| False rejection | **N/A**：无现有协议可表达并独立证明安全的绑定请求 | **N/A**：同左，不能声称误拒率为 0 |
| Unauthorized acceptance | 观测 0、接受 0；**比率 N/A** | 观测 0、接受 0；**比率 N/A** |
| 重复 Discover | **8/8** 文件结果一致 | **30/30** scope 结果一致 |
| 重建检查 | 原图全部渲染，编辑链因缺入口阻断 | **30/30** scope 重建检查一致；重复 Apply 均拒绝且源/config 字节不变 |

没有获接受的编辑，因此本轮**不能证明获接受编辑的越权率为 0，也不能证明成功 Apply 的幂等性**。
稳定拒绝不是成功编辑；Verify 的 `0 verified / 0 failed` 不是验证通过率 100%。
源文件缺绑定的合法视觉意图仍保留在编辑成功率分母，未以“当前不支持”为由删去。

逐文件整数见 `summary.json`：A 正确提示为 1/3、1/2、2/3；B 为 2/3、0/2、1/2；C 为 1/2、1/2。
R0 缺失 10 个“文件×角色种类”：8 个默认刻度、通过 `Axes.set(xlabel/ylabel)` 创建的轴标签、
以及通过 `Axes.errorbar` 创建的连接曲线。

## 3. 管线到底走到了哪里

所有条件均实际尝试 Discover → Verify → compare/Apply → receipt/audit，保存命令、退出码和 stdout/stderr。
前置失败的后续命令记录失败，不制造成功产物。

- **R0**：Discover 可产生部分源文提示，但 0 个可编辑候选；Verify 记录 0 个 verified。
  plate 的建图/审计阶段报 `RuntimeError: script exposes no build entry`，退出 1。
  该拒绝目前是 traceback，尚不是统一的结构化能力拒绝回执。
- **R1**：既有协议使测量与报告阶段可达。Apply 仍无可授权写回入口，结果 FAILED / NOT_WRITTEN / NOT_RUN。
  图例、面板字母保持 compare-only；没有把科学数据、视图或误差棒偷偷改掉以满足目标。
- 源码参数不一定等于单一 Artist/视觉角色；本轮没有获得任何合法可编辑绑定，
  所以不能据此估计通用多 Artist 属性控制模型的充分性，也没有加 errorbar 特殊豁免。

## 4. 发现的真实边界

1. **源码入口和参数接线是第一道瓶颈**：原始 gallery 不是约定中的参数化脚本；身份声明不会自动创建源码控制权。
2. **发现器的语法/可见性边界**：默认刻度、`Axes.set(...)`、`Axes.errorbar(...)` 未被源文发现覆盖；wrapper 内的动态执行不被 AST 发现追踪。
3. **提示层有语义错配**：`set_title` 被提示为 axis.title；C 的 34 个普通 annotate 调用被提示为 panel.label。
   它们没有升级为 editable 绑定，不能称为已接受的越权，但也不能因为 0 candidates 就把这些提示误报归零。
4. **测量不等于控制**：Figure legend/Collection 等可以存在、可以测到部分规格，并不意味着有经过扰动验证的源码绑定。
5. **成功编辑的关键指标尚不可估计**：binding precision、已表达安全修改的误拒率、获接受修改的越权率，
   都因 0 个绑定/0 个获接受编辑而没有有效分母。G14 的安全证据不能自动替代 G15 的陌生输入证据。

## 5. 实验自身的有效性勘误

本轮审阅纠正了评测代码和评分错误；所有旧证据留在归档，但不进入主表：

- B 初稿将 scatter 按 `# %%` 拆段重放，丢掉随机状态和之前代码的随机数消耗。
  属 **harness-invalid**，不是引擎不确定性。修正为完整原文执行，三个原文 Figure 的 offsets/sizes
  两次重放均逐值及完整 SHA-256 等于原始顺序执行；父代理再次独立执行验证。
- C 初稿将多个 Figure 的 registry 塞给第一个 Figure，且构造了不存在的节点。
  属 **harness-invalid**。修正为每 Figure 一个 scope，真实节点枚举；全部 6 个 annotation Figure 重新跑管线。
- A 初稿缺少必需的 layout_contract，不能将缺声明的 AttributeError 当作完整 R1 结果。
  补的只是空参数、真实节点元数据；全部 17 scope 重新跑 Apply/receipt/audit，未补绑定。
- 缺 Agg、CLI 参数形状错误、隔离副本遗漏 raw 文件，均归类为评测环境/运行器问题，而非引擎问题。
- 更正默认刻度真值、literal unresolved 的召回计数、缺席轴标签不算合法请求等评分错误。
  样本未更换，绘图逻辑、引擎和 QA 均未因此修改。

本轮评测有效性修正不是新的产品适配。报告保留这些勘误，避免把评测器缺陷包装成产品结论。

## 6. 独立复核与复跑

父代理除读取分组回执外，实际执行了：

- 原始 barchart Discover：ylabel/legend 提示正确，set_title 角色提示错误，0 candidates。
- 协议 barchart Apply：退出 1，FAILED，NOT_WRITTEN。
- 共享轴 fig07：共享关系、视图、数据、Artist 所属 Figure、contract 节点身份一致。
- 三个 scatter Figure：与完整原文的 offsets/sizes 精确相等。
- 六个 annotation Figure：视图、曲线、文字/xy/文字位置、箭头路径和 patch 顶点一致；节点真实且属于返回 Figure。
- 8 个原始源码 SHA-256 与输入清单一致；冻结产品文件摘要前后一致。

分组可复跑入口（需按运行器参数选择输出目录，使用冻结引擎和 Agg）：

- A：`tools/g15/A/run_r0_baseline.py` → `run_correction.py` → `reassemble_results.py`。
- B：`tools/g15/B/run_B.py`；`FREEZE_SHA` 设为冻结 SHA，支持 `--output-dir`。
- C：`tools/g15/C/run_c.py` → `build_results.py`，支持 `--output-dir`。

A 的基线命令需传 `--raw-dir tools/g15/A/raw --out-root <archive/A> --manifest tools/g15/A/r0_manifest.json`；
管线命令需传 `--logs <archive/A/logs> --out tools/g15/A/correction_evidence.json`。
两个结果构建器默认读取仓库同级 `figpact-archive/g15-frozen/<组别>`；自定义输出目录时需相应保存输入证据。
本轮 A 初次归档的部分 stdout/stderr 仅保留末尾 6000 字符；退出码与结构化结果已保留，
不能声称这些旧日志是完整输出。复跑运行器已改为保留完整 stdout/stderr。

分组的逐步命令/源码真值/哈希见各 `tools/g15/{A,B,C}/results.json` 与运行器。
大日志、PNG、无效旧试验及隔离工作副本在 `D:/L/AI/figpact-archive/g15-frozen/`，
不将它们作为正式出版图发布。首次复跑应在相同宿主库版本下进行；改变宿主版本需另记环境，不能沿用此轮数值。

## 7. G14 纠正与验证时间线

冻结前已经修复 top-level 状态：工作草稿允许 COMMITTED + FAIL，
但子结果、plate 聚合结果、CLI 顶层均为 FAILED（对象审计阻断优先），receipt 保留 COMMITTED/FAIL，CLI 退出 1。
没有增加 Strict 发布 API，也没有把失败图发布成正式产物。

- G14 历史全量：对应 `590df03` 产品状态，非浏览器 554 passed / 7 skipped / 87 subtests，浏览器 22 passed。
- `d465a6e`：两组实际执行 12 passed 与 34 passed，测试有交集；未重跑全量/浏览器。
- `793aaa8` 冻结前：相关组合 23 passed / 1 warning；另有真实失败草稿 CLI smoke。
  本轮没有重新执行全量或浏览器测试，不将旧结果冒充最新 SHA 的验证结果。
- 原 G14 的“61 passed”已更正为 **61 collected**，不再把 collect-only 记成执行通过。

FTIR 的 4.702 pt 小字、统计图空间 FAIL、Demo 长标签空间限制继续保留。
`docs/UI/` 与 `docs/figpact-vnext-kit/` 未纳入本轮提交。

## 8. 下一步决策边界

先决定如何让陌生源码获得**真实、可验证的参数—Artist—属性授权关系**，而不是先做 GUI 或继续修 Demo。
本轮结果不足以支持现在就扩展成通用多对象控制模型；也不足以支持宣布现有引擎已实现任意科研图编辑。
G15 的价值是把缺入口、缺绑定、语法漏检、错误角色提示与安全拒绝明确分开，而不是追求示例通过率。
