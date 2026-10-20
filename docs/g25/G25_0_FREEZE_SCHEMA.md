# G25-0 Freeze Schema（DRAFT，未冻结）

状态：**DRAFT 草案**。独立复核通过并签署冻结记录之前，不构成冻结，不主张任何 freeze / SHA / 基线结论。本文件只定 schema（文件、字段、枚举、不变量、校验规则），不等同于冻结包本身。本轮不做模型调用、不做产品实现。

依据（真实来源，不猜测）：

- 协议：`docs/G25_PROTOCOL.md`（§数据分割与冻结、§每题金标准、§Semantic Target Hints 实验变量、§冻结与判读）
- 调研：`docs/G25_RESEARCH_BRIEF.md`（§仓库可行性审计、§设计建议）
- 当前接口唯一事实来源：`figpact/edit_plan.py:35-51`（`PLAN_SCHEMA`）、`:61-104`（`check_plan`）、`:107-121`（`combine_contexts`）
- 上下文事实来源：`figpact/plan_context.py:89-175`（`discover_native`：controls 含 `path/role/objects/scope/axis/current`，nodes 含 `id/type/parent/scope/bounds_mm`）、`:188-253`（`discover_overlay`：controls 含 `role/property/selector/display`，nodes 投影只有 `id/type/bounds_mm`，见 `:244-247`）
- 角色权威：`figpact/roles.py:35-`（`ROLE_REGISTRY`）、`figpact/style_identity.py:62-68`（`ALLOWED_TARGETS` 闭集）、`:411-412`（`axes_index`/`axes_key` hint）
- 既有冻结先例（只借格式，不借分数）：`tools/g24/blind_cases.json`（`format: g24-blind-v1` + `frozen_sha256`）、`tools/g24/score.py:39-41`（canonical sha）、`tools/g24/case_validity.json`（金标准缺陷单列、不改题）

## 1. 冻结包文件清单（冻结时才产生，本文件只定形状）

冻结包根（建议 `docs/g25/freeze/`，冻结前不得创建占位断言）必须包含以下文件，缺一即未冻结：

| 文件 | 内容 |
|---|---|
| `contamination_manifest.json` | G24 开发回归集清单 + 未见候选与开发集的污染检查结论 |
| `family_registry.json` | 图族注册表：同图变体、同源 panel、仅改措辞样本的家族归属 |
| `cases_gold.json` | §2 每题金标准数组 |
| `preflight_evidence.json` | §3 每题预检证据（真实 inventory/contract + 隔离引擎回执） |
| `ab_packets/<sample_id>/A.json`、`B1.json`（`B2.json` 仅当预注册信息增量臂存在） | §4 每题每臂模型可见 payload 原文 |
| `ab_equivalence.json` | §4 A/B 等价检查结论 |
| `prompt_schema_frozen.json` | 冻结的 system prompt + `PLAN_SCHEMA` 快照（必须与 `figpact/edit_plan.py` 当时版本逐字节一致，记录 commit/文件 sha） |
| `scorer_frozen/` | 判分程序快照（含 canonical hash 函数） |
| `model_config.placeholder.json` | §6 模型配置占位（冻结时只填已知的调用约束，未知留 `TBD`，不得虚构版本号） |
| `freeze_record.json` | §5 每个文件的 SHA256 + 冻结声明 + 停止阈值/分层覆盖/置信区间方法 |
| `review_signoffs.json` | §7 独立复核签名 |

## 2. Case gold 字段

`cases_gold.json` 形状：`{"format": "g25-gold-v1", "cases": [<case>, ...]}`。每题：

