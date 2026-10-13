# G5b：先计划、后授权的受限源码写入

## 工作事实

G5b 把 G4 的「先计划、后授权」从 Python API 接成一条**用户可见的同意链路**：用户在图上选中对象 → Agent 从 Hub 读到选区 → Agent 铸造修改计划（**零写入**）→ **用户在页面会话里授权** → 申请计划的客户端 apply（写盘）→ 重建验证 → 记录 History。

两次提交：授权后端 `ce3240d`；页面授权 UI + 层 1 门禁 `587e4aa`。

**这是本机单用户的同意绑定**（回环 + 同源 + 页面会话令牌），**不是**多用户认证；本轮**未做**多用户认证，也不宣称抗本机恶意进程冒充同一 `client_id`。

修改文件（本轮）：

- **改** `figpact/hub.py`：`SessionHub` 在既有选区/任务协调之上新增计划路径——`create_plan` / `read_plans` / `authorize_plan` / `apply_plan` / `cancel_plan`，以及模块级常量 `PLAN_TTL = timedelta(minutes=15)`、`UI_TOKEN_HEADER = 'X-Figpact-Ui'`、`CLIENT_HEADER = 'X-Figpact-Client'`、`PLAN_KIND = 'layout_edit'`（后续 G5c 增加 `PLAN_KINDS = ('layout_edit', 'authoring_edit')`，见 `docs/G6B_THREE_ARM_PROTOCOL_V2_1.md` §10.4）。
- **改** `figpact/inspector_server.py`：`InspectorServer` 构造时签发页面会话令牌并注入 `/frame.js`（`window.FIGPACT_UI_TOKEN=…`，即 `self._app.ui_token` 的 JSON 字面量）；新增 `GET/POST /api/plans` 与 `/api/plans/<plan_id>/<action>` 路由，**只有 authorize / cancel / apply 三个动作**，其它形状一律 404。
- **改** `tools/inspector/inspector.js`：`#agent-plans` 计划列表与 `[data-plan-id]` / `[data-plan-diff]` / `[data-plan-action=authorize|cancel]` / `[data-plan-status]` 渲染；authorize/cancel 请求带 `X-Figpact-Ui`（取自 `window.FIGPACT_UI_TOKEN`）。
- **新增** `tests/test_g5b_authorization.py`（499 行）：13 条授权用例。
- **新增** `tests/browser/test_g5b_workflow.py`（362 行）与 `tests/browser/conftest.py`（450 行）：层 1 门禁（真 Playwright + 真 Chromium + 真子进程服务）。

页面**没有** apply 路径：网页只读计划列表、只发 authorize / cancel，写盘永远由申请计划的客户端做（`inspector.js` 中该段注释即此语义）。

## 授权与不变量

### 网页不能靠布尔字段授权

- 服务端为每次 `InspectorServer` 构造签发 `secrets.token_urlsafe(32)` 页面会话令牌，注入 `/frame.js` 的 `window.FIGPACT_UI_TOKEN`。
- `POST /api/plans/<id>/authorize` 必须带 `X-Figpact-Ui`，服务端用 `hmac.compare_digest` 校验；缺失或错误 → **403 FORBIDDEN**。
- 因此**网页不能靠传一个 `authorized: true` 让服务器认为已取得用户授权**——授权校验的是页面会话令牌，不是 body 里的布尔字段。

### 计划由服务端铸造，铸造本身零写入

- `POST /api/plans {client_id, kind:"layout_edit", script, gid, value, reason}` 内部调用 `python_native.plan_layout_edit`，**不改用户源码一个字节**。
- 记录 `{plan_id, client_id, journal_id, files:[{path, before_sha256, after_sha256, diff}], expires_at, state}`。
- 定位/取值被拒时**原样透传** `AMBIGUOUS` / `NEEDS_AUTHORING` / `INVALID`，且**不铸造计划**。

### apply 的前置校验链（任一不过 → 零写入 + 409）

`POST /api/plans/<id>/apply` 必须带 `X-Figpact-Client: <client_id>`；写盘前依次校验：

