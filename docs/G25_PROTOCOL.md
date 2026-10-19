# G25：Identity & Scope Generalization Gate

状态：仅协议；未启动实现、收集新题或模型评测。G24 按原报告收口；不追加修复复测来提高其成绩。

## 目标与非目标

只验证未见图上的唯一目标／scope 定位、既有授权绑定选择，以及歧义、no-op、缺少控制权和科学修改的正确处置。

保留 `edit_plan.py` 与 `plan_context.py` 两层，继续消费已有 Native／Overlay 控制契约与验证引擎。不新增统一执行引擎、Agent 抽象、自动重试、规划器、GUI、Artist 类型或写入权限。不允许相似参数名搜索替代身份确认、改 Python 兜底、降低保护或自动提交。

## 数据分割与冻结

1. G24 的 24 条题目及所有已见输出归入开发回归集，不再作为未见样本。保留原首次结果、修复复测与标注缺陷记录。
2. 后续由独立标注者制作未用于提示调试的新图／新语料；同一图的变体、同源 panel 及仅改措辞的样本不得跨开发／未见分割。记录图族、来源及污染检查。
3. 新语料优先覆盖：相同文本但不同 panel；一个对象有多个候选控制；Native／Overlay 都涉及；语义合法但最终 QA 不通过。另覆盖科学修改、无控制权、歧义及 no-op。
4. 冻结前用真实 inventory／contract 核对身份和权限，用既有引擎在隔离副本上预检可行性。预检不调用受测模型，不修改正式来源；留下配置／数据／引擎／环境指纹和原始回执。不能以源码出现了参数名代替当前配置下的真实授权。
5. 模型第一次运行前冻结样本、金标准、判分程序、提示／schema、模型配置、分割清单和停止阈值；分别记录 SHA256。模型不可访问金标准、预检答案、开发输出或其他题目的回复。
6. 评测后不改题、不补目标、不修金标准来提升分数。发现标注错误，保留原始主结果，单列更正记录、发现时间、理由和影响；修订版只能用于下一次独立评测，不能追认首次成功。
7. 冻结 `schema_representability`：`REPRESENTABLE`、`UNREPRESENTABLE` 或 `UNKNOWN`，并说明原因。当前 G24 schema 只允许一个 route、一个 scope 和同一路径下的编辑；`combine_contexts()` 也要求上下文属于同一 scope。因此跨 scope 目标集合、必须同时使用 Native 与 Overlay 的原子请求、或其他无法由一份当前 `PLAN_SCHEMA` 完整表达的任务，不能标为预期 READY。它们只能作为能力边界样本，预期处置为拒绝／澄清，或从 READY 分母排除；模型不能因无法生成不存在的 schema 表达而被记为绑定错误。
   同时冻结 `NO_OP` 与 `REJECT` 到当前接口的映射：`PLAN_SCHEMA` 没有独立状态。no-op 若由引擎按当前值拒绝，记录规范处置 `NO_OP`、要求模型输出 `REFUSE` 并说明无变化；一般拒绝记录为 `REJECT`，同样映射到 `REFUSE`。保留规范处置和接口状态两个字段，不混为同一产品枚举。

## Semantic Target Hints 实验变量

该实验仅验证上下文呈现是否降低目标／scope 歧义；不新增产品区域层或 `region.py`，不改变 `PLAN_SCHEMA`、控制权、身份、QA 或提交语义。重用只读 Scene、Artist 身份与 Native／Overlay 契约。
建议把两种机制区分；若纳入实验，先比较呈现效应，不增加接口字段：

| 臂 | 模型可见输入 |
|---|---|
| A：生产基线 | 当前实际生产 prompt packet 的完整 Scene／控制清单、固定 prompt/schema |
| B：呈现对照 | 与 A 完全相同的信息和控制项，只把其中已有的 scope、parent/panel ID、现有 role、axis、selector/binding 按对象邻近重组为只读提示 |

