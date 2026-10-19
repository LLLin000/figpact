# G22：证据完整性与内部 Figure ownership

## 范围与代码基线

产品／回归代码基线：`170578b`。本轮只修 manifest／QA 异常失败关闭、FTIR／NMR 内部基线场景生命周期；不扩展 Artist、FTIR 图例控制、普通刻度裁切 QA、自动布局、Agent 或 GUI，不合并独立验证，不增加长期缓存。

科研数据、私有脚本和图像留在仓库外。G19／G20／G21 历史源码与证据未覆盖。旧 source 和新 source 的语义对照使用专门的私有 fixture，运行中的试验输入不被替换。

脱敏验收摘要：[results.json](../tools/g22/results.json)。最终证据／报告提交不改变上述已验证产品代码。

## P0：证据失败不再表现为证据为空

`figpact/style_overlay.py`：

- 未提供可选 `science_manifest`，仍按原协议使用 `None`；成功返回 `None` 也保留原语义，兼容 CCK-8 G19 wrapper。
- 已声明的 manifest 缺少 loader、loader 抛异常、manifest 抛异常，返回 `AUDIT_INCOMPLETE` 拒绝，不退回 `None`。
- `qa.measure()` 抛异常，或返回缺少 records list 的无效结果，拒绝为 `AUDIT_INCOMPLETE`；成功测量的合法 `records=[]` 仍有效。
- 统一转成既有验证失败通道，保留原异常分类和详情。严格加载、渲染、空 Overlay 读取、清除最后一个覆盖和第二独立验证对都保留拒绝语义，正式 Overlay／输出不因失败被改写。
- manifest 调用移入已有 Figure 的 `try/finally`；失败的构图不得用 `plt.close(None)` 意外关闭外部当前 Figure。

新增 `tests/test_overlay_audit_incomplete.py` 的 13 个故障／正常对照案例，包括 loader、manifest、QA、第二验证对、重新打开、清空和渲染故障。回执为局部 ERROR／整图 ERROR／NOT_WRITTEN，没有成功空记录降级。科学 capture 的既有 digest 缺失拒绝机制保留，没有新建第二套判据。

## P1：明确内部基线 Figure 的所有权

修改集中于两个示例模块的基线提取边界：

- `layout_contract()`／`science_manifest()` 的外层调用拥有本次创建的基线场景；同一调用内的嵌套提取可复用，最外层 `finally` 逐个关闭自身 Figure 并清掉缓存／owner 引用。
- `_BASELINE_SCENES` 不再跨公开提取调用长期保存 Figure。没有新增持久 Figure／Canvas／Manager 缓存，也没有用 Gcf 前后差集猜 ownership。
- `_build(..., _owned=...)`／NMR `_draw_spectra(..., _owned=...)` 在 `plt.subplots` 后立即记录明确的内部 owner；绘制中途异常也关闭已创建的半成品。普通 caller-owned 构图仍返回 caller 的 Figure，不提前关闭。
- NMR 原 `_draw_spectra` 的模块全局 `reg`／`artists_by_sample` 会继续持有 artists；改为局部返回并显式传给峰标签布局。不是改变科学计算或标签算法。
- 没有在产品操作后执行 `plt.close('all')`，也没有修改任何验证次数。

新增 ownership 回归覆盖 FTIR／NMR、多 scope、嵌套提取、绘制中途和角色提取中途抛异常、GC 后弱引用释放，以及外部 Figure 的 manager 与数据仍存活。审查中发现的双 pop 和 NMR `_draw_spectra` 返回前的创建点缺口均已修复，最终回归覆盖这些路径。

## P2-A：修复前后语义严格相等

最终对照不是两个不同路径下的 digest 做文字替换：在独立 **same-path fixture** 中，先运行 G19 原字节脚本的子进程，退出后仅将该 fixture 的脚本换成新字节，再运行新子进程。真实数据、配置、样式文件、`__file__` 和 `science_inputs` 路径保持相同；不修改原归档，不改任何 digest 或声明。

FTIR 的 main／annotated／compare_raw／compare_processed 四个 scope 和 NMR main，一个不漏。每个 scope 都重新建真实 Figure，直接采集：

