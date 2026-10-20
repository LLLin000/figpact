# G25-S2：外部 Artist 兼容性修复

正式 G25 独立评测仍为 **BLOCKED**。本轮只使用 G25-S 已公开的 DEVELOPMENT_EXPOSED 来源修复已观察兼容性问题；不新增角色、控制权、Agent、规划器或 QA 豁免，不生成独立金标准，不调用受测模型。源脚本/许可及 G25-S 原始结果保留，不用复测改写首次结果。

## 修复与证据

### P0：ContourLabeler 被误当作 Text

`scene._artist_node` 曾按 `hasattr(get_text)` 提取文本。`QuadContourSet` 的同名方法实际是 `ContourLabeler.get_text(lev, fmt)`，不符合 Text 无参接口。现在与已有语义分类一致，只有 `isinstance(artist, matplotlib.text.Text)` 才提取文本与 baseline。

真实 contour_demo 的六张图参与回归：ContourSet 仍是 collection，实际 clabel 文本仍在 Scene，不因跳过错误文本分支而丢掉对象，也没有获得权限。未知图元不捕获异常填空文本。

### P0：样式数组比较与不可比较值

`change_audit` 的样式比较不再将 ndarray 的 `==` 结果放入标量条件。

- 普通浮点标量和浮点数组保留绝对容差 **1e-9，rtol=0**；同位置双 NaN 视为同口径缺失，一侧 NaN 为变化；同号 Infinity 保持相等。
- 数组 shape/dtype、容器类型或 bool/number 类型变化不会判相等。整数数组不经浮点提升，以免大整数差异被浮点舍入吞掉。字符串/布尔数组精确比较，复杂未知 dtype 不猜测。
- list/tuple/dict 递归比较。object/masked/未知数组、未知对象和捕获时已标为 `AUDIT_INCOMPARABLE` 的值保持不可比较，即使前后标记相同也不能变成无变化。
- 不可比较值进入 JSON 可表示的结构化拒绝，允许集及豁免不能放行；`required_targets_effectively_changed` 不会把未知伪装成已证实变化。
- 集合样式的数值数组在 snapshot 中保留为列表，不丢弃 linewidth 元素。

真实 contour snapshot 的等值和 linewidth 篡改都参与公开 `audit_pair` 回归；另覆盖容差、形状、dtype、NaN、Infinity、容器、未知对象和允许集反例。测试不调用内部比较助手来替代公开审计行为。

### P1：Shadow 的显示派生偏移不是原生科学几何

逐对象差异见 `tools/g25s/s2/science/prefix-shadow-raw.json`。该文件是本轮对旧记录算法的明确重建诊断，不冒充原始 G25-S 首次回执。饼图 fig5/fig7 各有四个 Shadow：path codes 不变，首次 draw 后 vertices 摘要改变。Shadow 的组合 transform 含由 `points_to_pixels` 在 draw 时刷新的显示偏移；旧记录把这部分误当成 native vertices。

修复只改变科学快照表示：Shadow 记录声明的 point offsets 以及 wrapped patch 的完整原生几何，不豁免 Shadow。真实 Wedge 角度、Shadow 声明偏移、Sankey path 变化仍产生 `SCIENCE_CHANGED`；重复 draw 和改变 DPI 不再把相同原始 Shadow 误判为科学修改。

### P1：Sankey 的原生等比例视图结算

逐对象原始 before/after 见 `science/diagnosis-raw.json`。三张 Sankey 图首次 draw 只有 `panel.0:view` 改变，Patch/文本数据不变。例如 fig0 的 ylim 从 `[-1.3671279704941823, 1.4090829520530463]` 变为 `[-1.2215595481633847, 1.2635145297222488]`，第二次绘制稳定；这是 `aspect=1`、`adjustable=datalim` 的原生生命周期。

`inspector.capture_figure` 在科学基线前只结算 **未被覆盖的原生 Axes.apply_aspect、非 auto aspect、adjustable=datalim**。不额外 draw，不调用未知 override，不对所有 Axes 增加完整结算开销。结算异常明确拒绝并保留 cause；结算前后任何非 view 科学对象或声明变化均拒绝，防止 callback 把真实数据修改洗进基线。科学基线后的 draw/snapshot 差异检查继续保留。

反例涵盖 Wedge/Shadow offset/真实 Sankey path/view 篡改、draw_event 数据修改、aspect 结算 callback 修改数据、自定义 aspect draw 修改数据，以及无法结算的共享轴布局。未知或失败不算通过。

