# G5a：会话 Hub（选区与几何任务协调）

## 工作事实

基线：`f07c135abd85896c6d22c2f6eaaa82d30fc62d70`（G5a 改动位于工作树，未提交）。本轮实现 **兼容性扩展的会话 Hub**：页面把当前选区发布到 Hub，Agent 读同一份选区并提交几何任务，Hub 复用既有 `IntentSession.evaluate` 试算。

**Hub 只做协调。** 它读选区、收几何任务、调用既有试算，**不授予源码写入或发布权限**，不另建 Figure、不另算科学、不另做 QA。本轮**没有替换任何既有接口**：`/api/intents/evaluate`、`/api/intents/decision`、`/api/frame/quality`、`GET /api/frame`、`/frame.js`、静态资源与旧 YAML Agent API 逐字不变（D-15）。

状态只在内存、会话级、**不落盘**：不写 history、不改用户文件。服务器是单线程 `HTTPServer`，写入天然串行，因此本轮未引入锁。

修改文件：

- **新增** `figpact/hub.py`：`SessionHub`，纯 Python、不依赖 matplotlib；公开方法返回 `(payload, http_status)`。
- **改** `figpact/inspector_server.py`（+41/−16）：抽出 `_json_body()`（与原内联校验的文案、状态码一致），新增 GET/POST 的 selection/tasks 分支；既有路由行为逐字不变。
- **新增** `tests/test_session_hub.py`：假 session，不构图。
- **改** `tools/inspector/inspector.js`：在 `publishAgentDetail()` 末尾发布选区到 `/api/selection`（模块级自增 `selection_seq`，只在选区/微调/试算/决定/加载时发布，hover 不发布，失败静默）。
- **方案包更新（未跟踪）**：`PLAN.md`、`README.md`、`docs/ROADMAP_AND_ACCEPTANCE.md`、`docs/DECISIONS_AND_RISKS.md`（新增 D-14/D-15/D-16、O-08，更新 O-02）、`agent/WORK_ORDER_G5A.md`（新建）、`agent/WORK_ORDER_G4_G6.md`、`docs/ARCHITECTURE_AND_PROTOCOL.md`。

`tools/inspector/inspector.js` 同一文件还含上一轮极简面板的**宿主收走焦点时的方向键加固**：`acceptsArrowKeys` 纯函数 + `pointerup` 补聚焦。这是检查器自身的行为修补，与 Hub 无耦合。

## 接口与兼容性

四条新路由，全部为新增；返回体一律 JSON。

### `POST /api/selection`（页面 → Hub）

`selection_seq` 必须是非负整数且**严格递增**（否则 400 `INVALID_SELECTION`，文案含当前值）；`selected` 非 null 时必须有 `gid`（否则 400 `INVALID_SELECTION`）；**清空选区用 `selected: null`**。

body 还含 `session_id` / `scene_revision` / `source_revision` / `scope` / `mode` / `selected{gid, title, type, bounds_mm, linked_guide_gid, registered, identity_stability, can_evaluate}` / `delta_mm` / `status` / `related` / `constraints`。

返回 `{"status":"OK","selection_seq":N,"hub_revision":M}`。

### `GET /api/selection`（任意本地客户端 ← Hub）

返回已发布选区原文，外加实时会话的 `session_id` / `scene_revision` / `source_revision` / `accepted_operation_ids`。发布值与实时会话在这三个版本字段上不一致时 `stale=true` 并给出 `stale_reason`（形如「图帧已变化：选区 X，实时会话 Y」）。选区未发布时 `stale=false`。

### `POST /api/tasks`（Agent → Hub）

- `kind="geometry"`：要求 `selection_seq` 等于当前选区（否则 409 `STALE_SELECTION`）、`target_gid` 省略或等于选区 gid、发布选区不得 stale。用选区上下文构造与页面同形的 intent（`operation=translate`、`preserve.science=true`、`follow_gids=[linked_guide_gid]`、`fixed_gids=[]`、`demonstration.display_only=true`、`tolerance_mm` 默认 `0.01`）调用既有 `session.evaluate`，返回 `{"status":"OK","task_id":...,"task_status":"EVALUATED","evaluate":{既有响应原样}}`。
- `kind="layout_request"`：只登记 → `task_status:"RECORDED"`，**不触发任何自动动作**。
- `kind ∈ {source_write, publish, delete, git}`，或 body 里 `source_write`/`publish` 为真 → 403 `FORBIDDEN`。
- 只有被接受的任务进入记录（`deque` 上限 50）；被拒任务不进入 Hub 状态。

### `GET /api/tasks`

返回最近 50 条任务 + `hub_revision`。

