# G5b：单题真 Agent 冒烟（真实服务 + 真实页面授权 + 落盘核对）

## 工作事实

本文件记录**一次**真实链路的单题冒烟：真实服务进程、真实 HTTP、真实文件字节、真实渲染图、真实页面点击。它**不是 G6b 三臂实验的一部分**（三臂协议仍冻结在 `docs/G6B_THREE_ARM_PROTOCOL.md`，本文件不构成其中任何一臂的数据），也不算 G5b 的正式门禁——门禁是 `docs/G5B_ACCEPTANCE_LAYERS.md` 里的层 1 独立 Chromium。这里要回答的只有一件事：**当一个 Agent（而不是确定性测试客户端）在真实页面上接到一份真实选区时，计划铸造 → 页面同意 → 客户端 apply → 磁盘与 history 核对，这条链是否真的走通、证据是什么**。

三段职责分得很清楚：

- **Agent 决策**（本 Agent，读真实选区后自己定 gid / 值 / 理由）：占位是"改哪个图元、改成什么、为什么"，不是"要不要授权"。
- **页面同意**（父代理在真实 Chromium 里**代用户点击**）：`POST /api/plans/<id>/authorize` 必须带服务端注入 `/frame.js` 的页面会话令牌，**网页自身无法授权**；本冒烟没有伪造令牌。
- **客户端 apply**（申请该计划的客户端，带 `X-Figpact-Client`）：写盘、返回诚实的 `commit_state`、必要时在 history 追加检查点。

服务与工作区（全部在仓库之外，避免污染受版本管理的样例）：

```bash
# 工作区：逐字节复制的样例 + 空配置；state home 在脚本/配置目录之外
#   C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke/simple_figure.py   ← 复制自 examples/python_native/simple_figure.py
#   C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke/config.yaml        ← 内容 "{}"
#   C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke_state/             ← 第二轮起的 FIGPACT_STATE_HOME

FIGPACT_STATE_HOME=C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke_state \
PYTHONPATH=D:/L/AI/figpact \
D:/programs/Python/python.exe -m figpact.inspector_server \
  --script C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke/simple_figure.py \
  --config C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke/config.yaml \
  --scope main --dpi 240 --port 17870
# 启动输出：
#   Inspector: http://127.0.0.1:17870
#   G2/G5a: session acceptance only; G5b source writes land only after the page session token consents to a minted plan
```

**为什么不用 `--example plain/nmr`。** `layout_edit` 只认源码里的 `LAYOUT_MM`（`python_native.LAYOUT_NAME`）；`tools/inspector_demo.plain_figure()`、`examples/nmr/08 NMR.py`、`examples/ftir/plot_ftir.py` 里都没有 `LAYOUT_MM` 这个绑定，铸造计划只会得到 `NEEDS_AUTHORING`（需要作者级改动，不猜常量）。所以走 Inspector 的显式信任本地脚本入口 `--script` + `--config`，指向 `examples/python_native/simple_figure.py` 的副本：它的 `LAYOUT_MM` 声明了 `intent.main.label.A`、`intent.main.label.B` 两个 `[dx, dy]`，是本次可铸造计划的真实目标（图元还有 `intent.main.curve`，但它的 `science_policy` 是 `LOCKED_SCIENCE`）。

**为什么用副本而不是仓库文件。** 二进制级写盘是这次冒烟要测的行为，直接打在受版本管理的样例上会留下工作树改动。副本与仓库文件**初始逐字节相同**（`fe298676aa8277db9420c61483ede491fef16c0ef1a7ca53392f589e2642b663`，两者 `sha256` 一致），全程只改副本；收尾时仓库文件 `sha256` 仍为 `fe298676…b663`（见下"真实验收"的核对表）。

一轮环境故障如实记：以服务方式启动时第一次用 PATH 上的 `python` 失败（`/usr/bin/bash: 行 1: python: command not found`），改用绝对解释器路径 `D:/programs/Python/python.exe` 后正常。

两次运行（第二轮是第一轮的修正重跑，原因见"第一轮的检查点缺失"）：

| 轮次 | 选区 gid | 计划 id | 结果 | 检查点 |
|---|---|---|---|---|
| 1 | `intent.main.label.A` | `03d663ebcbd949e6b6d4d99cbc71436e` | HTTP 200，`COMMITTED_AND_VERIFIED`，磁盘 == 计划 after | **无**（`checkpoint_id: null` + `history_error`） |
| 2 | `intent.main.label.B` | `3f4a49ab6320449aad46030ac91f93d3` | HTTP 200，`COMMITTED_AND_VERIFIED`，磁盘 == 计划 after | `f891d16d3f404c0e82c6f73b1bfd7f66` |

