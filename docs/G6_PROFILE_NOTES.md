# G6 引擎级剖析记录：一次真实 evaluate（NMR 例图）

> **这份报告只测引擎内部的 evaluate 路径，不是完整 Agent 生命周期。**
> 它不包含 LLM 推理、token、工具调用、人机交互、装包/冷启动之外的环境准备，也不是三臂
> Agent 盲测。因此**不得**用它宣称任何端到端（含 Agent）提速百分比；README 里既有的
> ~4.1% 是另一回事，两者不可互相折算、不可相乘。本单元没有跑任何 Agent 会话。
>
> 所有数字都来自现场测量：包装真实方法计数 + `cProfile`/`pstats`。没有估算值；确实没测的
> 地方写“未测”。**没有改动任何产品代码**（只在进程内 monkey-patch 计数，磁盘上的 `figpact/`
> 一个字节未动；没有 git 操作、没有跑测试/lint）。

## 0. 结论摘要（一句话版）

在一次真实的 `IntentSession.evaluate()`（NMR 例图、scope `main`、dpi 600、把
`fig2_nmr.main.peak.vancho.3p91` 上移 0.15 mm、`status=OK`）里：

| 项 | 数字（history=True，3 样本中位数） | 占 7.264 s |
|---|---|---|
| 整图重建次数 | **3 次**（`FigureSession._call_builder`） | — |
| 真实绘制次数 | **25 次**（`Figure.draw` == `FigureCanvasAgg.draw`） | 1.777 s（24.5%） |
| scene 快照/几何测量（1 次） | `scene.snapshot` 2.132 s | **29.4%（单一最大项）** |
| 来源指纹 `_source_evidence`（2 次，哈希 11,090,048 B） | 0.657 s | 9.1% |
| 来源指纹 mtime 族（`script_fingerprint` 7 / `module_revision` 5 / `source_revision` 3 / `engine_fingerprint` 7，互相嵌套不可相加） | `_guard` 0.839 s + `_sync` 0.165 s 等 | 约 11–14% |
| QA（`blocking_problems` 3 次 = 9 个检查项调用） | 0.692 s（其中 9 次 QA 绘制 0.594 s） | 9.5%（8.2%） |
| history I/O | evaluate 内 **0 次**写入；历史成本全在 accept/undo/reopen | — |

同一 evaluate 在 `history=False` 下是 5.433 s（差 1.83 s）——**其中 0.65 s 能直接指到 history 专属的
来源证据重算**（`_guard` 里的 `_source_fresh → _live_source → _source_evidence`，在 `history=False`
下为 0 s）；另外约 1.2 s 落在**两种模式共有**的代码里（`_capture_baseline` 0.848 vs 0.218、
`Figure.draw` 1.777 vs 1.278 等），**成因未测**，不能记到指纹账上（见 §5.2 末）。

## 1. 场景与复现

| 项 | 值 |
|---|---|
| 脚本 / 配置 | `examples/nmr/08 NMR.py` / `examples/nmr/nmr.yaml` |
| 入口 | `figpact.intents.IntentSession`（`script=`、`config=`、`scope='main'`、`dpi=600`、`history=True/False`） |
| 目标 | `fig2_nmr.main.peak.vancho.3p91`（`type=text`，`linked_guide_gid=fig2_nmr.main.guide.vancho.3p91`） |
| 意图 | `operation='translate'`，`delta_mm=[0.0, 0.15]`（上移 0.15 mm），`tolerance_mm=0.01`，`preserve.follow_gids=['fig2_nmr.main.guide.vancho.3p91']`，`demonstration.display_only=True` |
| 实测结果 | 3/3 样本 `status=OK`，`measured_delta_mm=[0.0, 0.1500000000000039]`，`error_mm=3.9e-15`，`checks`：science PASS / qa PASS（`qa_kind='blocking_problems'`，baseline 0 条、candidate 0 条）/ target PASS / impact PASS |
| 解释器 / matplotlib | Python 3.14.0 (MSC v.1944 64bit)、matplotlib 3.10.8、后端 `MPLBACKEND=Agg` |
| 环境变量 | `TEMP=TMP=TMPDIR=I:/figpact-test-archive/g6-prof/tmp`，`MPLCONFIGDIR=I:/figpact-test-archive/g6-prof/mpl`，`FIGPACT_STATE_HOME=I:/figpact-test-archive/g6-prof/state/sample<N>`，`PYTHONDONTWRITEBYTECODE=1` |
| 机器 | Windows 10.0.26200 x64（本机磁盘；工作目录 `I:\figpact-test-archive\g6-prof`） |