| 字段 | 类型 | 冻结要求 |
|---|---|---|
| `sample_id` | string，非空 | 全局唯一（见不变量 D1） |
| `family_id` | string | 必须在 `family_registry.json` 中存在 |
| `source_fingerprint` | object | `{script_sha256, config_sha256, contract_source, base_config_revision, source_revision, overlay_sha?}`；缺失即无来源证据（见不变量 D4） |
| `request` | string，非空 | 原始自然语言，运行时不得改写 |
| `expected_disposition` | enum §2.1 | 规范处置 |
| `interface_status` | enum §2.1 | 当前接口映射（`NO_OP→REFUSE`，`REJECT→REFUSE`，见不变量 D2） |
| `expected_scope_set` | string[]，≥1 | 精确 scope 集合；跨 scope 列出全部；歧义记录候选集合，不得任择其一 |
| `target_scope_set` | string[]，≥1 | 目标对象自身 scope，与绑定对象 scope 分开保存；外层清单 scope 字符串不得证明内部 Artist 归属 |
| `expected_target` | object[] / null | 稳定 Artist 身份或精确目标集合，含 panel/Axes/role；相同文字不算同一对象；无目标或不适用用显式 `null` + `null_reason`，不得填猜测值 |
| `expected_binding` | object / null | `{route, kind: "native-path" \| "overlay-target", path?: string[], target_id?: string, acceptable_set?: [...], selection_basis?: string}`；两条路径均合法时预列有限可接受集合及选择依据 |
| `binding_scope` | string / null | 绑定对象自身 scope（与 `target_scope_set` 分开字段） |
| `expected_value` | object[] / null | 每编辑 `{value, unit, base_value?, absolute_value?}`；相对编辑必须记录真实基值与解析后绝对值 |
| `engine_feasibility` | enum §2.1 | 预检结论；`UNKNOWN` 不进“预期可受理”分母 |
| `feasibility_detail` | object | `{receipt_ref, science, view, qa, refuse_reason?}`，`receipt_ref` 指向 `preflight_evidence.json` 条目 |
| `schema_representability` | enum §2.1 | `REPRESENTABLE / UNREPRESENTABLE / UNKNOWN` + `representability_reason`（见不变量 D1） |
| `expected_reason` | enum[] + string | §2.1 结构化原因数组（≥1）+ `reason_detail` 自由文本 |
| `splits` | object | `{split: "unseen", developer_regression: false, family_exclusive: true}` |
| `null_reason` | string? | 凡 `expected_target/binding/value` 为 `null` 时必填 |

### 2.1 枚举（exact）

```text
expected_disposition: READY | CLARIFY | REJECT | NO_OP
interface_status:     READY | CLARIFY | REFUSE        # 当前 PLAN_SCHEMA 唯一合法集合（edit_plan.py:38）
schema_representability: REPRESENTABLE | UNREPRESENTABLE | UNKNOWN
engine_feasibility:   ACCEPTABLE | DRAFT_ONLY | REJECTED | UNKNOWN
route:                native | overlay                # edit_plan.py:39
binding_kind:         native-path | overlay-target
expected_reason[] items: SCIENCE_LOCK | NO_AUTHORITY | AMBIGUOUS_TARGET
                     | SCOPE_MISMATCH | NO_CHANGE | QA_BLOCKED
axis:                 x | y | null
overlay_role:         axis.title | axis.tick | curve.linewidth   # 闭集（style_identity.py:62-64）
                      # axes.title 为保留只读角色，永不作为 expected binding role
```

Native 语义 role 不另立枚举：必须逐字等于对应 contract 记录的 `expected.kind` 或 `operation`（`plan_context.py:123-142`），校验时按 `source_fingerprint` 所指 contract 逐题核对。易读标签不得扩大可编辑集合或创造新 role 权限。

### 2.2 分层规划数（允许与冻结实际数不同）

规划目标（仅为组卷指导，不是冻结断言）：`READY 48 / CLARIFY 16 / REJECT 16 / NO_OP 16`，合计 96。`cases_gold.json` 另设 `stratification: {planned: {READY:48, CLARIFY:16, REJECT:16, NO_OP:16}, frozen: {READY:n1, ...}}`。冻结签名之前 `frozen` 允许与 `planned` 不一致；签名之后 `frozen` 即实际题数，不可更改。任何“通过率/分母”指标的分母以 `frozen` + §2.3 的 READY-专项规则为准，不得用 `planned` 回填。

### 2.3 READY 专项分母规则（schema 级）

- 首次 READY 完整计划分母 = `frozen.expected_disposition==READY AND schema_representability==REPRESENTABLE` 的题数；另列不可表达数与 UNKNOWN 数，不混入分母。
- 全题首次完整计划指标仍保留（分母 = 全部冻结题数），不得用 READY 专项替代。

## 3. 预检证据字段

`preflight_evidence.json` 按题：`{sample_id, probed_at, config_fp, data_fp, engine_fp, env_fp, inventory_snapshot_ref, contract_snapshot_ref, isolated_copy: true, model_called: false, receipt_raw: {...}, feasibility, refuse_reason?}`。硬性规则：预检不调用受测模型、不修改正式来源；`model_called` 必须为 `false`；不得以“源码出现过参数名”代替当前配置下的真实授权；`receipt_raw` 保留引擎原始回执（含科学/视图/QA 状态）。

## 4. A/B packet 与等价检查

- A = 当前真实生产 prompt packet（完整 Scene/控制清单、固定 prompt/schema）；B1 = 与 A 完全相同的信息与控制项，只把其中已有的 scope、parent/panel ID、现有 role、axis、selector/binding 按对象邻近重组为只读提示（键名/布局/措辞可变）。
- 若研究目标是增加生产包没有的字段，必须单独立项为 B2（信息增量臂），不得与 B1 合并后声称“呈现改善”。
- 每题每臂记录：规范化 payload hash、可见控制 ID 集合、每条提示的 `{text, source_field, derivation_rule, provenance}`（provenance 见 §8）。
- `ab_equivalence.json` 按题记录 `{sample_id, arm_pair: "A-vs-B1", control_ids_equal: bool, fact_set_equal: bool, only_presentational_diff: bool, pass: bool}`。纯重排臂 `pass` 要求三者全真：控制 ID 集合相等、事实集合相等、仅呈现差异；不增删事实、控制、顺序优先级或答案线索。B2 不做等价断言，改为记录 `{added_fields: [{field, source, derivation, unknown_rate}]}`。