1. 计划 `state == AUTHORIZED`（否则 `PLAN_NOT_PENDING` / `PLAN_CANCELLED` / `PLAN_APPLIED`）；
2. 计划未过期（`PLAN_EXPIRED`）；
3. `client_id` 匹配（不是申请者 → 拒绝）；
4. grant 存活且未使用（`GRANT_UNKNOWN` / `GRANT_ALREADY_USED` / `GRANT_EXPIRED`）；
5. journal 仍 `PREPARED` 且 before 哈希与计划一致（`JOURNAL_*`）；
6. **逐文件磁盘 sha256 == 计划的 `before_sha256`**（否则 `STALE_SOURCE`）。

全部通过后才标记 grant 已用 / `APPLIED`，走既有的 `source_writes.apply_source_change`，并返回诚实的
`commit_state`（`COMMITTED_AND_VERIFIED` / `COMMITTED_BUT_UNVERIFIED` / `RECOVERY_REQUIRED` / `NOT_WRITTEN`）——写盘已成事实时不得报 `NOT_WRITTEN`。**`commit_state` 现在是兼容字段**：名字里的 `VERIFIED` 只指
「journal + 逐文件磁盘字节核对」，回执另有下面两个**互不推导**的字段。

### P0a：写盘之后回两个独立状态（不再让"字节已提交"冒充"图已验证"）

写盘成为事实之后，Hub **自己另起一个进程**重建一次（`python_native.verify_committed_source` →
`_measure_geometry`），回执拆成两条通路：

|字段|取值|回答|
|---|---|---|
|`source_commit_state`|`NOT_WRITTEN` / `COMMITTED` / `RECOVERY_REQUIRED`|源码是否安全提交？|
|`figure_verification_state`|`NOT_RUN` / `PASS` / `FAIL` / `ERROR`|提交后的图是否通过**独立**验证？|

- 验证证据**绑定这次提交的版本**：脚本 `sha256`、目标 `gid`、`scope`、请求与实测位移、实测残差、
  科学指纹（`figure_verification`）。源码事后再变一个字节，`GET /api/plans` 就把旧结论撤下
  （`figure_verification_state` 回到 `NOT_RUN` + `figure_verification_stale` / `SOURCE_CHANGED`）。
- `PASS` 的三个条件与 G4 的 `edit_layout_and_verify` 同一套：目标 gid 实测位移在容差内（源码写毫米
  字面量 `0.01 mm`；作者化写回的 pt 偏移 `0.2 mm`）、其余可见几何一动不动、科学指纹逐位相同。
- 页面：只有 `COMMITTED` + `PASS` 才出现「修改已保存并通过验证」；写盘已成事实而验证
  失败/未完成只能说「源码已提交，图形验证失败/未完成」。

> **仍然成立的语义边界**：旧字段 `commit_state = COMMITTED_AND_VERIFIED` **只**表示「源码已写盘 +
> journal 与逐文件磁盘字节比较通过」，本身**不含**目标位移 / 科学内容结论（结论在
> `figure_verification_state` 与它的证据里）。正式轮判分口径（独立判分器必须自建重建；`completed`
> 只由自建结果判定；A16b / A17 不得把该返回值计为科学验证通过）见
> `docs/G6B_THREE_ARM_PROTOCOL_V2_1.md` **§12 已知语义限制：Hub 的 `COMMITTED_AND_VERIFIED`**；
> 该节登记的产品层待开票项（拆分两个字段）已在本单元落地。

### cancel 与状态寿命

- `cancel` **零写入**；已 `APPLIED` 的计划不可取消（409，要走历史恢复）。
- 计划 TTL **15 分钟**、上限 **50**（FIFO）；计划与 grant **全部内存态、会话级**，进程重启即失去所有批准。
- 服务器仍是单线程 `HTTPServer`，写入天然串行，本轮**未引入锁**。

### 已知安全边界（如实）

这是**本机单用户**的同意绑定：回环 + 同源 + 页面会话令牌。它**不是**多用户认证，**不防**本机恶意进程冒充同一 `client_id`。

## 三层验收

三层定义、每层能证明/不能证明什么的完整表述见 `docs/G5B_ACCEPTANCE_LAYERS.md`；此处只记归属：