计划里的时间戳是 **UTC**（本地日期已是次日）。

## Agent 决策

**输入是真实选区**（`GET /api/selection`，两轮都是页面点选后发布的；第一轮第 4 次轮询、9.1 s 读到，第二轮第 5 次轮询、12.1 s 读到）：

```json
{"status": "OK", "hub_revision": 3, "selection": {
  "selection_seq": 3, "session_id": "3c5ee157-e3a8-4325-85d8-cb4fddc47d7c",
  "scene_revision": "61fcee6ecb05923ad81164e327600430ba70f4f5cdced938880ba24575a0857c",
  "source_revision": "cecbb040750c2a94cca6be8e8e287a557e02172b737807434336519b7c1e15ac",
  "scope": "main", "mode": "canvas",
  "selected": {"gid": "intent.main.label.A", "title": "A", "type": "文本",
    "bounds_mm": [20.316969696969696, 28.543587368481674, 22.01030303030303, 30.97775403514834],
    "linked_guide_gid": null, "registered": true, "identity_stability": "stable", "can_evaluate": false},
  "delta_mm": [0, 0], "status": "DESIRED_ONLY", "related": [], "constraints": ["preserve_science"]},
 "stale": false, "stale_reason": null}
```

第二轮同形，`selection_seq: 3`、`session_id: 41e32f73-d44b-4778-95e8-a07a264d36d6`，`selected.gid = intent.main.label.B`（`bounds_mm` 的 y 段同为 `28.5436/30.9778`——A 已在第一轮被压到曲线附近，页面重建后 B 仍停在原位）。

**决策依据是渲染出来的图，不是猜。** 先按副本原样渲染（`PYTHONPATH=D:/L/AI/figpact python simple_figure.py`，产出 `simple_figure.png`）：标签 A、B 停在 y≈0.62 的高度，而这条高斯曲线在 x=2.0 与 x=7.5 处只有 y=exp(−4.5)≈**0.0111** 与 exp(−3.125)≈**0.0439**——两个标签悬在空白处，指向不明。锚点无法由 `layout_edit` 改（那是数据/科学侧），可改的只有源码里 `LAYOUT_MM` 的毫米位移。

**毫米换算（用于定值，不是拍脑袋）。** 画布 60×45 mm，axes rect `(0.18, 0.22, 0.76, 0.68)` → y 轴跨度 9.9→40.5 mm；曲线值域 0.0111→1.0 加上 matplotlib 5% 边距后 ylim≈(−0.0383, 1.0494)，即 30.6 mm / 1.0877 ≈ **28.13 mm 每数据单位**。锚点 y=0.62 的文本底边落在 9.9+(0.62+0.0383)×28.13 ≈ **28.41 mm**，与选区报的 `bounds_mm` 底边 28.54 mm 相符（差值是文本 bbox 的内边距），换算可用。把底边压到曲线值之上约 0.05 数据单位（≈1.4 mm 间隙）：`(0.0111+0.05+0.0383)×28.13+9.9 ≈ 12.4 mm`，即 `dy ≈ −16.0 mm`；`dx` 保持 0，标签本来就在自身数据点正上方居中。

**决策内容**（两轮同构，目标按选区落到实际选中的那个 gid）：

- 第一轮：`intent.main.label.A`，`value = [0.0, -16.0]`。
- 第二轮：`intent.main.label.B`，`value = [0.0, -16.0]`。

`reason` 原文（第一轮，随计划铸造入服务端记录）：

> 选区命中 label.A；渲染实测标签停在数据锚点 (2.0, 0.62) 处，而曲线在 x=2 处只有 y≈0.0111——标签悬在空白处、指向不明。按毫米位移把它压到自身数据点正上方（曲线之上约 1mm 间隙），保持 dx=0 不横移。

第二轮同文，只把 A→B、x=2→x=7.5、y≈0.0111→y≈0.0439 换掉。

**结果验证（渲染，非断言）**：两轮 apply 后重渲染副本，A、B 分别贴着曲线在 x=2.0、x=7.5 处的上方（`C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke/simple_figure.png`，未入库）；副本最终 `LAYOUT_MM` 两行都是 `[0.0, -16.0]`。科学侧未动：`load_science` 与 `LABELS` 的锚点、文字一个字节没变（见 diff）。

