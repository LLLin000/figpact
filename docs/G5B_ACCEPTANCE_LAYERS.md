# G5b 三层验收策略与门禁

本文件回答一个问题：**G5b 的新授权路径（`/api/plans` 系列）到底由谁验收、验收到哪一层为止。**

硬前提（用户拍板，见 G5b 冻结契约）：网页**不能**靠传一个 `authorized: true` 就让服务器认为已取得用户授权。
后端校验的是**授权主体**（哪个 `client_id` 申请的计划）、**操作范围**（哪份计划、哪些文件、哪个 `gid`）、
**计划版本**（服务端铸造的 `plan_id` 与其 `before_sha256`）、以及**应用时磁盘文件的真实哈希**。
这是**本机单用户**的同意绑定（回环 + 同源 + 页面会话令牌），**不是**多用户认证——各层验收都不得宣称更强的东西。

---

## 1. 三层定义

| 层 | 名称 | 环境 | 驱动 | 定位 |
|---|---|---|---|---|
| **L1** | 独立浏览器（正式门禁） | 本机 figpact 服务 + 独立 Chromium 进程 | Playwright 1.58.0（Python，已安装）驱动 `%LOCALAPPDATA%\ms-playwright\chromium-1208`（另有 1217 与 headless shell）；selenium 4.40.0 亦可替代 | 真实点击 / 选中 / 方向键微调 / 任务提交 / 授权 / 历史恢复 |
| **L2** | 模拟宿主（集成 / 兼容） | 独立窗口、受控 WebView2 测试壳，或隔离本地部署 | WebView2 Runtime **154.0.4258.62**（本机已装）+ `pywin32 311`（已装）+ `~/.nuget/packages/microsoft.web.webview2`（已缓存）；Windows 窗/焦点/显示隐藏由壳自己控制 | 窗口尺寸、焦点切换、显示隐藏、服务重连 |
| **L3** | 真实 Tern 冒烟（可选、非阻断） | Tern 0.8.2（Windows）Browser Pane | 人工 | 等 Tern 宿主兼容改善后再验收 |

**本仓库当前可用的驱动（如实）**：

