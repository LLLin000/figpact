# G0：fe48fee 真实基线

## 工作事实与 existing/new gap

基线 HEAD：`fe48feef021f1f0e74472be65887632b91edf7a4`。开始时本地与 GitHub master 一致；恢复执行时 HEAD 未变，工作区只有本工单 FTIR QA 兼容修复、新回归测试及用户提供的未跟踪设计包。设计包不整体暂存。

|既有能力|G1 需要补的部分|
|---|---|
|scene.snapshot：已有 Figure、空注册表也可测量；renderer mm、裁剪后折线分段、诊断|同一实际 draw 的 PNG/几何投影，避免分别重绘造成错帧|
|registry：作者登记身份与精确参数路径|稳定身份与单帧临时身份的明确展示；可测量不是可编辑|
|geometry：关系与实际折线|浏览器本地指针到真实线段的距离；bbox 只作粗筛，不重写科学几何关系|
|session/runtime：YAML 编辑、热会话、重绘与科学保护|独立、无需 YAML 的只读 Inspector，不扩展巨型 Session 类|
|science/QA/agent_api/publish/patch：科学保护、原发布与保存闭环|全部保留，Inspector 不提供写入或发布入口|
|tools/gui：既有调参 GUI|独立 HTML/JS/CSS 展示、Hover、Click、轮换、mm 标尺；后端只测量和导出|

## 原仓库回归

专用代理经 omp 原生 task 指定 `opencode-go/step-5-preview-free` 执行。Windows、Python 3.14.0、Matplotlib 3.10.8、pytest 9.0.2；`MPLBACKEND=Agg`，`PYTHONDONTWRITEBYTECODE=1`；TEMP/TMP/TMPDIR 与 pytest basetemp 在 I 盘。

```text
D:/programs/Python/python.exe -B -X utf8 -m pytest -q -rs
  --junitxml I:/figpact-test-archive/G0-G1-fe48fee/full-baseline/junit.xml
  --basetemp I:/figpact-test-archive/G0-G1-fe48fee/full-baseline/pytest-tmp
```

结果：**269 passed，0 failed，6 skipped，另 71 subtests passed**。pytest 132.24 s，完整命令 135.274 s。JUnit 中的 subtests 不能重复计成独立 pytest 测试。

跳过项：

- Windows 当前账号不能创建符号链接：`test_install_refuses_destinations_outside_the_output_root`、`test_approved_path_refuses_a_linked_source_or_destination`、`test_publish_refuses_a_destination_parent_that_leaves_the_target_root`、`test_publish_refuses_a_staged_link_that_leaves_the_staging_root`。
- 旧脚本夹具缺失：`test_legacy_script_without_contract_is_unsupported_not_guessed`、`test_legacy_script_renders_and_refuses_undeclared_edits`。

设计包 `tools/validate_examples.py` 5/5 通过，只证明协议例子符合 schema，不证明 Inspector 已实现。stderr 有既有 RequestsDependencyWarning，未隐瞒或抑制。

## 真实图件与保护

|实际命令（cwd 为原脚本目录）|结果|完整命令秒数|
|---|---|---:|
|原 FTIR 脚本 `--strict --probe .../real-baseline/ftir-probe`|退出 0，12 文件，无阻断|3.2204|
|原 NMR 脚本 `--strict --probe .../real-baseline/nmr-probe`|退出 0，4 文件，无阻断|4.7919|

使用原来的 10 个 FTIR CSV、12 个 NMR Bruker 声明输入，没有用合成图代替。基线测试前后核对 249 个保护文件，**0 修改、0 缺失、0 新增**，包含科学输入、原脚本、YAML、样式和既有正式输出。这个结论仅覆盖原基线运行前后，不覆盖随后授权的源代码修改。

NMR 实测对象（canvas_bottom_left，mm，非物理标定）：