## 5. Hash / 冻结记录

- Canonical JSON：`sort_keys=True, ensure_ascii=False, allow_nan=False` 后 UTF-8 的 SHA256（沿用 `tools/g24/score.py:39-41` 口径）。
- `freeze_record.json`：`{frozen_at, files: {<path>: sha256}, samples_sha, gold_sha, scorer_sha, prompt_schema_sha, model_config_sha, split_list_sha, stop_thresholds: {min_n_per_stratum, pass_criteria, ci_method, baseline_compare_rule}, schema_representability_map_sha, no_op_mapping_sha, note: "门禁阈值在本协议之外另行冻结，本文件不定通过百分比"}`。
- 评测后不改题、不补目标、不修金标准；标注错误按 `tools/g24/case_validity.json` 模式单列更正记录（发现时间/理由/影响），修订版只用于下一次独立评测。

## 6. 模型配置占位

`model_config.placeholder.json`：`{model_id: "TBD", model_version: "TBD", prompt_version_ref, schema_version_ref, decoding: {temperature: "TBD", seed: "TBD"}, first_response_only: true, no_auto_repair: true, gold_inaccessible: true}`。冻结前全部可为 `TBD`；任何实际模型调用之前必须先填实并重新哈希，未填实不得运行。

## 7. 复核签名

`review_signoffs.json`：`[{role, reviewer, checked_at, verdict}]`，`role` 至少覆盖 `independent-annotator`（未参与提示调试）、`contamination-audit`、`representability-audit`、`ab-equivalence-audit`。任一 `verdict != "pass"` 即未冻结。本文件保持 DRAFT，直到全部为 `pass`。

## 8. Provenance tagging（source IDs / panel / role / axis / anchored_to / spatial）

每个 gold 或 B1 提示中出现的身份类断言，必须附 `provenance: {source, derivation, authoritative: bool, persistent: bool}`，`source` 枚举 exact：

```text
NATIVE_SCENE_NODE | NATIVE_CONTRACT | REGISTRY_GID | OVERLAY_INVENTORY
| OVERLAY_FRAME | CONTRACT_RELATION | REGISTRY_GROUP | VERIFIED_BINDING
| RENDER_OBSERVATION | ORDINAL_FALLBACK | UNKNOWN
```

规则：

1. `source_id`：Native 取 `NATIVE_SCENE_NODE`（`plan_context.py:148-150` 的 `id/type/parent/scope`）；Overlay 取 `OVERLAY_INVENTORY` 的真实 `id + axes_key + selector/fingerprint`。浮点 bbox 不得引入 ID。
2. `panel_id`：已注册 Axes 用 `REGISTRY_GID`（`persistent: true`）；匿名 `scope::panel.<index>` 必须标 `ORDINAL_FALLBACK` 且 `persistent: false`，不得包装成可跨重排比较的语义身份；不得按 Axes 次序推断 scope（一个逻辑 scope 可含多个 Axes）。
3. `role`：Overlay 限 §2.1 闭集，`source: OVERLAY_INVENTORY`；Native 逐字抄 contract，`source: NATIVE_CONTRACT`。`derivation` 写明测量/构造方式；无法证明时 `source: UNKNOWN` 并省略该提示。
4. `axis`：`x/y` 必须来自真实 Axes 结构（inventory 的 `axis` 字段）；序号 `axes_index` 只许 `RENDER_OBSERVATION` + `authoritative: false`（display hint，不是权威）。
5. `anchored_to`：只许 `CONTRACT_RELATION | REGISTRY_GROUP | VERIFIED_BINDING` 三者之一；Scene 几何邻近/包含测量不等于锚定；无法证明时省略或 `UNKNOWN`。当前 `discover_overlay()` 节点投影无 `parent/scope`（`plan_context.py:244-247`），B1 若出现 Overlay parent/scope 即视为新增事实，转 B2 处理。
6. 空间 hint（上下左右/邻近）：一律 `source: RENDER_OBSERVATION` + `authoritative: false` + `persistent: false`，仅作 non-authoritative 提示；不得进入 binding 选择依据。

## 9. 不变量与校验（schema 必须捕获的六类错误）

