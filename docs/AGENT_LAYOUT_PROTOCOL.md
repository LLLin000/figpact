# G7 P1-b：Agent 排版上下文协议（只读）

选区 → Agent 排版这一段的**服务端只读上下文**：Agent 选中一个图元后，能一次拿到足够的
事实去起草多目标改动，而不是靠猜参数。协议本体只有一条：**三部分都必须来自既有真值，
本通道不审批、不写盘、不解释自然语言。**

## 一、这一轮交付了什么

- **新增只读通道**：`figpact/hub.py` 的 `SessionHub.read_agent_context(session, body=None)`
  → `(payload, http_status)`。输入是当前选中的 GID（可选：候选 `delta_mm`、自然语言
  `intent` 文本），输出固定三段：`scene` / `constraints` / `impact`。
- **新增测试**：`tests/test_agent_context_surface.py`（真实临时脚本 + 真实 `IntentSession`，
  不 mock 被测事实），覆盖未知 GID、不可 ghost 对象、跨 scope 选择，以及三部分与既有
  Scene / oracle 事实的一致（一致与否用真实 `evaluate` 回执交叉核对）。
- 修改文件仅 `figpact/hub.py`；未改 `inspector_server.py`、`tools/inspector/*`、
  `tests/browser/*`、`examples/*`。

**本切片落地的是 Hub 方法本身。** 把它接到 HTTP 需要一个既有路由（形如
`GET /api/agent/context?gid=…`）——那属于 `figpact/inspector_server.py`，本轮**没有**改，
所以"已经有一个可用的 HTTP 端点"这句话现在是**假的**，不要这么写。

## 二、三部分的真值来源

| 部分 | 内容 | 唯一真值来源 |
| --- | --- | --- |
| `scene` | 目标图元 scope 内的图元清单（gid / 类型 / 文本 / `bounds_mm` / 可 ghost 性）+ 当前选中那条 | `session.snapshot()['scene_json']`（既有 Scene 构建 + Inspector 投影） |
| `constraints` | 允许/禁止 GID 集合、坐标空间与硬限、冻结科学指纹、不可独立微调项 | Hub 的 selection 通道 + `FigureSession.parameters()`（契约声明）+ `IntentSession._science` |
| `impact` | 候选改动会牵动谁、为什么（附着/连带/跨 scope）；无候选时给规则性说明 | Inspector 投影的 `linked_guide_gid`/`annotation`、`FigureSession.owned_closure()`、节点的 `controlled_by` 精确路径 |

三部分在回执里各自带 `source` 字段，写的就是上表右边那一列——读的人不必猜谁说了算。

**本通道不做的事**：不调 `evaluate`（那会铸造候选并改会话状态）、不写盘、不改选区、
不另算几何/科学、不在服务端重推前端判据。**回执里没有"已批准/已验证/已保存"。**

## 三、回执形状（真实片段）

`read_agent_context(session, {'delta_mm': [0.0, 0.15], 'intent': '把 A 上移 0.15mm'})`
在一个真实夹具上的输出（节选；`scene.nodes` 每项都带 `bounds_mm`/`measured`/
`fully_clipped`/`controlled_by`/`hit_mode`）：