- 标签 `fig2_nmr.main.peak.vancho.3p91`：`[24.2452, 13.5051, 33.4734, 16.4657]`。
- 引线 `fig2_nmr.main.guide.vancho.3p91`：`[28.8593, 13.1810, 33.5257, 13.4375]`。
- 二者是独立注册对象。引线独立可测量不代表能自由编辑其科学起点或末端。

普通无 YAML Figure：空 GidRegistry 下 7/7 节点可测量，RendererAgg、200 DPI。NaN 折线保留 4 段、3 处间断；原数组（含 NaN）不变，第二次只读快照一致。这是 scene 基础验收，不是浏览器 Inspector 验收。

## 隔离的性能基线

|路径|FTIR median / P95 秒|N|NMR median / P95 秒|N|
|---|---|---:|---|---:|
|main snapshot|1.92990 / 1.94361|7|2.69002 / 2.70344|7|
|未缓存预览|0.94118 / 1.16228|14 main+annotated|0.94935 / 0.97757|7|
|同 revision 缓存预览|0.10188 / 0.12148|14|0.18908 / 0.23711|7|
|独立 build+draw+QA|0.91597 / 1.28548|21 main+annotated+compare_raw|0.76935 / 0.79513|7|

未缓存预览 FTIR 14、NMR 7 次 build/render；缓存命中均不新增 build/render。strict 秒数各只有一次，不能称 P95。没有完整 Agent 往返、tokens 或随机配对对照，不据此宣称 Agent 任务整体提速。

## G0 实测发现与最小修复边界

原 FTIR 对照 `preview_qa` 使用仅含 axes/canvas/dpi/texts 的包装对象；既有 QA 已检查 Figure.images，导致实际 compare_raw/compare_processed 会话报 AttributeError。修复只补传真实 `fig.images`、`fig.bbox`，保持面板隔离与全局图幅图像保护，不修改数据、峰位、归属、排版或 QA 豁免。负向测试在修改前已捕获缺少 images 的失败。

首轮复测暴露两个新夹具假设错误：既有 QA 曲线检查针对垂直溢出，初始夹具造了水平溢出；scene 的 scope 表示整次测量归属，不是分别按两格面板命名。已把夹具纠正为实际垂直溢出，以及两个独立 panel ID/正确请求 scope，未据此改生产语义或削弱科学保护。最终修复回归统计独立记录，不混入上面的原仓库基线。

另有跨 scope 复用时科学缓存失效的性能问题；同 scope 可缓存。只记录，留给后续性能阶段，不在 G0/G1 扩大优化。

## G0 修复验收：通过

最终原生 Step 5 代理先按顺序运行新 FTIR 测试，再运行此前被全局样式污染的旧关系测试：3 passed、2 subtests passed。新测试导入原 FTIR 模块使用仓库既有 `matplotlib.rc_context()` 隔离方式；没有改旧关系测试或几何内核。

随后完整 pytest：**271 passed、0 failed、6 skipped、73 subtests passed**；原始日志 215.14 s，完整命令 217.45 s。六个跳过原因仍如上。证据：`g0-isolated-green/{focused.log,focused.xml,full.log,full.xml}`。

真实 `compare_raw`、`compare_processed` 会话预览分别 2.2214 / 1.7181 s，各含两个独立面板、QA 空、实际 PNG 签名正确、原 YAML SHA 未变。证据：`g0-resumed-green/logs/cmd2.out.txt` 及对应命令元数据。G0 通过，允许开始 G1；这些数字不是 G1 新 Inspector 性能。

## 证据与范围

本机原始证据：`I:/figpact-test-archive/G0-G1-fe48fee/` 下 `full-baseline/`、`real-baseline/`（timings、loader trace、probes、hashes/rehash-report.json）、`g0-compat-red/`、`g0-compat-green/`。私有科学输入与测试生成图不提交 Git。

G1 仅投影现有 scene 并提供只读浏览器视图。Source Authoring、History、MCP、nudge、自由拖拽、自动布局、Rust、替换旧 YAML API 均不在本工单。无 YAML 测量不得宣称无 YAML 编辑或 strict 发布验证。