| 检查层 | FTIR 4 scopes | NMR main |
|---|---|---|
| 完整 manifest，含 science body | 原始值完全相等 | 原始值完全相等 |
| 完整 layout contract／角色／GID | 相等 | 相等 |
| 科学 fingerprint 与原始 digest | 相等 | 相等 |
| 几何、受保护视图、对象样式审计 | 相等 | 相等 |
| QA 记录、问题、blocking 结果 | 相等 | 相等 |
| 外部 Figure／manager | 存活 | 存活 |
| 新版提取调用结束后内部基线引用 | 已释放 | 已释放 |

路径不同的早期对照曾需要归一化源文件路径；上表采用后续同路径直接比较，**无需归一化**。早期只存 nodes／viewports 的不完整快照不作为完整 manifest 一致的证据。

最终私有证据：`g22-semcmp/samepath_report.json`、`samepath_{old,new}_{ftir,nmr}.json`、`samepath_swap_record.json`。脚本哈希：

- FTIR 原 `32f8df6ffb592eb169cd91284266cc93988e5eab3d7afe51f4b5121422a8ed00` → 新 `edba9ef6a4fcc7b20e5b60af89b0230412bc8e22744d805f98e7a3aacca88806`。
- NMR 原 `f2044ad4fba0a10a770b65521c0eb328ac6fcc7c8199fcbf7416f732d9376ac9` → 新 `1c77356f37cae0f2f14be133d4a75b9451e28c119a969c473fcb132a0abc905c`。

## P2-B：真实 FTIR 3 次／10 次编辑与失败拒绝

每组在新进程里创建一个外部 Figure 作为反例，然后运行实际 StyleSession 预览／确认。编辑在基线字号 +0.2／+0.4 pt 间轮换，避免增长到新的布局限制；每组另含 3 次 4 pt 失败候选。失败均 STYLE_REJECTED，正式 Overlay 字节保持不变。

每次操作后测 Gcf、所有新建 Figure 的弱引用和 GC 后状态；**没有全局关闭 Figure**。全部采样点的内部 manager 和 GC 后内部存活 Figure 都是 0，外部 manager 及其数据始终保留。Gcf 总量为 1，因为外部调用方的 Figure 本来就应该活着。

| 试验 | 成功确认 | 失败拒绝 | 累计创建 Figure | 最终内部存活／管理器 | 释放 session 后 RSS（MiB） | 进程峰值 RSS（MiB） |
|---|---:|---:|---:|---:|---:|---:|
| G22 三轮 | 3 | 3 | 236 | 0／0 | 137.17 | 220.78 |
| G22 十轮 | 10 | 3 | 684 | 0／0 | 200.66 | 228.47 |

十轮每次确认后的 GC RSS 为 123.57、138.68、139.64、140.88、143.16、143.07、141.98、142.64、145.27、147.83 MiB。末次失败候选后及释放 session 后为 200.66 MiB；没有隐藏这个上跳。RSS 含分配器／其他缓存保留，不能据此宣布所有内存均稳定或已归还系统。对象数量证据证明的是已定位的 Figure 持有链被消除；十轮也不是“一整天零内存增长”的保证。

G21 原三轮在释放 session／GC 后仍有 120 个内部 Figure、约 1238.9 MiB RSS。G22 还增加了失败压力和外部 Figure，不能将两者当作精确同口径的内存性能 benchmark；但没有再出现每次动作新增 20 个持有 Figure 的现象。

核心构图仍为启动 2 次、每次预览 12 次、确认 12 次；失败候选 6 次。manifest 的真实基线场景仍会创建，只是提取后释放，不靠省略科学证据减少 Figure 数。

私有逐次记录：`g22/lifecycle-final-3/lifecycle.json`、`g22/lifecycle-final-10/lifecycle.json`。GC／profiling 会改变时序，不把这些 probe 的耗时作为交互性能结论。

## P2-C：出版、拒绝和草稿语义保持