复现命令（每个样本一个独立进程；`sample N` 决定状态目录，A 与 B 必须同号）：

```bash
cd I:/figpact-test-archive/g6-prof
python g6_prof.py a 1    # 冷启动构造 → evaluate → accept → 关会话   (history=True)  → prof/run_a_1.json
python g6_prof.py b 1    # 新进程重开（身份校验 + 重放 + restart 检查点）→ undo → 关 → prof/run_b_1.json
python g6_prof.py c 1    # 同场景 history=False 对照组               → prof/run_c_1.json
python g6_prof.py e 7    # 只对 evaluate 开 cProfile → prof/evaluate_7.pstats / .txt (+ run_e_7.json)
python agg.py            # 3 样本中位数汇总（读 prof/run_*.json）
```

样本：`a`/`b`/`c` 各 3 次独立进程（sample 1/2/3，每次都清空该样本的状态目录）。下表除特别
说明外一律取**中位数**，并在需要处给出三次原值。

## 2. 计数是怎么来的（方法，无估算）

`g6_prof.py` 在进程内 `setattr` 包装**真实**方法/函数，记录 `calls / time / bytes`：

- 绘制：`matplotlib.figure.Figure.draw`、`Figure.savefig`、`FigureCanvasAgg.draw`、
  `FigureCanvasAgg.get_renderer`、`FigureCanvasAgg.print_png`（`Figure.draw` 才是真正的整图绘制；
  `savefig`/`print_png` 内部会再触发一次）。
- 图重建：`figpact.session.FigureSession._call_builder`（= 一次脚本级整图构建）、`build_candidate`、
  `_capture_baseline`、`_reload`、`try_layout`、`_render_verify`、`_render_payload`、`_sync`、`_qa`。
- 来源身份：`figpact.session.source_revision / module_revision / script_fingerprint / engine_fingerprint /
  load_module_cached`，`figpact.intents._source_evidence / _file_record / _file_digest`（`_file_digest`
  同时累计真实读取字节数）。
- 几何/场景：`figpact.scene.snapshot / drawn_shapes`，`figpact.inspector.capture_figure / _png_bytes`，
  `figpact.science.capture_science / compare_science`。
- QA：`figpact.qa.blocking_problems / check_out_of_frame / check_text_overlap / check_text_on_data /
  check_glyph_floor / check_edge_clearance / check_series_order / diagnostic_key_of`。
- 历史：`figpact.history.HistoryStore.append / checkpoints / head / close / _write_blob / _load_blob /
  _record`、`history._fsync_dir / _canonical_payload_bytes`（blob 写入/读取字节数按真实 `bytes`）。
- 意图层：`IntentSession._guard / _rebuild / _capture / _persist / _history_payload / _open_history /
  _verify_restore / _replay_operation / _nodes` 等。

每个阶段（cold_open / evaluate / accept / close / reopen / undo）前后各取一次快照，阶段内增量逐条
写进 `prof/run_*.json` 的 `phases.<name>.delta`，所以上文每个数字都能指到“哪个阶段、哪个计数器”。
函数级占比来自 `cProfile`（只对 evaluate 开），`pstats` 落在 `prof/evaluate_7.pstats`（文本
`prof/evaluate_7.txt`）。**profile 模式的耗时被 profiler 放大**（evaluate 7.26 s → 12.01 s），
所以百分比只在 profiled 运行内部解释，绝对墙钟一律用计数器模式。

## 3. 阶段墙钟（秒，3 样本中位数 + 三次原值）