### P1：NaN 几何不再污染 canonical JSON

renderer bounds 先检查有限性和顺序；collection 的显示变换若产生非有限坐标，则明确 `UNMEASURED`。对应节点使用 `measured=false`、null bounds/envelope/anchors 和可追溯 `geometry_reason`，并产生 blocking diagnostic；不用零、猜测框或静默删除代替。

原始 log_demo 的负误差条图参与回归：Scene 可以有限 JSON 表示拒绝状态，Inspector 仍失败关闭，而不是在 JSON 编码时抛 NaN 异常。正常 NaN 断线语义不改成跨断口连线。

### P2：有证据的空几何，而非扩大 3D 支持承诺

`geometry-boundaries.json` 保留修复前逐对象测量：3D surface、heatmap fig1/fig2、streamplot 的四处拒绝都来自 **普通 LineCollection，segments=0**，即没有 path 的色条 divider，不是这些图的主要数据几何。

现在仅对准确的普通 `LineCollection` 空 path 返回可证明的空几何：0 segments、空 polylines、null bounds/anchors，不伪造零包围盒。未知子类仍可能自定义绘制，因此仍不可测并明确拒绝。`geometry-boundaries-after.json` 的四个场景均可测；这不代表所有 3D/collection/非线性投影都已支持。

## 针对性回归

命令：

```sh
python -B -X utf8 -m pytest tests/test_g25s_audit.py tests/test_g25s_science.py tests/test_g25s_scene.py -q -p no:cacheprovider --tb=short
```

集成后观察到 **19 passed、13 subtests passed**，3 条已有换行字形度量 warning 原样保留。最初的 Scene tracer tests 在修复前暴露六个 ContourLabeler TypeError、NaN JSON 错误及非有限已注册图元缺 blocking diagnostic；没有用仅“不抛异常”的空检查替代对象、权限和拒绝证据。

科学回归 fixture 的一次子测试运行曾残留前张 Figure，错取 pie 索引；已通过每次原始 source 运行前关闭旧 Figure 修复测试隔离。该错误不被报告为产品缺陷或首次通过。

## 复测与回归证据口径

复测使用原 26 个脚本版本，仍为 24 个 repository/upstream_path，作者及来源相关性不变。`compare_stress.py` 逐一保留原 **129 次候选**，按 source/scope/probe 对照 target/base/requested value，不因错误、拒绝、上下文缺失或版本不兼容而剔除分母。新增可产生的上下文只单列结构性负例，不变造原候选数。

`checks-first`、`rerun-first` 在集成审查发现 object-array 类型转换仍需不可比较拒绝后被主动停止；原因保存在 `s2/aborted-runs.json`。它们的部分文件保留，不属于验收证据，也不冒充完整失败或完整通过。最终执行与比较使用另外的 fresh directories。

完整 Python、Chromium、Node 与历史 NMR/FTIR Strict 行为通过既有命令运行；私有科研输入及 Strict 导出只进入临时隔离副本。Strict 子进程退出和 QA 回执必须分别看，不能把 FTIR 证据收集程序 exit 0 当作 Strict PASS。

## 26 份开发来源固定分母复测

执行 `run_stress.py` 的三份原 manifest，输出 `tools/g25s/s2/rerun-final/`；再运行：

```sh
python -B -X utf8 tools/g25s/s2/compare_stress.py --new tools/g25s/s2/rerun-final --output tools/g25s/s2/comparison-final.json
```

| 指标 | G25-S 原始开发结果 | G25-S2 复测 |
|---|---:|---:|
| 脚本版本 / 原样基线可运行 | 26 / 23 | 26 / 23 |
| Figure 数 | 51 | 51 |
| 可产生真实 context | 34 / 51 | 50 / 51 |
| Figure 零授权目标 | 14 / 51 | 14 / 51 |
| 历史候选探针分母 | 129 | 129 |
| 未捕获候选异常 | 12 / 129 | 0 / 129 |
| 有变化候选 local PASS | 47 / 55 | 53 / 55 |
| 有变化候选 whole QA PASS | 37 / 55 | 41 / 55 |
| no-op local PASS | 0 / 37 | 0 / 37 |
| 越界 local PASS | 0 / 37 | 0 / 37 |
| 原始脚本哈希不变 | 26 / 26 | 26 / 26 |
| 候选后正式 Overlay 不存在 | 129 / 129 | 129 / 129 |

