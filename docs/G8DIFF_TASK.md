# G8-DIFF 调研任务书：找到我们真正能被注意到的差异

**用户判断（必须当成前提）**：
> "3 分钟首跑（选标注→移动→保存→重跑一致）"是最吸引普通科研人员的，但**大部分已被 Tavotto 与 mpltweak 解决**；能力清单/体检/JSON schema 这些**吸引不到注意力**。顶多"测量扩展到**全版面（plate）**"可能帮上排版，但 **Tavotto 似乎也有这个方向**。

**因此本轮的唯一目标**：找出**未被解决、且科研人员真痛**的问题，并给出可核对的证据与"我们能占住"的位置论证。

## 共同要求
- 每条事实**带 URL**；本地能核的给**文件路径 + 行号/函数名**；【事实】与【推断】分开。
- **不利于我们的发现必须写**（例如"这个位置 Tavotto 已经做了，且做得更好"）。
- 未确证写"未找到"，不许编。
- 全文写指定文件；回父代理 **≤500 词**摘要。只写该文件，不改仓库其它内容，无 git 写操作。

## 路线 R10 → `docs/research/R10_tavotto_direction.md`
**把 Tavotto 的能力与方向查清楚**（本地源码 `C:/Users/Lin/.omp/plugins/cache/marketplaces/tavotto/`，以及其 GitHub 仓库/文档/issue/路线图）：
1. 是否做**多图 / 整版（plate）**层面：一图多面板、跨图统一规格、拼版导出、页面尺寸与 mm 口径？
2. 是否有**期刊规则检查**（最终有效字号、线宽下限、DPI、字体嵌入/中文 fallback）与**阻断语义**？阈值来源是什么？
3. **写回 Python 到底做到什么程度**：只读覆盖、只改 override，还是能落回脚本/YAML？有无版本/漂移检查？
4. **Agent 接口**：MCP 工具面的完整清单、是否有稳定 schema、回执是否结构化？
5. 路线图 / issue / release notes 里**正在做什么**——尤其是否朝"整版 + 规格检查"走（这决定"全版面"是不是已被占住）。

## 路线 R11 → `docs/research/R11_unserved_pain.md`
**找"真痛且未被解决"的证据**：
1. 期刊/编辑对图的**退改或拒稿**原因（官方作者指南/编辑说明/可引用的统计）。
2. **图不可复现**的证据：图与数据脱节、"后期手动美化导致无法重跑"的一手描述或研究。
3. 科研人员实际用什么（Origin / GraphPad / MATLAB / BioRender / Illustrator / Inkscape / TikZ / matplotlib），各自的**公认痛点**（无法版本控制、无法重跑、跨图不一致、期刊规则人工核对）。
4. 目前**跨图一致性与整版规格**是怎么被人手工核对的（找"人工按尺子对齐字号/线宽""逐图对照 author guidelines"这类真实描述）。

## 路线 R12 → `docs/research/R12_plate_level_code.md`
**"把多张代码图拼成一张投稿图（plate）"在代码路线上有什么、缺什么**：
1. 现有手段各能做什么：matplotlib `subfigures`/`GridSpec`、R `patchwork`/`cowplot`/`gridtext`/`egg`、`svgutils`、LaTeX 拼版、TikZ。
2. **缺口**（逐条给证据）：跨图角色统一（字号/线宽/面板字母）、最终尺寸下 `k≡1`、整版级规则校验与报告、**改一处能整版重跑**、对外给出可消费的证据/回执。
3. 结论：**"整版"是不是没人占住的位置**；若是，给出**3 条可演示的最小能力 + 验收标准**；若否，指出谁已占住。

## 环境
`TEMP/TMP/TMPDIR/MPLCONFIGDIR` 指向 `D:/L/AI/figpact-archive/g6b-v2/tmp*`；`D:/programs/Python/python.exe -B -X utf8`；允许 `web_search` 与 `read`。