| 阶段 | 中位数 | 三次原值 | 说明 |
|---|---|---|---|
| `1_cold_open`（history=True） | 2.282 | 2.353 / 2.272 / 2.282 | 冷进程：模块导入 0.672 s、科学载荷首装、基线构建、`_capture` |
| **`2_evaluate`（history=True）** | **7.264** | 7.714 / 7.262 / 7.264 | 本报告主角 |
| `2_evaluate`（history=False，mode c） | 5.433 | 5.593 / 5.433 / 5.265 | 对照组 |
| `3_accept`（history=True） | 2.132 | 2.132 / 2.178 / 1.949 | 历史检查点落盘 |
| `3_accept`（history=False） | 0.166 | 0.166 / 0.167 / 0.162 | 只改内存 |
| `4_close` | 0.003 | — | |
| `4b_inprocess_reopen`（同进程第二次构造，**失败**） | 3.424 | 3.424 / 3.430 / 3.314 | 见 §8 |
| `5_reopen`（新进程重开） | **16.205** | 16.205 / 17.790 / 14.418 | 身份校验 + 重放 1 条操作 + restart 检查点 |
| `6_undo` | 7.870 | 8.443 / 7.753 / 7.870 | 一次真实重建 + 一次检查点 |

## 4. ① 一次 evaluate 里图重建几次、draw 几次

`prof/run_a_{1,2,3}.json` → `phases.2_evaluate.delta`（3 样本完全一致）：

| 计数器 | 调用次数 | 中位耗时 | 占 7.264 s |
|---|---|---|---|
| `FigureSession._call_builder`（= 脚本 `08 NMR.py:_build` 一次整图构建） | **3** | 0.849 s | 11.7% |
| `Figure.draw` | **25** | 1.777 s | 24.5% |
| `FigureCanvasAgg.draw` | 25 | 1.791 s | 24.7% |
| `FigureCanvasAgg.get_renderer` | 105 | 0.010 s | 0.1% |
| `Figure.savefig` / `print_png` | 2 / 2 | 0.140 / 0.139 s | 1.9% |
| `scene.snapshot` | 1 | 2.132 s | 29.4% |
| `science.capture_science` | 6 | 0.015 s | 0.2% |
| `FigureSession._qa` / `qa.blocking_problems` | 3 / 3 | 0.692 s | 9.5% |
| `IntentSession._capture` | 1 | 3.300 s | 45.4% |
| `IntentSession._guard` | 2 | 0.839 s | 11.5% |
| `FigureSession._reload` | 1 | 1.430 s | 19.7% |

**3 次重建分别是**（对照 `figpact/intents.py:579 _capture` / `session.py:2507 _render_verify`）：

1. `_rebuild` → `FigureSession.__init__` → `_reload` → `_capture_baseline`（基线图：1 次构建 + 1 次 savefig PNG 指纹 + 1 次 QA）；
2. `try_layout` → `_render_verify` → `build_candidate`（候选图，含 1 次 savefig + QA）；
3. `IntentSession._capture` → `core.build_candidate(core.candidate_config)`（**与第 2 次同配置的候选图**，再算科学载荷 ×2、QA、`capture_figure`）。

**25 次绘制按上下文归类**（`draw[ctx] ...`，同一样本 3 次一致）：

| 上下文（谁触发的） | 次数 | 中位耗时 |
|---|---|---|
| `build`（`_call_builder` 内部的测量绘制：例图 `08 NMR.py` / `figure_style.py` 里共 10 处 `fig.canvas.draw()`，3 次构建 × 3 次） | 9 | 0.612 s |
| `qa`（3 个检查项 × 3 次 `fig.canvas.draw()`） | 9 | 0.594 s |
| `print_png`（savefig 内部的真实整图绘制） | 2 | 0.127 s |
| `capture`（`_capture` 里那次显式 `fig.canvas.draw()` 等） | 2 | 0.267 s |
| `try_layout` / `render_payload` / `baseline` | 1 / 1 / 1 | 0.058 / 0.055 / 0.070 s |

其它阶段对照（同源计数器）：`cold_open` = 2 次重建、19 次绘制；`accept` = 0 次重建、0 次绘制
（history=True 也一样，历史写入不重建）；`reopen` = 5 次重建、44 次绘制；`undo` = 2 次重建、16 次绘制。

## 5. ② 重复的 scene / source 指纹计算占多少

### 5.1 scene 侧（几何/科学指纹）