- 使用修复后的 NMR 脚本完整重跑 G21 Native 事务、严格沙箱、保存、新 worker 重开、第二次编辑提交、严格 Overlay load／render：全部保持成功。实际最终 PDF 最小字形仍为 **5.04 pt**，xlim／ylim、科学数据、标签和指纹检查通过。
- NMR 的两个既有贴边 warning 和约 0.39 px 最右刻度余量没有被本轮“修掉”。实际安装 PNG 已查看，但不声称外部审阅者取得过私有 PDF。普通刻度裁切 QA 覆盖仍留待 G23。
- FTIR 既有候选的整组 strict 仍退出 1，compare 图仍有 4 条文字压线，未产出正式 PDF。没有将 annotated 局部预览通过写成出版成功。
- 3／10 轮实际成功保存均 COMMITTED_DRAFT；整图 FAIL 未洗成 PASS；失败候选字节保留。真实 Chromium 的草稿新进程重开／继续编辑回归也重新执行通过。

私有产物在 `g22/nmr-publication-final/`、`g22/ftir-refusal-final/`，未提交公共仓库。

## P3：五轮同口径性能复测

全部回归、生命周期和语义 probe 结束后，在同一机器的新进程中串行执行；FTIR、NMR、CCK-8 原完整流程与纯构图各 5 轮，共 20 轮。输入数据、原配置和样式依赖与 G20 字节一致；仅 FTIR／NMR 脚本替换为本轮代码。沿用 G20 的完整流程与嵌套扣除计时，另外记录实际 API 操作耗时。每轮都实际确认、重开、继续预览及拒绝外部冲突；从保存的真实回执取状态，不推断缺失证据。

全部 20 轮成功；FTIR／NMR 各 5 次 COMMITTED_DRAFT／整图 FAIL，两种 CCK-8 各 5 次 COMMITTED／整图 PASS。每轮核心 build 都是 **60 次**，和 G20 相同；没有靠删独立构图、重新打开或 QA 提速。下面单位为秒，`p50 / p95` 为 5 点线性插值，不是平均值，也不是用户一次点击要等完整流程那么久。

| 样本 | 操作口径 | G20 p50 / p95 | G22 p50 / p95 |
|---|---|---:|---:|
| FTIR | 首次预览 | 13.22 / 14.63 | 8.39 / 9.40 |
| FTIR | 确认 | 14.66 / 14.90 | 8.61 / 9.42 |
| FTIR | 完整流程 | 79.02 / 80.59 | 50.39 / 51.21 |
| NMR | 首次预览 | 13.70 / 23.55 | 8.76 / 9.40 |
| NMR | 确认 | 13.83 / 26.24 | 8.74 / 9.66 |
| NMR | 完整流程 | 75.47 / 135.68 | 49.35 / 51.55 |
| CCK-8 原完整流程 | 首次预览 | 25.86 / 26.77 | 19.08 / 20.23 |
| CCK-8 原完整流程 | 确认 | 26.23 / 26.35 | 18.41 / 19.68 |
| CCK-8 原完整流程 | 完整流程 | 131.72 / 134.30 | 97.30 / 99.60 |
| CCK-8 纯构图 | 首次预览 | 13.19 / 14.68 | 11.19 / 11.96 |
| CCK-8 纯构图 | 确认 | 12.95 / 15.08 | 10.98 / 11.83 |
| CCK-8 纯构图 | 完整流程 | 67.92 / 72.72 | 56.47 / 57.93 |

新记录的其余操作拆分如下，G20 未单独记录这些字段，不补造历史值：

| 样本 | 启动＋快照 | 重开＋快照 | 继续预览 | 冲突 session 启动＋探测 |
|---|---:|---:|---:|---:|
| FTIR | 0.82 / 0.85 | 10.94 / 11.66 | 9.73 / 10.41 | 10.78 / 11.87 |
| NMR | 1.25 / 3.08 | 10.15 / 11.60 | 9.53 / 9.77 | 10.06 / 11.40 |
| CCK-8 原完整流程 | 3.12 / 5.69 | 17.19 / 18.35 | 19.40 / 20.10 | 18.65 / 19.78 |
| CCK-8 纯构图 | 1.73 / 1.90 | 10.29 / 10.67 | 10.98 / 11.26 | 10.02 / 10.66 |

方法和限制：