在冻结前对逐题 A/B payload 做字段与控制 ID 集合等价检查；只允许键名/布局/措辞变化，不增删事实、控制、顺序优先级或答案线索。若研究目标是**增加来源事实**（生产包确实没有的字段），那是另一个机制：必须单独标记该字段来源、生成规则和 UNKNOWN 情况，并设置独立实验臂；不能与 B 合并后声称是“呈现改善”。只有未见集和资源支持时才加入此臂，否则本轮限于 A/B 呈现对照。

### 来源约束与可行性

- Native Scene nodes 已含真实 `id/type/parent/scope`；控制记录含 exact YAML `path`、`objects`、scope、unit/range/axis。A 即已携带这些事实，B 只能重组，不得假称补全新信息。
- Native 一个逻辑 scope 可对应多个 Axes；不得按 Axes 次序推断 scope。注册 Axes ID 可来自 registry/GID，匿名 panel 的 `scope::panel.<index>` 是序号 fallback，不能把它包装成持久、可跨重排比较的语义身份。
- Overlay inventory 已含由真实 Axes 结构指纹构造的 `axes_key`、axis、role、selector/fingerprint；Axes index 是 display hint，不是 authority。当前 `discover_overlay()` 的节点投影只有 id/type/bounds，没有 parent/scope；G25 B 若要**新增**这些事实，应单列“信息增量”臂，且确认其 parent/scope 来源是显式事实而非从邻近 bbox 猜出。
- `anchored_to` 只可来自真实 contract relation、registry/group 显式关系或可核验 binding。当前 Scene geometry 的邻近/包含测量不等于标签锚定到曲线；无法证明时省略或 unknown。空间上下左右是当前渲染观察，不是稳定身份。
- Overlay 的 role 限于已有 `axis.title`、`axis.tick`、`curve.linewidth`。Native 的语义 role 取自契约 `expected.kind`/操作。易读标签不得扩大可编辑对象集合或创造新 role 权限。

### 冻结与判读

运行前记录每题 A/B 规范化 payload hash、可见控制 ID 集合、每项提示的来源字段与推导规则。纯重排臂必须通过事实等价检查；新增字段臂必须分别保留字段来源、schema 可表达性和 UNKNOWN 率。预注册目标定位、scope/axis、完整 READY 计划、错误 scope 计划率及拒绝/引擎可行性分层。若只改善 role/axis 词语匹配但未改善目标与完整计划，不能判为有用；引擎拒绝不抹掉定位正确，错误 scope 即使被引擎挡下仍是计划定位错误。

## 每题金标准

每题具备唯一 sample_id、图族／分割身份、来源指纹，以及以下字段。无目标或不适用项使用显式 null 并说明原因，不能填猜测值。

| 字段 | 冻结要求 |
|---|---|
| request | 原始自然语言，不在运行时改写 |
| expected_disposition | READY／CLARIFY／REJECT／NO_OP |
| expected_scope | 精确 scope；跨 scope 请求列出全部作用域，歧义记录候选集合而非任择其一 |
| expected_target | 稳定 Artist 身份或精确目标集合，含 panel／Axis／角色；相同文字不算同一对象 |
| expected_binding | 精确 Native YAML path 或 Overlay target_id；指定 route。若两条路径均合法，预先列出有限可接受绑定集合及选择依据 |
| expected_value | 每个编辑的数值与单位；相对编辑记录真实基值与解析后的绝对值 |
| engine_feasibility | ACCEPTABLE／DRAFT_ONLY／REJECTED／UNKNOWN；附预检回执、科学／视图／QA 状态和拒绝理由 |
| expected_reason | 结构化原因，如 SCIENCE_LOCK、NO_AUTHORITY、AMBIGUOUS_TARGET、SCOPE_MISMATCH、NO_CHANGE、QA_BLOCKED |

多编辑请求以整份目标／绑定／数值集合判分，不能只完成其中一项。no-op 必须由现值证明，不能作为模糊拒绝。UNKNOWN 不进入“预期可受理”分母；未知原因单独报告。

目标 scope 与绑定对象 scope 分开保存。清单的外层 scope 字符串不能证明内部 Artist 属于该 panel；不得在五条曲线中任选一条算作定位正确。

## 运行与权限

每题只取首次原始回复，不自动修 JSON、补保留字、选近似参数、重试或根据拒绝结果另生成候选。格式／协议错误也保留在整题首次分母中；另标为 CONTRACT_ERROR，不能转记为定位失败。

