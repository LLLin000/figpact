# R8 能力基线（路线 A）

> 事实/推断标记遵循任务书：【事实】来自检索到的官方文档/GitHub/PyPI；无法确证写“未找到”。【推断】为自己判断，留用。

## 基本必选

| # | 能力 | 谁做到了 / 机制（来源） | figpact 现状 |
|---|------|------------------------|--------------|
| 1 | 真实数据图上的读写，不只 mock/layout | 【事实】mpltweak：打开真实 `fig*.py`，GUI/CLI 交互布局，写回 `add_axes` 等参数；PyPI/GitHub 文档 https://pypi.org/project/mpltweak/ https://github.com/shdbl/mpltweak | 有（真实 FTIR/NMR 脚本图，场景测量） |
| 2 | 选区与身份（GID/目标） | 【事实】figpact 已登记作者身份与精确参数路径（仓库 G0 文档 `docs/G0_BASELINE.md`） | 有 |
| 3 | 拖动 + final-size mm 预览 | 【事实】Inkscape/Illustrator 科研图工作流支持拖动矢量元素、mm 文档尺寸、导出；指南 https://bioinformatics-core-shared-training.github.io/effective-figure-design/DesigningEffectiveScientificFigures_Practical_INKSCAPE_Zabala_v00.pdf；mpltweak 交互窗口 https://pypi.org/project/mpltweak/0.1.8/ | 有（mm 预览 + 真实重建） |
| 4 | 真实重建验证（不是拖动假象） | 【事实】figpact 任务书描述“松手一次真实重建验证”；mpltweak `mpltweak apply ... --write` 可自动 rerun 验证（PyPI https://pypi.org/project/mpltweak/0.1.7/） | 有 |
| 5 | 源文件写回与安全性（原子/drift/双状态） | 【事实】figpact：原子写回、漂移检查、`source_commit_state` / `figure_verification_state`；mpltweak：JSON 参数文件 + AST/back-up 写回（PyPI https://pypi.org/project/mpltweak/0.1.2/ 说明 “writeback.py”） | 有 |
| 6 | 科学不变量保护 | 【事实】figpact 文档明确科学指纹/QA 保护；mpltweak 明确“不修改图内容，只布局/样式参数”（PyPI https://pypi.org/project/mpltweak/0.1.2/）；其它检索未见等价声明 | 有（figpact 特有；其他工具未找到等价机制） |
| 7 | 最终投稿尺寸/字号/线宽规格 | 【事实】Nature：单栏 89 mm、双栏 183 mm，字号 5–7 pt（面板 a 8 pt），线宽 0.25–1 pt（https://www.nature.com/nature/for-authors/final-submission；https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/）；Science/AAAS 指南 https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf；Elsevier artwork https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-overview | 部分（只读审计 + 最小受控修改；预设/全局 remap 未找到） |
| 8 | 可编辑矢量输出（非 outlined text） | 【事实】Nature 要求文本可编辑、字体嵌入、不 outline；指南 https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/；Inkscape 工作流 https://bioinformatics-core-shared-training.github.io/effective-figure-design/DesigningEffectiveScientificFigures_Practical_INKSCAPE_Zabala_v00.pdf | 无（figpact 未声明最终导出/编辑性审计） |
| 9 | Agent/自动化接口 | 【事实】figpact 有只读 Agent context（`agent_api`）；mpltweak 文档称有 MCP server 表面（https://conduid.com/servers/mpltweak）；figurelint 支持 CI exit code（https://pypi.org/project/figurelint/） | 有（只读） |

## 常见