| 项 | 次数 | 中位耗时 | 占 evaluate | 证据 |
|---|---|---|---|---|
| `scene.snapshot`（`capture_figure` 内一次真实几何测量） | 1 | **2.132 s** | **29.4%** | `delta.scene.snapshot` |
| ├─ `scene._artist_node`（profile） | 31 | cum 3.797 s | 31.6%（profiled） | `evaluate_7.txt` |
| └─ `scene._clip_polyline_runs`（profile，15 个图元） | 15 | tottime 1.470 / **cum 3.638 s** | **30.3%（profiled）** | `pstats print_stats` |
| `science.capture_science`（科学载荷摘要） | 6 | 0.015 s | 0.2% | 便宜，不是瓶颈 |
| `intents._nodes`（把 `scene_json` 再解析成节点表） | 2 | 0.194 s | 2.7% | `delta.intents._nodes` |
| profile：`json.decoder.raw_decode`（3 次：`_nodes` 2 次 + `evaluate` 里取 `canvas_bounds_mm` 1 次） | 3 | 0.355 s | 3.0%（profiled） | `evaluate_7.txt` |

`_clip_polyline_runs` 内部（profile）：`_same_point` 201,977 次 0.906 s、`_clip_segment_t` 100,996 次
0.739 s —— 即**单张 NMR 图的 ~100 k 条线段逐段做 Liang–Barsky**，15 个折线图元全量重算。

### 5.2 source 侧（来源身份 / 具体调用了哪些路径）

| 计数器 | 次数 | 中位耗时 | 说明 |
|---|---|---|---|
| `IntentSession._source_evidence` | 2 | 0.657 s（9.1%） | 每次 `_guard` 都重算 |
| ├─ `intents._file_record` | 284 | 0.433 s | = 2 × 142 个文件 |
| └─ `intents._file_digest`（真实 sha256 内容哈希） | 284 | 0.351 s | **11,090,048 B = 11.1 MB / 次 evaluate** |
| `figpact.session.script_fingerprint` | 7 | 0.786 s | mtime 族，嵌套 |
| `figpact.session.module_revision` | 5 | 0.631 s | 含 `script_fingerprint` + `engine_fingerprint` |
| `figpact.session.source_revision` | 3 | 0.333 s | 含 `module_revision` |
| `figpact.session.engine_fingerprint` | 7 | 0.089 s | 遍历 `figpact/*.py` 的 stat |
| `IntentSession._guard`（= `_current_source()` + `_source_fresh()` 两条路） | 2 | 0.839 s（11.5%） | `intents.py:616` |
| profile：路径原语 `nt._getfinalpathname` 2572 / `nt.stat` 1547 / `nt._path_isfile` 1617 | — | 0.539 + 0.215 + 0.220 = **0.974 s** | 8.1%（profiled） |

- **不能相加**：`script_fingerprint` 在 `module_revision` 里、`module_revision` 在 `source_revision` 里，
  所以“来源指纹族”只能给区间：**`_guard` 0.839 s + `_sync` 0.165 s + `_reload` 内的指纹部分 ≈ 1.1–1.4 s，
  约 evaluate 的 15–19%**（`source_revision`/`module_revision` 的调用都落在 `_reload`、`_sync`、`_guard` 三处：
  `session.py:966/968/977/1001`、`intents.py:276/280/602/616`）。
- **history 模式专属的部分（可精确指认）**：`history=False` 时 `_source_fresh()` 因为
  `_source_files is None` 直接返回 True，`_source_evidence` **0 次**、耗时 **0.000 s**（同一次
  evaluate 在 a 模式是 2 次 / 0.658 s）。对照表（中位数，同一场景、同一计数器）：

  | 计数器 | history=True | history=False（mode c） |
  |---|---|---|
  | `IntentSession._source_fresh`（2 次） | 0.658 s | **0.000 s** |
  | `IntentSession._current_source`（2 次，两模式共有） | 0.183 s | 0.188 s |
  | `IntentSession._guard`（2 次） | 0.839 s | 0.188 s |
  | `FigureSession._reload`（1 次） | 1.430 s | 0.323 s |
  | `FigureSession._capture_baseline`（1 次） | 0.848 s | 0.218 s |
  | `Figure.draw`（25 次） | 1.777 s | 1.278 s |
  | `scene.snapshot`（1 次） | 2.132 s | 2.174 s |
  | evaluate 总墙钟 | 7.264 s | 5.433 s |

- **不能归因的部分（未测）**：上表里 `_reload`/`_capture_baseline`/`Figure.draw` 在同一段代码上
  a 模式慢 1.4–4×，而 numpy 为主的 `scene.snapshot` 两模式一致（2.132 vs 2.174）。这 ~1.2 s 的
  差额成因**未测**：可能是 history 会话持有的大对象图（帧/基线帧/来源证据）导致 GC 扫描变重，
  也可能是运行顺序/文件缓存效应（每轮 `a→b→c` 顺序固定）。**不要把它算作指纹开销**。