- 这是同口径历史比较，**不是受控的同期随机 A/B**。没有修改 baseline-scene ownership 的 CCK-8 也变快，说明系统负载、分配器／缓存和跨试验环境差异不可忽略；不能把上表所有时间差都归因为 P1。
- 最确定的收益是已测持有对象消失。首次预览依旧是秒级，未达到即时编辑；本轮不继续重写验证器去追 2 秒目标。
- FTIR 完整流程仍有约 24.06–28.14 秒、NMR 约 18.97–21.60 秒未被现有独占阶段 hooks 归类；不宣称所有成本均已定位。各阶段分位数不可相加当总分位数。
- CCK-8 原完整流程仍每轮真实 `fs.export=60`／`savefig=180`；5 轮合计 300／900。`fs.export` 的 p50／p95 为 38.13／39.06 秒，其中 savefig 为 29.28／30.34 秒，两者包含关系不能相加。纯构图保持 0／0，没有吞导出或伪造加速。
- 计时 harness 的原全局清理由 ownership 断言替代，不清理残留来掩盖失败。CCK-8 旧完整 wrapper 自身的原有 `close('all')` 行为未改，它不是本轮 FTIR／NMR ownership 修复或外部 Figure 保全证据。
- 一轮额外验收 PNG 不计入计时窗口。单轮 smoke 只验证工具调用，没有混入五轮样本；其并发环境下更短的耗时不作最终性能数据。

公开逐轮、操作和独占阶段记录：[performance_results.json](../tools/g22/performance_results.json)。私有原始回执和事件在 `g22/full5/`，没有覆盖 G20 记录。

## 回归与试验边界

针对产品代码 `170578b` 重新执行：

| 检查 | 实际结果 |
|---|---|
| 完整非浏览器 `pytest tests --ignore=tests/browser` | 634 passed、7 skipped、95 subtests passed；732.02 秒 |
| 完整真实 Chromium `pytest tests/browser` | 28 passed；239.41 秒 |
| Inspector Node | 54 passed |
| same-path 完整语义对照 | 5 scopes 原始 fingerprint／manifest／对象／QA 一致 |
| 真实 FTIR 三轮／十轮及失败拒绝 | 内部存活对象 0，外部 Figure 保留 |
| 真实 NMR Strict 出版／FTIR Strict 拒绝 | 原行为保持 |

测试期间仍有 requests 依赖版本警告；全量非浏览器另有 demo 示例打开超过 20 个 Figure 的 4 条 warning。它们不是本轮真实 FTIR probe 的残留，不隐藏，也不据此扩大本轮去重构 demo 或整个验证器。

首次试验有两个非产品问题，均保留失败记录后用新目录重跑：生命周期 probe 请求恢复到原始字号而触发既有 required-target-unchanged 拒绝，改为两个非基线字号轮换；新 stage 的 strict 子进程缺 PYTHONPATH，明确提供仓库路径后重跑。没有通过改产品规则让 harness 变绿。

## 复跑入口

所有 evidence 目录必须新建；原研究目录和 G19／G20／G21 归档只读。严格子进程需要 `PYTHONPATH` 包含当前仓库根。

```text
python tools/g22/lifecycle_trial.py --script "<隔离FTIR/plot_ftir.py>" --config "<隔离FTIR/ftir.yaml>" --output-dir "<新证据目录>" --edits 3
python tools/g22/lifecycle_trial.py --script "<隔离FTIR/plot_ftir.py>" --config "<隔离FTIR/ftir.yaml>" --output-dir "<另一个新证据目录>" --edits 10
```

Strict 行为复跑继续使用 G21 的 `nmr_publication.py --save` 与 `ftir_publication.py`，将输入指向新脚本的隔离副本；不能把 FTIR collector 自身退出 0 当作其内含 strict 子进程通过。

性能复跑（无其他测试／试验并发时）：

```text
python tools/g22/profile_trials.py --output-dir "<新私有结果目录>" --summary "<新脱敏汇总.json>" --ftir-script "<隔离FTIR脚本>" --ftir-config "<FTIR配置>" --nmr-script "<隔离NMR脚本>" --nmr-config "<NMR配置>" --cck8-pure-script "<CCK-8纯构图脚本>" --cck8-full-script tools/g19/trial_sources.py --cck8-full-env "<原脚本副本父目录，内含origrun>" --rounds 5
```

## 收口

异常不再静默降级、真实 FTIR 无持续 Figure 残留、外部 Figure 保留、原科学语义与出版／拒绝／草稿行为保持，三类完整回归和五轮性能均已实际完成。G22 在此停止。普通刻度裁切覆盖、可证明的验证冗余与 FTIR scope 图例控制仍未改变，不混入本轮。