```bash
# 页面发布选区
curl -s -X POST http://127.0.0.1:<port>/api/selection \
  -H 'Content-Type: application/json' \
  -d '{"selection_seq":1,"session_id":"...","scene_revision":3,"source_revision":"...","scope":"main","mode":"canvas","selected":{"gid":"..."},...}'

# 任意本地客户端读同一份选区与实时会话
curl -s http://127.0.0.1:<port>/api/selection

# Agent 提交几何任务
curl -s -X POST http://127.0.0.1:<port>/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"task_id":"t1","kind":"geometry","selection_seq":1,"delta_mm":[0,0.15]}'

curl -s http://127.0.0.1:<port>/api/tasks
```

请求校验沿用既有语义：`Content-Type` 必须 `application/json`（415）、恰好一个有效 `Content-Length`（400）、**64 KiB 上限**（413）、空 body 拒绝（400）、JSON 对象且不得含 NaN/Infinity（400）；服务器仍只绑定 `127.0.0.1`，同源校验照旧。抽出的 `_json_body()` 与原内联代码的文案与状态码逐字一致。

## 风险与权限

- **无源码写入权限**：Hub 没有写 Python/YAML 的入口；`source_write`/`publish`/`delete`/`git` 一律 403。持久接受不等于写入配置或发布（D-16）。
- **无发布权限**：不触发正式 strict 发布，不改用户图件；`demonstration.display_only=true`。
- **状态不落盘**：Hub 状态（选区、任务记录、`hub_revision`）只在进程内存、会话级；不写 history、不写磁盘、不改用户文件。
- **单线程串行**：服务器是单线程 `HTTPServer`，写入天然串行，本轮**未引入锁**；并发多客户端由单线程排队而非并发控制保证一致性。
- `layout_request` **只登记**，不做任何自动动作；自然语言目标留给后续 Agent/授权路径，不代表 Hub 具备自主执行能力。
- 复用既有试算意味着几何/科学结论仍由既有引擎给出，Hub 不自证正确性；本轮只验证选区与任务传递链路。
- 本轮**没有**新增持久 HTTP 写入口、MCP、共享 Worker 或浏览器身份认证，不能据此声称这些风险已经解决。

## 真实验收

以下数字均为父代理亲自跑出的实测结果，未沿用旧数据。

### 真实端到端 12/12

驱动脚本 `I:/figpact-test-archive/hub-e2e.py`，独立客户端。页面在 Chromium 里点击后：

| 观测项 | 实测值 |
|---|---|
| Hub 读到 `gid` | `fig2_nmr.main.peak.vancho.3p91` |
| `title` | `Ar–OCH₃` |
| `bounds_mm` | `[24.422442552083343,13.505131832797426,33.29615744791668,15.84338704113076]` |
| `linked_guide_gid` | 存在 |
| `stale` | `false` |

- `kind=source_write` / `publish` → 403 `FORBIDDEN`；过期 seq → 409 `STALE_SELECTION`。
- `layout_request` → `RECORDED` 且无 `evaluate`。
- 几何任务 → 既有引擎 `OK` / `RENDER_CHECKED`，`measured_delta_mm=[0.0, 0.1500000000000039]`，`error_mm=3.913536161803677e-15`；引线科学端 `PASS err=0.0`。
- `GET /api/tasks` 两个客户端可读；用既有 decision 路由取消后 `accepted_operation_ids=[]`。

### 针对性测试

```bash
pytest tests/test_session_hub.py tests/test_inspector_server.py -q
node --test tests/inspector/test_inspector.js
```

| 本轮运行 | 通过 | 失败 | 跳过 |
|---|---:|---:|---:|
| Python（Hub + 既有 Inspector 服务器） | 23, 另有 3 subtests passed | 0 | 0 |
| 前端 Node | 45 | 0 | 0 |

## 边界与未完成项

- **兼容性扩展的 Hub：已验证。** 既有 `/api/intents/evaluate`、`/api/intents/decision`、`/api/frame/quality`、`GET /api/frame`、`/frame.js`、静态资源与旧 YAML Agent API 未被替换、逐字不变。
- `layout_request` 只登记不做自动动作；自然语言目标执行留待后续 Agent/授权路径。
- **MCP 与共享 Worker 属 G5b**，本轮未做。
- Tern 0.8.2（Windows）只能显示网页、不能驱动页面，共享选区因此必须由 figpact 侧提供（已记入 O-02）；方向键加固在 Chromium 验证（含宿主收走焦点那一格），**Tern 宿主内的最终复验仍待做**。
- 未开发 History GUI、自由拖拽、自动排版或 SVG 底图；未做跨 scope 出版验收。
- 后续实施顺序：**G3b → G4 → G6**（原 G4 → G5 → G6 作废）。