- **重开时更严重**（`prof/run_b_*.json`，中位 16.205 s）：`_source_evidence` **7 次**、994 次文件记录、
  **38,815,168 B = 38.8 MB** 被哈希、2.602 s（16.1%）；`script_fingerprint` 14 次、`module_revision` 10 次、
  `intents._nodes` 10 次（1.374 s，8.5%）。
- 文件集合口径（单次 `_source_evidence` 的**现场计数**，`probe7` 专用命令见下）：`_file_record` 被调用
  **142 次**，但只有 **130 个不同文件**（例图目录 104 个 − 排除的 4 个声明产物 = 100；`figpact/*.py` 30 个）。
  多出来的 12 次是**重复哈希**：`intents.py:137` 先 `rglob` 整个脚本目录，之后又对 `required` 的 12 个
  声明科学输入再走一遍循环（解析后的路径字符串完全相同 → dict 键相同 → 第二次哈希覆盖第一次，
  语义无变化、纯浪费；被重复读的正是 Bruker 的 `acqus`/`1r`/`procs` 大文件）。
  命令：`python probe7.py`（输出 `_file_record calls: 142 distinct paths: 130 duplicated: 12`，
  `files: 100 engine_files: 30`），或直接看 `prof/*.json` 里 `intents._file_record`
  （284 次 / 2 次调用 = 142）与 `_file_digest` 字节（11,090,048 B / 2 = 5,545,024 B 每次）。

## 6. ③ QA 各检查项耗时占比

该例图**没有** `preview_qa` 钩子（`grep -c preview_qa "examples/nmr/08 NMR.py"` → 0），所以
`FigureSession._qa` 走 `figpact.qa.blocking_problems`（`qa_kind='blocking_problems'`），每次 evaluate 调 3 次。

| 检查项 | 调用次数 | 中位耗时 | 占 7.264 s | 每次调用内的 `fig.canvas.draw()` |
|---|---|---|---|---|
| `check_text_on_data` | 3 | 0.247 s | 3.4% | 1 |
| `check_text_overlap` | 3 | 0.230 s | 3.2% | 1 |
| `check_out_of_frame` | 3 | 0.222 s | 3.1% | 1 |
| **合计** `blocking_problems` | 3 | **0.692 s** | **9.5%** | **9 次绘制 = 0.594 s（8.2%）** |
| `check_glyph_floor` | 0 | — | — | **未调用**（只在 `qa.report()` 里） |
| `check_edge_clearance` | 0 | — | — | **未调用** |
| `check_series_order` | 0 | — | — | **未调用** |
| `qa.diagnostic_key_of`（`FigureSession._qa_keys` 内部） | 0 | — | — | 本帧 0 条 QA 问题，无需解析 |

补充：`inventory`（`_render_payload` 内）31 次 `_snapshot_artist` 共 0.024 s；scene 自身的
diagnostics 由 §5.1 的 `scene.snapshot` 计时覆盖，未单独拆。

## 7. ④ history I/O 占多少

一次 evaluate **不写历史**（`HistoryStore.append` 0 次）；历史成本集中在三处：

| 阶段 | 中位墙钟 | 历史相关计数器（中位） |
|---|---|---|
| `accept`（history=True） | 2.132 s | `_persist` 1.478 s；`_source_evidence` 2 次 0.997 s；`_guard` 0.654 s；`_history_payload` 0.446 s；`HistoryStore.append` 0.415 s；`_write_blob` 0.088 s；`_canonical_payload_bytes` 2 次 0.197 s；`history._fsync_dir` 1 次 <0.001 s |
| `accept`（history=False 对照） | 0.166 s | 全部为 0 |
| `undo` | 7.870 s | `_persist` 1.225 s、`HistoryStore.append` 0.547 s、`_source_evidence` 3 次 1.363 s |
| `reopen`（新进程） | 16.205 s | `HistoryStore.checkpoints` 0.059 s；`_load_blob` 2 次（读 16,805,572 B）0.234 s；`_validate_history_frame` 2 次 0.111 s；`_persist`(kind=restart) 1.665 s（写 8,403,319 B） |

字节数（`prof/run_a_*.json` → `facts.after_accept_store` / `run_b_*.json` → `facts.final_store`）：