| 层 | 环境 | 定位 | 本轮状态 |
|---|---|---|---|
| **L1** 独立浏览器（**G5b 正式门禁**） | 本机 figpact 服务 + 独立 Chromium 进程，Playwright 1.58.0 驱动 | 真实点击/选中/授权/apply/重建/History 全链路 | **已通过** |
| **L2** 独立 WebView2 宿主壳（集成/兼容） | 受控 WebView2 测试壳 | 窗口尺寸、焦点切换、显隐、服务重连 | **未做**（判定为可选后续） |
| **L3** 真实 Tern 冒烟（可选、非阻断） | Tern 0.8.2（Windows）Browser Pane，人工 | 网页能否在 Tern 里显示与驱动 | **未通过**（当前 Windows 版不可驱动；`ctl` 面板命令 >120s 无响应 → 非阻断） |

边界：**Chromium 通过 ≠ Tern WebView2 通过**（L2 的可证伪边界）；**只有 L3 通过才能声明「Tern 宿主兼容」**，当前一个字都不声称。

## 真实验收

以下数字均为父代理亲自跑出的实测结果。

```bash
pytest tests/test_g5b_authorization.py tests/test_session_hub.py tests/test_inspector_server.py -q
pytest tests/browser/test_g5b_workflow.py -q
node --test tests/inspector/test_inspector.js
```

| 本轮运行 | 通过 | 失败 | 跳过 | 实际耗时 |
|---|---:|---:|---:|---:|
| 授权 + Hub + Inspector 服务器（Python） | 36，另有 7 subtests passed | 0 | 0 | 未单独记录 |
| 层 1 门禁（真 Playwright + 真 Chromium + 真子进程服务） | 8 | 0 | 0 | 38.71 s |
| 前端纯逻辑（Node） | 47 | 0 | 0 | 未单独记录 |

### 13 条授权用例覆盖

伪造/缺失令牌 403、未知/过期/非 PENDING 计划 409、未授权 apply 零写入、授权后外部改写 `STALE_SOURCE` 零写入、grant 单次使用、客户端不匹配、过期 grant、cancel 零写入且已 `APPLIED` 不可取消、两客户端不覆盖。

### 层 1 门禁 8 条用例覆盖

- 点选 → Hub 收到新 publish（gid / bounds / identity 正确、`stale=false`）；
- 页面出现铸造的计划（含 diff）；
- 点授权 → `AUTHORIZED`；
- 授权后 apply → 磁盘 sha256 == 计划 after、`COMMITTED_AND_VERIFIED`、恰好一条 `source_change` 检查点且哈希与磁盘一致；
- 伪造授权（无令牌/错令牌）→ 403，且计划仍 `PENDING`、磁盘未变；
- 未授权 apply → 409 零写入；
- 授权后外部改写 → 409 `STALE_SOURCE`，且外部字节保留；
- **关闭浏览器上下文**后后端会话/选区/检查点完好，重开页面仍能点同一标签并发布同一 gid。

### 层 1 门禁发现并已修的真实缺陷

页面刷新后 `selection_seq` 从 1 重来，被 Hub 的严格递增校验拒（400 静默）→ 刷新后第一次点选发不到 Hub。修法：首次 publish 前从 `GET /api/selection` 播种序号（`max(hub_revision, selection_seq, current, 0)+1`），遇 `INVALID_SELECTION` 重播种并重试一次，失败可见化，并对 publish 串行化。

## 边界与未完成项

- **受限源码写入的同意链路：已验证**（层 1 门禁 8 项 + 授权单测 13 项 + 前端 47 项）。**这只到本机单用户同意绑定为止。**
- **未做多用户认证**，也不宣称抗本机恶意进程冒充同一 `client_id`；回环 + 同源 + 页面会话令牌就是全部前提。
- **未跑 G6b 三臂实验**：协议已冻结在 `docs/G6B_THREE_ARM_PROTOCOL.md`，本报告**不得**把它写成已跑。确定性测试客户端与门禁用例**一个数字都不贡献**给 G6b 的通过率/token/耗时分母。
- **层 2（独立 WebView2 宿主壳）未实现**：窗口尺寸、焦点切换、显隐、服务重连的兼容结论尚无证据。
- **层 3（真实 Tern 冒烟）未通过**：Tern 0.8.2 / Windows 只能显示网页、不能驱动页面；因此**不声称**「Tern 宿主兼容」。
- 计划与 grant 是**内存态、会话级、不落盘**：进程重启即失去所有批准，这是设计意图，不是缺陷。
- 服务器仍是单线程 `HTTPServer`；并发一致性靠排队与哈希校验，不靠并发控制。
- 未做自由拖拽、自动排版、History GUI 或跨 scope 出版验收。