## 授权与不变量（本次**实测到**的部分）

- **授权来自页面会话令牌，不来自请求体。** 第一轮计划铸造于 `17:19:15.107Z`、`state: PENDING`；父代理在真实 Chromium 页面点 `[data-plan-id="03d663eb…"] [data-plan-action="authorize"]` 后，`AUTHORIZED` 的 `authorized_at` 是 `17:19:17.659Z`（铸造后 2.55 s）。页面同时显示"已授权 · 计划 03d663eb（等待申请它的客户端应用，本页不写盘）"——页面**没有** apply 入口。第二轮同形：铸造 `17:20:47.137Z`，`authorized_at 17:20:49.617Z`（2.48 s）。
- **客户端绑定生效。** apply 带 `X-Figpact-Client: g5b-agent-smoke`，与铸造时 `client_id` 一致；两轮都返回 200。
- **before 哈希是链条而不是签名。** 第一轮计划 `before_sha256 = fe298676…b663`（= 副本初始 = 仓库样例），apply 后磁盘 `54932cf7…44a9`；第二轮计划 `before_sha256 = 54932cf7…44a9`（= 第一轮 after = 铸计划时的磁盘），apply 后磁盘 `71b2676a…d341e95`。每一轮写盘时磁盘都逐字节等于该轮计划的 before。
- **grant 单次使用。** 第二轮授权后读到的 grant 是 `{"single_use": true, "used": false}`；apply 200 之后同一 `/api/plans` 读到计划 `state: APPLIED`、`grant.used: true`。
- **第一轮的检查点缺失是配置失误，不是产品缺陷。** 第一轮 apply 响应里 `checkpoint_id: null` 且带
  `"history_error": "HistoryError: 历史目录必须位于脚本和配置目录之外"`。根因是我把 `FIGPACT_STATE_HOME` 设在了脚本目录**之内**（`…\g5b_agent_smoke\state`），而 `figpact/history.py:244` 明确要求 history 目录不能在 script/config 目录之下。产品在这里的选择是**如实回报擦不掉的事实**，不伪造一个检查点；写盘本身仍成功（`COMMITTED_AND_VERIFIED`，磁盘 == 计划 after）。第二轮把 state home 换成脚本目录之外的兄弟目录后，检查点正常写入。
- **本冒烟没有验证的负例（不宣称）：** 伪造/缺失令牌 403、未知/过期/非 PENDING 计划 409、未授权 apply 零写入、授权后外部改写 `STALE_SOURCE`、客户端不匹配、grant 过期、cancel 零写入。这些由 `tests/test_g5b_authorization.py`、`tests/browser/test_g5b_workflow.py` 覆盖（见上下文实测记录），本轮**一条都没有现场重跑**，也没有为了"凑证据"去伪造令牌。

## 真实验收

### 第一轮：`intent.main.label.A`（计划铸造 → 页面授权 → apply）

`POST /api/plans`（`Content-Type: application/json`）：

```json
{"client_id": "g5b-agent-smoke", "kind": "layout_edit",
 "script": "C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke/simple_figure.py",
 "gid": "intent.main.label.A", "value": [0.0, -16.0], "reason": "…（见上）"}
```

→ **HTTP 200**，计划关键字段：

```json
{"plan_id": "03d663ebcbd949e6b6d4d99cbc71436e", "journal_id": "38b7612d2f5e469b9bbf68288fa39580",
 "state": "PENDING", "created_at": "2026-10-12T17:19:15.107115+00:00",
 "expires_at": "2026-10-12T17:34:15.107115+00:00",
 "files": [{"path": "C:\\Users\\Lin\\AppData\\Local\\Temp\\g5b_agent_smoke\\simple_figure.py",
   "before_sha256": "fe298676aa8277db9420c61483ede491fef16c0ef1a7ca53392f589e2642b663",
   "after_sha256": "54932cf76261f1ad1d134c062072c8e93aac9f6c829efa278bf45f131f0e44a9",
   "diff": "--- a/…simple_figure.py\n+++ b/…simple_figure.py\n@@ -44,7 +44,7 @@\n LAYOUT_MM = {\n-    \"intent.main.label.A\": [0.0, 0.0],\n+    \"intent.main.label.A\": [0.0, -16.0],\n     \"intent.main.label.B\": [0.0, 0.0],\n }"}]}
```