```json
{"status": "OK", "schema": "figpact.hub.agent_context/1",
 "hub_revision": 1, "selection_seq": 1, "frame_revision": "…", "scene_sha256": "…",
 "stale": false, "stale_reason": null, "scope": "main", "target_gid": "agent.main.A",
 "intent_text": "把 A 上移 0.15mm",
 "scene": {"scope": "main", "scope_source": "target_node", "unit": "mm",
   "coordinate_reference": "canvas_bottom_left", "canvas_bounds_mm": [0, 0, 60, 40],
   "measurement": {"calibrated": false, "…": "…"},
   "ghost_rule": "tools/inspector/inspector.js:canGhostNode（预览资格，不构成可写结论）",
   "selected": "agent.main.A",
   "nodes": [
     {"gid": "agent.main.A", "type": "text", "text": "A", "bounds_mm": [20.45, …],
      "measured": true, "fully_clipped": false, "ghostable": true, "selected": true,
      "controlled_by": [["offsets_mm", "A"]], "linked_guide_gid": "agent.main.guide"},
     {"gid": "agent.main.D", "fully_clipped": true, "ghostable": false,
      "ghost_blockers": ["被完全裁掉：没有可见轮廓"], "hit_note": "完全裁掉：没有可见几何"},
     {"gid": "agent.main.guide", "type": "curve", "ghostable": false,
      "ghost_blockers": ["curve：不做刚体轮廓预览", "带清单附着关系的引线：不做独立预览"],
      "annotation": {"independent_endpoint_editable": false, "…": "…"}}],
   "nodes_outside_scope": {},
   "diagnostics": []},
 "constraints": {
   "scope": "main", "allow_gids": ["agent.main.A", "agent.main.guide"],
   "deny_gids": ["agent.main.B", "agent.main.C", "agent.main.D", "agent.main.curve"],
   "follow_gids": ["agent.main.guide"], "fixed_gids": [],
   "coordinate_space": {"unit": "mm", "reference": "canvas_bottom_left",
     "canvas_bounds_mm": [0, 0, 60, 40], "calibrated": false},
   "hard_limits": {"declared_bindings": [
       {"path": ["offsets_mm", "A"], "unit": "mm", "operation": "rebuild", "scale": 1.0,
        "mutability": "EDITABLE", "min": -10.0, "max": 10.0, "scopes": ["main"],
        "objects": ["agent.main.A", "agent.main.guide"], "objects_within_allow": true}],
     "delta_requested_mm": [0.0, 0.15]},
   "frozen_science": {"manifest_declared": true, "digest": "6d5fe921…",
     "policy_by_gid": {"agent.main.curve": "LOCKED_SCIENCE", "agent.main.A": "LAYOUT"}},
   "not_independently_tunable": [
     {"gid": "agent.main.curve", "why": "科学曲线不是刚体：不被受理为整体平移…"},
     {"gid": "agent.main.guide", "why": "引线端点不可独立微调（清单声明）：只随标签整体平移"}]},
 "impact": {
   "candidate": {"gid": "agent.main.A", "delta_mm": [0.0, 0.15], "intent_text": "把 A 上移 0.15mm"},
   "attached": [{"gid": "agent.main.guide", "relation": "guide",
     "why": "清单声明的标签↔引线附着：标签端随动、科学端固定"}],
   "ownership_closure": ["agent.main.A", "agent.main.B"],
   "co_bound": [{"gid": "agent.main.guide", "path": [["offsets_mm", "A"]],
     "why": "与选中对象同一条声明绑定：该绑定被重建时它们一起动"}],
   "cross_scope": [],
   "rules": ["本通道只描述、不审批：改动仍走既有通道（submit_task → evaluate，或计划 → apply → 验证）。", "…"]}}
```

### `scene`

- `nodes` 只列**目标图元所属 scope** 内、带 gid 的图元；其它 scope 只给 `nodes_outside_scope`
  的计数（跨 scope 选择时你一眼能看出还有一个 `detail` 版）。
- `scope` 取自**目标图元本身**（`scope_source: target_node`），不是页面的 `mode`。
- `ghostable` 是**预览**资格：规则本体唯一实现在
  `tools/inspector/inspector.js:canGhostNode`（P1-a 的拖动预览），服务端只把同一组既有
  Scene 字段翻成可读结论，`ghost_blockers` 逐条给阻止原因。**它不是"引擎会受理"的结论**：
  引擎受理与否只看 `evaluate` 回执。

### `constraints`

- `allow_gids` = `{选中 GID} ∪ {清单显式关联的引线}`；`deny_gids` 是同一 scope 内其余
  **非结构**图元。引擎对集合外非结构图元的任何几何变化判 `IMPACT_MISMATCH`。
- `follow_gids` 必须**恰好**等于清单关联的那一条，`fixed_gids` 必须为空——扩大影响许可的
  候选会被引擎直接拒绝。
- `hard_limits.declared_bindings` 是契约声明的参数（`min`/`max`/`unit`/`scale`/
  `operation`/`scopes`/`objects`）。例：NMR 的峰值标注位移声明为 ±10 mm，越界由引擎在受理
  期拒绝（`OUT_OF_RANGE`）——**本通道只回声明**：不代算位移、不扩限、不另立第二套算式。
- `objects_within_allow=false` 表示这条绑定的对象集合整体落不进本次许可集合，它**不服务**
  于本次选择（引擎铸造候选的前置条件）。
- `frozen_science.digest` 是引擎 `evaluate` 科学冻结用的同一份载荷捕获；读不到（普通
  Figure 会话 / 历史只读会话）时给 `SCIENCE_CAPTURE_UNAVAILABLE`，**不伪造指纹**。
- `scope_mismatch` 只在页面发布的 `scope` 与目标图元 scope 不一致时出现：引擎只受理与当前
  scope 一致的平移意图。

### `impact`

- `attached`：清单声明的附着（标签↔引线），科学端固定、标签端随动。
- `ownership_closure`：引擎 `owned_closure()` 的权威归属闭包（契约 `nodes`/`groups`
  声明的父子链），不是从包围盒猜的邻居。
- `co_bound`：走**同一条声明绑定**路径的图元——那条参数被重建时它们一起动。
- `cross_scope`：绑定声明的作用域不止本 scope（引擎判 `NEEDS_AUTHORING`），或在别的 scope
  里同样被这条绑定牵动的图元。
- 没给候选时 `candidate` 为 `null`，`rules` 给出规则性说明（而不是空词）。

## 四、Agent 怎么用它提多目标改动

1. **先读，不先改**：`read_agent_context(session, {'gid': 选中GID})`。确认 `status='OK'`、
   `stale=false`；`stale=true` 说明选区与实时会话已经不一致，先重读选区，别拿旧帧提议。