| 时刻 | 文件数 | 目录字节 |
|---|---|---|
| accept 后（1 检查点） | 2（blob + sqlite） | 8,427,362（8.4 MB，其中 blob 8,402,786 B） |
| undo 后（3 检查点） | 4 | 25,221,343（25.2 MB） |

结论：**一次检查点的 blob 落盘本身很便宜（`_write_blob` 0.088 s + fsync ≈ 0 s）**，8.4 MB 的证据
载荷里真正贵的是 ① 载荷构建：把 `frame`（600 dpi PNG base64 + 整帧 scene_json）+ `baseline_frame`
+ `science` 序列化成 8.4 MB JSON（`_history_payload` 0.446 s + `append` 内再规范序列化 0.415 s）；
② `_persist` 之前的**来源证据重算**（1.0 s，见 §5.2）。也就是说历史侧的优化空间主要不在“IO”，
而在“每次都把同一份证据重算一遍 + 每次都序列化整帧”。

## 8. 重开（会话重开）的两条路：新进程 OK，同进程失败

- **新进程重开（真实路径）= 16.205 s**（`prof/run_b_*.json`）：`_open_history` 0.376 s（身份+帧校验）→
  `FigureSession` 构造 → `_verify_restore` **13.592 s（83.9%）**，其中 `_replay_operation` 9.296 s
  （重放那条已接受操作：`_rebuild` 6.278 s + `evaluate` + `decide` + `_persist` restart 检查点）。
  恢复后 `accepted=['g6-prof-op-1']`、检查点数 2；undo 后 `accepted=[]`、检查点数 3。行为正确。
- **同进程第二次构造（任何第一步之后）**：3/3 样本稳定失败 ——
  `figpact.session.ContractError: 布局契约未通过校验：Dangling parameter objects: ['canvas_w_mm']`。
  同一失败也出现在 `history=False` 与“只构造、不 evaluate”的变体里（`probe3.py` 六种组合全失败）：

  ```bash
  python probe3.py open nohistory      # → ContractError（同进程第二次 IntentSession）
  ```

  现场证据（写进 `run_a_*.json` → `facts.inprocess_reopen`）：
  `cached_gids=31`、`fresh_gids=29`、`fresh_missing=[fig2_nmr.main.guide.vancho.3p68,
  fig2_nmr.main.peak.vancho.3p68]`。也就是说：契约来自脚本缓存的基线场景（31 个 gid），而校验用的
  新建基线只注册 29 个（少了 `vancho.3p68` 的标注与引线），`contracts._validate_parameter`
  对 `canvas_w_mm`（其 `objects` = 全部 gid）判为悬空并 fail closed。
  对比基线：`probe6.py` 里 `FigureSession → close → FigureSession` 两次都 31 个 gid **正常**；
  `probe4.py` 同一份配置连续建 3 次也都是 31 个 gid **完全一致**；`probe5.py` 里“先构造
  IntentSession、再直接 `mod.build_scene()`”也是 31 个 gid **正常**。也就是说：**只有“第二次
  `IntentSession`/`FigureSession` 自己的基线构建”看不到那 2 个 gid**，而脚本层直接构建看不到。
  **根因：未测**（把范围缩到“IntentSession 构造路径（`_capture` 等）与例图模块状态的交互”，
  未定位到具体行；本单元只做到“可复现 + 现场差异”，引擎侧指纹/契约逻辑本身没有发现缺陷证据）。
  对 G6 的影响：重开这一条腿**必须用新进程**测量（本报告就是这么做的），同进程复用会话暂不可用。

## 9. 热点排序（按证据，profiled evaluate = 12.012 s）

