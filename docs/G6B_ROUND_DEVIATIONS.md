# G6b 正式轮：轮次偏差与裁定记录（执行期）

冻结项：引擎 `f101113476cf3f0113ccbb5e054d700d8c0a433a`；协议 v2 + v2.1（`dba9114` 及之后仅文档）；题单 T01–T12；三臂权限与判分口径不变。
归档根：`D:/L/AI/figpact-archive/g6b-v2/`（`I:` 已不存在）。

## D-1 三臂并发执行（协议 v2 §4 要求"同一时刻只跑一条 trial"）

- **事实**：三臂并行开跑；臂 L 与臂 A/V 的产物同时出现在同一 `formal/` 目录下。
- **影响判定**：每 trial 独立提取树 / 独立状态 / 独立会话、H4 环境约束、`<T>/tree` 零写入检查均成立 → **正确性类结论不受影响**；**时间类指标属"并发窗口内测量"**。
- **裁定**：按轮次偏差登记，**不属**三类作废。**D2 的时间比较不得使用该并发窗口的墙钟值**；改用工具调用数，或事后单独串行复测 D2 子集。已完成 trial 不重跑。已通知三臂。

## D-2 §10.3 仅冻结 NMR 科学输入 → A24(FTIR) 缺输入

- **事实**：臂 L 的 A24 首跑因 `SCIENCE_INPUTS … 不存在` 失败，原件保留在 `formal/_pass_failed/A24-missing-science-input`；其后自建 FTIR manifest 并重跑成功。
- **裁定**：属**前置补齐**而非"重跑到成功"。现冻结正式 FTIR manifest：`D:/L/AI/figpact-archive/g6b-v2/ftir-science-manifest.json`（**43 文件 / 8,983,804 字节**，`--verify` 通过；导出图件按基线时点校验），三臂 T09/A24 一律使用。
- **协议层建议**：把"科学输入 manifest 需覆盖该题所用夹具"写成 §10.3 显式条件（本轮不追改冻结文本）。

## D-3 臂内工具口径偏差（不改协议，逐条留证）

- `figpact export --strict` 非法（`export` 已等价 `render --strict`）→ 失败往返保留在 `formal/_pass1/`。
- `figpact try` 单次 >300 s → 改用同白名单的 `validate`+`export`+独立重建，计时证据 `formal/_probe/try-timing.txt`。

## D-4 A16b 冻结题面的 gid 命名空间笔误

- **事实**：§11.1.3 冻结题面写 `intent.main.label.A`，而 A16b 夹具 `legacy_plain.py` 的 `FIGURE_ID="legacy"`，实际 gid 为 `legacy.main.label.A`；冻结串零命中、不可执行。
- **裁定**：**题面串笔误**（该串属 `simple_figure.py` 命名空间）；任务意图无歧义 → 按夹具实际 gid 执行正确，无需重跑；trial 记录须同时写明冻结串与实执行 gid。臂 A/L 在此题为 `structural_unsupported`，不受影响。
- **协议层建议**：后续版本对"题面 gid ↔ 夹具 `FIGURE_ID`"做机械一致性校验。

## D-5 判分工具在 FTIR 上的同进程双建伪影（臂 A 发现，已裁定）

- **事实**：`g6b-v2/harness/measure.py` 在同一进程里连建两次图；`plot_ftir.py` 的 `draw_panel()` 会就地把实测净距写回模块级 `_CFG`，于是第 1 次构建 ≠ 第 2 次；**两份字节相同的配置**也报出 Δ=(−0.06614583333, +0.35868962590) mm；一进程一配置则逐位确定。证据 `formal/ftir-measure-artifact.md`（臂 A 同时给了两套数）。影响面：仅 FTIR annotated（NMR 未触及 gid 在 measure.py 里逐位 0.0）。
- **裁定**：判 FTIR 时**判分器与臂侧一律"每个配置各起一次进程"**；同进程双建仅作收敛诊断，不得作为判分依据。已通知臂 V。
- **产品观察（本轮不修）**：`plot_ftir.py` 在同进程内不是输入的纯函数（模块级 `_CFG` 被回写）→ 记入后续开票候选，与 §12.4 并列。

## D-6 A24 冻结卡面描述与夹具不符

- **事实**：卡称 4 个 scope 各有 `fig2_ftir.<scope>.band.<bid>` 且 `label_edge_margin_mm` 在 4 个 scope 均声明；实测**只有 annotated 有 band 标签**、该参数**只在 annotated 的布局契约里声明**，另 3 个 scope 对同一路径返回 `UNSUPPORTED_PATH`。
- **裁定**：**卡面描述有误**。按 §11.1.5 判定顺序照实裁定即可（臂 A 记结局①完成：4/4 scope 无新增阻断项、未声明对象 Δ=0.00、只改该一键；臂 L 亦记 completed）。**不**为对齐卡面而改夹具或题面，不重跑。
- **协议层建议**：后续版本对题卡引用的 gid/参数路径做夹具级存在性校验。

## 待判分器遵守（来自 §12.3）

独立判分器**必须自建重建**决定科学与几何结果；`completed` 只由自建结果判定；**A16b、A17 不得**把 Hub 的 `COMMITTED_AND_VERIFIED` 计为科学验证通过；FTIR 一律一进程一配置（D-5）。
