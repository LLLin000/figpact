# G7-B 前端任务书：保存闭环的 Inspector 侧

**基线**：`D:/L/AI/figpact` @ `master`。本文件是 `docs/G7_PLAN.md` §4 的前端实施规格。
**已具备（勿重复实现）**：
- 后端 `figpact/intents.py::IntentSession.save_accepted_changes(*, authorized, state_home=None, reason=...)`，返回 `{status, source_commit_state, figure_verification_state, message, journal?}`；已接受候选带 `base_script_sha256` / `base_config_sha256`；保存前做漂移检查；写入走既有 journal；`source_writes._write_target` 会恢复 mode 位。
- 前端 `tools/inspector/*`：已有"拖动 → 松开一次真实 evaluate"；已有 `#agent-plans` / `#agent-commits` 两区；P0a 双状态文案在 `planCommitText`。
- 测试：`tests/inspector/test_inspector.js`（Node 纯逻辑，现 52 通过）；`tests/browser/`（真 Chromium + 真服务子进程，现 20 通过）。

## 产品红线（不得违反）
1. **预览 ≠ 验证**；**写盘 ≠ 科学验证**。
2. 只有 `source_commit_state=COMMITTED` 且 `figure_verification_state=PASS` 才可显示"修改已保存并通过验证"。
3. 任何未验证状态**不得**出现"已验证 / 已保存"字样。
4. 不支持、绑定歧义、漂移、未授权的情形必须**明确拒绝并说明原因**，不得静默降级。

## 目标文件（只改这些）
- `tools/inspector/inspector.js`、`tools/inspector/index.html`、`tools/inspector/inspector.css`
- 必要时 `inspector_server.py`（新增保存路由）
- 扩 `tests/inspector/test_inspector.js`
- 新建 `tests/browser/test_save_flow.py`
- **禁止**改 `figpact/intents.py`、`figpact/source_writes.py`、`examples/*` 科学内容、`figpact/final_size.py`

## 四件事

### 1) 待保存修改区
通过验证的候选进入**待保存集合**（可多条；用户可继续改其他标注）。每条显示：
- **目标文件**路径
- **参数变更**（旧值 → 新值）
- **源码差异**（可读文本，非二进制）
- 可**移除单条**

### 2) "保存修改"
点击后**先展示**将要写入的目标文件与差异，**用户显式确认后**才调用 `save_accepted_changes`；未确认**不得**写盘。

### 3) 文案必须跟双状态
| 状态 | 文案 |
|---|---|
| 未写入 / 未运行 | 有待保存修改 |
| 已提交 / 通过 | 修改已保存并通过验证 |
| **已提交 / 失败** | **源码已写入，但图形验证失败**（不得说成"未修改"或"保存失败"） |
| 拒绝 / 取消 | 原文件未修改 |

### 4) 漂移拒绝要看得见
保存时若目标文件被外部改过：页面显示**拒绝理由**（点名文件与漂移），磁盘保持不变。

## 测试要求
**Node 纯逻辑**：待保存集合增/删；差异行生成；双状态→文案判定；**回绕断言**：任何非 PASS 状态不得包含"已验证 / 已保存"。

**层 1 真 Chromium（真实服务 + NMR 夹具）**：
1. 拖动 → 接受 → 待保存区出现 1 条 → 保存 → 断言发往保存路由的请求与回执字段，且**页面文案来自回执**。
2. 拒绝路径：保存前**外部改文件** → 页面显示拒绝 → 文件**字节不变**。

## 验收
两条浏览器用例真实跑通（给通过数与耗时）；`tests/browser/` 整套保持绿；不做 git 写操作。