| 排名 | 热区 | profiled 占比 | 现场计数（clean，中位） | 每次 evaluate 的重复度 |
|---|---|---|---|---|
| 1 | `scene._clip_polyline_runs` / `_clip_segment_t` / `_same_point`（折线逐段裁剪） | 3.638 s = 30.3%（tottime 1.470 s） | `scene.snapshot` 1 次 2.132 s = 29.4% | 15 个图元、~100 k 条线段全量重算 |
| 2 | 25 次真实整图绘制（其中 9 次来自 QA、9 次来自构建） | `Figure.draw` cum 3.074 s = 25.6%（`draw_path` 仅 0.347 s） | `Figure.draw` 25 次 1.777 s = 24.5% | 同一个候选配置被建 3 次、画 25 次 |
| 3 | 3 次整图重建（`_build`） | `_call_builder` cum 1.570 s = 13.1% | 0.849 s = 11.7% | 第 2、3 次是**同配置**候选图 |
| 4 | `intents._numeric_error`（逐键递归比较两帧节点） | 303,159 calls，cum 1.393 s = 11.6%（tottime 0.686 s） | `_geometry_error` 29 次、`_nodes` 2 次 0.194 s | 同一对帧被多个检查重复比对 |
| 5 | 来源指纹族（`_source_evidence` + mtime 族） | 路径原语 0.974 s = 8.1% | `_source_evidence` 2 次 0.657 s + `_guard` 0.839 s | 一次 evaluate 内 2 次内容哈希（11.1 MB），reopen 里 7 次（38.8 MB） |
| 6 | QA 三个检查项 | `blocking_problems` cum 1.157 s = 9.6%（子项 `check_text_on_data` 0.404 / `check_text_overlap` 0.386 / `check_out_of_frame` 0.365，tottime 都 <0.04 s —— 时间在绘制里） | 3 项 3 次 0.692 s = 9.5% | 每项各自 `fig.canvas.draw()`，共 9 次 |
| 7 | JSON 序列化/反序列化（scene_json / 历史载荷） | `raw_decode` 0.355 s + `iterencode` 0.240 s = 5.0% | `_nodes` 2 次 0.194 s；accept `_history_payload` 0.446 s（8.4 MB） | 同一帧解析多次、整帧反复编码 |

相对次要（现场已测、都 <1%）：`science.capture_science` 6 次 0.015 s；`_png_bytes` 0.080 s；
`encoder.PyImagingEncoder`（600 dpi PNG 编码）profile 0.085 s；`drawn_shapes` / `inventory` 的 31 次
`_snapshot_artist` 0.024 s。

## 10. 未测 / 明确不覆盖

- **未测**：任何 Agent/LLM 层数字（token、工具调用次数、端到端 wall-clock、三臂盲测）——本单元
  只做引擎级分母，**不做也不宣称端到端提速**；README 的 ~4.1% 与本报告不构成任何相乘关系。
- **未测**：`figpact.runtime`/worker 进程路径（`_session_request` IPC）、GUI/Inspector 前端、
  真实发布/导出（`publish`）、多图/多 scope 场景、其它例图（NMR 之外）。
- **未测**：`check_glyph_floor`/`check_edge_clearance`/`check_series_order`/`preview_qa` 的耗时
  （该例图不走这些路径，调用次数为 0）；严格 QA（`strict`）路径未跑。
- **未测**：冷启动的磁盘缓存影响（第二次起 matplotlib 字体缓存已热）、机械磁盘/网络盘差异、
  多核并行与内存峰值。
- 计时噪声：`evaluate` 三次原值 7.714 / 7.262 / 7.264 s（首个样本偏高），冷启动 2.35/2.27/2.28 s；
  profiler 模式整体放大 ~65%，只用其相对占比。**history=True 与 history=False 的对照是跨进程
  对照**（每轮按 `a→b→c` 固定顺序跑，c 总是紧跟 b，文件缓存/堆状态不同），加上 §5.2 末那个
  成因未测的共有代码差异，所以这两列只用于指认“history 专属”的那 0.65 s，**不用于给总提速下结论**。

## 11. 如果要做优化：3 条最小且可验证的候选（**只提候选，本单元未改任何代码**）

> 判据：“最小”= 改动局限在一个函数/一处调用点；“可验证”= 有现成断言或计数器能判定等价与收益。

**候选 1（收益最大）：把 `scene._clip_polyline_runs` 的逐段 Python 循环向量化，或整段跳过。**
- 依据：§5.1 / §9 —— profiled 30.3%（cum 3.638 s）、`_clip_segment_t` 100,996 次、`_same_point` 201,977 次，
  每次 evaluate 15 个折线图元全量重算。
- 最小做法：在 `figpact/scene.py:213` 用 numpy 一次性算所有线段的 `(t0, t1, visible)`（Liang–Barsky
  的四个不等式都是对整条数组的 `max/min`），点链合并改成对布尔掩码做差分；再加一条“整条折线都
  在裁剪框内 → 直接返回原段”的快路径。