`POST /api/plans/03d663eb…/apply`（`X-Figpact-Client: g5b-agent-smoke`）：

```json
{"status": "OK", "commit_state": "COMMITTED_AND_VERIFIED", "plan_id": "03d663ebcbd949e6b6d4d99cbc71436e",
 "journal_id": "38b7612d2f5e469b9bbf68288fa39580", "state": "APPLIED",
 "checkpoint_id": null, "history_error": "HistoryError: 历史目录必须位于脚本和配置目录之外"}
```

→ **HTTP 200**；磁盘 `sha256 = 54932cf76261f1ad1d134c062072c8e93aac9f6c829efa278bf45f131f0e44a9`，**等于计划的 after**。该轮的 journal 与两个 blob 落在第一轮的 state home（`…\g5b_agent_smoke\state\source-journals\38b7612d….json`、`…\blobs\sha256\{fe,54}\…`）——把 state home 放在脚本目录里正是检查点被拒的原因，这两处产物保留为证据，未删除。

### 第二轮：`intent.main.label.B`（修正重跑，检查点完整）

服务在 `FIGPACT_STATE_HOME=C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke_state` 下重启（同一端口 17870、同一副本脚本）。

`POST /api/plans` → **HTTP 200**：

```json
{"plan_id": "3f4a49ab6320449aad46030ac91f93d3", "journal_id": "92a5005cb41b46549431c7812b658400",
 "state": "PENDING", "created_at": "2026-10-12T17:20:47.137430+00:00",
 "expires_at": "2026-10-12T17:35:47.137430+00:00",
 "files": [{"path": "C:\\Users\\Lin\\AppData\\Local\\Temp\\g5b_agent_smoke\\simple_figure.py",
   "before_sha256": "54932cf76261f1ad1d134c062072c8e93aac9f6c829efa278bf45f131f0e44a9",
   "after_sha256": "71b2676a5682ffb67f44d4953f5ba385dbfec5b89f1dfed3c76c65706d341e95",
   "diff": "@@ -45,7 +45,7 @@\n LAYOUT_MM = {\n     \"intent.main.label.A\": [0.0, -16.0],\n-    \"intent.main.label.B\": [0.0, 0.0],\n+    \"intent.main.label.B\": [0.0, -16.0],\n }"}]}
```

授权后（页面点击，父代理执行）`GET /api/plans` 读到：

```json
{"state": "AUTHORIZED",
 "grant": {"plan_id": "3f4a49ab6320449aad46030ac91f93d3", "authorized_at": "2026-10-12T17:20:49.616920+00:00",
           "expires_at": "2026-10-12T17:35:47.137430+00:00", "single_use": true, "used": false}}
```

`POST /api/plans/3f4a49ab…/apply`（`X-Figpact-Client: g5b-agent-smoke`）：

```json
{"status": "OK", "commit_state": "COMMITTED_AND_VERIFIED", "plan_id": "3f4a49ab6320449aad46030ac91f93d3",
 "journal_id": "92a5005cb41b46549431c7812b658400", "state": "APPLIED",
 "checkpoint_id": "f891d16d3f404c0e82c6f73b1bfd7f66"}
```

→ **HTTP 200**。

### 核对：磁盘字节 / 计划 / blob / 检查点

| 核对项 | 观测值 | 结论 |
|---|---|---|
| 副本磁盘 `sha256` | `71b2676a5682ffb67f44d4953f5ba385dbfec5b89f1dfed3c76c65706d341e95` | == 第二轮计划 `after_sha256` |
| `blobs/sha256/71/71b2…e95` | 文件内容 == 磁盘副本；`sha256(blob)` == 文件名 | 一致 |
| `blobs/sha256/54/54932cf7…44a9` | `sha256(blob)` == 文件名；内容 == 第一轮 after（≠ 当前磁盘，符合"before"语义） | 一致 |
| 检查点 `f891d16d…` 的 `payload_sha256` | `9126c35a4103ba78dc0e177b45d36dc250f3fd7a8c38011f8412c149078ec2b0`，blob 内容 `sha256` 与文件名相同 | 一致 |
| 检查点 `file_changes[0]` | `before_sha256 = 54932cf7…44a9`（== 第二轮计划 before）、`after_sha256 = 71b2676a…e95`（== 第二轮计划 after == 磁盘） | 一致 |
| 仓库样例 `examples/python_native/simple_figure.py` | `fe298676aa8277db9420c61483ede491fef16c0ef1a7ca53392f589e2642b663`，全程前后一致 | **未改动** |

