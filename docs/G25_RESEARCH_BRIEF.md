# G25 Semantic Target Hints：调研与实验建议

状态：证据收集与设计建议；**未启动 G25 语料制作、盲测或产品实现**。G24 继续作为开发回归，不充当未见泛化集。

## 结论

建议把 G25 保持为只读 **Semantic Target Hints** 配对实验，不建设互斥的“区域树”或权限层。图表语义模型普遍区分对象、数据作用域、编码、布局关系和约束；图表还存在跨区域／叠加关系。它们支持把这些信息分别投影给模型，但只是建模依据，**没有找到直接实验能证明加这些提示就会提升 NL 编辑目标定位或首次计划准确率**。收益仍是 G25 待验证假设。

已有证据支持的设计约束：真实稳定对象身份优先；逻辑 scope、panel/parent、角色、axis 和空间关系各自独立；空间方位是当前渲染观察值，不是永久身份；关联／锚定只能在源数据、Scene 或契约明确时给出；不确定时必须保留 unknown／不提供。提示不增权限、不改现有验证器，也不代替 QA。

## 研究证据

| 来源 | 研究对象与直接证据 | 局限及对 G25 的解释 |
|---|---|---|
| Liu et al., [Manipulable Semantic Components](https://doi.org/10.1109/TVCG.2024.3456296), IEEE VIS/TVCG 2024；[全文](https://arxiv.org/html/2408.04798) | 计算场景模型将 marks、glyphs、collections、composites、数据 scope、encoding、algorithmic layout、relational constraints 和 view config 分开；包含 align/affix/z-order 等关系。复合图表可叠加或并置。 | 这是场景表示和应用案例，不是提示消融或 NL grounding 准确率试验。支持关系式／多维提示，不支持绩效因果主张。 |
| Chen et al., [Mystique: Deconstructing SVG Charts for Layout Reuse](https://doi.org/10.1109/TVCG.2023.3327354), VIS 2023/TVCG 2024；[论文](https://www.hdi.cs.umd.edu/papers/Mystique_VIS23.pdf) | 对矩形 SVG 图混合自动与人工分解 grouping、spatial relationships、encodings、graphical constraints；轴和图例单独识别并可纠错。论文报告 150 张图上的轴／图例提取和布局分解结果，并做 n=12 重用研究。 | 仅矩形 SVG 等有限范围；自动轴／图例识别并非无错，重用实验含向导和用户纠错。不能转用其准确率预测 G25；支持显式来源和可纠正性。 |
| Liu et al., [ChartKG](https://doi.org/10.1109/TVCG.2024.3476508), 2024；[公开预印本](https://arxiv.org/html/2410.09761v1) | 将视觉元素、元素属性值、数据变量／值和 visual insight 建成有向关系图；一个 visual element 可通过多个 property/encoding relation 连到不同变量，而非只归属一个区域。 | 目标是 bitmap 图挖掘、检索和 QA；仅四种标准图，识别使用 CNN/YOLO/OCR/启发规则，论文自述复杂图需扩展关系，解析错误向下游传播。其图像识别指标不是编辑目标定位指标，也无 ROI 结论。 |
| Ren et al., [Charticulator](https://doi.org/10.1109/TVCG.2018.2865158), InfoVis 2018/TVCG 2019；[论文](https://www.microsoft.com/en-us/research/wp-content/uploads/2018/08/Charticulator-InfoVis2018.pdf) | Glyph-level 与 chart-level 布局约束分离；plot segment、scaffold/axis、layout 和 scale/binding 为不同组件。相对定位通过 anchors/constraints 表示。 | 表达力／重建研究，不是 NL grounding 或语义提示消融。支持对象／约束拆分，不支持固定屏幕“区域树”。 |
| [Matplotlib Figure/Axes 官方说明](https://matplotlib.org/stable/users/explain/axes/arranging_axes.html)；[Artist model](https://matplotlib.org/stable/users/explain/artists/artist_intro.html) | Axes 是包含数据、x/y 轴、ticks、labels、title 等的绘图区；Figure 还可含多个 Axes、SubFigure、Figure-level text/legend；嵌套 grids 和跨行列 Axes 合法。 | 官方文档给出 API 语义，不评估自然语言理解。反例说明：几何外观或画布方位不能定义唯一、互斥归属。 |
| Wang et al., [Towards Natural Language-Based Visualization Authoring](https://doi.org/10.1109/TVCG.2022.3209357), TVCG 2022；[全文](https://arxiv.org/html/2208.10947v2) | 提出可执行 `editing action={operation, objects, parameters}`；讨论 object selectors/naming、缺省目标、vague/relative 参数，并建议维护上下文、必要时澄清。含 formative n=6、工具原型和小规模 exploratory study。 | 不是现代 LLM 提示消融；小样本，且对象／参数仍需应用解析。不证明 G25 hints 有提升。 |
| Srinivasan et al., [NL utterance corpus](https://doi.org/10.1145/3411764.3445400), CHI 2021；[论文](https://arxiv.org/html/2110.00680v1) | N=102、893 utterances，发现 explicit、semantic、value-based、implicit references 与多种措辞；NL4DV 在其 755 单句 specification 题上 exact 64%、partial 75%。 | 测的是新图规格而非现有图编辑／panel grounding；不能把分数当 G25 基线。其价值是预先覆盖同义、值描述和隐含引用。 |
| Vaithilingam et al., [DynaVis](https://doi.org/10.1145/3613904.3642639), CHI 2024；[全文](https://arxiv.org/html/2401.10880) | 编辑已有 Vega-Lite 图的 n=24 within-subject 研究；NL + 动态 widgets 对比 NL + 静态 widgets，报告用户偏好、重复调整和反馈体验差异。作者记录自然语言目标／属性误解与 widget 错误。 | 对照改变了交互能力和反馈，不是单独 scope/role hint 消融；不能归因于语义提示。支持显式呈现可调整对象、值和立即反馈是不同研究因素。 |
| Park et al., [DirectVis](https://doi.org/10.1109/pacificvis68791.2026.00014), PacificVis 2026；[论文](https://hcil.snu.ac.kr/cms/uploads/Direct_Vis_71bac5663c.pdf) | n=12 code-literate participants；直接选中 SVG 元素并与共享 chart state/code 对应，相比 NL-only 条件完成部分 refinement 任务时交互次数较少；访谈报告 current-state + target/action + constraints 的提示习惯。 | 样本窄、只评 bar/line、系统同时增加直接操作和预览；不是 semantic-hints 单因素实验。支持作为 G25 题型／假设来源，不能外推改善幅度。 |
| Gao et al., [DataTone](https://doi.org/10.1145/2807442.2807478), UIST 2015；[论文](https://www.zcliu.cs.umd.edu/datatone/DataTone-UIST15.pdf) | 将歧义保留为 ambiguity space，通过即时 ambiguity widgets 让人纠正解析；n=16 比较中多数参与者偏好该交互。 | 自然语言查询／新图生成，不是受约束编辑；结果支持必要时询问人，不支持自动猜区域。 |

**直接证据结论：**现有文献支持“场景由对象、绑定和关系组成”及“自然语言引用会省略、模糊或使用属性描述”；没有文献直接比较 figpact 这种相同控制清单上增加 panel/role/axis 投影前后的编辑定位效果。检索中未找到 Semantic Target Hints 同型的因果试验。

## 仓库可行性审计

依据 `figpact/scene.py`、`plan_context.py`、`style_identity.py` 和 G25 当前协议：

- Native `discover_native()` 的只读节点已经包含 `id/type/parent/scope/bounds_mm`；Native 控制含 `path/role/objects/scope/axis/current/range`。Scene 通常把 Axes 节点作为 panel；但已注册 Axes 的稳定 ID 依赖 registry/GID；匿名 Axes 会用 `scope::panel.<index>`，索引仅用于内部显示/投影，不足以作为“上方面板”语义身份。`scene.snapshot()` 文档明确一个逻辑 scope 可以含多个 Axes，scope 数不能按 Axes 数推断。
- Scene 里的已注册 Artists 尽可能由真实 Axes parent 连接；缺省父对象可再按 group 归属，无法归属时回退 canvas。group 父关系来自作者契约；不是普遍保证的完整语义层级。`scope` 通过作者元数据、registry scope 或有限 GID 约定归属；未标注或未知不能推断。
- Overlay inventory 已有真实 role、stable `axes_key`、axis x/y、selector/fingerprint、current。其 Axes key 来自唯一 Axes GID + 结构指纹，或结构指纹；轴序号只作为 display hint，不是身份权威。可直接证实 axis/panel association，但不能把浮点 bbox 位置引入 ID。
- `discover_overlay()` 当前从 Scene 节点投影的字段只有 `id/type/bounds_mm`，**没有保留 parent/scope**。这说明同一项对照中 A 臂本来已含 Native parent/scope，B 臂若额外只给 Overlay parent/scope，会是来源／完整度差异而非对所有模型输入统一加的呈现实验。应先用每题原始包盘点字段来源；优先把两臂共同 baseline 定义为当前真实生产包，不要在报告中把现有字段误说成全路径都已提供。
- Overlay `axis.title` 与 `axis.tick` 的身份从真实 Axis、Axis、可见主刻度和精确 tick 位置/side 构造。`curve.linewidth` 的 Axis identity 和数据指纹是真实事实；“某条标注锚定到某曲线”目前没有通用推断器。只有已有 contract relation、registry group/parent 或明确数据 binding 才能给 `anchored_to`；几何邻近不能构成锚定证据。
- `scene` 可以实测毫米 bbox、polylines、anchors、relations、containment，但很多事实是 renderer 当前几何，不是稳定语义。QA 用规则/scope/object IDs 的全图检查，不读取所谓区域白名单。Hint feature 应是提示序列化，不改变验证调用或数据。

**A/B 实验的处理定义需要再冻结：**当前 baseline 本身已有结构化信息，故“增加 hints”可有两个不同处理：①纯重排/自然语言解释同一字段（呈现效应）；②新增加基线没有的、但可从现有权威 source 派生字段（信息效应）。两者不能混成一个 B 臂。若目的是判断语义投影作为产品层的增益，建议拆成 A=当前生产 prompt payload，B1=相同事实的角色化、按目标邻近呈现，B2=只多提供一个经验证的来源字段。样本数允许才做三臂；否则冻结一个机制清楚的 B。不得拿同数据的 B 优势归因于“新增信息”或“更易读呈现”的另一机制。

## 设计建议与未验证项

1. 不新增互斥区域层；采用多维关系视图：真实对象 ID、logical scope、Axis/panel ID、role、encoding/binding、可靠 parent/anchor，各自独立、可 unknown。
2. 把 target grounding 与 action feasibility 分开测：先按原始首次回复计 exact target/scope/role/axis，再给现有引擎试算；引擎拒绝不抹掉定位正确，且不把错误计划被拒绝记为定位正确。
3. 若研究“用户／Agent 能否消歧”，保持题目包含 role、panel、scope 冲突、相同标签不同 Axes、多候选 curve、cross-scope 和外置 annotation。题目金标准必须来自真实 selector/contract，而非视觉猜测。
4. 将 semantic hint 类型作为可分层／消融变量：`scope+panel`、`role+axis`、`anchored_to/spatial`。第三类没有统一可靠真值时只能用有显式 relation/binding 的小子集，不能用 bbox 最近邻自动伪造 gold。
5. 报告配对 exact-match 差、置信区间、错误类别和是否 engine-refused；若不显著／效应不确定，不把字段长期加入上下文。
6. G25 当前报告要求“空间方位仅作 non-authoritative提示”，但建议增补预注册“B臂构成”和机制隔离，否则实验结果可能不可解释（事实新增 vs 改写格式 vs 控件顺序）。这属于评测协议补充，尚未实施。

## 研究限制

来源涵盖 chart authoring、规格生成、图像去构造与 visualization QA。证据强度不同：建模论文只证明表达形式存在；小型用户研究支持交互/澄清需求；没有直接测量 G25 hints 的因果效果。ChartKG 是 bitmap 解析，Mystique 是 rectangle SVG，DirectVis 是 D3 bar/line，均不能替代 figpact Matplotlib 的真实提示验证。所有数字应限定在各自原研究语料、任务和样本中。