- 可验证：`scene.snapshot` 计数耗时与 `_clip_segment_t` 调用次数（本报告的计数器直接可复用）；
  **等价性**用现成断言 —— 同一意图的 `frame_revision` 必须逐字节不变，`tests/` 里
  `_geometry_error` / `_nodes` / `QA_MISMATCH` 相关用例（`tests/test_intents.py`、
  `tests/test_intent_history.py`）必须全绿。

**候选 2：一次 evaluate 内不要重建同一配置三次。**
- 依据：§4 —— `_call_builder` 3 次 0.849 s（profiled cum 1.570 s）；第 3 次 `_capture` 的
  `build_candidate(core.candidate_config)` 与第 2 次 `_render_verify` 的候选图**同配置**，
  且 25 次绘制里有 9 次来自这一路的 build。
- 最小做法：让 `IntentSession._rebuild` 复用 `try_layout` 已构建并验证通过的候选图（`Figure`/registry）
  来做 `capture_figure`，而不是 `_capture` 再 `build_candidate` 一次；`plt.close` 的所有权随之明确。
- 可验证：`FigureSession._call_builder` 3 → 2、`Figure.draw` 25 → 16；`frame_revision`、
  `measured_delta_mm`、`checks` 与现在逐项一致（现有 intent 测试直接覆盖这条返回值）。

**候选 3：来源证据在一次公开调用内只算一次（guard → persist 传同一份）。**
- 依据：§5.2 —— 单次 evaluate `_source_evidence` 2 次 / 284 次 `_file_record` / 11.1 MB；其中**每次调用有
  12 个声明科学输入被哈希两遍**（142 次调用对 130 个不同文件，现场计数）；accept 里又 2 次
  （1.0 s，占 accept 2.13 s 的一半）；reopen 里 7 次 / 994 次文件记录 / 38.8 MB。
- 最小做法：`IntentSession._guard` 里把 `_current_source()`（mtime 族）与 `_source_fresh()`
  （内容哈希族）合成一次调用，并把结果沿 evaluate→decide→`_persist` 传下去；或在单次公开调用内按
  `(path, size, mtime_ns)` memoize `script_fingerprint`/`engine_fingerprint`（`intents.py:276/280/602/616`、
  `session.py:966/1001`）。
- 可验证：`intents._file_digest` 调用数/字节数（evaluate 284 → 142、reopen 994 → 更少）；
  语义不变用 `STALE_REVISION` / `SOURCE_CHANGED` / `EVIDENCE_INCOMPLETE` 的现成用例判定
  （`tests/test_intents.py`、`tests/test_intent_history.py`）。
- 同族小项（不单列为候选，因单项 <10%）：QA 三项各自 `fig.canvas.draw()`（9/25 次绘制、0.594 s）
  可共享同一次绘制；`intents._nodes` 每次 evaluate 重新解析 `scene_json`（0.194 s，
  profile 里 json decode 0.355 s）可按 `frame_revision` 缓存已解析节点表。

## 12. 文件清单

| 路径 | 内容 |
|---|---|
| `I:/figpact-test-archive/g6-prof/g6_prof.py` | 计数/剖析 harness（模式 `a`=冷启动+evaluate+accept、`b`=新进程重开+undo、`c`=history=False 对照、`e`=只剖析 evaluate；`p*` 前缀=整段 cProfile） |
| `I:/figpact-test-archive/g6-prof/agg.py` | 读 `prof/run_*.json` 输出各阶段中位数与计数器表 |
| `I:/figpact-test-archive/g6-prof/probe_gids.py`、`probe2.py` … `probe6.py` | §8 的现场探针（gid 差异、同进程第二次会话、同配置重复构建） |
| `I:/figpact-test-archive/g6-prof/probe7.py` | §5.2 的文件去重计数（一次 `_source_evidence` = 142 次 `_file_record` / 130 个不同文件） |
| `I:/figpact-test-archive/g6-prof/prof/run_{a,b,c}_{1,2,3}.json`、`run_e_7.json` | 原始测量数据（含每阶段 `delta` 计数器、`draws`、`facts`） |
| `I:/figpact-test-archive/g6-prof/prof/evaluate_7.pstats` / `.txt` | evaluate-only 的 `cProfile` 结果与文本 top 表 |
| `I:/figpact-test-archive/g6-prof/state/sample{1,2,3}/` | 历史状态目录（accept/undo/reopen 的 blob + sqlite，共 25.2 MB/样本） |
