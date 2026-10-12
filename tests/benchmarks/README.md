# G6 引擎级分母（`nmr_engine_denominators.py`）

> **这是引擎级分母，不是三臂 Agent 盲测。**
> **不能拿这里的数字宣称端到端提速。**

冻结一个真实场景 —— `examples/nmr/08 NMR.py` + `nmr.yaml`，scope `main`，600 DPI，
把 `fig2_nmr.main.peak.vancho.3p91` 上移 0.15 mm —— 走**既有**的
`figpact.intents.IntentSession`（evaluate → accept → undo），重复采样 n 次，把每个阶段的
**引擎级分母**如实写进 JSON。它只记录，不判定：没有阈值、没有 pass/fail。

## 跑法

```bash
python -X utf8 tests/benchmarks/nmr_engine_denominators.py            # n=5（默认）
python -X utf8 tests/benchmarks/nmr_engine_denominators.py --n 3
python -X utf8 tests/benchmarks/nmr_engine_denominators.py --self-check   # 秒级，不建图
```

产物：`I:/figpact-test-archive/g6-bench/engine_denominators.json`
（`--archive-root` / `--out` 可改）。退出码：5 个样本全部可用 → 0，否则 1（JSON 照样写）。

脚本自己落环境并把同一份环境交给每个子进程：
`TEMP`/`TMP`/`TMPDIR` → `g6-tmp`、`MPLCONFIGDIR` → `g6-mpl`、
`FIGPACT_STATE_HOME` → `g6-state`、`MPLBACKEND=Agg`、`PYTHONDONTWRITEBYTECODE=1`。
只读 `examples/nmr/`，只写 `I:/figpact-test-archive/g6-*`，**不修改任何产品代码**
（计数靠运行时包装真实方法），不跑测试/lint/git。

## 每样本记录什么

| 阶段 | 墙钟 | 真实计数 |
|---|---|---|
| `construct` | 会话冷构造（含基线构建与首帧） | `Figure.draw` / `build_candidate` / QA |
| `evaluate` | 候选真实重建（`_rebuild`）+ 科学/QA/目标/影响校验 | 同上 |
| `accept` | 决定接受（含 history 检查点落盘） | 同上 |
| `undo` | 独立撤销（另一次真实重建 + 检查点） | 同上 |

外加每个阶段之后的 history 状态：`checkpoint_count`、state 目录 `files`/`bytes`/
`sqlite_bytes`/`blob_bytes`（`session.history()` 公开读 + 目录 `stat`，不是估算）、
`last_kinds`、`accepted_operation_ids`、`frame_revision`；以及
`figpact.session.loader_counters()` 的模块/科学装载次数。

计数怎么来的（都是**包装真实方法**，没有估算）：

* `figure_draw_calls` —— 包装 `matplotlib.figure.Figure.draw`。QA 内部
  `fig.canvas.draw()` 触发的那几次也算在内。
* `build_candidate_calls` —— 包装 `figpact.session.FigureSession.build_candidate`。
  基线构建走 `_call_builder`，因此不计入。
* `qa_calls` / `qa_seconds` —— 包装 `figpact.qa` 的**全部公开函数**；耗时只累加最外层
  调用（`blocking_problems` 里再调 `check_text_overlap` 时不重复计时）；
  `qa_by_function` 是逐函数的账本（父子会重叠，看"谁被调了"而不是"一共多久"）。
* `process_wall_seconds` —— 子进程整墙钟（含解释器启动），单列，**不并入阶段分母**。

## 正确性护栏（不许只看时间）

每个样本都记 `evaluate` 的 `status` / `evaluation_state` / `verification_level` /
`target_delta_mm` / `measured_delta_mm` / `error_mm` 与 `checks` 摘要，`accept`/`undo` 的
`status` 与 `persistence_state`，以及回到基线的证据：
`accepted_operation_ids` 回到空、`frame_revision` 与基线一致。样本的 `usable` 要求
evaluate/accept/undo 全 `OK` 且基线已还原；聚合里给出 `usable_samples` 与
`max_abs_error_mm`。**时间面上的样本数 ≠ 可用样本数**，引用时看后者。

## 它不是

* **不是三臂 Agent 盲测**：没有人、没有 Agent 会话、没有对照组、没有臂间随机化。
* **不能宣称端到端提速**：分母只覆盖"引擎在一次意图往返里实际做了什么"，不含 Agent 的
  读图/思考/工具往返/重试，也不含真人判断；与 README 里 ~4.1% 那类对照口径**不可混算**。
* **热几何阶段 ≠ 完整 Agent 任务**：`undo` 的若干秒不是"Agent 帮用户改一张图要几秒"。
* 不是测试：测试套件**不许**拿这些数字当门槛（耗时是机器状态，不是正确性）。

## 为什么一个样本一个进程

`examples/nmr/08 NMR.py` 的 `_BASELINE_SCENES` 是模块级缓存，`layout_contract` 复用该缓存
构建的基线；同一解释器里第二次构造顶层 `IntentSession` 会以
`ContractError: 布局契约未通过校验：Dangling parameter objects: ['canvas_w_mm']` 失败
（已实测）。所以每个样本各自冷起一个进程、各自一个**全新 state 目录**（样本之间互不
串味，history 都从 0 检查点起），这也让"冷构造"是名副其实的冷路径。
`cold_start` 与 `session_reopen` 是循环之外的一次性测量：前者在新 state 上只构造，
后者复用 `sample-01` 的 state（已有检查点）走 history 重开路径。