2. **看清楚能不能动**：`scene.nodes[*].ghostable` 与 `constraints.not_independently_tunable`
   决定哪些对象**根本没有**整体平移这条路（曲线、引线端点、被裁掉/未测量的对象）。
3. **把改动拆成许可集合内的动作**：只用 `allow_gids`／`hard_limits.declared_bindings`
   里声明的绑定，把 `follow_gids` 写死成 `constraints.follow_gids`，`fixed_gids` 保持空。
   候选位移先对照 `declared_bindings` 的 `min`/`max` 自检，别指望通道替你放宽。
4. **逐条走既有通道**：每次候选送 `POST /api/tasks`（`kind='geometry'`）→ 既有
   `IntentSession.evaluate`；要落盘才走计划通道（`create_plan → authorize → apply`），
   授权、磁盘字节核对与验证都归那条链。
5. **用引擎回执说话**：只引用 `evaluate`/计划回执里的 `status`、`checks`、
   `measured_delta_mm`、`unapproved_objects`、`source_commit_state`、
   `figure_verification_state`。多目标时**逐条**报，不要合成一句"全部通过"。
6. **会牵动谁要事前说清**：`impact.attached`/`co_bound`/`cross_scope` 就是"这次会动到谁"的
   候选集；`ownership_closure` 里被同一条绑定带动的对象也要点名。

## 五、措辞红线

- **预览 ≠ 验证**：ghost 轮廓、拖动读数、本地 overlay、`impact` 里的推测，都不是引擎结论。
  只有引擎回执（状态 `OK` 且逐项 `PASS`）才能说"检查通过"；否则只能说"预览，尚未验证"。
- **写盘 ≠ 科学验证**：`source_commit_state='COMMITTED'` 只说明源码已安全提交；
  `figure_verification_state` 才是重建验证的结论。两者互不推导：
  - 两者都成立 → "修改已保存并通过验证"；
  - 写了但验证没过/没跑 → "源码已提交，图形验证失败/未完成"；
  - 拒绝/取消 → 磁盘一个字节没动，不说"已验证"。
- **本通道不授权**：`constraints.allow_gids` 是"引擎会怎么判"的描述，不是批准书；
  `read_agent_context` 成功更不代表任何改动会被接受。
- **别把 `ghostable` 当受理结论**：它只是预览资格；受理与否看 `evaluate`。
- **别把声明当既成事实**：`hard_limits` 是契约里写的范围，不是实测结果；实测值以回执的
  `measured_delta_mm`/`error_mm` 为准。
- 没跑过就说没跑过：`frozen_science.digest` 缺失时按 `reason` 如实说明，不要省略。

## 六、本阶段**未**实现（不要暗示已实现）

- **Agent 不自动排版、不自动写盘**：本通道是只读上下文；写盘仍走既有
  `plan → authorize → apply → verify` 通道，且必须由页面会话令牌同意。
- **不解释自然语言**：`intent` 文本只原样回显（`intent_note` 明说），把它变成改动的责任在
  Agent 与本通道之外的链路。
- **没有 HTTP 路由**：本切片只新增 Hub 方法，未接 `inspector_server.py`。
- **不做缩放/改尺寸**：只有 `translate` 这条路存在；resize/scale 需要新的 operation kind
  与 oracle。
- **不做跨 scope 的合并验收**：跨输出版本的绑定在引擎那边就是 `NEEDS_AUTHORING`，本通道
  只如实报告，不替你拼一个跨版本候选。
- **不新造真值**：本通道没有自己的几何、没有自己的科学指纹、没有自己的 ghost 实现
  （规则在页面侧，唯一）。

## 七、验收与运行

```bash
# 只跑本切片；其它测试/lint 不在本轮范围内
TEMP=D:/L/AI/figpact-archive/g6b-v2/tmp TMP=... TMPDIR=... MPLBACKEND=Agg \
  python -m pytest tests/test_agent_context_surface.py -q
```

测试断言的事实来源（都不是 mock）：

- Scene 一致：`payload['scene']['nodes']` 的 `gid`/`bounds_mm`/`text`/`controlled_by`
  与同一帧 `scene_json` 逐项相等；
- 约束一致：`hard_limits.declared_bindings` 与 `session._core.parameters()` 的声明逐项相等，
  `frozen_science.digest` 与 `session._science['digest']` 相等；
- impact 一致：`ownership_closure` 等于引擎 `owned_closure([gid])`；
- oracle 一致：不可 ghost 的曲线/引线在真实 `evaluate` 下是 `INVALID_INTENT`，跨 scope 的
  选择与跨输出版本的绑定分别是 `INVALID_INTENT` 与 `NEEDS_AUTHORING`，正常标签 + 跟随引线
  是 `OK`（`measured_delta_mm` 如实核到 0.15 mm）；
- 只读：调用前后帧、候选（`_pending`）、已接受操作、计划列表、选区和磁盘字节一律不动。
