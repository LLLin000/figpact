# G7-STRATEGY 调研任务书（两路）

**背景**：figpact 是"直接改 Python 科研图排版细节 + 让不同尺寸小图在最终投稿尺寸下规格统一"的工具，已具备：真实图上的测量/选区/拖动（毫米预览）、松手一次真实重建验证、接受→原子写回源文件（漂移检查 + 双状态：`source_commit_state` / `figure_verification_state`）、最终尺寸只读审计与最小受控修改、科学指纹/QA 保护、只读 Agent 上下文。
**用户发现一个定位重合的项目：`mpltweak`**，感到被挤压；需要**客观研究**：这类工具到底该具备哪些基本能力，我们的优势究竟在哪，应往哪个方向推进。

## 共同要求
- 每条事实**带 URL**；无法确证写"未找到"，**不许编**；区分【事实】与【推断】。
- 不许写营销话术、不许自我安慰式结论；**不利于我们的发现必须写出来**。
- 全文写进指定文件；回给父代理 **≤500 词**摘要。
- 只允许写指定文件，不改仓库其它内容，不跑测试，无 git 写操作。

## 路线 A（写 `docs/research/R8_capability_baseline.md`）
**问题**：像 figpact 这类工具（面向科研人员、目标是"发布级图的排版与规格"）**应当具备哪些基本能力**？
调研对象（至少覆盖，找官方文档/源码/论文）：
1. `mpltweak`；2. SciencePlots / proplot（样式与规格）；3. adjustText / labellines / mpl-typography 类**标签避让**；4. Inkscape / Illustrator 的科研图工作流与"可编辑性"要求；5. 期刊端硬要求（Nature/Science/Elsevier… 的最终尺寸、字号、矢量、多面板一致性）；6. TikZ/PGFPlots 与"代码即图"路线；7. 论文图 **lint/checker** 类工具（检查字号/线宽/DPI 的自动化）；8. 组合图工具（patchwork/cowplot/svgutils/figurefirst）。
**产出**：一张**能力清单表**，分「基本必选 / 常见 / 加分」三档，每项注明：谁做到了、用什么机制、figpact 目前有无（无则写"无"）。

## 路线 B（写 `docs/research/R9_mpltweak_vs_figpact.md`）
1. **mpltweak 深挖**：它是什么、解决什么问题、交互形态（桌面/GUI/Notebook？）、**是否编辑原始 Python 源码**、如何处理最终尺寸/字号、如何验证、许可、活跃度（提交/发布/issue 量）、已知限制。
2. **逐项对比矩阵**（行=能力，列=mpltweak / figpact / 其他代表工具）：测量与场景、选区与身份（GID）、拖动与预览、真实验证、写回源文件与其安全性、科学不变量保护、最终尺寸/跨图规格、多面板拼版、Agent/自动化接口、审计与报告、可复现性。
3. **重叠区**（真撞车的地方）与**各自独有**（客观写，包含"我们弱于它"的项）。
4. **结论与推进方向**：我们**不应**去竞争的领域；**应该加深**的（候选：可验证编辑闭环 / 科学不变量 / 跨图最终规格 / 与拼版编辑器的协作 / 被 Agent 可靠调用）；给出**三条**最值得投入的方向及其理由与风险。

## 环境
`TEMP/TMP/TMPDIR/MPLCONFIGDIR` 指向 `D:/L/AI/figpact-archive/g6b-v2/tmp*`；`D:/programs/Python/python.exe -B -X utf8`。允许 `web_search` 与 `read` 抓取官方文档/GitHub。