逐项对照 **0 missing、0 target/base/value drift**，没有新增候选混入原分母。原来的 12 次异常变成 6 次有变化 local PASS、6 次 no-op 结构化 FAIL；其他局部状态保持 47 PASS、33 FAIL、37 ERROR。后者的 37 ERROR 是原越界探针的预期结构化回执，不是未捕获异常。

仍拒绝：负误差条 log fig2 以未知几何阻止 context，tick change 的 `unexplained geometry` 不放行；原始未固定随机状态的 32-Axes 图以科学变化拒绝。三个外部脚本版本/API 不兼容失败保留。12 个有变化候选 local PASS 但 whole FAIL，不能升级为严格出版成功。分类详情在 `outcomes-final.json`。

新增可用 context 后结构性计划负例为 180/180 拒绝（原为 130/130），两者分母不同，不能据此计算模型安全率提升。零授权 Figure 仍是 14，不强迫其可编辑。

另通过真实 `capture_figure` 保存并查看了 7 个 PNG + Scene bundle，覆盖两张 Shadow、三张 Sankey、3D surface 及 colorbar heatmap；`frames/captures.json` 记录 revision/PNG/Scene hashes，`frames/capture-contact-sheet.png` 为实际 Inspector 帧拼图，而非仅原始脚本 baseline 图片。没有新增 GUI/权限接口。

## 完整回归与 Strict 历史语义

全部在最终产品修订上完成；`checks-final/results.json` 记录所有命令 exit 0、无超时，且 `engine_unchanged_during_checks=true`。各命令完整 stdout/stderr 均保留：

| 检查 | 实际结果 |
|---|---|
| 完整 Python 非浏览器 | 694 passed、7 skipped、120 subtests passed；865.80 秒 |
| 真实 Chromium | 28 passed；339.57 秒 |
| Node Inspector | 54 passed、0 failed |
| NMR Strict | 子进程 rc=0；publication `STRICT_VERIFIED`；PDF 最小字号 5.04 pt；隔离保存/重启/继续操作及 strict Overlay load/render PASS |
| FTIR Strict | 预期 FAIL：strict rc=1、4 个未豁免阻断、未生成候选 PDF；native preview OK 不被冒充为严格通过 |

运行入口是 `python -B -X utf8 tools/g25s/s2/run_checks.py --output tools/g25s/s2/checks-final`。其中 Python 排除 browser 后全跑；Chromium 单独全跑；Node 使用 `node --test tests/inspector/test_inspector.js`；Strict 复用 `tools/g23/publication_trial.py` 及 G21 原验证器，不另造 QA。

Strict raw artifacts/private clinical-source copies 的位置和原始回执哈希保存在 `checks-final/results.json` / `strict-proof.json`；没有将原始科研数据纳入仓库。实际出版动作仅对隔离副本和沙箱输出执行，用于验收保存/重启语义，不是向正式科研目录发布。

`strict-summary.json:outcome=G23_TICK_PASS`，NMR 72/120/300/600 DPI 的 tick-clip 检查均无阻断；72 DPI 仍有分辨率相关 TEXT_ON_DATA 项，原样披露，不把该 DPI sweep 说成所有 QA 全绿。NMR 的非阻断贴边提示、FTIR 的四条 compare 文字压线阻断均保留，未降低阈值或增加豁免。requests 依赖 warning、demo Figure 累积 warning、NaN DPI cast warning、Sankey 换行字形 warning 均未抑制。

至此 G25-S2 四项停止条件均有证据：P0 结构化结果、P1 原因和反例、26 来源/129 候选固定分母复测、完整三套回归与 Strict 语义保持。保留的未知几何、QA FAIL、无授权及第三方 API 兼容失败不被记为通过。

## 状态与历史

G25-S 仍是已完成的外部开发压力测试，首次历史结果不改写。G25-S2 是兼容性修复/回归线；G25 未见集/独立标注/模型评测是另一条线，继续 BLOCKED。所有这里使用过的图保持污染登记。

`G25_0_STATUS.md` 已修订 Publication boundary：保留早期远端 404 的历史，同时明确 G25-S 已通过 `74ea67a` 推送并经用户独立核验。本报告的验收记录先于 G25-S2 提交/推送；后续发布状态以仓库历史和实际 push 回执为准，不改变 G25 的 BLOCKED 状态。