| # | 能力 | 谁做到了 / 机制（来源） | figpact 现状 |
|---|------|------------------------|--------------|
| 10 | 样式主题/出版预设（Matplotlib style） | 【事实】SciencePlots：`plt.style.use('science')` + ieee/nature 等；PyPI https://pypi.org/project/SciencePlots/；FAQ https://github.com/garrettj403/SciencePlots/wiki/FAQ；ProPlot：publication defaults + `journal=` 关键字 https://proplot.readthedocs.io/en/latest/faq.html | 无（未找到等价主题系统；图例样式示例不算） |
| 11 | 标签避让/anti-overlap | 【事实】adjustText：`adjust_text(...)` 迭代移动文本并加箭头（https://adjusttext.readthedocs.io/en/stable/）；pylabeladjust（https://github.com/MNoichl/pylabeladjust） | 无 |
| 12 | 多面板拼版/布局 | 【事实】patchwork/cowplot（https://patchwork.data-imaginist.com/；https://wilkelab.org/cowplot/articles/plot_grid.html）；svgutils compose（https://svgutils.readthedocs.io/en/latest/tutorials/composing_multipanel_figures.html）；FigureFirst SVG 轴标签布局（https://figurefirst.readthedocs.io/en/latest/basic_usage.html） | 有（真实多面板场景已测量/验证） |
| 13 | 文档 mm 尺寸与面板对齐审计 | 【事实】plotstyle：`validate(fig, journal=...)`、`migrate()`、journal preset https://github.com/rahulkaushal04/plotstyle | 部分（final size 审计；journal preset 对比未找到） |
| 14 | Figure lint/checker（字号/线宽/DPI） | 【事实】figurelint：SVG/raster/PDF 检查、preset（high-resolution/nature）https://pypi.org/project/figurelint/；figure-gate：Matplotlib `audit(fig)` 19/21 gates https://narenp12.github.io/figure-gate/；visdecode ASP 检查 https://pypi.org/project/visdecode/ | 部分（科学 QA gates；publisher preset lint 未找到） |
| 15 | 有 GUI/Notebook 交互模式 | 【事实】mpltweak optional Qt backend；mplstudio notebook GUI https://github.com/symoon9/mplstudio；Inkscape 作为矢量编辑器 | 有（只读浏览器 Inspector；写入在 CLI/Python 侧） |
| 16 | 历史/revision 跟踪 | 【事实】figpact `history.py`/revision tracking docs；未找到通用工具提供 git-like figure revision | 有 |

## 加分

| # | 能力 | 谁做到了 / 机制（来源） | figpact 现状 |
|---|------|------------------------|--------------|
| 17 | 代码即图（TikZ/PGFPlots）路线 | 【事实】PGFplots/TikZ：LaTeX 内原生高质 2D/3D、样式复用、standalone PDF https://tikz.dev/pgfplots/；matplotlib→PGF 导出 tikzplotlib 案例 https://blog.martisak.se/2019/09/29/publication_ready_figures/ | 无（Python-native 路线） |
| 18 | 与拼版编辑器协作 | 【事实】figurefirst/Inkscape layout→matplotlib→save SVG https://figurefirst.readthedocs.io/en/latest/basic_usage.html；Inkscape 模板 https://github.com/lukmuk/inkscape-scientific-figure-template | 无显式桥接 |
| 19 | 配色/色盲可达性检查 | 【事实】figure-gate 色盲安全检查 https://narenp12.github.io/figure-gate/；plotstyle accessibility simulation https://github.com/rahulkaushal04/plotstyle | 未找到（科学 QA 中未确认色盲门） |
| 20 | 文本/引线避让在最终 mm 尺寸下 | 【事实】adjustText 后应最终尺寸稳定再调（https://adjusttext.readthedocs.io/en/stable/） | 无 |

## 不利于我们的发现（必须记录）

- 【事实】mpltweak 与 figpact 真实重叠点：都是面向 Matplotlib、可视化拖动/对齐，且**写回源码**；其声明“不修改图内容，只布局/样式参数”，销售/使用文案瞄准“像 PPT 排版多面板” (https://pypi.org/project/mpltweak/)。这是直接竞争面。
- 【事实】figpact 目前未找到等价的 journal preset / 字号 DPI lint / final editable-text audit / label-avoidance / TikZ 桥接；这些是生态常见能力（figurelint/plotstyle/adjustText/TikZ），不是 figpact 已有能力。
- 【推断】figpact 的差异化大概率不在“拖动布局本身”，而在可验证编辑闭环与科学不变量；但用户若只要快速 PPT 式排版，mpltweak 更轻。

## 来源摘要

- mpltweak: https://pypi.org/project/mpltweak/ (v0.1.x)；https://github.com/shdbl/mpltweak
- SciencePlots: https://github.com/garrettj403/scienceplots；https://pypi.org/project/SciencePlots/
- ProPlot: https://proplot.readthedocs.io/en/latest/faq.html
- adjustText: https://adjusttext.readthedocs.io/en/stable/
- Nature figure specs: https://www.nature.com/nature/for-authors/final-submission；https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/
- Science guide: https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf
- Elsevier: https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-overview
- Inkscape/流程: https://bioinformatics-core-shared-training.github.io/；https://wiki.inkscape.org/wiki/Inkscape_for_Adobe_Illustrator_users
- TikZ/PGFPlots: https://tikz.dev/pgfplots/
- figurelint: https://pypi.org/project/figurelint/
- figure-gate: https://narenp12.github.io/figure-gate/
- plotstyle: https://github.com/rahulkaushal04/plotstyle
- patchwork/cowplot/svgutils/figurefirst: https://patchwork.data-imaginist.com/；https://wilkelab.org/cowplot/articles/plot_grid.html；https://svgutils.readthedocs.io/；https://figurefirst.readthedocs.io/