- Python 侧已装 `playwright==1.58.0`，浏览器二进制在 `%LOCALAPPDATA%\ms-playwright\`（`chromium-1208`、`chromium-1217`、
  `chromium_headless_shell-*`、`ffmpeg-1011`、`firefox-1538`）；`selenium==4.40.0` 也在。Playwright 是既有轮次实际用过的驱动。
- 仓库**内**没有浏览器端到端测试文件：`tests/inspector/test_inspector.js` 用 Node v24 内置 `node --test` 跑**纯逻辑**套件，
  不起浏览器；上一轮真实端到端驱动脚本是仓库外的 `I:/figpact-test-archive/hub-e2e.py`（归档，不在仓库内，不能被 CI 引用）。
  → L1 的浏览器驱动脚本需要**新写并落进仓库**（或明确记录其归档路径），不得把"归档里有"说成"仓库里有"。
- L2 的 WebView2 壳目前**不存在**，需要新写：WebView2 Runtime 与 WebView2 NuGet 包已就位，`pywin32` 已装，
  **没有装 `pythonnet` / `pywebview`**，所以最省的做法是 `win32com` + WinForms/WPF 或直接用 Edge WebView2 的 COM 加载器起一个最小窗口，
  **不新增 pip 依赖**。

---

## 2. 每层能证明什么 / 不能证明什么

### L1 独立浏览器 —— 能证明

- 真实指针事件链：hover → hit-test → click 选中（含重叠对象轮换）→ 方向键微调（`ArrowUp/Down/Left/Right`）→ 任务提交。
- 真实同源 + 回环约束：页面对 `/api/plans/<id>/authorize` 必须带服务端注入的 `X-Figpact-Ui` 会话令牌；
  缺 header → `403 FORBIDDEN`；**页面无法仅凭 body 字段自我授权**——这正是硬安全边界要证的那一条。
- 真实磁盘事务：`apply` 前逐文件校验 `before_sha256`；`source_writes.apply_source_change` 后的 `commit_state`
  语义（`COMMITTED_AND_VERIFIED` / `COMMITTED_BUT_UNVERIFIED` / `RECOVERY_REQUIRED` / `NOT_WRITTEN`）与 `history` 的
  `source_change` 检查点，以及"关闭浏览器后 History 不损"。

### L1 不能证明

- **不能证明 WebView2 宿主兼容**。Chromium 通过 ≠ Tern WebView2 通过。
- 不能证明 Tern 特有的窗口/焦点管理没问题（宿主动画、Pane 尺寸、宿主收走 `document.activeElement` 等）。
- 不能证明多用户认证、跨机授权、网络边界安全——本层只有回环 + 同源 + 单用户同意绑定。

### L2 模拟宿主 —— 能证明

- 页面在受控窗口尺寸变化下仍能正确把 mm 映射到 CSS px，hit target 不漂。
- **焦点切换**：宿主/窗口抢焦点后方向键仍生效（`acceptsArrowKeys` 的加固路径），或有明确的失败断言。
- 显示 / 隐藏后重绘与状态保持（`document.visibilityState`、ResizeObserver 路径）。
- **服务重连**：Hub 进程重启时段内页面无陈旧批准可用于写盘（grant 过期 / `STALE_SOURCE`），重连后能重新取回选区与计划列表。

### L2 不能证明

- **独立 WebView2 壳通过 ≠ Tern 特有焦点/窗口管理无问题**。壳是我们自己写的，Tern 的 Pane 生命周期、Luau 适配、
  宿主键盘拦截都不在壳里，L2 结论不得外推到 Tern。
- 不能替代 L1 的授权/事务验收——L2 只做集成与兼容，不做正式门禁判定。

### L3 真实 Tern 冒烟 —— 能证明

- 网页能在 Tern Pane 里显示；鼠标选中与键盘输入在**该 Tern 版本**上是否可用；面板命令是否响应。
- **只有这一层通过**，才允许在文档里写「Tern 宿主兼容」。

### L3 不能证明 / 现状

- 只能证明**所测的那个 Tern 版本 + 那个 OS**，不能证明"Tern 兼容"。
- 现状（已实测，见 O-02）：Tern 0.8.2 / Windows **能显示网页、不能驱动页面**
  （`driving web pages is not supported on this platform`）、headless 不显示页面、AX 可读页面控件；
  `tern browser …` / `ctl` 面板命令宿主上 >120 s 无响应（窗口本身仍响应 `state`），面板内键盘复验因此**未完成**。
  → L3 当前**做不了**，因此它**不阻断**任何 Gate。

---

## 3. G5b 门禁归属

| 判定 | 归属层 |
|---|---|
| **G5b 必须通过** | **L1**（真实 Chromium 上的点击/微调/任务/授权/历史恢复全链路） |
| G5b 的集成 / 兼容结论 | L2（窗口尺寸、焦点、显隐、重连）——**通过与否只写进 L2 结论，不改变 L1 的门禁判定** |
| 「Tern 宿主兼容」这句话能不能说 | L3——未通过就**一个字都不能声称**；缺 L3 不影响 G5b 是否 Go |
| 单元 / 逻辑回归 | `pytest` + `node --test tests/inspector/test_inspector.js`（既有套件，属工程卫生，不是浏览器验收） |

**Go**：L1 的 9 条用例全过，且副作用与拒绝语义逐条对上（未授权写入事件后磁盘字节不变、陈旧计划拒绝、
History 可单独恢复）。**No-Go**：任何一条用例"看起来成功了但盘上字节变了"或"拒绝了却已经写了一半"。

---

## 4. 9 条 G5b 验收用例（L1 正式门禁）

分层列 `L1` 表示正式门禁用例；括号里的路由是断言的落点。

| # | 用例 | 操作 | 期望（可观测断言） |
|---|---|---|---|
| 1 | 正常修改 | 点击目标 → 方向键微调 → 页面授权 → 客户端 `apply` | `POST /api/plans` 铸造 `PENDING` 计划（含 `files[].before_sha256/after_sha256/diff`）→ `authorize` 后 `state=AUTHORIZED` + `grant{single_use:true}` → `apply` 返回 `commit_state=COMMITTED_AND_VERIFIED`，磁盘字节 = `after_sha256`，figure 重建可见，`history` 追加 `source_change` 检查点 |
| 2 | 旧选区 | 选区变更后再提交旧 `selection_seq` 的任务 | 拒绝且**不铸造计划**：`409 STALE_SELECTION`（`/api/plans` 只透传 `python_native` 的 `AMBIGUOUS`/`NEEDS_AUTHORING`/`INVALID`，值非法与定位歧义均不产生计划） |
| 3 | 未授权写入 | 客户端直接 `apply`（无 `authorize`），或伪造 `{"authorized":true}` 在同一 body 里 | `POST apply` 无 `X-Figpact-Client` 或缺 `grant` → 拒绝；页面侧缺/错 `X-Figpact-Ui` → `403 FORBIDDEN`；**磁盘字节与调用前逐字节相同**，`GET /api/plans` 里该计划仍为 `PENDING` |
| 4 | 用户取消 | 页面 `POST /api/plans/<id>/cancel` | `state=CANCELLED`，**零写入**；此后 `authorize`/`apply` 均被拒（`409`）；已 `APPLIED` 的计划不可取消（`409`） |
| 5 | 科学数据改变 | 铸造计划后、`apply` 前改动被保护的科学载荷（数据/参数/科学文本） | `apply` 前哈希校验失败 → `409 STALE_SOURCE`，**一个字节都不写**；底层 journal 非 `PREPARED` 或 before 哈希与计划不符时同样拒绝 |
| 6 | 修改后探针失败 | 计划通过并写入，但重建后的探针 / 科学不变量检查失败 | `commit_state` 必须是 `COMMITTED_BUT_UNVERIFIED` 或 `RECOVERY_REQUIRED`，**不得**把已写盘说成未写；页面与任一本地客户端显示同一验证等级；History 保留可回退检查点 |
| 7 | 写入期间崩溃 | 在 `apply_source_change` 中途杀进程（客户端或服务端） | 重启后 `GET /api/plans` 无可用批准（grant 内存态即失，计划不复活）；磁盘处于可判定状态（完整 `after` 或原 `before`，**不得**半写）；`history` 能给出 `RECOVERY_REQUIRED`/检查点，恢复路径可判定 |
| 8 | 关闭浏览器后 History 不损 | 授权 → 应用 → 关闭页面/浏览器 → 重新打开 | 重新打开后 `state` 内存计划清空（会话级，不落盘），但 `history` 中 `source_change` 检查点仍在，可单独恢复；`GET /api/plans` 不因页面关闭而丢磁盘产物 |
| 9 | 两客户端竞争 | 两个 `client_id` 同时读同一份计划 / 争同一 gid 的授权 | 单线程 `HTTPServer` 串行：只有申请该计划的那个 `client_id` 可 `apply`（另一个 → 拒绝）；`grant` 单次使用，第二次 `apply` 拒绝；两个客户端不会各建独立候选并各写一份（`selection_seq`/计划一致性与 `STALE_SOURCE` 兜住） |

每条用例都必须同时记录：**HTTP 状态 + 错误信封文案 + 磁盘 before/after 哈希 + `commit_state` + history 检查点**。
只记"页面看起来成功了"不算证据。

---

## 5. 职责区分：确定性测试客户端 vs 真实 LLM Agent

| 项 | 确定性测试客户端（L1/L2 用） | 真实 LLM Agent |
|---|---|---|
| 谁 | 脚本化的 HTTP 客户端 + Playwright 脚本，输入固定 | 真模型，读 `GET /api/selection` 的真实上下文 |
| 证什么 | **协议与事务**：路由契约、header 校验、状态机（`PENDING/AUTHORIZED/APPLIED/CANCELLED`）、`before_sha256` 校验、`grant` 单次使用、`expires_at` 15 min、计划/grant 上限 50 与 FIFO、崩溃恢复语义 | 真 Agent 在真实图件上确实**读了选区再行动**、不靠猜「改这个」 |
| 不证什么 | **不能**证明任何 Agent 能力、token 开销、成功率或质量 | **不**用来验协议细节（协议由确定性客户端守） |
| 跑在哪 | L1 门禁 + L2 集成 | 只属于 G6（三臂协议）或 G5b 之后的人工抽查 |

**硬边界**：确定性测试客户端**不得**冒充 G6 三臂实验（见 `docs/G6B_THREE_ARM_PROTOCOL.md`，臂 L / A / V）。
G6b 的三臂是预冻结、按 trial 隔离 worktree 与 state home 的**计量实验**，本文件的用例表**一个数字都不贡献**给它：
L1 里"任务成功/失败"是布尔断言，不是 G6b 的通过率、token 数或耗时分母。反过来，G6b 的任何结果也**不能**当作
G5b 授权路径的验收证据。两套证据不得互相折算。

---

## 6. 边界声明（写给未来的自己）

1. **Chromium 通过 ≠ Tern WebView2 通过。** L1 全绿只说明页面逻辑与本机 HTTP 契约在独立 Chromium 里成立。
2. **独立 WebView2 壳通过 ≠ Tern 特有焦点/窗口管理无问题。** L2 的壳由我们控制，Tern 的 Pane 生命周期与键盘拦截不在其内。
3. **没有 L3，就不说「Tern 宿主兼容」。** 只能写「独立 Chromium 已验收，Tern 嵌入未实测」。
4. **L1 通过不证明**多用户认证、跨机授权、网络边界安全。本机单用户同意绑定（回环 + 同源 + 页面会话令牌）就到此为止。
5. 服务器仍是**单线程** `HTTPServer`：写入天然串行，因此不引入锁；并发一致性靠排队与哈希校验，不靠并发控制。
6. 计划与 grant **内存态、会话级、不落盘**（除 `python_native`/`source_writes` 既有的 `state_home` 产物外）：
   进程重启即失去所有批准，这是设计意图，不是缺陷。