采用一致的独立进程／渲染环境隔离准备与试算；绑定真实来源、当前修订及正式 Overlay 路径身份。来源或上下文漂移时拒绝，记录为运行／身份失效，不重绑定旧回复。工具／网络失败保留缺失结果及失败原因，不从总样本数删除。

语言处置 `NO_OP`／`REJECT` 映射至当前 `REFUSE` 的规则见冻结条款；报告同时保留规范处置和接口状态。

`preserve` 必须明确包含字面值 `science`、`view`，但这只是承诺。实际科学／视图不变仍以既有引擎证据为准，缺失测量失败关闭。额外自然语言不变量也不能被当作已验证事实。

试算不保存、不出版。Native 候选受理不等于 DRAFT_SAVED／STRICT_VERIFIED；Overlay 局部 PASS、整图状态与 qa_delta 草稿资格独立保留。不得把可保存失败工作草稿报告为严格 PASS。

## 逐题证据与统计

每题记录原始输入包及哈希、原始首次回复、模型与提示版本、时间、解析结果、模型选定身份／绑定／值、引擎原始回执、实际影响集合、文件前后哈希、判分结论及失败类别。所有汇总分子必须能回溯到 sample_id。

| 指标 | 分子／分母定义 |
|---|---|
| 目标定位 | 完全匹配稳定目标集合及 scope 的题数／预先标注可判定目标的题数；与完整计划独立计分 |
| 参数绑定 | 完全匹配授权 route／绑定集合的题数／预先标注可判定绑定的题数；数值正确性另列 |
| 首次完整计划（全题） | 首次处置、目标、scope、绑定、数值、必要不变量和完整性全部正确的题数／全部冻结题数 |
| 首次 READY 完整计划 | 完全正确的 READY 计划数／预先标注且 schema 可表达的 READY 题数；另列不可表达和 UNKNOWN 数，不混入分母 |
| 引擎受理 | 实际受理数／实际提交引擎数，同时报告实际提交数／预期 READY 数和未提交原因；预检 ACCEPTABLE／DRAFT_ONLY／REJECTED 分层展示 |
| 安全处置 | 正确 REJECT／CLARIFY／NO_OP 数／相应冻结样本数，分类展示；不能仅“未执行”就算处置正确 |
| 错误 scope 计划 | 首次 READY 中计划声明的 scope／目标对象 scope 与金标准冲突的题数／全部冻结题数；无论后续是否被拒绝均计入 |
| 错误 scope 候选影响 | 实际候选相对基线影响了授权目标范围外 scope 的题数／全部实际候选试算数；用引擎影响对象／scope 回执判定，未试算单列 |
| 错误 scope 引擎拒绝 | 引擎拒绝的错误 scope READY 计划数／错误 scope READY 计划数；单列拒绝原因。拒绝可防止错误影响，但不能改写计划定位分数 |

READY 专项分母只包含冻结为 READY 且 `schema_representability=REPRESENTABLE` 的题；全部冻结题上的完整计划指标仍保留，不能用 READY 专项指标替代。

计划正确而引擎拒绝时，按照预检可行性区分预期拒绝与非预期引擎失败，不自动归为模型失败。预检 UNKNOWN 不得事后凭受理与否补成正确答案。无试算分母不能声称引擎越权率为零；小样本零观察不等于普遍安全。

## 停止与后续门禁

本协议不指定未经讨论的通过百分比，不启动运行。开始新评测前须冻结样本量、分层最低覆盖、完整计划正确率阈值、置信区间方法及相对冻结开发基线的比较规则。此前 G24 修复复测不能当作未见集基线来宣称统计提升。

门禁至少要求：未见集完整计划正确率达到预先冻结标准；没有错误 scope 的实际编辑；没有负例错误执行／受理；科学／视图证据和文件不变证据齐全；首次与任何后续修复复测分别报告。未达到时，只归因身份／scope／契约／绑定／可行性问题，不扩展 Agent 功能。

只有该门禁通过后，才另行讨论 Inspector 自然语言入口；通过协议定义本身不构成可靠性验收。