- **D1 重复/不可表达**：`sample_id` 全局唯一；同一 packet 内控制 ID 唯一。`expected_disposition==READY` 要求 `schema_representability==REPRESENTABLE` 且单 route 单 scope、全部 edits 同 route 同 scope（`check_plan:100-101` + `combine_contexts:109-111` 的 gold 侧镜像）。跨 scope 目标集合、必须同时用 Native+Overlay 的原子请求、或其他无法由一份当前 `PLAN_SCHEMA` 完整表达的任务：`representability` 必须为 `UNREPRESENTABLE`，`expected_disposition` 只能是 `CLARIFY/REJECT`（能力边界样本）或从 READY 分母排除；绝不允许 `READY + REPRESENTABLE + 跨 scope/跨 route` 通过。
- **D2 no-op 映射**：`expected_disposition==NO_OP` 必须 `interface_status==REFUSE`、`expected_reason` 含 `NO_CHANGE`、`expected_binding/expect_value` 为 `null`、`edits` 为空，并有现值证据（`feasibility_detail` 引用预检“按当前值拒绝”回执）。`REJECT` 同样 `interface_status==REFUSE` 但原因不得为 `NO_CHANGE`。校验器区分规范处置与接口状态两个字段，不得合并为同一枚举。
- **NO_OP 表达性约束**：`expected_disposition==NO_OP` 必须 `schema_representability==REPRESENTABLE`；它表示当前单 route、单 scope 请求经现值证据确认无需改动，不表示无法表达的跨 route/跨 scope 请求。不可表达请求只能 CLARIFY/REJECT。
- **D3 重复绑定/A-B 事实不等**：READY + REPRESENTABLE 的 `expected_binding` 每个 ID 必须属于冻结时该题可见控制 ID 集合成员；`acceptable_set` 有限且 `selection_basis` 非空。A-vs-B1 `ab_equivalence.pass` 为 false 的题不得进入“呈现效应”结论分母。
- **D4 缺来源证据**：任一 `expected_target/binding/value` 非 null 但对应 `source_fingerprint` 缺失、或 §8 provenance 缺失/`UNKNOWN` 却仍给出确定断言、或 `anchored_to` 来自几何邻近、或空间 hint 被标 authoritative，即失败。
- **D5 未知可行性**：`engine_feasibility==UNKNOWN` 的题不进“预期可受理”分母；`feasibility_detail.receipt_ref` 必须存在（未知探针的回执本身也是证据）；事后凭受理与否回填可行性即失败。
- **D6 冻结完整性**：`freeze_record.json` 缺任一文件 sha、或任一 sha 与实测 canonical sha 不等、或 `review_signoffs.json` 任一非 pass、或模型配置仍含 `TBD` 却已运行，即未冻结。

最小校验器（伪代码，冻结工具实现时照此落实，JSON Schema 只做枚举/必填，跨字段不变量走本过程）：

```text
for case in gold:
  assert unique(sample_id); assert disposition/interface mapping (D2)
  if disposition == READY:
    assert representability == REPRESENTABLE
    assert len(scope_set) == 1 and len(routes_in_bindings) == 1  # 否则 D1 失败
    assert bindings ⊆ visible_control_ids and values finite  # D3
  if representability == UNREPRESENTABLE:
    assert disposition in {CLARIFY, REJECT}  # D1
  if disposition == NO_OP:
    assert representability == REPRESENTABLE  # D1/D2
    assert binding is null and value is null and NO_CHANGE in reasons  # D2
  assert provenance_complete(case)  # D4
  assert not (feasibility == UNKNOWN and in_admissible_denominator)  # D5
assert ab_equivalence[A-vs-B1].pass for all presentation-effect claims  # D3
assert freeze_record hashes match and all signoffs pass  # D6
```

## 10. 非目标（本 schema 不做什么）

不定通过百分比、不定基线比较统计结论、不新增执行引擎/Agent/重试/GUI/Artist 类型/写入权限、不改 `PLAN_SCHEMA`（单 route 单 scope 同路径 edits 的限制即当前能力边界，见协议 §7）。`preserve` 仍须含字面值 `science`、`view`（`edit_plan.py:45-47`），但实际科学/视图不变以引擎证据为准，不由自然语言承诺证明。

## 11. JSON Schema 说明（有意不附）

有意只留本 Markdown + §9 伪代码，不另建 `schemas/g25_cases.schema.json`：枚举/必填可用 JSON Schema 表达，但 D1–D6 全部是跨字段/跨文件不变量（集合包含、A/B 事实等价、哈希一致、签名门），JSON Schema 写不出可读可审的版本。冻结工具落地时按 §9 实现一个小校验脚本即可；需要机器 schema 时再从本文件生成。

→ skipped: 独立 `schemas/g25_cases.schema.json`，add when 冻结工具需要机器校验且本文件 §9 已不够用。