产品自身的只读视图（`python -m figpact.history list …`，`FIGPACT_STATE_HOME=…g5b_agent_smoke_state`）：

```
f891d16d3f404c0e82c6f73b1bfd7f66  kind=source_change  created_at=2026-10-12T17:20:54.819997+00:00  parent=-  payload=9126c35a4103
```

检查点 payload（存于 `workspaces/37/37904f96…/blobs/9126c35a…`，逐字摘）：

```json
{"commit_state": "COMMITTED_AND_VERIFIED", "kind": "source_change",
 "gid": "intent.main.label.B", "plan_id": "3f4a49ab6320449aad46030ac91f93d3",
 "journal_id": "92a5005cb41b46549431c7812b658400",
 "requested_mm": [0.0, -16.0],
 "reason": "…（第二轮 reason 原文）",
 "file_changes": [{"path": "C:\\Users\\Lin\\AppData\\Local\\Temp\\g5b_agent_smoke\\simple_figure.py",
   "before_sha256": "54932cf76261f1ad1d134c062072c8e93aac9f6c829efa278bf45f131f0e44a9",
   "after_sha256": "71b2676a5682ffb67f44d4953f5ba385dbfec5b89f1dfed3c76c65706d341e95",
   "before_blob": "blobs/sha256/54/54932cf7…44a9", "after_blob": "blobs/sha256/71/71b2676a…e95",
   "is_binary": false, "diff": "…（同计划 diff）"}]}
```

检查点落在工作区 `37904f962255e0d6eacc96c61e5c2a1a3ee10f33e226b3f75de088570cdd36b8`（工作区身份 = script/config/scope），`meta.head` 即该检查点 id。

### 未入库的产物（临时目录，可能被系统清理）

`C:/Users/Lin/AppData/Local/Temp/g5b_agent_smoke/`：`simple_figure.py`（已改的副本）、`config.yaml`、`plan_response.json`、`plan2_response.json`、`apply2_response.json`、`simple_figure.png`（两轮 apply 后的渲染）；`…/g5b_agent_smoke/state/`（第一轮 state home，缺检查点的证据）；`…/g5b_agent_smoke_state/`（第二轮 state home，含 `workspaces/…/history.sqlite3` 与两个 blob）。报告里已逐字保留关键 JSON，产物丢失不影响上述结论。

## 边界与未完成项

- **单题、单用户、回环。** 这是"本机单用户 + 同源 + 页面会话令牌"的同意绑定，**不是多用户认证**，也不宣称防本机恶意进程冒充同一 `client_id`。
- **授权由父代理在真实页面代用户点击**，因为网页不能自行授权；令牌由服务端注入 `/frame.js`，本冒烟两轮的授权都是页面点击的结果，未用其它路径制造 `AUTHORIZED`。
- **不计入 G6b 三臂实验**：没有模型对比、没有臂间指标、没有协议冻结项被跑；本文件的数据不进入 `docs/G6B_THREE_ARM_PROTOCOL.md`。
- **不是 G5b 正式门禁**：门禁是层 1 独立 Chromium（`tests/browser/test_g5b_workflow.py`）。层 2（独立 WebView2 宿主壳）未实现；层 3（真实 Tern 冒烟）未通过，因此不能由本文件推出"Tern 宿主兼容"。
- **负例未现场验证**：伪造令牌、过期、`STALE_SOURCE`、单次使用之外的重复 apply、客户端不匹配、cancel 等均由测试覆盖，本冒烟只走正向链路一次（外加一次因 state home 配置失误而暴露 `history_error` 的重跑），未把这些写成"已在本冒烟中验证"。
- **重跑的原因只有一条**：第一轮把 `FIGPACT_STATE_HOME` 放在脚本目录内 → 检查点被 `history.py:244` 的约束拒掉、产品如实回报。第二轮换成目录之外即恢复；除此之外无失败、无重试。
- **本轮没有跑项目测试、lint 或 git**；验收命令只有上面列出的真实服务、真实 HTTP 与只读的 `python -m figpact.history list`。
- 副本与 state home 都在临时目录：**仓库内除了本文件没有任何新增/修改文件**，`examples/python_native/simple_figure.py` 前后 `sha256` 相同。
